"""Read API for the structured log bus.

The dashboard tails logs over the WebSocket for live output. This endpoint
serves history: initial page load, scroll-back, filtering, and catch-up after a
reconnect (by passing ``since``).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
async def get_logs(
    since: int | None = Query(
        default=None,
        description="Return only records with seq greater than this. Exclusive.",
    ),
    limit: int = Query(default=500, ge=0, le=5000),
    level: str | None = Query(
        default=None,
        description="Comma-separated levels to include, e.g. 'WARNING,ERROR'.",
    ),
    stage: str | None = Query(default=None, description="Exact stage name to include."),
    search: str | None = Query(default=None, description="Case-insensitive substring match."),
    ascending: bool = Query(default=True, description="Oldest first when true."),
):
    """Return retained log records plus the cursor to resume from.

    Thin wrapper over the ``read_logs`` operation — one implementation, two
    front doors. Extra query params pass straight through to the operation so
    behaviour cannot drift.
    """
    from agent.operations import registry

    op = registry.get("read_logs")
    if op is None:
        raise HTTPException(503, "read_logs operation missing")
    result = await op.handler(
        limit=limit,
        level=level,
        since=since,
        stage=stage,
        search=search,
        ascending=ascending,
    )
    return {
        "records": result["records"],
        "latest_seq": result["latest_seq"],
        "retained": result["retained"],
        "dropped": result["dropped"],
        "stages": result["stages"],
    }


@router.get("/stages")
async def get_stages():
    """Distinct stage names seen so far, for building a filter control."""
    from agent.operations import registry

    op = registry.get("read_logs")
    if op is None:
        raise HTTPException(503, "read_logs operation missing")
    result = await op.handler(limit=1)
    return {"stages": result["stages"]}
