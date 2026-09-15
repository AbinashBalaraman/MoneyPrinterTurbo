"""Universal OpenCode AI Client with auto-model & reasoning fetch."""

import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from .models import ModelInfo, get_all_models, resolve_model_reasoning, resolve_endpoint_type
except ImportError:
    from models import ModelInfo, get_all_models, resolve_model_reasoning, resolve_endpoint_type


def _load_env_file():
    """Loads .env file in the current or parent directory if not already set."""
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip("\"'")
                    if k not in os.environ:
                        os.environ[k] = v


class OpenCodeClient:
    """Universal OpenCode API Client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        default_reasoning: Optional[str] = None,
    ):
        _load_env_file()
        # Deliberately no hardcoded fallback: a key compiled into the source is
        # a key that cannot be rotated. Supply it via OPENCODE_API_KEY or the
        # api_key argument.
        self.api_key = api_key or os.environ.get("OPENCODE_API_KEY") or ""
        self.base_url = (
            base_url
            or os.environ.get("OPENCODE_BASE_URL")
            or "https://opencode.ai/zen/v1"
        ).rstrip("/")
        self.default_model = (
            default_model
            or os.environ.get("OPENCODE_DEFAULT_MODEL")
            or "muse-spark-1.3-contributor-free"
        )
        self.default_reasoning = (
            default_reasoning
            or os.environ.get("OPENCODE_DEFAULT_REASONING")
            or "xhigh"
        )

        self._cached_models: Optional[List[ModelInfo]] = None

    def _build_headers(self) -> Dict[str, str]:
        now_ms = int(time.time() * 1000)
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "x-opencode-session": f"session-{now_ms}",
            "x-opencode-request": f"req-{now_ms}",
            "x-opencode-client": "vscode-copilot-chat",
            "User-Agent": "opencode-copilot-chat/0.7.5 VSCode",
        }

    def list_models(self, only_free: bool = False, refresh: bool = False) -> List[ModelInfo]:
        """Auto-fetches and returns available models with supported reasoning tiers."""
        if self._cached_models is None or refresh:
            self._cached_models = get_all_models(api_key=self.api_key, base_url=self.base_url)

        if only_free:
            return [m for m in self._cached_models if m.is_free]
        return list(self._cached_models)

    def get_reasoning_options(self, model: Optional[str] = None) -> Dict[str, Any]:
        """Auto-fetches the supported reasoning tiers and recommended default for a model."""
        target_model = model or self.default_model
        # Check cached models first
        if self._cached_models:
            for m in self._cached_models:
                if m.id == target_model:
                    return {
                        "model": m.id,
                        "supported_tiers": m.supported_reasoning,
                        "default_tier": m.default_reasoning,
                        "endpoint_type": m.endpoint_type,
                    }

        # Fallback to analytical resolver
        tiers, def_tier = resolve_model_reasoning(target_model)
        endpoint = resolve_endpoint_type(target_model)
        return {
            "model": target_model,
            "supported_tiers": tiers,
            "default_tier": def_tier,
            "endpoint_type": endpoint,
        }

    def chat(
        self,
        prompt_or_messages: Any,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        timeout: int = 30,
    ) -> str:
        """Sends a query to OpenCode and returns the response string.

        Args:
            prompt_or_messages: String prompt or list of {"role": ..., "content": ...}
            model: Model ID to use. Defaults to default_model.
            reasoning_effort: "xhigh", "high", "medium", "low", or "off". Auto-resolved if None.
            temperature: Sampling temperature (for chat completions).
            system_prompt: Optional system instructions if passing a simple string prompt.
            timeout: HTTP timeout in seconds.
        """
        active_model = model or self.default_model

        # Auto-fetch reasoning recommendation if not explicitly passed
        if reasoning_effort is None:
            reasoning_info = self.get_reasoning_options(active_model)
            active_reasoning = reasoning_info["default_tier"]
        else:
            active_reasoning = reasoning_effort

        endpoint_type = resolve_endpoint_type(active_model)

        # Normalize messages
        if isinstance(prompt_or_messages, str):
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt_or_messages})
        elif isinstance(prompt_or_messages, list):
            messages = list(prompt_or_messages)
            if system_prompt and not any(m.get("role") == "system" for m in messages):
                messages.insert(0, {"role": "system", "content": system_prompt})
        else:
            raise ValueError("prompt_or_messages must be either a string prompt or list of dicts.")

        # Build payload & URL depending on endpoint type
        if endpoint_type == "responses":
            url = f"{self.base_url}/responses"
            payload: Dict[str, Any] = {
                "model": active_model,
                "input": messages,
            }
            if active_reasoning and active_reasoning != "off":
                payload["reasoning"] = {"effort": active_reasoning}
        else:
            url = f"{self.base_url}/chat/completions"
            payload = {
                "model": active_model,
                "messages": messages,
                "temperature": temperature,
            }
            if active_reasoning and active_reasoning != "off":
                payload["reasoningEffort"] = active_reasoning

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._build_headers(), method="POST")

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
                    return ""
                else:
                    return result["choices"][0]["message"]["content"]

        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenCode API HTTP {e.code} error: {err_body}") from e
        except Exception as e:
            raise RuntimeError(f"OpenCode request failed: {e}") from e
