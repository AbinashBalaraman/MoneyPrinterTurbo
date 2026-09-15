"""DIRECTOR department — story: scripts, pacing, characters, continuity.

Thin wrappers over the pipeline CLI's own verbs (`direct`, `storyboard`) plus the
continuity ledger. Deliberately no story logic here: the director lives in
``shorts_content_engine/src/director/`` and this must not become a second one.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.operations.registry import RISK_READ, RISK_WRITE, OperationError, operation
from agent.operations.shell import run_pipeline_cli

logger = logging.getLogger(__name__)


def validate_manifest(manifest: dict) -> dict:
    """Check an episode manifest: 4-6 scenes, <=10s each, 30-50s total.

    A pure function rather than a CLI call, because the model usually has the
    manifest *in the conversation* and asking it to write a file first just to
    have it validated is a pointless round trip.
    """
    if not isinstance(manifest, dict):
        return {"valid": False, "errors": ["manifest must be an object"]}

    scenes = manifest.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return {"valid": False, "errors": ["manifest.scenes must be a non-empty array"]}

    errors: list[str] = []
    if not 4 <= len(scenes) <= 6:
        errors.append(f"scenes count {len(scenes)}: want 4-6")

    total = 0.0
    phases: list[str] = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            errors.append(f"scene {i}: must be an object")
            continue
        try:
            duration = float(scene.get("duration", 0) or 0)
        except (TypeError, ValueError):
            errors.append(f"scene {i}: bad duration")
            continue
        total += duration
        if duration > 10.0:
            errors.append(f"scene {i}: duration {duration}s exceeds the 10s limit")
        if scene.get("phase"):
            phases.append(str(scene["phase"]))
        if not (scene.get("narrator_text") or scene.get("image_prompt") or scene.get("prompt")):
            errors.append(f"scene {i}: missing narrator_text/image_prompt")

    if total and not 30 <= total <= 60:
        errors.append(f"total duration {total:.1f}s: want 30-50s")

    return {
        "valid": not errors,
        "errors": errors,
        "scene_count": len(scenes),
        "total_duration": round(total, 1),
        "phases": phases,
    }


@operation(
    name="validate_script",
    department="director",
    risk=RISK_READ,
    description="Check an episode manifest: 4-6 scenes, <=10s each, 30-50s total, 5-phase arc.",
    args={"manifest": {"scenes": [{"duration": 8, "phase": "Hook", "image_prompt": "…"}]}},
)
async def validate_script(manifest: dict | None = None) -> dict:
    """Validate an episode manifest held in the conversation."""
    return validate_manifest(manifest or {})


@operation(
    name="continuity_status",
    department="director",
    risk=RISK_READ,
    description="Series continuity: episode history, last cliffhanger, next hook.",
    args={"series_id": "optional"},
)
async def continuity_status(series_id: str | None = None) -> dict:
    """Continuity state from the ledger.

    Reads the same ledger the dashboard's continuity panel uses. Imported from
    ``api/continuity.py`` rather than reimplemented — that module owns the
    ledger shape, and a second reader would drift from it.
    """
    from agent.api import continuity

    try:
        state = await continuity.get_ledger_state()
    except Exception as exc:  # noqa: BLE001 - a missing ledger is not a crash
        raise OperationError(f"Could not read the continuity ledger: {exc}")

    if not series_id:
        return state

    series = [s for s in (state.get("series") or []) if s.get("id") == series_id]
    if not series:
        raise OperationError(f"No series {series_id!r} in the continuity ledger.")
    return {**state, "series": series}


@operation(
    name="direct_episode",
    department="director",
    risk=RISK_WRITE,
    description="Direct the next episode: script, pacing and the 5-phase retention arc.",
    args={"series_id": "series identifier", "episode": "optional index", "output_manifest": "optional path"},
)
async def direct_episode(
    series_id: str,
    episode: int | None = None,
    output_manifest: str | None = None,
) -> dict:
    """Direct an episode through the pipeline CLI."""
    if not (series_id or "").strip():
        raise OperationError("direct_episode needs a 'series_id'.")

    argv = ["direct", "--series-id", series_id]
    if episode is not None:
        argv += ["--episode", str(int(episode))]
    if output_manifest:
        argv += ["--output-manifest", output_manifest]

    result = await run_pipeline_cli(argv, timeout=600)
    if result.get("exit_code") != 0:
        raise OperationError(
            f"direct failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result


@operation(
    name="storyboard",
    department="director",
    risk=RISK_WRITE,
    description="Generate slideshow still-image prompts plus a PDF storyboard from an episode script.",
    args={"manifest_path": "path to the episode manifest JSON", "style": "cinematic_photorealistic"},
)
async def storyboard(
    manifest_path: str, style: str = "cinematic_photorealistic"
) -> dict:
    """Produce storyboard prompts and a PDF."""
    if not (manifest_path or "").strip():
        raise OperationError("storyboard needs a 'manifest_path'.")

    result = await run_pipeline_cli(
        ["storyboard", "--manifest", manifest_path, "--style", style], timeout=600
    )
    if result.get("exit_code") != 0:
        raise OperationError(
            f"storyboard failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result
