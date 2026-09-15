"""POST department — cleaning the finished artifact.

Owns watermark removal and container-metadata stripping. Wraps the pipeline
CLI's `scrub` verb, which is the single implementation the batch runner also
uses.

Note: watermark removal currently exists in three places in this repo
(``shorts_content_engine/src/postprocess/watermark.py``,
``automation/watermark_scrub.py``, ``flowkit/agent/services/post_process.py``).
This operation goes through the pipeline's own verb, so the assistant and the
unattended runner at least agree with each other. Collapsing the other two is
tracked in ``docs/IMPLEMENTATION.md`` §2 (POST).
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent.operations.registry import RISK_WRITE, OperationError, operation
from agent.operations.shell import WORKSPACE_ROOT, run_pipeline_cli

logger = logging.getLogger(__name__)

_PROFILES = ("veo_bottom_right", "gemini_bottom_right", "custom")
_MODES = ("delogo", "boxblur")


@operation(
    name="scrub_video",
    department="post",
    risk=RISK_WRITE,
    description=(
        "Remove the AI watermark and container metadata from an MP4. "
        "Args: input_path, output_path (optional), profile, mode."
    ),
    args={
        "input_path": "path to the MP4",
        "output_path": "optional output path",
        "profile": "veo_bottom_right",
    },
)
async def scrub_video(
    input_path: str,
    output_path: str | None = None,
    profile: str = "veo_bottom_right",
    mode: str = "delogo",
) -> dict:
    """Scrub a video through the pipeline's own `scrub` verb."""
    if not (input_path or "").strip():
        raise OperationError("scrub_video needs an 'input_path'.")

    resolved = Path(input_path)
    if not resolved.is_absolute():
        resolved = WORKSPACE_ROOT / resolved
    if not resolved.exists():
        raise OperationError(f"Input video not found: {resolved}")

    if profile not in _PROFILES:
        raise OperationError(f"Unknown profile {profile!r}. Known: {', '.join(_PROFILES)}.")
    if mode not in _MODES:
        raise OperationError(f"Unknown mode {mode!r}. Known: {', '.join(_MODES)}.")

    argv = ["scrub", "--input", str(resolved), "--profile", profile, "--mode", mode]
    if output_path:
        argv += ["--output", output_path]

    result = await run_pipeline_cli(argv, timeout=900)
    if result.get("exit_code") != 0:
        raise OperationError(
            f"scrub failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result
