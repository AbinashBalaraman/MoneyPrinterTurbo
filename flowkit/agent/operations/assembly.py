"""ASSEMBLY department — cutting the final video.

Narration (TTS), subtitles, BGM, and the image→video concat. This is the
MoneyPrinterTurbo core at the repository root (``app/``, root ``cli.py``); it is
live and load-bearing, driven by ``automation/runner.py`` via ``--batch-file``.

Deliberately a thin wrapper over that same entry point. The assembly engine has
its own task schema and its own validation, and re-implementing any of it here
would create a second path that drifts from the one the unattended runner uses.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent.operations.registry import RISK_SPEND, OperationError, operation
from agent.operations.shell import WORKSPACE_ROOT, run_assembly_cli

logger = logging.getLogger(__name__)


@operation(
    name="assemble_episode",
    department="assembly",
    risk=RISK_SPEND,
    description=(
        "Assemble final video(s) from a task file: narration, subtitles, BGM and "
        "the image→video concat. SPENDS COMPUTE and takes minutes per episode."
    ),
    args={"batch_file": "path to the task JSON/JSONL file"},
)
async def assemble_episode(batch_file: str) -> dict:
    """Run the assembly engine over a batch file."""
    if not (batch_file or "").strip():
        raise OperationError("assemble_episode needs a 'batch_file'.")

    candidate = Path(batch_file)
    resolved = candidate if candidate.is_absolute() else WORKSPACE_ROOT / candidate
    if not resolved.exists():
        raise OperationError(
            f"Task file not found: {resolved}. Assembly reads the same "
            f"--batch-file format the unattended runner uses."
        )

    result = await run_assembly_cli(["--batch-file", str(resolved)], timeout=1800)
    if result.get("exit_code") != 0:
        raise OperationError(
            f"assembly failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result
