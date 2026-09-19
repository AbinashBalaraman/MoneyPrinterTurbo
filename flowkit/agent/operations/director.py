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
from agent.services.ledger import ledger_path

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

    # The ledger's series records key on `series_id`, not `id` — filtering on
    # `id` matched nothing, so asking for a series that existed still answered
    # "No series ... in the continuity ledger". `id` is accepted as well only so
    # a future ledger shape does not reintroduce the same silent miss.
    series = [
        s
        for s in (state.get("series") or [])
        if series_id in (s.get("series_id"), s.get("id"))
    ]
    if not series:
        raise OperationError(f"No series {series_id!r} in the continuity ledger.")
    return {**state, "series": series}


@operation(
    name="create_series",
    department="director",
    risk=RISK_WRITE,
    description=(
        "Create a new series in the continuity ledger. Everything else that "
        "makes episodes needs the series to exist first, so this is the step to "
        "call when asked to start a new series."
    ),
    args={
        "series_id": "unique id, e.g. interesting_facts",
        "title": "display title",
        "genre": "narrative genre, e.g. 'Cyberpunk Noir'",
        "logline": "optional core premise",
        "target_duration": "optional seconds per episode (default 45)",
        "pacing_rhythm": "pulse_action or noir_suspense",
        "seed_characters": "seed the default recurring characters (default true)",
    },
)
async def create_series(
    series_id: str,
    title: str,
    genre: str,
    logline: str = "",
    target_duration: float | None = None,
    pacing_rhythm: str | None = None,
    seed_characters: bool = True,
) -> dict:
    """Create a series through the pipeline CLI's ``init-series`` verb.

    This exists because its absence was a real, reproducible failure: asked to
    "create new series 'interesting facts' create first video", the assistant
    called ``direct_episode``, which correctly refused with "Run 'init-series
    --series-id ...' first" -- and then had no way to run it. It spent its
    remaining rounds on `dir` and on probing for modules that do not exist
    (`python -m automation.director`, `python -m pipeline`, `python -m ledger`),
    and answered with nothing.

    The capability was never missing from the project, only from the catalogue:
    ``init-series`` has been in ``shorts_content_engine/src/cli.py`` all along.
    A tool the model cannot see is a tool it does not have.
    """
    for field, value in (("series_id", series_id), ("title", title), ("genre", genre)):
        if not (value or "").strip():
            raise OperationError(f"create_series needs a '{field}'.")

    argv = [
        "init-series",
        "--series-id",
        series_id.strip(),
        "--title",
        title.strip(),
        "--genre",
        genre.strip(),
        # Explicit, because the CLI's default is relative to its cwd and lands
        # in a different file than the one continuity_status reads.
        "--db-path",
        ledger_path(),
    ]
    if logline:
        argv += ["--logline", logline]
    if target_duration is not None:
        argv += ["--target-duration", str(float(target_duration))]
    if pacing_rhythm:
        # Passed through rather than validated here: argparse owns the allowed
        # values, and it rejects a bad one loudly.
        argv += ["--pacing-rhythm", pacing_rhythm]
    if not seed_characters:
        argv += ["--no-seed-characters"]

    result = await run_pipeline_cli(argv, timeout=300)
    if result.get("exit_code") != 0:
        output = (result.get("output") or "")[:800]
        raise OperationError(
            f"init-series failed (exit {result.get('exit_code')}): {output}"
        )
    return result


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

    argv = ["direct", "--series-id", series_id, "--db-path", ledger_path()]
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
