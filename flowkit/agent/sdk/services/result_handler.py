"""Shared result parsing + DB update helpers for SDK direct execution and background processor."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from agent.db import crud
from agent.utils.entity_match import declared_names, resolve_matched
from agent.worker._parsing import _is_error, _extract_media_id, _extract_output_url

if TYPE_CHECKING:
    from agent.sdk.models.media import GenerationResult

logger = logging.getLogger(__name__)


def parse_result(raw: dict, req_type: str) -> GenerationResult:
    """Parse a raw FlowClient/OperationService response into a GenerationResult."""
    from agent.sdk.models.media import GenerationResult

    if _is_error(raw):
        error_msg = raw.get("error")
        if not error_msg:
            data = raw.get("data", {})
            if isinstance(data, dict):
                ef = data.get("error", "Unknown error")
                error_msg = ef.get("message", str(ef)[:200]) if isinstance(ef, dict) else str(ef)
            else:
                error_msg = "Unknown error"
        return GenerationResult(success=False, error=str(error_msg), raw=raw)

    media_id = _extract_media_id(raw, req_type)
    url = _extract_output_url(raw, req_type)
    return GenerationResult(success=True, media_id=media_id, url=url, raw=raw)


async def _conditioning_record(scene: dict) -> str:
    """JSON list of the reference names this image was actually conditioned on.

    Recorded at completion rather than inferred later, because "was this still
    conditioned?" cannot be answered from the *current* project links: linking a
    character afterwards would make an un-conditioned image look fine. This is
    what lets ``services/consistency.py`` tell the truth about the past.

    An empty list is a real answer — it means the scene named characters but
    none of them were linked with a reference image, so the still rendered
    un-conditioned.
    """
    declared = declared_names(scene)
    if not declared:
        # Names nobody: no reference image was ever needed.
        return json.dumps([])

    project_id = scene.get("_project_id")
    if not project_id:
        video = await crud.get_video(scene.get("video_id")) if scene.get("video_id") else None
        project_id = (video or {}).get("project_id")
    if not project_id:
        return json.dumps([])

    linked = await crud.get_project_characters(project_id)
    matched, _ = resolve_matched(declared, linked, require_media=True)
    # Record the *declared* names that were satisfied, not every alias the
    # entity answers to — the question is "which of the references this scene
    # asked for actually got used".
    return json.dumps(sorted(declared & matched))


async def apply_scene_result(
    scene_id: str | None,
    req_type: str,
    orientation: str,
    result: GenerationResult,
) -> None:
    """Update scene DB fields after a successful generation.

    Handles cascade: image regen clears video+upscale, video regen clears upscale.
    This is the shared version of processor.py's _update_scene_from_result.
    """
    if not scene_id or not result.success:
        return

    p = "vertical" if orientation == "VERTICAL" else "horizontal"
    updates = {}

    if req_type in ("GENERATE_IMAGE", "REGENERATE_IMAGE", "EDIT_IMAGE"):
        updates.update({
            f"{p}_image_media_id": result.media_id,
            f"{p}_image_url": result.url,
            f"{p}_image_status": "COMPLETED",
            # Cascade: clear downstream
            f"{p}_video_media_id": None, f"{p}_video_url": None, f"{p}_video_status": "PENDING",
            f"{p}_upscale_media_id": None, f"{p}_upscale_url": None, f"{p}_upscale_status": "PENDING",
        })
        # Record what this image was really conditioned on, so the report in
        # services/consistency.py is a fact rather than a guess. Best-effort:
        # failing to record must not fail the generation that just succeeded.
        try:
            scene = await crud.get_scene(scene_id)
            if scene:
                updates["conditioned_with"] = await _conditioning_record(scene)
        except Exception:  # noqa: BLE001
            logger.warning("Could not record conditioning for scene %s", scene_id[:8], exc_info=True)

        # Chain cascade: update parent's end_scene_media_id so its video
        # transitions to this child's new image
        scene = await crud.get_scene(scene_id)
        if scene and scene.get("parent_scene_id") and result.media_id:
            await crud.update_scene(
                scene["parent_scene_id"],
                **{f"{p}_end_scene_media_id": result.media_id},
            )
    elif req_type in ("GENERATE_VIDEO", "REGENERATE_VIDEO", "GENERATE_VIDEO_REFS"):
        updates.update({
            f"{p}_video_media_id": result.media_id,
            f"{p}_video_url": result.url,
            f"{p}_video_status": "COMPLETED",
            # Cascade: clear upscale
            f"{p}_upscale_media_id": None, f"{p}_upscale_url": None, f"{p}_upscale_status": "PENDING",
        })
    elif req_type == "UPSCALE_VIDEO":
        updates.update({
            f"{p}_upscale_media_id": result.media_id,
            f"{p}_upscale_url": result.url,
            f"{p}_upscale_status": "COMPLETED",
        })

    if updates:
        await crud.update_scene(scene_id, **updates)


async def apply_character_result(
    character_id: str,
    result: GenerationResult,
) -> None:
    """Update character DB fields after a successful reference image generation."""
    if not result.success:
        return
    updates = {}
    if result.media_id:
        updates["media_id"] = result.media_id
    if result.url:
        updates["reference_image_url"] = result.url
    if updates:
        await crud.update_character(character_id, **updates)
