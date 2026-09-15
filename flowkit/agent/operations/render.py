"""RENDER department — turning prompts into media, via Google Flow.

Owns the queue, the worker, the extension bridge, and the client that drives it.
The operations here are the *read* side (what is in the queue, what failed, what
generated without conditioning) plus the one that spends money.

Ported from the hand-written tools in ``services/chat_agent.py`` so there is a
single implementation. Behaviour is unchanged; the shapes are the same.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.operations.registry import RISK_READ, RISK_SPEND, OperationError, operation

logger = logging.getLogger(__name__)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[truncated, {len(text) - limit} more characters]"


@operation(
    name="project_list",
    department="render",
    risk=RISK_READ,
    description="List FlowKit projects (id, name, status).",
    takes_args=False,
)
async def project_list() -> dict:
    """List projects, newest first."""
    from agent.db import crud

    projects = await crud.list_projects()
    return {
        "projects": [
            {"id": p.get("id"), "name": p.get("name"), "status": p.get("status")}
            for p in projects[:50]
        ],
        "note": "Capped at 50, newest first.",
    }


@operation(
    name="project_status",
    department="render",
    risk=RISK_READ,
    description="Pipeline snapshot: scenes, per-status request counts, recent failures.",
    args={"project_id": "optional"},
)
async def project_status(project_id: str | None = None) -> dict:
    """Scenes, request counts and recent failures for a project."""
    from agent.db import crud

    pid = (project_id or "").strip()
    project = await crud.get_project(pid) if pid else None

    if project is None:
        projects = await crud.list_projects()
        if not projects:
            return {"projects": [], "note": "No projects exist yet."}
        project = projects[0]

    videos = await crud.list_videos(project_id=project["id"])
    video = videos[0] if videos else None
    scenes = await crud.list_scenes(video_id=video["id"]) if video else []
    requests = await crud.list_requests(project_id=project["id"])

    counts: dict[str, int] = {}
    for req in requests:
        counts[req["status"]] = counts.get(req["status"], 0) + 1

    failures = [
        {"type": req["type"], "error": _truncate(str(req.get("error_message") or ""), 200)}
        for req in requests
        if req["status"] == "FAILED"
    ]

    return {
        "project": {
            "id": project["id"],
            "name": project.get("name"),
            "status": project.get("status"),
        },
        "video": (
            {"id": video["id"], "title": video.get("title"), "status": video.get("status")}
            if video
            else None
        ),
        "scene_count": len(scenes),
        "scenes": [
            {
                "order": s.get("display_order"),
                "image": s.get("vertical_image_status"),
                "video": s.get("vertical_video_status"),
            }
            for s in scenes[:25]
        ],
        "request_counts": counts,
        "failed_requests": failures[:10],
        "note": "Scenes capped at 25, failed_requests at 10.",
    }


@operation(
    name="queue_status",
    department="render",
    risk=RISK_READ,
    description="Request queue counts only — quicker than project_status.",
    args={"project_id": "optional", "video_id": "optional"},
)
async def queue_status(project_id: str | None = None, video_id: str | None = None) -> dict:
    """Pending/processing/completed/failed counts for the request queue."""
    from agent.db import crud

    rows = await crud.list_requests(
        project_id=(project_id or None),
        video_id=(video_id or None),
    )
    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("status") or "?"
        counts[key] = counts.get(key, 0) + 1

    outstanding = counts.get("PENDING", 0) + counts.get("PROCESSING", 0)
    return {
        "total": len(rows),
        "counts": counts,
        "outstanding": outstanding,
        "settled": outstanding == 0,
    }


@operation(
    name="consistency_check",
    department="render",
    risk=RISK_READ,
    description=(
        "Scenes that generated without character reference conditioning "
        "(the character will look inconsistent)."
    ),
    args={"project_id": "optional"},
)
async def consistency_check(project_id: str | None = None) -> dict:
    """Which scenes were generated without reference conditioning."""
    from agent.services import consistency

    return await consistency.unconditioned_scenes(project_id)


@operation(
    name="generate_episode",
    department="render",
    risk=RISK_SPEND,
    description=(
        "Queue stills and video for an episode manifest. SPENDS MONEY — requires "
        "spending to be enabled."
    ),
    args={"manifest_path": "path to the episode manifest JSON"},
)
async def generate_episode(manifest_path: str) -> dict:
    """Queue media generation for a manifest via the SCE pipeline.

    Thin wrapper over the existing CLI verb — deliberately no new pipeline logic
    here, so this cannot diverge from the CLI path the unattended runner uses.
    """
    from agent.operations.shell import run_pipeline_cli

    if not (manifest_path or "").strip():
        raise OperationError("generate_episode needs a 'manifest_path'.")

    result = await run_pipeline_cli(["generate", "--manifest", manifest_path], timeout=1800)
    if result.get("exit_code") != 0:
        raise OperationError(
            f"generate failed (exit {result.get('exit_code')}): "
            f"{_truncate(result.get('output') or '', 800)}"
        )
    return result


ONEOFF_VIDEO_TITLE = "One-off images"


@operation(
    name="generate_image",
    department="render",
    risk=RISK_SPEND,
    description=(
        "Queue ONE standalone still image in Google Flow from a text prompt. "
        "SPENDS MONEY — requires spending to be enabled."
    ),
    args={"prompt": "the image prompt", "project_id": "optional", "orientation": "optional: VERTICAL or HORIZONTAL"},
)
async def generate_image(
    prompt: str,
    project_id: str | None = None,
    orientation: str = "VERTICAL",
) -> dict:
    """Queue a single Flow still outside any episode.

    Creates the scene under a `"One-off images"` video in the project (never
    inside an episode video, so episode assemblage is untouched) plus one
    ``GENERATE_IMAGE`` request. The worker picks it up when the Chrome
    extension is connected; until then it stays PENDING.
    """
    from agent.db import crud

    prompt = (prompt or "").strip()
    if not prompt:
        raise OperationError("generate_image needs a 'prompt'.")
    orient = (orientation or "VERTICAL").strip().upper()
    if orient not in ("VERTICAL", "HORIZONTAL"):
        raise OperationError("orientation must be VERTICAL or HORIZONTAL.")

    pid = (project_id or "").strip()
    project = await crud.get_project(pid) if pid else None
    if project is None:
        projects = await crud.list_projects()
        if not projects:
            raise OperationError("No projects exist yet — direct an episode first.")
        project = projects[0]

    videos = await crud.list_videos(project_id=project["id"])
    video = next((v for v in videos if (v.get("title") or "") == ONEOFF_VIDEO_TITLE), None)
    if video is None:
        video = await crud.create_video(
            project_id=project["id"],
            title=ONEOFF_VIDEO_TITLE,
            description="Standalone images queued from chat; not part of any episode.",
            orientation=orient,
        )

    scenes = await crud.list_scenes(video_id=video["id"])
    scene = await crud.create_scene(
        video_id=video["id"],
        display_order=len(scenes),
        prompt=prompt,
        image_prompt=prompt,
        source="oneoff",
    )
    req = await crud.create_request(
        "GENERATE_IMAGE",
        orientation=orient,
        scene_id=scene["id"],
        project_id=project["id"],
        video_id=video["id"],
    )
    return {
        "request_id": req["id"],
        "scene_id": scene["id"],
        "video_id": video["id"],
        "project": {"id": project["id"], "name": project.get("name")},
        "orientation": orient,
        "status": req.get("status"),
        "note": (
            "Queued as PENDING. The worker dispatches it when the Chrome "
            "extension is connected; check queue_status for progress."
        ),
    }


def _json_or_none(raw: Any) -> Any:
    """Best-effort JSON parse, used for CLI output passthrough."""
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
