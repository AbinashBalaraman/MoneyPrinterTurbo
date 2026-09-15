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


def _mask(val: str | None) -> str | None:
    if not val or not val.strip():
        return None
    v = val.strip()
    if len(v) <= 8:
        return "********"
    return f"{v[:4]}...{v[-4:]}"


@operation(
    name="credentials_status",
    department="ops",
    risk=RISK_READ,
    description="Inspect configuration status of external API keys & OAuth credentials across the pipeline.",
    takes_args=False,
)
async def credentials_status() -> dict:
    """Check availability of external keys and platform distribution credentials."""
    import os
    from agent import config

    google_key = getattr(config, "GOOGLE_API_KEY", None) or os.environ.get("GOOGLE_API_KEY", "")
    opencode_key = getattr(config, "OPENCODE_API_KEY", None) or os.environ.get("OPENCODE_API_KEY", "")
    anthropic_key = getattr(config, "ANTHROPIC_API_KEY", None) or os.environ.get("ANTHROPIC_API_KEY", "")
    suno_key = getattr(config, "SUNO_API_KEY", None) or os.environ.get("SUNO_API_KEY", "")

    yt_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    yt_sec = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    yt_ref = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()

    tt_tok = os.environ.get("TIKTOK_ACCESS_TOKEN", "").strip()
    tt_id = os.environ.get("TIKTOK_OPEN_ID", "").strip()

    ig_tok = os.environ.get("INSTAGRAM_ACCESS_TOKEN", "").strip()
    ig_id = os.environ.get("INSTAGRAM_ACCOUNT_ID", "").strip()

    eleven_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    azure_key = os.environ.get("AZURE_SPEECH_KEY", "").strip()

    providers = {
        "google_flow": {
            "name": "Google Flow / Veo / Gemini",
            "department": "render",
            "configured": bool(google_key),
            "preview": _mask(google_key),
            "purpose": "Google Flow batch execution and still conditioning",
        },
        "opencode": {
            "name": "OpenCode AI Studio",
            "department": "assistant",
            "configured": bool(opencode_key),
            "preview": _mask(opencode_key),
            "purpose": "Autonomous Chat Studio operator and scriptwriting",
        },
        "youtube": {
            "name": "YouTube Data API v3",
            "department": "publish",
            "configured": bool(yt_id and yt_sec and yt_ref),
            "details": {
                "client_id": bool(yt_id),
                "client_secret": bool(yt_sec),
                "refresh_token": bool(yt_ref),
            },
            "purpose": "Direct YouTube Shorts automated distribution",
        },
        "tiktok": {
            "name": "TikTok Content Posting API",
            "department": "publish",
            "configured": bool(tt_tok and tt_id),
            "purpose": "Direct TikTok video publishing",
        },
        "instagram": {
            "name": "Instagram Graph API (Reels)",
            "department": "publish",
            "configured": bool(ig_tok and ig_id),
            "purpose": "Direct Instagram Reels publishing",
        },
        "suno": {
            "name": "Suno Music API",
            "department": "assembly",
            "configured": bool(suno_key),
            "preview": _mask(suno_key),
            "purpose": "AI background music generation",
        },
        "elevenlabs": {
            "name": "ElevenLabs TTS",
            "department": "assembly",
            "configured": bool(eleven_key),
            "preview": _mask(eleven_key),
            "purpose": "High-fidelity AI voice narration",
        },
        "azure_speech": {
            "name": "Azure Speech Services",
            "department": "assembly",
            "configured": bool(azure_key),
            "preview": _mask(azure_key),
            "purpose": "Multi-lingual TTS speech synthesis",
        },
    }

    configured_count = sum(1 for p in providers.values() if p["configured"])

    return {
        "total_providers": len(providers),
        "configured_count": configured_count,
        "providers": providers,
        "env_file": "AutoShorts/.env",
        "note": "Secrets are masked for security. Edit AutoShorts/.env to configure missing providers.",
    }

