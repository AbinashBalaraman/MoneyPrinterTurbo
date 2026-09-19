"""Boundary checker — keeps the departments from eroding back into each other.

Why this exists
---------------
The architecture in ``docs/ARCHITECTURE.md`` is only real if something enforces
it. Every rule here was broken at least once in this repository's history, and
each break cost real debugging time:

* two things named ``flowkit`` (server and client) — the reference-image bug took
  hours because the failure appeared in one and the cause lived in the other;
* the same slug-matching rule in two places, which would have let the
  conditioning report disagree with the generator;
* a hand-written chatbot tool list alongside the REST routes, which drifted.

A document cannot stop any of that. This can.

Usage::

    python tools/check_boundaries.py          # report and exit non-zero on failure
    python tools/check_boundaries.py --quiet  # only failures

Run it in the same pass as the test suites.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AGENT = REPO / "flowkit" / "agent"
OPERATIONS = AGENT / "operations"

#: Modules allowed to import ``agent.api.*``. Layering says a department should
#: not reach into the HTTP layer; these are the exceptions, each with a reason.
API_IMPORT_ALLOWLIST = {
    # The continuity ledger's only reader lives in api/continuity.py. Reusing it
    # beats writing a second reader that would drift from the dashboard's.
    "director.py",
}

#: Names that must not be used directly in an operation — they must go through
#: ``operations/shell.py``, which owns the cwd pin, timeout and output cap.
SHELL_ESCAPES = {"subprocess", "Popen", "create_subprocess_shell", "create_subprocess_exec"}


class Failure:
    def __init__(self, rule: str, path: Path, detail: str):
        self.rule = rule
        self.path = path
        self.detail = detail

    def __str__(self) -> str:
        try:
            shown = self.path.relative_to(REPO)
        except ValueError:
            shown = self.path
        return f"  [{self.rule}] {shown}\n      {self.detail}"


def _py_files(root: Path):
    if not root.exists():
        return []
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _parsed(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return None


PIPELINE_CLI = REPO / "shorts_content_engine" / "src" / "cli.py"


def _cli_options_by_verb() -> dict[str, set[str]]:
    """``{verb: {valid --options}}`` from the pipeline CLI's own argparse setup.

    Read from the source rather than by running ``--help``: the check then needs
    no interpreter, no working directory and no subprocess, so it cannot fail for
    environmental reasons and be ignored.
    """
    tree = _parsed(PIPELINE_CLI)
    if tree is None:
        return {}

    # p_init = subparsers.add_parser("init-series", ...) -> {"p_init": "init-series"}
    parser_vars: dict[str, str] = {}
    options: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_parser"):
            continue
        if not (node.value.args and isinstance(node.value.args[0], ast.Constant)):
            continue
        verb = node.value.args[0].value
        if not isinstance(verb, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                parser_vars[target.id] = verb
                options.setdefault(verb, set())

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "add_argument"):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        verb = parser_vars.get(func.value.id)
        if verb is None:
            continue
        for arg in node.args:
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value.startswith("-")
            ):
                options[verb].add(arg.value)
    return options


def _operation_cli_invocations():
    """``(op name, file, function node, [argv expressions])``."""
    for path in _py_files(OPERATIONS):
        tree = _parsed(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_operation = any(
                isinstance(d, ast.Call) and getattr(d.func, "id", "") == "operation"
                for d in node.decorator_list
            )
            if not is_operation:
                continue
            exprs = [
                call.args[0]
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and getattr(call.func, "id", "") == "run_pipeline_cli"
                and call.args
            ]
            if exprs:
                yield node.name, path, node, exprs


def _argv_strings(expr: ast.AST, fn: ast.AST) -> list[str]:
    """Every string literal that can end up in this argv.

    Follows a bare name back to its assignments and ``+=`` augmentations in the
    same function, because that is how these argvs are actually built — the
    flags added conditionally are just as capable of being wrong as the base
    ones.
    """
    if isinstance(expr, ast.Name):
        strings: list[str] = []
        for node in ast.walk(fn):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            if not any(isinstance(t, ast.Name) and t.id == expr.id for t in targets):
                continue
            value = node.value
            if isinstance(value, (ast.List, ast.Tuple)):
                strings += [
                    e.value
                    for e in value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                ]
        return strings
    if isinstance(expr, (ast.List, ast.Tuple)):
        return [
            e.value
            for e in expr.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
    return []


def check_operation_argv_matches_the_cli() -> list[Failure]:
    """Operations must call the pipeline CLI with arguments it actually accepts.

    `generate_episode` ran ``generate --manifest <path>``. That verb has never
    accepted ``--manifest`` and *requires* ``--series-id``, so every call died
    with an argparse usage error and the operation could not have worked once.
    Nothing caught it: the op was registered, its handler was async, and every
    declared argument was a real parameter. The argv itself was never checked
    against the CLI it targets.

    This reads both sides statically — the CLI's argparse setup and the argv
    each operation builds — so the next such mismatch fails here instead of in
    production.
    """
    options_by_verb = _cli_options_by_verb()
    if not options_by_verb:
        return [
            Failure(
                "operation-argv",
                PIPELINE_CLI,
                "could not read any subcommands from the pipeline CLI; the "
                "parsing below assumes add_parser(...) plus add_argument(...).",
            )
        ]

    failures: list[Failure] = []
    for name, path, fn, exprs in _operation_cli_invocations():
        for expr in exprs:
            strings = _argv_strings(expr, fn)
            if not strings:
                continue
            verbs = [s for s in strings if s in options_by_verb]
            if len(verbs) != 1:
                # Ambiguous or unrecognised — do not guess and cry wolf.
                continue
            verb = verbs[0]
            valid = options_by_verb[verb]
            for flag in sorted({s for s in strings if s.startswith("--")}):
                if flag not in valid:
                    failures.append(
                        Failure(
                            "operation-argv",
                            path,
                            f"{name} passes {flag!r} to '{verb}', which does not "
                            f"accept it. Valid: {', '.join(sorted(valid))}.",
                        )
                    )
    return failures


def check_operations_declared_in_one_place() -> list[Failure]:
    """`@operation` may only appear under agent/operations/.

    A declaration anywhere else is a second front door that the registry cannot
    see — and therefore one the risk gate cannot protect.
    """
    failures = []
    for path in _py_files(AGENT):
        if OPERATIONS in path.parents:
            continue
        tree = _parsed(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    name = getattr(target, "id", None) or getattr(target, "attr", None)
                    if name == "operation":
                        failures.append(
                            Failure(
                                "operations-live-in-one-place",
                                path,
                                f"{node.name}() is decorated with @operation outside "
                                f"agent/operations/ — the registry cannot see it and the "
                                f"risk gate cannot protect it.",
                            )
                        )
    return failures


def check_no_handwritten_tool_list() -> list[Failure]:
    """chat_agent must not carry its own tool catalogue.

    It used to. That list and the REST routes drifted twice, which is the whole
    reason the operations catalog exists.
    """
    path = AGENT / "services" / "chat_agent.py"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    failures = []
    if 'TOOLS: dict' in text and "_build_tools()" not in text:
        failures.append(
            Failure(
                "tools-come-from-the-catalog",
                path,
                "TOOLS is assigned a literal dict instead of being built from the "
                "operations registry.",
            )
        )
    # A literal list of tool dicts is the old shape. The signal is a *quoted*
    # tool name — `"name": "web_search"`. Matching a bare `"name":` would flag
    # the registry-driven version, which builds dicts as `"name": op.name`, and a
    # checker that cries wolf gets switched off.
    if "def tool_specs" in text:
        body = text.split("def tool_specs", 1)[1].split("\ndef ", 1)[0]
        if '"name": "' in body:
            failures.append(
                Failure(
                    "tools-come-from-the-catalog",
                    path,
                    "tool_specs() contains a hardcoded tool list instead of reading "
                    "the registry.",
                )
            )
    return failures


def check_operations_do_not_escape_the_shell_layer() -> list[Failure]:
    """Operations must not spawn processes directly.

    ``operations/shell.py`` owns the pinned cwd, the timeout, the output cap and
    the refusal list. An operation that calls subprocess itself silently opts out
    of all four.
    """
    failures = []
    for path in _py_files(OPERATIONS):
        if path.name in ("shell.py", "registry.py", "__init__.py"):
            continue
        tree = _parsed(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in SHELL_ESCAPES:
                        failures.append(
                            Failure(
                                "no-direct-subprocess",
                                path,
                                f"imports {alias.name!r} directly. Use "
                                f"agent.operations.shell so the cwd pin, timeout and "
                                f"output cap apply.",
                            )
                        )
            elif isinstance(node, ast.Attribute):
                if node.attr in SHELL_ESCAPES:
                    failures.append(
                        Failure(
                            "no-direct-subprocess",
                            path,
                            f"calls {node.attr}() directly. Use agent.operations.shell.",
                        )
                    )
    return failures


def check_operations_respect_layering() -> list[Failure]:
    """A department must not import the HTTP layer."""
    failures = []
    for path in _py_files(OPERATIONS):
        if path.name in ("registry.py", "__init__.py"):
            continue
        tree = _parsed(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.startswith("agent.api"):
                    if path.name in API_IMPORT_ALLOWLIST:
                        continue
                    failures.append(
                        Failure(
                            "no-api-imports",
                            path,
                            f"imports {name!r}. Operations are the layer *under* the "
                            f"API; if this is genuinely needed, add {path.name!r} to "
                            f"API_IMPORT_ALLOWLIST with a reason.",
                        )
                    )
    return failures


def check_flowkit_means_one_thing() -> list[Failure]:
    """The client package must not be named `flowkit` again.

    Two things called `flowkit` (the server and the client library) is what made
    the reference-image bug take so long: the symptom was in one, the cause in
    the other.
    """
    failures = []
    sce = REPO / "shorts_content_engine" / "src"
    if (sce / "flowkit").exists():
        failures.append(
            Failure(
                "flowkit-is-the-server-only",
                sce / "flowkit",
                "the SCE client package is named 'flowkit' again. It is "
                "'render_client'; 'flowkit' must mean the server and nothing else.",
            )
        )
    return failures


CHECKS = (
    check_operations_declared_in_one_place,
    check_no_handwritten_tool_list,
    check_operations_do_not_escape_the_shell_layer,
    check_operations_respect_layering,
    check_flowkit_means_one_thing,
    check_operation_argv_matches_the_cli,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--quiet", action="store_true", help="only print failures")
    args = parser.parse_args(argv)

    failures: list[Failure] = []
    for check in CHECKS:
        failures.extend(check())

    if failures:
        print(f"boundary check FAILED — {len(failures)} violation(s):\n")
        for failure in failures:
            print(failure)
        print(
            "\nEach rule maps to a bug that actually happened. Fix the code, or "
            "add a documented exception — do not delete the check."
        )
        return 1

    if not args.quiet:
        print(f"boundary check passed — {len(CHECKS)} rule(s) upheld")
    return 0


if __name__ == "__main__":
    sys.exit(main())
