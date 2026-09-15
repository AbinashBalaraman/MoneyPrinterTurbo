"""Subprocess plumbing shared by the department operations.

Why this is its own module
--------------------------
Three operations need to run a process — the pipeline CLI, the assembly CLI, and
the general shell — and all three need the same guards: a pinned working
directory, a timeout, an output cap, and a refusal list. Writing that three times
is how one of them ends up subtly weaker than the others.

Interpreter gotcha
------------------
The pipeline and the assembly engine have **separate virtualenvs**. A CLI wrapper
cannot use ``sys.executable`` — the agent runs in the flowkit venv, which does
not have the pipeline's dependencies. The interpreters come from config, with
this machine's layout as the default.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path
from typing import Any, Optional

from agent import config
from agent.operations.registry import OperationError

logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]  # AutoShorts/

COMMAND_TIMEOUT_DEFAULT = 30.0
COMMAND_TIMEOUT_MAX = 1800.0
OUTPUT_CAP = 12_000

#: Refused outright. A guardrail against a catastrophic typo, not a security
#: boundary — see the module docstring of the chat tool loop.
_BLOCKED = (
    "rm -rf /",
    "mkfs",
    "dd if=",
    "shutdown",
    "vssadmin delete",
    "format c:",
    "format d:",
    "del /f /s /q c:",
    "rd /s /q c:",
)


def _truncate(text: str, limit: int = OUTPUT_CAP) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[truncated, {len(text) - limit} more characters]"


def resolve_cwd(raw: Optional[str]) -> Path:
    """Pin a working directory inside the workspace."""
    base = WORKSPACE_ROOT.resolve()
    if not raw:
        return base
    candidate = Path(str(raw))
    target = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise OperationError(f"cwd {raw!r} is outside the workspace")
    return target


async def _run(argv: list[str], *, cwd: Path, timeout: float) -> dict[str, Any]:
    """Run a program, capture combined output, never raise on a non-zero exit."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        raise OperationError(f"Could not start {argv[0]!r}: {exc}")

    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise OperationError(f"{Path(argv[0]).name} timed out after {timeout:.0f}s")

    output = (raw or b"").decode("utf-8", "replace")
    try:
        shown_cwd = str(cwd.relative_to(WORKSPACE_ROOT.resolve())) or "."
    except ValueError:
        shown_cwd = "."

    return {
        "exit_code": proc.returncode,
        "output": _truncate(output),
        "cwd": shown_cwd,
    }


async def run_pipeline_cli(args: list[str], *, timeout: float = 600.0) -> dict[str, Any]:
    """Run a DIRECTOR / POST / PUBLISH verb through the pipeline CLI.

    `shorts_content_engine/src/cli.py` is the pipeline's own entry point; the
    unattended runner calls the same verbs. Going through it rather than
    re-implementing anything is what keeps the assistant and the automation from
    drifting apart.
    """
    cli = Path(config.PIPELINE_ROOT) / "src" / "cli.py"
    if not cli.exists():
        raise OperationError(
            f"Pipeline CLI not found at {cli}. Set PIPELINE_ROOT in AutoShorts/.env."
        )
    if not Path(config.PIPELINE_PYTHON).exists():
        raise OperationError(
            f"Pipeline interpreter not found at {config.PIPELINE_PYTHON}. "
            f"Set PIPELINE_PYTHON in AutoShorts/.env."
        )
    result = await _run(
        [config.PIPELINE_PYTHON, str(cli), *args],
        cwd=Path(config.PIPELINE_ROOT),
        timeout=min(timeout, COMMAND_TIMEOUT_MAX),
    )
    result["command"] = " ".join(["shorts_engine", *args])
    return result


async def run_assembly_cli(args: list[str], *, timeout: float = 1800.0) -> dict[str, Any]:
    """Run the ASSEMBLY engine (MoneyPrinterTurbo) through its CLI."""
    cli = WORKSPACE_ROOT / "cli.py"
    if not cli.exists():
        raise OperationError(f"Assembly CLI not found at {cli}.")
    if not Path(config.ASSEMBLY_PYTHON).exists():
        raise OperationError(
            f"Assembly interpreter not found at {config.ASSEMBLY_PYTHON}. "
            f"Set ASSEMBLY_PYTHON in AutoShorts/.env."
        )
    result = await _run(
        [config.ASSEMBLY_PYTHON, str(cli), *args],
        cwd=WORKSPACE_ROOT,
        timeout=min(timeout, COMMAND_TIMEOUT_MAX),
    )
    result["command"] = " ".join(["assemble", *args])
    return result


async def run_shell(
    command: str, *, cwd: Optional[str] = None, timeout_s: float = COMMAND_TIMEOUT_DEFAULT
) -> dict[str, Any]:
    """Run an arbitrary shell command in the workspace.

    This is a genuine shell with the user's privileges — the cwd is pinned and
    catastrophic patterns are refused, but it is a **guardrail, not a sandbox**.
    """
    command = (command or "").strip()
    if not command:
        raise OperationError("run_command needs a 'command'.")

    lowered = command.lower()
    if any(pattern in lowered for pattern in _BLOCKED):
        raise OperationError("Refused: that command matches a destructive pattern.")

    try:
        timeout = float(timeout_s or COMMAND_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):
        timeout = COMMAND_TIMEOUT_DEFAULT
    timeout = max(1.0, min(timeout, COMMAND_TIMEOUT_MAX))

    workdir = resolve_cwd(cwd)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        raise OperationError(f"Could not start the command: {exc}")

    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise OperationError(f"Command timed out after {timeout:.0f}s.")

    try:
        shown_cwd = str(workdir.relative_to(WORKSPACE_ROOT.resolve())) or "."
    except ValueError:
        shown_cwd = "."

    return {
        "command": command,
        "cwd": shown_cwd,
        "exit_code": proc.returncode,
        "output": _truncate((raw or b"").decode("utf-8", "replace")),
    }
