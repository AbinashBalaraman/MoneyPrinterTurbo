"""Model discovery, metadata, and reasoning effort resolver for OpenCode AI."""

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

# Standard reasoning tiers
REASONING_TIERS_MUSE = ["xhigh", "high", "medium", "low", "off"]
REASONING_TIERS_STANDARD = ["high", "medium", "off"]
REASONING_TIERS_NONE = ["off"]


@dataclass
class ModelInfo:
    id: str
    name: str
    endpoint_type: str  # "responses" or "chat-completions"
    supported_reasoning: List[str]
    default_reasoning: str
    is_free: bool = False
    supports_vision: bool = True
    context_window: int = 1000000
    max_output_tokens: int = 16000
    source: str = "api"  # "api", "vscode", or "builtin"


def resolve_model_reasoning(model_id: str) -> tuple[List[str], str]:
    """Returns (supported_reasoning_tiers, default_reasoning) for any given model."""
    mid = model_id.lower()
    if "muse-spark" in mid:
        return REASONING_TIERS_MUSE, "xhigh"
    elif any(k in mid for k in ["deepseek-v4", "glm-5", "qwen", "mimo"]):
        return REASONING_TIERS_STANDARD, "high"
    elif any(k in mid for k in ["nemotron", "ling"]):
        return REASONING_TIERS_NONE, "off"
    elif any(k in mid for k in ["claude", "gpt-5", "gemini"]):
        return REASONING_TIERS_STANDARD, "medium"
    return REASONING_TIERS_STANDARD, "off"


def resolve_endpoint_type(model_id: str) -> str:
    """Returns 'responses' or 'chat-completions' depending on model family."""
    mid = model_id.lower()
    if "muse-spark" in mid:
        return "responses"
    return "chat-completions"


def fetch_models_online(
    api_key: str,
    base_url: str = "https://opencode.ai/zen/v1",
    timeout: int = 10,
) -> List[ModelInfo]:
    """Fetches real-time available models from OpenCode /models endpoint."""
    url = f"{base_url.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-opencode-session": "fetch-models-session",
        "x-opencode-request": "req-models",
        "x-opencode-client": "vscode-copilot-chat",
        "User-Agent": "opencode-copilot-chat/0.7.5 VSCode",
    }
    req = urllib.request.Request(url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw_models = data.get("data", [])

            results: List[ModelInfo] = []
            for item in raw_models:
                m_id = item.get("id", "")
                if not m_id:
                    continue

                tiers, def_reasoning = resolve_model_reasoning(m_id)
                endpoint = resolve_endpoint_type(m_id)
                is_free = "free" in m_id.lower()

                results.append(
                    ModelInfo(
                        id=m_id,
                        name=m_id,
                        endpoint_type=endpoint,
                        supported_reasoning=tiers,
                        default_reasoning=def_reasoning,
                        is_free=is_free,
                        supports_vision=True,
                        source="api",
                    )
                )
            return results
    except Exception as e:
        # If network or API fails, return empty list to allow fallbacks
        return []


def fetch_models_vscode_config() -> List[ModelInfo]:
    """Inspects VS Code's chatLanguageModels.json to auto-import models and reasoning presets."""
    appdata = os.environ.get("APPDATA", "")
    config_path = os.path.join(appdata, "Code", "User", "chatLanguageModels.json")
    if not os.path.exists(config_path):
        return []

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results: List[ModelInfo] = []
        if isinstance(data, list):
            for endpoint_config in data:
                models_list = endpoint_config.get("models", [])
                settings = endpoint_config.get("settings", {})

                for m in models_list:
                    m_id = m.get("id")
                    if not m_id:
                        continue
                    m_name = m.get("name", m_id)
                    tiers, def_reasoning = resolve_model_reasoning(m_id)
                    endpoint = resolve_endpoint_type(m_id)

                    # Check if VS Code settings have custom reasoning configured
                    for key, val in settings.items():
                        if m_id in key and isinstance(val, dict) and "reasoningEffort" in val:
                            def_reasoning = val["reasoningEffort"]

                    results.append(
                        ModelInfo(
                            id=m_id,
                            name=m_name,
                            endpoint_type=endpoint,
                            supported_reasoning=tiers,
                            default_reasoning=def_reasoning,
                            is_free="free" in m_id.lower(),
                            supports_vision=m.get("vision", True),
                            context_window=m.get("maxInputTokens", 1000000),
                            max_output_tokens=m.get("maxOutputTokens", 16000),
                            source="vscode",
                        )
                    )
        return results
    except Exception:
        return []


def get_all_models(api_key: Optional[str] = None, base_url: str = "https://opencode.ai/zen/v1") -> List[ModelInfo]:
    """Combines online API discovery, local VS Code configuration, and canonical free fallbacks."""
    models_dict: Dict[str, ModelInfo] = {}

    # 1. Online discovery
    if api_key:
        for m in fetch_models_online(api_key, base_url):
            models_dict[m.id] = m

    # 2. Local VS Code discovery (supplements or updates local tokens/names)
    for m in fetch_models_vscode_config():
        if m.id not in models_dict:
            models_dict[m.id] = m
        else:
            # Enrich existing with VS Code local metadata if present
            models_dict[m.id].name = m.name
            models_dict[m.id].context_window = m.context_window
            models_dict[m.id].max_output_tokens = m.max_output_tokens
            models_dict[m.id].default_reasoning = m.default_reasoning

    # 3. Canonical Free Fallbacks (ensures critical models always exist)
    canonical_free = [
        ModelInfo(
            id="muse-spark-1.3-contributor-free",
            name="Muse Spark 1.3 (Free · Meta)",
            endpoint_type="responses",
            supported_reasoning=REASONING_TIERS_MUSE,
            default_reasoning="xhigh",
            is_free=True,
            supports_vision=True,
            source="builtin",
        ),
        ModelInfo(
            id="muse-spark-1.2-contributor-free",
            name="Muse Spark 1.2 (Free · Meta)",
            endpoint_type="responses",
            supported_reasoning=REASONING_TIERS_MUSE,
            default_reasoning="xhigh",
            is_free=True,
            supports_vision=True,
            source="builtin",
        ),
        ModelInfo(
            id="deepseek-v4-flash-free",
            name="DeepSeek v4 Flash (Free)",
            endpoint_type="chat-completions",
            supported_reasoning=REASONING_TIERS_STANDARD,
            default_reasoning="high",
            is_free=True,
            supports_vision=True,
            source="builtin",
        ),
        ModelInfo(
            id="mimo-v2.5-free",
            name="Mimo v2.5 (Free)",
            endpoint_type="chat-completions",
            supported_reasoning=REASONING_TIERS_STANDARD,
            default_reasoning="high",
            is_free=True,
            supports_vision=True,
            source="builtin",
        ),
        ModelInfo(
            id="nemotron-3-ultra-free",
            name="Nemotron 3 Ultra (Free)",
            endpoint_type="chat-completions",
            supported_reasoning=REASONING_TIERS_NONE,
            default_reasoning="off",
            is_free=True,
            supports_vision=False,
            source="builtin",
        ),
        ModelInfo(
            id="ling-3.0-flash-fin-free",
            name="Ling 3.0 Flash (Free)",
            endpoint_type="chat-completions",
            supported_reasoning=REASONING_TIERS_NONE,
            default_reasoning="off",
            is_free=True,
            supports_vision=False,
            source="builtin",
        ),
    ]

    for cm in canonical_free:
        if cm.id not in models_dict:
            models_dict[cm.id] = cm

    return list(models_dict.values())
