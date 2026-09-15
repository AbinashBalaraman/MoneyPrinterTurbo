"""OPS department — the substrate: shell access and log reading.

Not a pipeline stage. These are the operations that let the assistant see *how*
the machine is behaving rather than what the pipeline contains.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.operations.registry import RISK_READ, RISK_WRITE, operation
from agent.operations.shell import run_shell

logger = logging.getLogger(__name__)


@operation(
    name="run_command",
    department="ops",
    risk=RISK_WRITE,
    description=(
        "Run a shell command in the workspace and return its output. "
        "The cwd is pinned to the workspace; this is a guardrail, not a sandbox."
    ),
    args={"command": "shell command", "cwd": "optional relative dir", "timeout_s": 30},
)
async def run_command(
    command: str, cwd: str | None = None, timeout_s: float = 30.0
) -> dict:
    """Run a shell command in the workspace.

    Deliberately `write`, not `destructive`. Marking it destructive would require
    a confirmation token, and the only token available is one the *model* sets —
    so it would be a speed bump that looks like a safety check while checking
    nothing. The real controls are the ones that actually bind: the cwd is pinned
    to the workspace, catastrophic patterns are refused, output is capped, and
    the user asked for terminal access explicitly. The Terminal tab is a full
    unsandboxed shell by design, so gating only the chat would be inconsistent
    theatre.
    """
    return await run_shell(command, cwd=cwd, timeout_s=timeout_s)


@operation(
    name="read_logs",
    department="ops",
    risk=RISK_READ,
    description="Recent log records from the agent, newest last. Use to diagnose a failure.",
    args={
        "limit": 50,
        "level": "optional: INFO/WARNING/ERROR/CRITICAL",
        "since": "optional: only records with seq greater than this",
        "stage": "optional: exact stage name",
        "search": "optional: case-insensitive substring",
    },
)
async def read_logs(
    limit: int = 50,
    level: str | None = None,
    since: int | None = None,
    stage: str | None = None,
    search: str | None = None,
    ascending: bool = True,
) -> dict:
    """Read recent log records from the in-process log bus.

    ``log_bus.history`` already filters by level and returns plain dicts, so this
    is a thin pass-through rather than a second reader that could disagree with
    what the dashboard's Logs tab shows.

    Extended filter set (since/stage/search) exists so the REST route
    ``GET /api/logs`` can delegate here instead of calling the service layer
    directly — one implementation, two front doors.
    """
    from agent.services.log_bus import log_bus

    if limit is None:
        count = 50
    else:
        try:
            count = int(limit)
        except (TypeError, ValueError):
            count = 50
    count = max(0, min(count, 5000))

    records = log_bus.history(
        since=since,
        limit=count,
        level=level or None,
        stage=stage,
        search=search,
        ascending=ascending,
    )
    return {
        # `count` is a @property, not a method.
        "buffered": log_bus.count,
        "returned": len(records),
        "records": records,
        "latest_seq": log_bus.latest_seq,
        "retained": log_bus.count,
        "dropped": log_bus.dropped,
        "stages": log_bus.stages(),
        "note": "Oldest first within the returned window; newest last.",
    }
