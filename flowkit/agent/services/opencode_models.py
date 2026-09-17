"""OpenCode model catalogue — the single source of truth.

Why this module exists
----------------------
The dashboard used to carry its own hardcoded model list *and* its own guess at
which protocol each model speaks::

    endpoint: isResponses ? 'responses' : 'chat/completions'

That guess is the "models mismatching" bug. A model whose real endpoint is
``responses`` but whose id does not contain ``muse-spark`` would be sent to
``chat/completions``, and the request would fail in a way that looks like a
model problem rather than a routing one.

So resolution lives here, once, server-side. The client asks for the catalogue
and then names a model; it never decides how to talk to it.

Naming
------
``endpoint_type`` is ``"responses"`` or ``"chat-completions"`` — a hyphen, per
the reference implementation in ``opencode_endpoint/models.py``. The slash form
``chat/completions`` is a URL path, not a name, and the two had drifted apart.
:func:`endpoint_path` is the only place that translation happens.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://opencode.ai/zen/v1"

# Reasoning tiers, mirroring the reference resolver.
REASONING_TIERS_MUSE = ["xhigh", "high", "medium", "low", "off"]
REASONING_TIERS_STANDARD = ["high", "medium", "off"]
REASONING_TIERS_NONE = ["off"]

#: Canonical endpoint names. ``chat-completions`` is the name; the URL path is
#: ``/chat/completions`` and is derived, never stored.
ENDPOINT_RESPONSES = "responses"
ENDPOINT_CHAT_COMPLETIONS = "chat-completions"

_ENDPOINT_PATHS = {
    ENDPOINT_RESPONSES: "/responses",
    ENDPOINT_CHAT_COMPLETIONS: "/chat/completions",
}


@dataclass
class ModelInfo:
    id: str
    name: str
    endpoint_type: str
    provider: str = "Other"
    supported_reasoning: list[str] = field(default_factory=lambda: list(REASONING_TIERS_STANDARD))
    default_reasoning: str = "off"
    is_free: bool = False
    supports_vision: bool = True
    context_window: int = 1_000_000
    max_output_tokens: int = 16_000
    source: str = "builtin"

    def to_dict(self) -> dict:
        return asdict(self)


def endpoint_path(endpoint_type: str) -> str:
    """Map a canonical endpoint name to its URL path.

    The single translation point. Everything upstream speaks
    ``chat-completions``; only the HTTP call needs the slash.
    """
    path = _ENDPOINT_PATHS.get(endpoint_type)
    if not path:
        raise ValueError(f"Unknown endpoint type: {endpoint_type!r}")
    return path


def resolve_model_provider(model_id: str) -> str:
    """Return the primary provider segment name for a model."""
    mid = (model_id or "").lower()
    if mid.startswith("nvidia/") or "nemotron" in mid or "riva" in mid or "ising" in mid:
        return "NVIDIA NIM"
    if mid.startswith("gemini-") or mid.startswith("google/") or "gemini" in mid:
        return "Google Gemini"
    if mid.startswith("meta/") or "muse" in mid or "llama" in mid:
        return "Meta"
    if mid.startswith("openai/") or "gpt" in mid:
        return "OpenAI"
    if "deepseek" in mid:
        return "DeepSeek"
    if mid.startswith("mistralai/") or "mistral" in mid or "mixtral" in mid:
        return "Mistral AI"
    return "OpenCode / Community"


def resolve_model_reasoning(model_id: str) -> tuple[list[str], str]:
    """Return ``(supported_tiers, default_tier)`` for a model id."""
    mid = (model_id or "").lower()
    if "muse-spark" in mid:
        return list(REASONING_TIERS_MUSE), "xhigh"
    if any(k in mid for k in ("deepseek-v4", "glm-5", "qwen", "mimo")):
        return list(REASONING_TIERS_STANDARD), "high"
    if any(k in mid for k in ("nemotron-3.5", "reasoning", "550b")):
        return list(REASONING_TIERS_STANDARD), "medium"
    if any(k in mid for k in ("nemotron", "ling", "llama", "mistral")):
        return list(REASONING_TIERS_NONE), "off"
    if any(k in mid for k in ("claude", "gpt-5", "gemini")):
        return list(REASONING_TIERS_STANDARD), "medium"
    return list(REASONING_TIERS_STANDARD), "off"


def resolve_endpoint_type(model_id: str) -> str:
    """Which protocol a model speaks.

    ``responses`` is the exception, not the default: only the muse-spark family
    uses it. Stated as an explicit allow-list so adding a second ``responses``
    model is a deliberate edit rather than a side effect of a substring match.
    """
    mid = (model_id or "").lower()
    if "muse-spark" in mid:
        return ENDPOINT_RESPONSES
    return ENDPOINT_CHAT_COMPLETIONS


def _builtin(
    model_id: str,
    name: str,
    *,
    is_free: Optional[bool] = None,
    vision: bool = True,
    source: str = "builtin",
    provider: Optional[str] = None,
) -> ModelInfo:
    tiers, default = resolve_model_reasoning(model_id)
    free_flag = ("free" in model_id.lower()) if is_free is None else is_free
    prov = provider or resolve_model_provider(model_id)
    return ModelInfo(
        id=model_id,
        name=name,
        endpoint_type=resolve_endpoint_type(model_id),
        provider=prov,
        supported_reasoning=tiers,
        default_reasoning=default,
        is_free=free_flag,
        supports_vision=vision,
        source=source,
    )


#: Always present, so the dashboard has something usable when the network or
#: the API key is unavailable. Segmented cleanly by providers.
CANONICAL_FREE_MODELS: list[ModelInfo] = [
    # ── NVIDIA NIM & Nemotron Models ────────────────────────────────────
    _builtin("nvidia/nemotron-3-ultra-550b-a55b", "NVIDIA Nemotron 3 Ultra 550B (NIM · Reasoning)", is_free=True),
    _builtin("nvidia/nemotron-3.5-lightning-30b-a3b", "NVIDIA Nemotron 3.5 Lightning (NIM · 668ms)", is_free=True),
    _builtin("nemotron-3.5-lightning-free", "NVIDIA Nemotron 3.5 Lightning (Free · 650ms)", is_free=True, vision=False),
    _builtin("nvidia/nemotron-3-super-120b-a12b", "NVIDIA Nemotron 3 Super 120B (NIM · Fast)", is_free=True),
    _builtin("nemotron-3-ultra-free", "NVIDIA Nemotron 3 Ultra (Free)", is_free=True, vision=False),
    _builtin("nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "NVIDIA Nemotron 3 Nano Omni (NIM · 785ms)", is_free=True),
    _builtin("nvidia/ising-calibration-1.5-31b", "NVIDIA Ising Calibration 31B (NIM · 700ms)", is_free=True),
    _builtin("nvidia/riva-translate-4b-instruct-v2", "NVIDIA Riva Translate 4B (NIM · 342ms)", is_free=True),

    # ── Google Gemini Models ────────────────────────────────────────────
    _builtin("gemini-2.5-flash", "Gemini 2.5 Flash (Google · Fast)", is_free=True),
    _builtin("gemini-2.5-pro", "Gemini 2.5 Pro (Google · Thinking)", is_free=True),
    _builtin("gemini-1.5-flash", "Gemini 1.5 Flash (Google · Fast)", is_free=True),
    _builtin("gemini-2.0-flash", "Gemini 2.0 Flash (Google · Fast)", is_free=True),
    _builtin("gemini-3.8-flash", "Gemini 3.8 Flash (Google · Ultra Fast)", is_free=True),
    _builtin("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite (Google)", is_free=True),

    # ── Meta Models ─────────────────────────────────────────────────────
    _builtin("meta/muse-glimmer-30b", "Meta Muse Glimmer 30B (NIM · 549ms)", is_free=True),
    _builtin("meta/llama-3.2-11b-vision-instruct", "Meta Llama 3.2 11B Vision (NIM · 762ms)", is_free=True),
    _builtin("muse-spark-1.3-contributor-free", "Muse Spark 1.3 (Free · Meta)", is_free=True),
    _builtin("muse-spark-1.2-contributor-free", "Muse Spark 1.2 (Free · Meta)", is_free=True),

    # ── OpenAI Models ───────────────────────────────────────────────────
    _builtin("openai/gpt-oss-20b", "OpenAI GPT OSS 20B (NIM · 514ms)", is_free=True),

    # ── DeepSeek & Community Models ─────────────────────────────────────
    _builtin("deepseek-v4-flash-free", "DeepSeek v4 Flash (Free)", is_free=True),
    _builtin("mimo-v2.5-free", "Mimo v2.5 (Free)", is_free=True),
    _builtin("ling-3.0-flash-fin-free", "Ling 3.0 Flash (Free)", is_free=True, vision=False),
]


class ModelCatalogue:
    """Fetches and caches the live catalogue, falling back to the built-ins."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._cache: list[ModelInfo] = []
        self._fetched_at: float = 0.0
        self._last_error: Optional[str] = None
        self._last_source: str = "builtin"

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    @property
    def last_source(self) -> str:
        """``"api"`` when the live list was fetched, else ``"builtin"``."""
        return self._last_source

    @property
    def cached_count(self) -> int:
        """Models in the last resolved catalogue; 0 before the first ``get()``."""
        return len(self._cache)

    @property
    def builtin_count(self) -> int:
        """Fallback models that exist even with no key and no network."""
        return len(CANONICAL_FREE_MODELS)

    async def get(self, api_key: Optional[str] = None, base_url: str = DEFAULT_BASE_URL) -> list[ModelInfo]:
        """Return the catalogue, refreshing at most once per TTL."""
        fresh = (time.monotonic() - self._fetched_at) < self._ttl
        if self._cache and fresh:
            return self._cache

        merged: dict[str, ModelInfo] = {}

        if api_key:
            for m in await self._fetch_online(api_key, base_url):
                merged[m.id] = m

        for m in CANONICAL_FREE_MODELS:
            merged.setdefault(m.id, m)

        self._cache = list(merged.values())
        self._fetched_at = time.monotonic()
        self._last_source = "api" if any(m.source == "api" for m in self._cache) else "builtin"
        return self._cache

    async def _fetch_online(self, api_key: str, base_url: str) -> list[ModelInfo]:
        """Ask OpenCode Zen for the live model list.

        A failure here is not fatal: the canonical list still stands, and the
        reason is recorded so ``/api/opencode/status`` can explain it instead of
        silently pretending the list is live.
        """
        url = f"{base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "x-opencode-session": "flowkit-models",
            "x-opencode-request": "req-models",
            "x-opencode-client": "flowkit-agent-studio/1.0",
            "User-Agent": "flowkit-agent-studio/1.0 VSCode",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                self._last_error = f"model list request failed ({response.status_code})"
                logger.warning("OpenCode model list failed: %s", response.status_code)
                return []
            payload = response.json()
        except Exception as e:
            self._last_error = str(e)
            logger.warning("Could not reach OpenCode for the model list: %s", e)
            return []

        self._last_error = None
        results: list[ModelInfo] = []
        for item in payload.get("data", []) or []:
            model_id = item.get("id")
            if not model_id:
                continue
            results.append(
                _builtin(
                    model_id,
                    item.get("name") or model_id,
                    vision=item.get("vision", True),
                    source="api",
                )
            )
        return results

    def find(self, model_id: str) -> Optional[ModelInfo]:
        """Look up a model in the last fetched catalogue."""
        return next((m for m in self._cache if m.id == model_id), None)

    def invalidate(self) -> None:
        self._fetched_at = 0.0


# ── Protocol translation ────────────────────────────────────────────────
#
# Both directions live here, next to ``endpoint_path``, so that everything
# which knows the difference between the two protocols is in one file. The
# dashboard used to carry its own copy of this, which is how the naming drifted.

def build_request_payload(
    model_id: str,
    endpoint_type: str,
    messages: list[dict],
    reasoning_effort: Optional[str] = None,
    temperature: float = 0.7,
) -> dict:
    """Build the request body for whichever protocol the model speaks."""
    if endpoint_type == ENDPOINT_RESPONSES:
        payload: dict = {
            "model": model_id,
            "input": [{"role": m["role"], "content": m["content"]} for m in messages],
        }
        if reasoning_effort and reasoning_effort != "off":
            payload["reasoning"] = {"effort": reasoning_effort}
        return payload

    if endpoint_type == ENDPOINT_CHAT_COMPLETIONS:
        payload = {
            "model": model_id,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "temperature": temperature,
        }
        is_direct = any(model_id.lower().startswith(p) for p in ("nvidia/", "meta/", "mistralai/", "openai/", "poolside/", "gemini-", "google/"))
        if not is_direct and reasoning_effort and reasoning_effort != "off":
            payload["reasoningEffort"] = reasoning_effort
        return payload

    raise ValueError(f"Unknown endpoint type: {endpoint_type!r}")


def parse_chat_response(endpoint_type: str, data: dict) -> dict:
    """Normalise either protocol's response into one shape.

    The two protocols disagree on where the text, the reasoning trace and the
    token counts live. Callers should not have to know which model they used to
    read the answer.
    """
    if endpoint_type == ENDPOINT_RESPONSES:
        text = ""
        thought = None
        for item in data.get("output", []) or []:
            if item.get("type") == "message":
                for part in item.get("content", []) or []:
                    if part.get("type") == "output_text" or part.get("text"):
                        text = part.get("text") or text
            elif item.get("type") == "reasoning":
                summary = item.get("summary")
                if summary:
                    thought = "\n".join(summary)
        usage = data.get("usage", {}) or {}
        return {
            "text": text,
            "thought_trace": thought,
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    usage = data.get("usage", {}) or {}
    return {
        "text": message.get("content") or "",
        "thought_trace": message.get("reasoning_content") or None,
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


# ── Streaming ───────────────────────────────────────────────────────────
#
# The two protocols stream in different shapes, and neither is stable enough to
# hand to the browser. This translates both into one small vocabulary of deltas
# so the client does not have to know which model it is talking to:
#
#   {"type": "text",      "text": "..."}
#   {"type": "reasoning", "text": "..."}
#   {"type": "usage",     "reasoning_tokens": N, "input_tokens": N, ...}
#
# Events carrying nothing the UI needs return None rather than an empty delta,
# so the client is not forced to filter.

def build_stream_payload(
    model_id: str,
    endpoint_type: str,
    messages: list[dict],
    reasoning_effort: Optional[str] = None,
    temperature: float = 0.7,
) -> dict:
    """The same request, asking for a streamed response."""
    payload = build_request_payload(
        model_id, endpoint_type, messages, reasoning_effort, temperature
    )
    payload["stream"] = True
    if endpoint_type == ENDPOINT_CHAT_COMPLETIONS:
        # Without this the final chunk omits usage entirely, and the token
        # counts shown in the UI would be permanently zero.
        payload["stream_options"] = {"include_usage": True}
    return payload


def _usage_delta(usage: dict, *, responses: bool) -> dict:
    if responses:
        details = usage.get("output_tokens_details") or {}
        return {
            "type": "usage",
            "reasoning_tokens": details.get("reasoning_tokens", 0),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }
    details = usage.get("completion_tokens_details") or {}
    return {
        "type": "usage",
        "reasoning_tokens": details.get("reasoning_tokens", 0),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
        "total_tokens": usage.get("total_tokens", 0),
    }


def parse_stream_event(endpoint_type: str, data: dict) -> Optional[dict]:
    """Normalise one decoded SSE payload. ``None`` means "nothing to show"."""
    if endpoint_type == ENDPOINT_RESPONSES:
        etype = data.get("type")
        if etype == "response.output_text.delta":
            return {"type": "text", "text": data.get("delta") or ""}
        if etype == "response.reasoning_summary_text.delta":
            return {"type": "reasoning", "text": data.get("delta") or ""}
        if etype == "response.completed":
            response = data.get("response") or {}
            usage = response.get("usage") or {}
            if usage:
                return _usage_delta(usage, responses=True)
        return None

    if endpoint_type == ENDPOINT_CHAT_COMPLETIONS:
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            # Reasoning arrives on its own field, and may share a chunk with
            # content, so reasoning is checked first and content is not dropped.
            if delta.get("reasoning_content"):
                return {"type": "reasoning", "text": delta["reasoning_content"]}
            if delta.get("content"):
                return {"type": "text", "text": delta["content"]}
        usage = data.get("usage")
        if usage:
            return _usage_delta(usage, responses=False)
        return None

    raise ValueError(f"Unknown endpoint type: {endpoint_type!r}")


_catalogue: Optional[ModelCatalogue] = None


def get_catalogue() -> ModelCatalogue:
    """The shared catalogue.

    Built lazily so this module stays import-pure (no config read at import
    time) while still honouring ``OPENCODE_MODELS_TTL`` from configuration.
    """
    global _catalogue
    if _catalogue is None:
        try:
            from agent.config import OPENCODE_MODELS_TTL
            ttl = OPENCODE_MODELS_TTL
        except Exception:  # config unavailable (e.g. a bare import in a test)
            ttl = 300.0
        _catalogue = ModelCatalogue(ttl_seconds=ttl)
    return _catalogue
