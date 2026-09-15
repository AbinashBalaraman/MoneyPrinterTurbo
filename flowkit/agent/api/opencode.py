"""OpenCode access for Agent Studio.

The dashboard used to talk to ``opencode.ai`` directly through a Vite dev proxy,
carrying a hardcoded API key in its JavaScript bundle and its own guess at each
model's protocol. Two problems followed: a live credential was readable by
anyone who loaded the page, and a wrong protocol guess looked like a broken
model rather than a routing bug.

So the browser now asks this router. The key stays in server configuration, the
protocol is resolved from the catalogue, and an unknown model is rejected
outright instead of being guessed at.

Both endpoints here share one validation path (:func:`_resolve_model`) so a rule
cannot hold for the buffered call and not for the streamed one.
"""

from __future__ import annotations

import json
import logging
import time
from typing import AsyncIterator, Callable, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent import config
from agent.services import chat_agent
from agent.services.opencode_models import (
    ModelInfo,
    build_request_payload,
    build_stream_payload,
    endpoint_path,
    get_catalogue,
    parse_chat_response,
    parse_stream_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/opencode", tags=["opencode"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage] = Field(default_factory=list)
    reasoning_effort: Optional[str] = None
    temperature: float = 0.7


class AgentChatRequest(ChatRequest):
    """A chat request that may use server-side tools."""

    use_tools: bool = True
    max_rounds: int = Field(default=chat_agent.MAX_ROUNDS, ge=1, le=8)


def _key_configured() -> bool:
    return bool(config.OPENCODE_API_KEY)


def _upstream_headers() -> dict:
    return {
        "Authorization": f"Bearer {config.OPENCODE_API_KEY}",
        "Content-Type": "application/json",
        "x-opencode-session": f"flowkit-{int(time.time())}",
        "x-opencode-request": f"req-{int(time.time())}",
        "x-opencode-client": "flowkit-agent-studio/1.0",
        "User-Agent": "flowkit-agent-studio/1.0 VSCode",
    }


def _sse(payload: dict) -> str:
    """One Server-Sent Events frame."""
    return f"data: {json.dumps(payload)}\n\n"


async def _resolve_model(body: ChatRequest) -> ModelInfo:
    """Validate a request and return the catalogue entry it names.

    Raises ``HTTPException`` rather than substituting a default: an unknown
    model, or a reasoning tier the model does not offer, is a client mistake and
    saying so is more useful than quietly doing something else.
    """
    if not _key_configured():
        raise HTTPException(
            503,
            "OpenCode is not configured. Set OPENCODE_API_KEY in the environment "
            "and restart the agent.",
        )
    if not body.messages:
        raise HTTPException(422, "messages must not be empty")

    cat = get_catalogue()
    models = await cat.get(api_key=config.OPENCODE_API_KEY, base_url=config.OPENCODE_BASE_URL)
    model = next((m for m in models if m.id == body.model), None)

    if model is None:
        # Rejecting beats guessing: a silent fallback to a different model is
        # how "the models are mismatching" presents from the outside.
        raise HTTPException(
            400,
            f"Unknown model {body.model!r}. It is not in the catalogue; "
            "refresh the model list or pick a listed model.",
        )

    if body.reasoning_effort and body.reasoning_effort not in model.supported_reasoning:
        raise HTTPException(
            422,
            f"{model.id} does not support reasoning effort "
            f"{body.reasoning_effort!r}; supported: {model.supported_reasoning}",
        )

    return model


@router.get("/status")
async def status():
    """Whether a key is configured. Never returns the key itself."""
    cat = get_catalogue()
    return {
        "configured": _key_configured(),
        "base_url": config.OPENCODE_BASE_URL,
        # ``cached`` is 0 until /models has resolved once; ``builtin`` is what
        # the UI can always fall back to. Reporting both avoids the old "0
        # models" reading that looked like a broken catalogue.
        "models_cached": cat.cached_count,
        "models_builtin": cat.builtin_count,
        "source": cat.last_source,
        "error": cat.last_error,
    }


@router.get("/models")
async def list_models(refresh: bool = False):
    """The model catalogue, resolved server-side.

    Includes the canonical free models even when the live list cannot be
    fetched, so the UI always has something selectable — and reports which
    source it used, so it does not claim to be live when it is not.
    """
    cat = get_catalogue()
    if refresh:
        cat.invalidate()

    models = await cat.get(api_key=config.OPENCODE_API_KEY or None,
                           base_url=config.OPENCODE_BASE_URL)

    return {
        "models": [m.to_dict() for m in models],
        "source": cat.last_source,
        "key_configured": _key_configured(),
        "error": cat.last_error,
    }


@router.post("/chat")
async def chat(body: ChatRequest):
    """Proxy a completion, injecting the key server-side."""
    model = await _resolve_model(body)

    payload = build_request_payload(
        model_id=model.id,
        endpoint_type=model.endpoint_type,
        messages=[m.model_dump() for m in body.messages],
        reasoning_effort=body.reasoning_effort or model.default_reasoning,
        temperature=body.temperature,
    )

    url = f"{config.OPENCODE_BASE_URL.rstrip('/')}{endpoint_path(model.endpoint_type)}"

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=config.OPENCODE_TIMEOUT, trust_env=False) as client:
            response = await client.post(url, headers=_upstream_headers(), json=payload)
    except httpx.TimeoutException:
        raise HTTPException(504, f"OpenCode timed out after {config.OPENCODE_TIMEOUT:.0f}s")
    except Exception as e:
        raise HTTPException(502, f"Could not reach OpenCode: {e}")

    latency_ms = int((time.monotonic() - started) * 1000)

    if response.status_code >= 400:
        logger.warning("OpenCode %s failed (%s): %s",
                       model.id, response.status_code, response.text[:300])
        raise HTTPException(response.status_code, response.text[:500])

    parsed = parse_chat_response(model.endpoint_type, response.json())

    logger.info("OpenCode %s replied in %dms (%s)", model.id, latency_ms, model.endpoint_type)

    return {
        **parsed,
        "model": model.id,
        "endpoint_type": model.endpoint_type,
        "reasoning_effort": body.reasoning_effort or model.default_reasoning,
        "latency_ms": latency_ms,
    }


@router.post("/chat/stream")
async def chat_stream(body: ChatRequest):
    """Stream a completion as Server-Sent Events.

    Same validation and same server-side key injection as ``/chat``. The
    difference is that text arrives as it is produced rather than after the
    whole reply is buffered — a long generation used to leave the UI blank,
    which reads as "broken" rather than "slow".

    Frames are the normalised deltas from
    :func:`agent.services.opencode_models.parse_stream_event`, plus a final
    ``done`` carrying the model, the protocol actually used, and the latency.
    """
    # Validation happens before the response starts, because an exception
    # raised inside a StreamingResponse body cannot set a status code.
    model = await _resolve_model(body)

    effort = body.reasoning_effort or model.default_reasoning
    payload = build_stream_payload(
        model_id=model.id,
        endpoint_type=model.endpoint_type,
        messages=[m.model_dump() for m in body.messages],
        reasoning_effort=effort,
        temperature=body.temperature,
    )
    url = f"{config.OPENCODE_BASE_URL.rstrip('/')}{endpoint_path(model.endpoint_type)}"

    async def event_stream():
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=config.OPENCODE_TIMEOUT, trust_env=False
            ) as client:
                async with client.stream(
                    "POST", url, headers=_upstream_headers(), json=payload
                ) as response:
                    if response.status_code >= 400:
                        raw = (await response.aread()).decode("utf-8", "replace")
                        logger.warning("OpenCode %s stream failed (%s): %s",
                                       model.id, response.status_code, raw[:300])
                        yield _sse({"type": "error", "message": raw[:500]})
                        return

                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        if not raw:
                            continue
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            # One malformed frame is not worth killing the
                            # stream over; keep going and let the UI show text.
                            continue
                        delta = parse_stream_event(model.endpoint_type, data)
                        if delta:
                            yield _sse(delta)
        except httpx.TimeoutException:
            yield _sse({
                "type": "error",
                "message": f"OpenCode timed out after {config.OPENCODE_TIMEOUT:.0f}s",
            })
            return
        except Exception as e:  # noqa: BLE001 - the client must be told, not left hanging
            logger.warning("OpenCode %s stream broke: %s", model.id, e)
            yield _sse({"type": "error", "message": f"Stream broke: {e}"})
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info("OpenCode %s streamed in %dms (%s)",
                    model.id, latency_ms, model.endpoint_type)
        yield _sse({
            "type": "done",
            "model": model.id,
            "endpoint_type": model.endpoint_type,
            "reasoning_effort": effort,
            "latency_ms": latency_ms,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Without this an intermediary that buffers would defeat streaming.
            "X-Accel-Buffering": "no",
        },
    )


def _stream_model_call(
    model: ModelInfo, effort: str, temperature: float, url: str
) -> Callable[[list[dict]], AsyncIterator[dict]]:
    """Build the ``model_call`` the tool loop drives.

    Returns an async generator factory: given a conversation it streams one
    completion and yields the same normalised deltas ``parse_stream_event``
    already produces. Raising here surfaces to the client as an ``error`` frame
    rather than a silent empty answer.
    """

    async def model_call(messages: list[dict]):
        payload = build_stream_payload(
            model_id=model.id,
            endpoint_type=model.endpoint_type,
            messages=messages,
            reasoning_effort=effort,
            temperature=temperature,
        )
        async with httpx.AsyncClient(
            timeout=config.OPENCODE_TIMEOUT, trust_env=False
        ) as client:
            async with client.stream(
                "POST", url, headers=_upstream_headers(), json=payload
            ) as response:
                if response.status_code >= 400:
                    raw = (await response.aread()).decode("utf-8", "replace")
                    logger.warning(
                        "OpenCode %s agent stream failed (%s): %s",
                        model.id, response.status_code, raw[:300],
                    )
                    raise RuntimeError(raw[:500])

                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    if not chunk:
                        continue
                    try:
                        data = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
                    delta = parse_stream_event(model.endpoint_type, data)
                    if delta:
                        yield delta

    return model_call


@router.post("/agent/stream")
async def agent_chat_stream(body: AgentChatRequest):
    """Stream a completion with server-side tools available.

    Same validation and key injection as ``/chat/stream``; the difference is
    that the reply is scanned for tool markers, which the server executes
    itself, feeding results back for up to ``max_rounds`` before the final
    answer is streamed. This is what lets the assistant act instead of handing
    the user commands to paste.

    Adds two frame types on top of the existing vocabulary: ``tool`` (with
    ``status`` of ``running``/``ok``/``error``) and ``error``.
    """
    model = await _resolve_model(body)
    effort = body.reasoning_effort or model.default_reasoning
    url = f"{config.OPENCODE_BASE_URL.rstrip('/')}{endpoint_path(model.endpoint_type)}"

    messages = [m.model_dump() for m in body.messages]
    if body.use_tools:
        messages = chat_agent.prepare_messages(messages)

    model_call = _stream_model_call(model, effort, body.temperature, url)

    async def event_stream():
        started = time.monotonic()
        rounds = 0
        try:
            async for event in chat_agent.run_agent(
                messages, model_call, max_rounds=body.max_rounds
            ):
                if event.get("type") == "tool":
                    rounds += 1
                yield _sse(event)
        except Exception as e:  # noqa: BLE001 - the client must be told, not left hanging
            logger.warning("OpenCode %s agent loop broke: %s", model.id, e)
            yield _sse({"type": "error", "message": f"Agent loop broke: {e}"})
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "OpenCode %s agent finished in %dms (%s, %d tool events)",
            model.id, latency_ms, model.endpoint_type, rounds,
        )
        yield _sse({
            "type": "done",
            "model": model.id,
            "endpoint_type": model.endpoint_type,
            "reasoning_effort": effort,
            "latency_ms": latency_ms,
            "tools_used": rounds > 0,
        })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

