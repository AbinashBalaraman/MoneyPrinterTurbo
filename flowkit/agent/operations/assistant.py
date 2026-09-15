"""ASSISTANT department — the chatbot's own capabilities.

Web search and long-term memory. These are the only operations that are *about*
the assistant rather than about the pipeline, which is why they are grouped here
instead of being spread across the departments they happen to serve.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.operations.registry import RISK_READ, RISK_WRITE, OperationError, operation

logger = logging.getLogger(__name__)

MEMORY_PROMPT_CHARS = 4_000


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[truncated, {len(text) - limit} more characters]"


@operation(
    name="web_search",
    department="assistant",
    risk=RISK_READ,
    description="Search the live web (TinyFish). Use for anything current, or to check a library/API.",
    args={"query": "search terms", "max_results": 5},
)
async def web_search(
    query: str,
    max_results: int = 5,
    domain_type: str = "web",
    recency_minutes: int | None = None,
    location: str | None = None,
    language: str | None = None,
    purpose: str | None = None,
) -> dict:
    """Run a web search."""
    from agent.services import web_search as search_service

    query = (query or "").strip()
    if not query:
        raise OperationError("web_search needs a 'query'.")

    try:
        limit = int(max_results or 5)
    except (TypeError, ValueError):
        limit = 5

    out = await search_service.search(
        query,
        purpose=purpose,
        max_results=max(1, min(limit, 20)),
        domain_type=domain_type or "web",
        recency_minutes=recency_minutes,
        location=location,
        language=language,
    )
    if "error" in out:
        raise OperationError(out["error"])
    return out


@operation(
    name="memory_read",
    department="assistant",
    risk=RISK_READ,
    description="Read long-term memory notes from previous sessions.",
    takes_args=False,
)
async def memory_read() -> dict:
    """Read the assistant's long-term memory."""
    from agent.services import agent_memory

    content = agent_memory.read_memory()
    if not content.strip():
        return {"memory": "", "note": "Long-term memory is empty."}
    return {"memory": _truncate(content, MEMORY_PROMPT_CHARS)}


@operation(
    name="memory_append",
    department="assistant",
    risk=RISK_WRITE,
    description="Append a durable fact or preference to long-term memory.",
    args={"text": "the note to remember"},
)
async def memory_append(text: str) -> dict:
    """Append one note to long-term memory."""
    from agent.services import agent_memory

    text = (text or "").strip()
    if not text:
        raise OperationError("memory_append needs 'text'.")
    agent_memory.append_memory(text)
    return {"saved": text}


@operation(
    name="memory_write",
    department="assistant",
    risk=RISK_WRITE,
    description="Replace the whole memory document. Use sparingly.",
    args={"content": "the full replacement text"},
)
async def memory_write(content: str | None = None) -> dict:
    """Replace the memory document."""
    from agent.services import agent_memory

    if content is None:
        raise OperationError("memory_write needs 'content'.")
    written = agent_memory.write_memory(str(content))
    return {"chars": len(written)}
