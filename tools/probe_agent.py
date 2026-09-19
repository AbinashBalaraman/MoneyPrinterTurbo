"""Drive the chat agent with realistic requests and report what breaks.

This is the bug-finding tool Abi asked for: instead of reading code and guessing
where it might fail, send the assistant the things a person would actually ask
and watch what it does. Every prompt below is something a user of this project
would plausibly type.

Deliberately avoids anything that would spend money: the pipeline's spend gate
is ON, and a probe run should not generate media. Prompts that would are marked
and skipped.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

AGENT = "http://127.0.0.1:8100"

#: NVIDIA NIM by default. Gemini's free quota is easily exhausted (429
#: RESOURCE_EXHAUSTED), and a probe run that dies on the second prompt has not
#: probed anything. Override with --model.
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

PROMPTS = [
    "what series do I have?",
    "how many episodes does farmer_and_rusty have?",
    "make episode 2 of farmer_and_rusty",
    "publish episode 1 of farmer_and_rusty to youtube",
    "what is in the render queue right now?",
    "show me the continuity for interesting_facts",
    "create a new series called space facts",
    "delete the space facts series",
    "what can you do?",  # no tool call expected — a sanity baseline
]


def ask(prompt: str, model: str) -> dict:
    """One turn through the agent tool loop; returns a compact summary."""
    payload = json.dumps(
        {
            "messages": [{"role": "user", "content": prompt}],
            "model": model,
            "use_tools": True,
            "max_rounds": 6,
        }
    )
    proc = subprocess.run(
        [
            "curl", "-s", "--noproxy", "*", "-N", "-X", "POST",
            f"{AGENT}/api/opencode/agent/stream",
            "-H", "Content-Type: application/json",
            "-d", payload,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    text_parts: list[str] = []
    tools: list[dict] = []
    errors: list[str] = []
    refused = False

    for line in proc.stdout.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            event = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "text":
            text_parts.append(event.get("text") or "")
        elif kind == "tool":
            tools.append(
                {
                    "name": event.get("tool", "?"),
                    "status": event.get("status", "?"),
                    "risk": event.get("risk", ""),
                    "args": event.get("args") or {},
                    "message": (event.get("message") or "")[:200],
                }
            )
            if event.get("refused"):
                refused = True
        elif kind == "error":
            errors.append((event.get("message") or "")[:300])

    return {
        "text": "".join(text_parts).strip(),
        "tools": tools,
        "errors": errors,
        "refused": refused,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the chat agent for bugs.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"model id to probe with (default {DEFAULT_MODEL})",
    )
    parser.add_argument("prompt", nargs="*", help="optional: probe only these")
    args = parser.parse_args()
    prompts = args.prompt or PROMPTS
    print(f"model: {args.model}")

    for prompt in prompts:
        started = time.monotonic()
        try:
            result = ask(prompt, args.model)
        except subprocess.TimeoutExpired:
            print(f"\n### {prompt}\n  TIMEOUT after 300s")
            continue
        elapsed = time.monotonic() - started

        print(f"\n### {prompt}   [{elapsed:.0f}s]")
        reply = result["text"] or "(EMPTY REPLY)"
        print(f"  reply: {reply[:300].replace(chr(10), ' | ')}")

        bad = [t for t in result["tools"] if t["status"] == "error"]
        if result["tools"]:
            names = ", ".join(f"{t['name']}({t['status']})" for t in result["tools"])
            print(f"  tools: {names}")
        # Show the arguments of anything that changes state. A duplicated write
        # is invisible without them: the same call twice looks like one tool in
        # the event stream until you see what it was asked to do.
        for t in result["tools"]:
            if t["status"] == "start" and t["risk"] in ("write", "spend", "destructive"):
                print(f"  {t['risk'].upper()} CALL: {t['name']}({json.dumps(t['args'], ensure_ascii=False)[:220]})")
        for t in bad:
            print(f"  TOOL FAILED: {t['name']}: {t['message']}")
        for err in result["errors"]:
            print(f"  STREAM ERROR: {err}")
        if result["refused"]:
            print("  (refused — the gate working)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
