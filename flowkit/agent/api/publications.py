"""Publish outcomes.

The dashboard cannot publish. Uploading belongs to ``shorts_content_engine``,
which is headless by design; it reports each platform outcome here and this
router stores and serves it. That keeps one UI, one WebSocket and one log bus
instead of a second backend for the browser to talk to.

Every write is logged under the ``publish`` stage, so publish activity shows up
in the Publish node of the pipeline rail alongside everything else.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from agent.db import crud
from agent.models.publication import (
    Publication,
    PublicationCreate,
    PublicationListResponse,
    PublicationSummary,
    RetryRequest,
)
from agent.services.event_bus import event_bus
from agent.services.log_bus import log_stage
from agent.services.stages import STAGE_PUBLISH

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publications"])


def _to_model(row: dict) -> Publication:
    """Convert a stored row into the API model.

    ``metadata`` is JSON in the database; a malformed value must not take down
    the whole list, so it degrades to an empty object.
    """
    data = dict(row)
    raw = data.get("metadata")
    if isinstance(raw, str):
        try:
            data["metadata"] = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            data["metadata"] = {"_unparsable": raw[:200]}
    elif raw is None:
        data["metadata"] = {}
    data["is_mock"] = bool(data.get("is_mock"))
    return Publication(**data)


@router.get("/videos/{vid}/publications", response_model=PublicationListResponse)
async def list_publications(vid: str):
    """Every publish outcome for a video, plus server-computed counts."""
    video = await crud.get_video(vid)
    if not video:
        raise HTTPException(404, "Video not found")

    rows = await crud.list_publications(vid)
    return PublicationListResponse(
        video_id=vid,
        publications=[_to_model(r) for r in rows],
        summary=PublicationSummary.from_rows(rows),
    )


@router.post("/videos/{vid}/publications", response_model=Publication)
async def report_publication(vid: str, body: PublicationCreate):
    """Record one platform outcome, as reported by the directing engine."""
    video = await crud.get_video(vid)
    if not video:
        raise HTTPException(404, "Video not found")

    with log_stage(STAGE_PUBLISH):
        try:
            row = await crud.record_publication(
                video_id=vid,
                platform=body.platform,
                status=body.status,
                post_id=body.post_id,
                video_url=body.video_url,
                error_message=body.error_message,
                is_mock=body.is_mock,
                metadata=body.metadata,
                published_at=body.published_at,
                project_id=video.get("project_id"),
            )
        except ValueError as e:
            # The honesty rules live in crud; surface them as a 422, not a 500.
            raise HTTPException(422, str(e))

        if body.is_mock:
            logger.info(
                "Publish DRY RUN for %s on %s — nothing was posted",
                vid[:8], body.platform,
            )
        elif body.status == "published":
            logger.info("Published %s to %s as %s", vid[:8], body.platform, body.post_id)
        elif body.status == "failed":
            logger.warning("Publish FAILED for %s on %s: %s", vid[:8], body.platform, body.error_message)

    await event_bus.emit("publication_update", {
        "video_id": vid, "platform": body.platform,
        "status": body.status, "is_mock": body.is_mock,
    })
    return _to_model(row)


@router.post("/videos/{vid}/publications/retry", response_model=PublicationListResponse)
async def request_retry(vid: str, body: Optional[RetryRequest] = None):
    """Queue a re-attempt for one or more platforms.

    The dashboard cannot upload, so this records an intent that the directing
    engine collects from ``/publications/pending``. The row stays ``requested``
    until something actually acts on it — the UI never shows a retry as done
    just because it was asked for.
    """
    video = await crud.get_video(vid)
    if not video:
        raise HTTPException(404, "Video not found")

    body = body or RetryRequest()
    reason = body.reason

    if body.platforms:
        platforms = [p.strip().lower() for p in body.platforms if p.strip()]
    else:
        # Default to everything that did not succeed live.
        rows = await crud.list_publications(vid)
        latest: dict[str, dict] = {}
        for r in rows:  # newest first
            latest.setdefault(r["platform"], r)
        platforms = [
            p for p, r in latest.items()
            if r.get("status") != "published" or r.get("is_mock")
        ]

    if not platforms:
        raise HTTPException(409, "Nothing to retry: every platform already published live")

    with log_stage(STAGE_PUBLISH):
        queued = []
        for platform in platforms:
            row = await crud.request_publication_retry(
                video_id=vid, platform=platform,
                project_id=video.get("project_id"), reason=reason,
            )
            queued.append(row)
        logger.info("Queued publish retry for %s: %s", vid[:8], ", ".join(platforms))

    await event_bus.emit("publication_update", {
        "video_id": vid, "status": "requested", "platforms": platforms,
    })

    rows = await crud.list_publications(vid)
    return PublicationListResponse(
        video_id=vid,
        publications=[_to_model(r) for r in rows],
        summary=PublicationSummary.from_rows(rows),
    )


@router.get("/publications/pending", response_model=list[Publication])
async def list_pending():
    """Queued retries, for the directing engine to collect."""
    rows = await crud.list_publications_by_status("requested")
    return [_to_model(r) for r in rows]
