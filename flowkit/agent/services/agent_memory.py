"""Persistent memory for the in-app assistant.

Two things live here:

* **Long-term memory** (``memory.md``) — durable facts, preferences and project
  conventions the assistant should remember across sessions.
* **Conversations** (``conversations/<id>.json``) — persisted chat history.

Where the files live, and why it moved
--------------------------------------
Runtime data sits under ``flowkit/agent_data/``, next to ``flow_agent.db`` —
the same convention the database already follows.

It was originally under ``AutoShorts/.workbuddy-ai/agent/``, which was a mistake:
that folder is *protected project data*, and this environment's safe-delete shim
refuses deletions inside it. Deleting a conversation is an ordinary user action
(``DELETE /api/agent/conversations/{id}``), so it must not live somewhere that
blocks deletion — it produced a 500 on every delete. (A third reason, dodging a
collision with the since-removed vendored VS Code extension, no longer applies:
that extension was deleted from the repo on 2026-09-17.)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from agent import config

logger = logging.getLogger(__name__)

BASE_DIR = Path(config.BASE_DIR) / "agent_data"
MEMORY_FILE = BASE_DIR / "memory.md"
CONVERSATIONS_DIR = BASE_DIR / "conversations"

MAX_CONVERSATIONS = 50
MAX_MEMORY_CHARS = 50_000

_SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure() -> None:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    CONVERSATIONS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Long-term memory ────────────────────────────────────────

def read_memory() -> str:
    try:
        return MEMORY_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        logger.warning("agent_memory: could not read memory: %s", exc)
        return ""


def write_memory(content: str) -> str:
    """Replace the whole memory document."""
    _ensure()
    content = (content or "")[:MAX_MEMORY_CHARS]
    MEMORY_FILE.write_text(content, encoding="utf-8")
    return content


def append_memory(text: str) -> str:
    """Append a bullet (or raw text) to the memory document."""
    text = (text or "").strip()
    if not text:
        return read_memory()
    current = read_memory()
    line = text if text.startswith(("-", "*", "#")) else f"- {text}"
    sep = "" if (not current or current.endswith("\n")) else "\n"
    return write_memory(f"{current}{sep}{line}\n")


# ─── Conversations ───────────────────────────────────────────

def _safe_id(conversation_id: str) -> str:
    return _SAFE_ID.sub("_", conversation_id or "")[:120]


def _path(conversation_id: str) -> Path:
    return CONVERSATIONS_DIR / f"{_safe_id(conversation_id)}.json"


def list_conversations() -> list[dict]:
    _ensure()
    out = []
    for p in CONVERSATIONS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out.append(
            {
                "id": data.get("id") or p.stem,
                "title": data.get("title") or "Untitled",
                "updated_at": data.get("updated_at") or "",
                "message_count": len(data.get("messages") or []),
            }
        )
    out.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return out[:MAX_CONVERSATIONS]


def load_conversation(conversation_id: str) -> dict | None:
    path = _path(conversation_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def save_conversation(conversation_id: str, messages: list, title: str | None = None) -> dict:
    _ensure()
    record = {
        "id": _safe_id(conversation_id),
        "title": title or "Untitled",
        "updated_at": _now(),
        "messages": messages or [],
    }
    path = _path(conversation_id)
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("agent_memory: could not save conversation: %s", exc)
        raise
    return record


def delete_conversation(conversation_id: str) -> bool:
    """Delete a saved conversation. Returns True when the file is gone.

    Catches broadly and never raises: this is called straight from a request
    handler, and a filesystem refusal must not surface as a 500. A narrow
    ``except OSError`` is not enough here — filesystem shims and antivirus
    layers can raise their own exception types, which is exactly what happened
    when this lived under a protected folder.
    """
    path = _path(conversation_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.warning("agent_memory: could not delete %s: %s", path.name, exc)
        return False
