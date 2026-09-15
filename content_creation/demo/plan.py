#!/usr/bin/env python3
"""
plan.py - turn a topic into a renderable scene JSON using a FREE text LLM.

Providers tried in order (all zero-cost):
  1. ollama       - local model, no key, no network   (ollama pull qwen3:8b)
  2. pollinations - keyless OpenAI-compatible hosted endpoint
  3. example      - bundled demo script (offline fallback)

Any other free OpenAI-compatible endpoint works too:
  python demo/plan.py --topic "..." --provider custom \
      --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT_PATH = HERE / "plan_prompt.md"
EXAMPLE = HERE / "script.example.json"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
POLLI_URL = "https://text.pollinations.ai/openai"
POLLI_MODEL = os.environ.get("POLLI_MODEL", "openai")
# OVHcloud AI Endpoints: truly anonymous tier, OpenAI-compatible, no key.
# Verified 2026-09-12: Mistral-7B-Instruct-v0.3 and Qwen3-32B respond keyless
# (per-IP rate limit ~ tens of requests/minute; backoff on 429).
OVH_URL = "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1"
OVH_MODEL = os.environ.get("OVH_MODEL", "Qwen3-32B")

VALID_MOTIONS = {"zoom_in", "zoom_out", "pan_left", "pan_right", "static"}


def build_prompt(topic: str) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    block = re.search(r"```text\n(.*?)```", template, re.S)
    body = block.group(1) if block else template
    return body.replace("{{TOPIC}}", topic).strip()


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a chat response."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in response")
    return json.loads(text[start : end + 1])


def validate(data: dict) -> dict:
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 10:
        raise ValueError("expected 3-10 scenes")
    for i, s in enumerate(scenes):
        if not isinstance(s.get("narration"), str) or not s["narration"].strip():
            raise ValueError(f"scene {i}: missing narration")
        if s.get("motion", "zoom_in") not in VALID_MOTIONS:
            s["motion"] = "zoom_in"
        s.setdefault("stock_query", "abstract")
    data["aspect"] = data.get("aspect", "9:16")
    data["voice"] = data.get("voice", "en-US-AndrewMultilingualNeural")
    data.setdefault("title", "Untitled")
    return data


def chat_ollama(topic: str) -> dict:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": build_prompt(topic)}],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.8},
    }
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return extract_json(json.load(r)["message"]["content"])


def chat_openai_compat(base: str, model: str, topic: str, key: str = "") -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_prompt(topic)}],
        "temperature": 0.8,
    }
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        body = json.load(r)
    return extract_json(body["choices"][0]["message"]["content"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--out", default=str(HERE.parent / "out" / "script.json"))
    ap.add_argument("--provider", default="auto",
                    choices=["auto", "ollama", "pollinations", "ovhcloud",
                             "custom", "example"])
    ap.add_argument("--base-url", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--api-key", default=os.environ.get("LLM_API_KEY", ""))
    a = ap.parse_args()

    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    order = (["ollama", "ovhcloud", "pollinations", "example"] if a.provider == "auto"
             else [a.provider])
    data, used = None, None
    errors = []

    for prov in order:
        try:
            if prov == "example":
                data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
            elif prov == "ollama":
                data = chat_ollama(a.topic)
            elif prov == "pollinations":
                data = chat_openai_compat(POLLI_URL, POLLI_MODEL, a.topic)
            elif prov == "ovhcloud":
                data = chat_openai_compat(OVH_URL, OVH_MODEL, a.topic)
            else:
                if not a.base_url:
                    raise ValueError("--base-url is required for provider=custom")
                data = chat_openai_compat(a.base_url, a.model or "gpt-4o-mini", a.topic, a.api_key)
            data = validate(data)
            used = prov
            break
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, KeyError,
                json.JSONDecodeError) as e:
            errors.append(f"{prov}: {type(e).__name__}: {e}")
            print(f"[plan] {prov} unavailable -> {e}", file=sys.stderr)
            if prov == "ovhcloud" and "429" in str(e):
                print("[plan] OVH rate-limited, backing off 8s...", file=sys.stderr)
                import time; time.sleep(8)

    if data is None:
        print("[plan] every provider failed:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1

    out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    total_words = sum(len(s["narration"].split()) for s in data["scenes"])
    print(f"[plan] provider={used} scenes={len(data['scenes'])} "
          f"words={total_words} (~{total_words / 2.6:.0f}s)")
    print(f"[plan] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
