"""PUBLISH department — getting the video onto the platforms, and tracking it.

The one department whose operations are **destructive**: publishing is public and
irreversible. The CLI's `--mock` flag defaults to true, so a real publish has to
ask for `--live` explicitly — two independent guards, because a mistake here is
visible to the world rather than merely expensive.
"""

from __future__ import annotations

import logging

from agent.operations.registry import RISK_DESTRUCTIVE, RISK_READ, OperationError, operation
from agent.operations.shell import run_pipeline_cli
from agent.services.ledger import ledger_path

logger = logging.getLogger(__name__)

_PLATFORMS = ("youtube", "tiktok", "instagram")
_PRIVACY = ("public", "unlisted", "private")


@operation(
    name="publication_status",
    department="publish",
    risk=RISK_READ,
    description="What has been published, to which platforms, and whether it succeeded.",
    args={"video_id": "optional FlowKit video id"},
)
async def publication_status(video_id: str | None = None) -> dict:
    """Publication records from the FlowKit server."""
    from agent.db import crud

    if video_id:
        rows = await crud.list_publications(video_id=video_id)
    else:
        rows = await crud.list_all_publications()

    counts: dict[str, int] = {}
    for row in rows:
        key = row.get("status") or "?"
        counts[key] = counts.get(key, 0) + 1

    return {
        "total": len(rows),
        "counts": counts,
        "publications": [
            {
                "id": r.get("id"),
                "video_id": r.get("video_id"),
                "platform": r.get("platform"),
                "status": r.get("status"),
                "url": r.get("video_url") or r.get("post_id"),
                "is_mock": bool(r.get("is_mock")),
            }
            for r in rows[:25]
        ],
        "note": "Capped at 25, newest first.",
    }


@operation(
    name="publish_episode",
    department="publish",
    risk=RISK_DESTRUCTIVE,
    description=(
        "Publish an episode to YouTube Shorts / TikTok / Instagram Reels. "
        "PUBLIC AND IRREVERSIBLE — requires explicit confirmation."
    ),
    args={
        "series_id": "series identifier",
        "episode": 1,
        "platforms": "youtube,tiktok,instagram",
        "confirm": "must be true to actually publish",
    },
)
async def publish_episode(
    series_id: str,
    episode: int,
    platforms: str = "youtube,tiktok,instagram",
    privacy: str = "public",
    confirm: bool = False,
) -> dict:
    """Publish an episode via the pipeline CLI, with `--live`."""
    if not (series_id or "").strip():
        raise OperationError("publish_episode needs a 'series_id'.")
    if episode is None:
        raise OperationError("publish_episode needs an 'episode' number.")
    if not confirm:
        # Belt and braces: the risk gate already asked for a confirm token, but
        # this operation is public and irreversible, so it checks again.
        raise OperationError(
            "Refused: publishing is public and irreversible. Re-issue with "
            '"confirm": true once the user has explicitly agreed.'
        )

    wanted = [p.strip() for p in (platforms or "").split(",") if p.strip()]
    unknown = [p for p in wanted if p not in _PLATFORMS]
    if unknown:
        raise OperationError(
            f"Unknown platform(s) {unknown}. Known: {', '.join(_PLATFORMS)}."
        )
    if privacy not in _PRIVACY:
        raise OperationError(f"Unknown privacy {privacy!r}. Known: {', '.join(_PRIVACY)}.")

    result = await run_pipeline_cli(
        [
            "publish",
            "--series-id", series_id,
            "--episode", str(int(episode)),
            "--platforms", ",".join(wanted),
            "--privacy", privacy,
            "--live",
            "--db-path", ledger_path(),
        ],
        timeout=1800,
    )
    if result.get("exit_code") != 0:
        raise OperationError(
            f"publish failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result
