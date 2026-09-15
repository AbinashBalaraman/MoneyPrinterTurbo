"""Agent capability endpoints — things the in-app assistant can actually *do*.

The chat used to only describe commands. These are the server-side tools that
let it act: web search (TinyFish) and, later, memory.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/agent", tags=["agent"])


class SearchRequest(BaseModel):
    query: str
    purpose: str | None = None
    max_results: int = Field(default=8, ge=1, le=50)
    domain_type: str = "web"
    recency_minutes: int | None = None
    location: str | None = None
    language: str | None = None


@router.get("/search/status")
async def search_status():
    """Whether the TinyFish key is present — the UI hides search when it is not."""
    from agent.services import web_search

    return {"configured": web_search.configured()}


@router.post("/search")
async def search(body: SearchRequest):
    """Run a web search. Always returns 200; failures come back as ``{"error": …}``."""
    from agent.services import web_search

    return await web_search.search(
        body.query,
        purpose=body.purpose,
        max_results=body.max_results,
        domain_type=body.domain_type,
        recency_minutes=body.recency_minutes,
        location=body.location,
        language=body.language,
    )


# ─── Capabilities ────────────────────────────────────────────


@router.get("/capabilities")
async def capabilities():
    """What the assistant can and cannot do right now.

    Exists so the dashboard can state the mode plainly. A gate the user cannot
    see is indistinguishable from the assistant being broken: the model would
    refuse a generation with no visible reason why.
    """
    from agent import config
    from agent.operations import registry

    ops = registry.all_operations()
    by_risk: dict[str, int] = {}
    for op in ops.values():
        by_risk[op.risk] = by_risk.get(op.risk, 0) + 1

    departments = {
        dept: [o.name for o in items]
        for dept, items in registry.by_department().items()
    }

    return {
        "allow_spend": bool(getattr(config, "AGENT_ALLOW_SPEND", False)),
        "operation_count": len(ops),
        "by_risk": by_risk,
        "departments": departments,
        "note": (
            "allow_spend gates every operation whose risk is 'spend' or "
            "'destructive'. Set AGENT_ALLOW_SPEND=1 in AutoShorts/.env and restart "
            "the agent to enable them."
        ),
    }


# ─── Consistency (warn-and-continue report) ──────────────────


@router.get("/consistency")
async def get_consistency(project_id: str | None = None):
    """Scenes that generated without reference conditioning.

    Thin wrapper over the ``consistency_check`` operation — one implementation,
    two front doors. Warn-and-continue means these still produce an image and
    report COMPLETED — the character just will not match the rest of the series.
    """
    from agent.operations import registry

    op = registry.get("consistency_check")
    if op is None:
        raise HTTPException(503, "consistency_check operation missing")
    return await op.handler(project_id)


# ─── Memory ──────────────────────────────────────────────────


class MemoryUpdate(BaseModel):
    """Send ``content`` to replace the document, or ``append`` to add to it."""

    content: str | None = None
    append: str | None = None


@router.get("/memory")
async def get_memory():
    """Thin wrapper over ``memory_read`` — shape preserved for the dashboard."""
    from agent.operations import registry

    op = registry.get("memory_read")
    if op is None:
        raise HTTPException(503, "memory_read operation missing")
    result = await op.handler()
    return {"content": result.get("memory", "")}


@router.post("/memory")
async def update_memory(body: MemoryUpdate):
    """Thin wrapper over ``memory_write`` / ``memory_append`` / ``memory_read``.

    Route preserves the legacy ``{"content": …}`` shape; the operations own
    the logic so behaviour cannot drift.
    """
    from agent.operations import registry

    if body.content is not None and body.append is not None:
        raise HTTPException(422, "Send either 'content' or 'append', not both.")
    if body.content is not None:
        op = registry.get("memory_write")
        if op is None:
            raise HTTPException(503, "memory_write operation missing")
        await op.handler(content=body.content)
    elif body.append is not None:
        op = registry.get("memory_append")
        if op is None:
            raise HTTPException(503, "memory_append operation missing")
        await op.handler(text=body.append)
    read_op = registry.get("memory_read")
    if read_op is None:
        raise HTTPException(503, "memory_read operation missing")
    result = await read_op.handler()
    return {"content": result.get("memory", "")}


# ─── Conversations ───────────────────────────────────────────


class ConversationSave(BaseModel):
    messages: list = Field(default_factory=list)
    title: str | None = None


@router.get("/conversations")
async def list_conversations():
    from agent.services import agent_memory

    return {"conversations": agent_memory.list_conversations()}


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    from agent.services import agent_memory

    record = agent_memory.load_conversation(conversation_id)
    if record is None:
        return {"id": conversation_id, "messages": [], "title": "Untitled"}
    return record


@router.put("/conversations/{conversation_id}")
async def save_conversation(conversation_id: str, body: ConversationSave):
    from agent.services import agent_memory

    return agent_memory.save_conversation(conversation_id, body.messages, body.title)


@router.delete("/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    """Delete a saved conversation.

    Three outcomes, kept distinct so the UI can say something true: gone,
    never existed, or exists but could not be removed. A blanket 200 with
    ``deleted: false`` would leave the caller unable to tell a typo from a
    filesystem refusal — and the refusal is the case worth knowing about.
    """
    from agent.services import agent_memory

    if agent_memory.delete_conversation(conversation_id):
        return {"deleted": True}

    if agent_memory.load_conversation(conversation_id) is None:
        raise HTTPException(404, f"No conversation {conversation_id!r}.")

    raise HTTPException(
        409,
        f"Conversation {conversation_id!r} exists but could not be deleted "
        f"(the filesystem refused). Check {agent_memory.CONVERSATIONS_DIR} "
        f"permissions.",
    )
