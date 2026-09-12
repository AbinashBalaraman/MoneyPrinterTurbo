"""
OpenCode AI Zen native integration for MoneyPrinterTurbo.
Supports auto-endpoint routing (/responses vs /chat/completions),
reasoning effort auto-detection, and real-time model discovery without an external server.
"""

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

DEFAULT_OPENCODE_BASE_URL = "https://opencode.ai/zen/v1"
DEFAULT_OPENCODE_MODEL = "muse-spark-1.3-contributor-free"

REASONING_TIERS_MUSE = ["xhigh", "high", "medium", "low", "off"]
REASONING_TIERS_STANDARD = ["high", "medium", "off"]
REASONING_TIERS_NONE = ["off"]


def resolve_endpoint_type(model_id: str) -> str:
    """Routes Muse models to /responses and all other models to /chat/completions."""
    mid = model_id.lower().strip()
    if "muse-spark" in mid:
        return "responses"
    return "chat-completions"


def resolve_model_reasoning(model_id: str, override: Optional[str] = None) -> Tuple[List[str], str]:
    """Returns (supported_reasoning_tiers, default_reasoning) for any given model."""
    if override and override.strip():
        val = override.strip().lower()
        if val != "auto":
            return [val], val

    mid = model_id.lower().strip()
    if "muse-spark" in mid:
        return REASONING_TIERS_MUSE, "xhigh"
    elif any(k in mid for k in ["deepseek-v4", "glm-5", "qwen", "mimo"]):
        return REASONING_TIERS_STANDARD, "high"
    elif any(k in mid for k in ["nemotron", "ling"]):
        return REASONING_TIERS_NONE, "off"
    elif any(k in mid for k in ["claude", "gpt-5", "gemini"]):
        return REASONING_TIERS_STANDARD, "medium"
    return REASONING_TIERS_STANDARD, "off"


def build_headers(api_key: str) -> Dict[str, str]:
    """Constructs required headers for OpenCode Zen API authentication."""
    now_ms = int(time.time() * 1000)
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key.strip()}",
        "x-opencode-session": f"session-{now_ms}",
        "x-opencode-request": f"req-{now_ms}",
        "x-opencode-client": "vscode-copilot-chat",
        "User-Agent": "opencode-copilot-chat/0.7.5 VSCode",
    }


def fetch_models_online(
    api_key: str,
    base_url: str = DEFAULT_OPENCODE_BASE_URL,
    timeout: int = 15,
) -> List[Dict[str, Any]]:
    """Fetches real-time available models from the OpenCode /models endpoint."""
    url = f"{base_url.rstrip('/')}/models"
    req = urllib.request.Request(url, headers=build_headers(api_key), method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_models = data.get("data", [])
            models: List[Dict[str, Any]] = []
            for item in raw_models:
                m_id = item.get("id")
                if not m_id:
                    continue
                tiers, def_reasoning = resolve_model_reasoning(m_id)
                models.append(
                    {
                        "id": m_id,
                        "name": m_id,
                        "endpoint_type": resolve_endpoint_type(m_id),
                        "supported_reasoning": tiers,
                        "default_reasoning": def_reasoning,
                        "is_free": "free" in m_id.lower(),
                    }
                )
            return models
    except Exception as e:
        logger.warning(f"failed to query opencode models: {e}")
        return []


def generate_opencode_response(
    api_key: str,
    base_url: str,
    model_name: str,
    prompt: str,
    reasoning_effort: Optional[str] = None,
    timeout: int = 120,
) -> str:
    """
    Executes a prompt against OpenCode AI Zen using the appropriate endpoint.
    Handles responses format for Muse models and chat/completions format for others.
    """
    if not api_key:
        raise ValueError("opencode: api_key is not set")

    model_name = model_name or DEFAULT_OPENCODE_MODEL
    base_url = (base_url or DEFAULT_OPENCODE_BASE_URL).rstrip("/")
    endpoint_type = resolve_endpoint_type(model_name)
    _, def_reasoning = resolve_model_reasoning(model_name, override=reasoning_effort)
    active_reasoning = def_reasoning

    headers = build_headers(api_key)

    if endpoint_type == "responses":
        url = f"{base_url}/responses"
        payload: Dict[str, Any] = {
            "model": model_name,
            "input": [{"role": "user", "content": prompt}],
        }
        if active_reasoning and active_reasoning != "off":
            payload["reasoning"] = {"effort": active_reasoning}
    else:
        url = f"{base_url}/chat/completions"
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }
        if active_reasoning and active_reasoning != "off":
            payload["reasoningEffort"] = active_reasoning

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))

            if endpoint_type == "responses":
                outputs = result.get("output", [])
                for item in outputs:
                    if item.get("type") == "message":
                        content = item.get("content", [])
                        if content and "text" in content[0]:
                            return content[0]["text"]
                raise ValueError("opencode responses endpoint returned no message content")
            else:
                choices = result.get("choices", [])
                if not choices:
                    raise ValueError("opencode chat endpoint returned empty choices")
                return choices[0].get("message", {}).get("content", "")

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenCode HTTP {e.code} error: {err_body}") from e
    except Exception as e:
        raise RuntimeError(f"OpenCode request failed: {e}") from e
