"""ASSEMBLY department — cutting the final video.

Narration (TTS), subtitles, BGM, and the image→video concat. This is the
MoneyPrinterTurbo core at the repository root (``app/``, root ``cli.py``); it is
live and load-bearing, driven by ``automation/runner.py`` via ``--batch-file``.

Deliberately a thin wrapper over that same entry point. The assembly engine has
its own task schema and its own validation, and re-implementing any of it here
would create a second path that drifts from the one the unattended runner uses.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from agent.operations.registry import RISK_SPEND, RISK_WRITE, OperationError, operation
from agent.operations.shell import WORKSPACE_ROOT, run_assembly_cli, run_bridge

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


_MANIFEST_DIR = "storage/automation/manifests"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def _slug(text: str, limit: int = 40) -> str:
    cleaned = _SAFE_NAME.sub("_", text or "").strip("_")
    return cleaned[:limit] or "task"


async def _stage_flowkit_project(project_ref: str, task_tag: str) -> dict:
    """Stage a FlowKit project's completed media through the staging bridge.

    The bridge (``automation/flowkit_bridge.py``, assembly venv) is the single
    staging implementation: download guards, format normalisation, project
    watermark scrubbing, local material layout. This op only drives its CLI
    and reads back the emitted params — never a second copy of that logic.
    """
    manifest_dir = WORKSPACE_ROOT / _MANIFEST_DIR
    manifest_dir.mkdir(parents=True, exist_ok=True)
    staged_params_path = manifest_dir / f"flowkit_{task_tag}.params.json"
    result = await run_bridge(
        [
            "--from-project", project_ref,
            "--task-id", f"flowkit_{task_tag}",
            "--emit-params", str(staged_params_path),
            "--media", "auto",
        ],
        timeout=1200,
    )
    if result.get("exit_code") != 0:
        raise OperationError(
            f"flowkit staging failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[-800:]}"
        )
    try:
        staged = json.loads(staged_params_path.read_text(encoding="utf-8"))
        return staged[0]
    except Exception as exc:
        raise OperationError(f"flowkit staging wrote no usable params: {exc}")


@operation(
    name="build_batch_task",
    department="assembly",
    risk=RISK_WRITE,
    description=(
        "Build a MoneyPrinterTurbo batch task file: subject, script, terms and "
        "the full assembly settings surface (voice_*, bgm_*, subtitle_*, "
        "video_source, video_aspect, video_concat_mode, video_transition_mode, "
        "font_*, stroke_*, ...). Optionally stages a FlowKit project's completed "
        "videos and stills in as scrubbed local materials (single staging "
        "implementation in automation/flowkit_bridge.py). Writes the file only — run "
        "assemble_episode on the returned manifest to spend compute."
    ),
    args={
        "subject": "video topic (required)",
        "script": "narration script; omitted = engine generates from subject",
        "terms": "material search keywords",
        "settings": "VideoParams overrides, e.g. voice_name, bgm_volume, font_size",
        "flowkit_project": "FlowKit project id or name whose media become materials",
    },
)
async def build_batch_task(
    subject: str,
    script: str | None = None,
    terms: str | list | None = None,
    settings: dict | None = None,
    flowkit_project: str | None = None,
) -> dict:
    """Write one batch-manifest entry covering the whole assembly surface."""
    if not (subject or "").strip():
        raise OperationError("build_batch_task needs a 'subject'.")
    if settings is not None and not isinstance(settings, dict):
        raise OperationError("'settings' must be an object of VideoParams fields.")

    entry: dict = {"video_subject": subject.strip()}
    if script:
        entry["video_script"] = script
    if terms:
        entry["video_terms"] = terms
    for key, value in (settings or {}).items():
        if key not in ("video_subject", "video_script", "video_terms"):
            entry[key] = value

    manifest_dir = WORKSPACE_ROOT / _MANIFEST_DIR
    manifest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    task_tag = f"{stamp}_{_slug(subject, 24)}"

    media_count = 0
    if flowkit_project:
        staged = await _stage_flowkit_project(flowkit_project.strip(), task_tag)
        entry["video_source"] = "local"
        entry["video_materials"] = staged.get("video_materials", [])
        if not script and staged.get("video_script"):
            entry["video_script"] = staged["video_script"]
        media_count = len(entry["video_materials"])

    manifest = manifest_dir / f"agent_{task_tag}.json"
    manifest.write_text(json.dumps([entry], ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "manifest": str(manifest),
        "video_subject": entry["video_subject"],
        "video_source": entry.get("video_source", "pexels"),
        "material_count": len(entry.get("video_materials", [])),
        "media_staged": media_count,
        "script_chars": len(entry.get("video_script", "")),
        "settings_applied": sorted(
            k
            for k in entry
            if k not in ("video_subject", "video_script", "video_terms")
        ),
    }
