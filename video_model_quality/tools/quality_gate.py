#!/usr/bin/env python
"""Quality gate — the single command to run before every commit / task completion.

Autonomous agents commit fast; this gate is the tripwire that stops a
regression from landing. It enforces the invariants the project actually
promises in PROJECT.md / GOAL.md, so "it works on my machine" is replaced by
"the gate is green".

Checks
------
1. tests      : full pytest suite must pass.                       [hard]
2. static     : unreachable code after return/raise/break/continue. [hard]
3. static     : pyflakes — undefined names are hard, unused are warnings.
4. contract   : every catalog action builds; an UNKNOWN action must raise
                (PROJECT.md: "never silent wrong mapping").         [hard]
5. invariants : correct feature dims + no joint below the ground plane. [hard]
6. hygiene    : stray scripts under out/ + missing README.          [warn]

Usage
-----
    python tools/quality_gate.py            # full gate (includes eval)
    python tools/quality_gate.py --fast     # skip the 100-prompt eval
    python tools/quality_gate.py --json     # machine-readable summary

Exit code 0 = green (warnings allowed), 1 = a hard check failed.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TERMINATORS = (ast.Return, ast.Raise, ast.Break, ast.Continue)
SOURCE_DIRS = ("src", "tools", "tests")
PASS, WARN, FAIL = "pass", "warn", "fail"


class Result:
    def __init__(self) -> None:
        self.checks: List[Dict[str, Any]] = []

    def add(self, name: str, severity: str, detail: str,
            items: List[str] | None = None) -> None:
        self.checks.append({"name": name, "severity": severity,
                            "detail": detail, "items": items or []})

    @property
    def failed(self) -> List[Dict[str, Any]]:
        return [c for c in self.checks if c["severity"] == FAIL]

    @property
    def warned(self) -> List[Dict[str, Any]]:
        return [c for c in self.checks if c["severity"] == WARN]


# --------------------------------------------------------------------------- 1
def check_tests(res: Result) -> None:
    proc = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"],
                          cwd=ROOT, capture_output=True, text=True)
    lines = (proc.stdout or "").strip().splitlines()
    summary = lines[-1] if lines else "(no output)"
    if "No module named pytest" in (proc.stderr or ""):
        res.add("unit tests", FAIL, "pytest not installed in this interpreter")
        return
    res.add("unit tests", PASS if proc.returncode == 0 else FAIL, summary)


def check_eval(res: Result) -> None:
    proc = subprocess.run([sys.executable, "-m", "src.eval"],
                          cwd=ROOT, capture_output=True, text=True)
    out = proc.stdout or ""
    ok = proc.returncode == 0 and "100/100 passed" in out
    line = next((l.strip() for l in out.splitlines() if "passed" in l), "(no summary)")
    res.add("100-prompt eval", PASS if ok else FAIL, line)


# --------------------------------------------------------------------------- 2
def _scan_body(stmts: List[ast.stmt], path: str, found: List[str]) -> None:
    terminated = False
    for stmt in stmts:
        if terminated:
            found.append(f"{path}:{stmt.lineno}: unreachable {type(stmt).__name__} after a terminator")
        if isinstance(stmt, TERMINATORS):
            terminated = True


def _walk_bodies(node: ast.AST, path: str, found: List[str]) -> None:
    for field in ("body", "orelse", "finalbody"):
        stmts = getattr(node, field, None)
        if isinstance(stmts, list) and stmts and isinstance(stmts[0], ast.stmt):
            _scan_body(stmts, path, found)
    for child in ast.iter_child_nodes(node):
        _walk_bodies(child, path, found)


def check_unreachable(res: Result) -> None:
    found: List[str] = []
    for base in SOURCE_DIRS:
        for py in sorted((ROOT / base).rglob("*.py")):
            if "__pycache__" in py.parts:
                continue
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                found.append(f"{py.relative_to(ROOT)}: SYNTAX ERROR {exc}")
                continue
            _walk_bodies(tree, str(py.relative_to(ROOT)), found)
    res.add("dead code (unreachable)", FAIL if found else PASS,
            f"{len(found)} unreachable statement block(s)" if found else "clean", found)


# --------------------------------------------------------------------------- 3
def check_pyflakes(res: Result) -> None:
    proc = subprocess.run([sys.executable, "-m", "pyflakes", *SOURCE_DIRS],
                          cwd=ROOT, capture_output=True, text=True)
    if "No module named pyflakes" in (proc.stderr or ""):
        res.add("static analysis", WARN,
                "pyflakes not installed — run: pip install pyflakes  (skipped)")
        return
    issues = [l for l in (proc.stdout or "").splitlines() if l.strip()]
    # Only genuine correctness bugs are hard. Style nits (unused imports/vars,
    # f-strings without placeholders, benign shadowing) are warnings.
    HARD_MARKERS = ("undefined name", "referenced before assignment",
                    "undefined local variable")
    hard = [i for i in issues if any(m in i for m in HARD_MARKERS)]
    soft = [i for i in issues if i not in hard]
    sev = FAIL if hard else (WARN if soft else PASS)
    detail = (f"{len(issues)} issue(s): {len(soft)} warning, {len(hard)} hard"
              if issues else "clean")
    res.add("static analysis", sev, detail, (hard + soft)[:40])


# --------------------------------------------------------------------------- 4
def check_contract(res: Result) -> None:
    from src.catalog import ACTIONS_1P, ACTIONS_2P
    from src.puppet.choreography import build_motion_from_action, build_combat_pair

    problems: List[str] = []
    try:
        for action in sorted(ACTIONS_1P):
            build_motion_from_action(action, duration_s=1.0)
        for action in sorted(ACTIONS_2P):
            build_combat_pair(action, duration_s=1.0)
    except Exception as exc:
        problems.append(f"declared action failed to build: {exc!r}")

    for bogus in ("floss_dance", "definitely_not_an_action"):
        try:
            build_motion_from_action(bogus, duration_s=1.0)
            problems.append(
                f"build_motion_from_action({bogus!r}) silently succeeded — "
                "must raise (PROJECT.md: 'never silent wrong mapping')")
        except (ValueError, KeyError):
            pass

    res.add("action contract", FAIL if problems else PASS,
            f"{len(problems)} contract violation(s)" if problems else
            f"{len(ACTIONS_1P)}+{len(ACTIONS_2P)} actions build, unknowns rejected",
            problems)


# --------------------------------------------------------------------------- 5
def check_invariants(res: Result) -> None:
    import numpy as np
    from src.catalog import ACTIONS_1P
    from src.puppet.choreography import build_motion_from_action
    from src.rig import FEAT_DIM, GROUND_Y
    from src.renderer import decode_motion_features

    problems: List[str] = []
    for action in sorted(ACTIONS_1P):
        feat = np.asarray(build_motion_from_action(action, duration_s=2.0))
        if feat.ndim != 2 or feat.shape[1] != FEAT_DIM:
            problems.append(f"{action}: bad feature shape {feat.shape}, expected (T,{FEAT_DIM})")
            continue
        joints = decode_motion_features(feat)
        lowest = float(joints[..., 1].min())
        if lowest < GROUND_Y - 0.05:
            problems.append(f"{action}: ground penetration min_y={lowest:.3f} < {GROUND_Y - 0.05:.3f}")
    res.add("motion invariants", FAIL if problems else PASS,
            f"{len(problems)} violation(s)" if problems else
            f"{len(ACTIONS_1P)} actions: dims OK, no ground penetration", problems)


# --------------------------------------------------------------------------- 6
def check_hygiene(res: Result) -> None:
    """Advisory only: `out/` doubles as the team's diagnostics scratch pad."""
    notes: List[str] = []
    out = ROOT / "out"
    if out.is_dir():
        strays = sorted(p.name for p in out.glob("*.py"))
        if strays:
            notes.append(
                f"{len(strays)} diagnostic script(s) live in out/ — "
                "consider moving to tools/diagnostics/ and updating HEAD_STATE.md: "
                + ", ".join(strays[:8]))
    if not (ROOT / "README.md").exists():
        notes.append("no README.md — new agents/humans have no single onboarding entry point")
    res.add("repo hygiene", WARN if notes else PASS,
            f"{len(notes)} advisory note(s)" if notes else "clean", notes)


# --------------------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description="Stickman project quality gate")
    ap.add_argument("--fast", action="store_true", help="skip the 100-prompt eval")
    ap.add_argument("--json", action="store_true", help="emit JSON summary")
    args = ap.parse_args()

    res = Result()
    print("=" * 70)
    print("  QUALITY GATE — stickman video model")
    print("=" * 70)

    check_tests(res)
    check_unreachable(res)
    check_pyflakes(res)
    check_contract(res)
    check_invariants(res)
    check_hygiene(res)
    if not args.fast:
        check_eval(res)

    marks = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL"}
    for c in res.checks:
        print(f"[{marks[c['severity']]}] {c['name']:22s} {c['detail']}")
        for item in c["items"][:12]:
            print(f"         - {item}")
        if len(c["items"]) > 12:
            print(f"         ... and {len(c['items']) - 12} more")

    print("-" * 70)
    if res.failed:
        print(f"RESULT: FAIL — {len(res.failed)} hard check(s) failed: "
              f"{', '.join(c['name'] for c in res.failed)}")
    elif res.warned:
        print(f"RESULT: PASS (with {len(res.warned)} warning(s): "
              f"{', '.join(c['name'] for c in res.warned)})")
    else:
        print("RESULT: PASS — all checks green")
    print("=" * 70)

    if args.json:
        print(json.dumps({"passed": not res.failed, "checks": res.checks}, indent=2))
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
