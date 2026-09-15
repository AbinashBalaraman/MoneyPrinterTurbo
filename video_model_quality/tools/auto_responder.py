"""Autonomous Auto-Responder Daemon for Pi Agent (pi coding agent harness).

Continuously monitors conversation.md and out/task_board.json.
When a message or delegated task arrives for @Pi-Agent, it automatically invokes
the Pi Coding Agent CLI (`pi -p ...`) to process the request, run tests/edits,
and post the response back to the conversation bus.

Usage:
  python tools/auto_responder.py [--poll 5]
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVO_FILE = ROOT / "conversation.md"
TASK_BOARD_FILE = ROOT / "out" / "task_board.json"

HEADER_RE = re.compile(r"^### \[(.*?)\] @(.*?)$")
TEMPLATE_MARKERS = ("<Model-Name>", "YYYY-MM-DD")


def get_cursor_file(agent_name: str) -> Path:
    slug = agent_name.lower().replace("@", "").split("-")[0]
    return ROOT / f".{slug}-convo-seen"


def get_seen_count(agent_name: str) -> int:
    cursor_f = get_cursor_file(agent_name)
    if cursor_f.exists():
        try:
            return int(cursor_f.read_text().strip())
        except Exception:
            return 0
    return 0


def set_seen_count(agent_name: str, count: int) -> None:
    cursor_f = get_cursor_file(agent_name)
    cursor_f.write_text(str(count), encoding="utf-8")


def load_entries():
    if not CONVO_FILE.exists():
        return []
    lines = CONVO_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    starts = [i for i, l in enumerate(lines) if HEADER_RE.match(l.strip()) and not any(t in l for t in TEMPLATE_MARKERS)]
    entries = []
    for k, s_idx in enumerate(starts):
        e_idx = starts[k + 1] if k + 1 < len(starts) else len(lines)
        entries.append("\n".join(lines[s_idx:e_idx]).strip())
    return entries


def invoke_pi_agent(agent_name: str, incoming_messages: list):
    """Invokes the Pi Coding Agent harness (pi -p) to autonomously process incoming messages."""
    combined_msg = "\n\n".join(incoming_messages)
    prompt = (
        f"You are @{agent_name} collaborating on the 2D stickman video model project.\n"
        f"You just received the following message(s) on the conversation bus:\n"
        f"--------------------------------------------------\n"
        f"{combined_msg}\n"
        f"--------------------------------------------------\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Read AGENTS.md and the message above carefully.\n"
        f"2. If a task or action is requested, carry it out in the codebase (e.g. edit files, run python -m pytest tests/ -v).\n"
        f"3. Always report back to the team by running either:\n"
        f"   python tools/agent_bus.py send --from {agent_name} --to Gemini-e48e797c --summary \"...\" --body \"...\"\n"
        f"   or if completing a task:\n"
        f"   python tools/agent_bus.py complete --task <TASK-ID> --by {agent_name} --notes \"...\"\n"
    )

    print(f"\n[AUTO-RESPONDER] Invoking Pi Coding Agent for @{agent_name} (pi -p)...")
    sys.stdout.flush()

    cmd = ["cmd", "/c", "pi", "-p", prompt]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=300
        )
        print(f"[AUTO-RESPONDER] Pi finished with exit code {proc.returncode}")
        if proc.stdout:
            print("--- Pi Output ---")
            print(proc.stdout[:1000])
        if proc.stderr:
            print("--- Pi Stderr ---")
            print(proc.stderr[:500])
        sys.stdout.flush()
    except subprocess.TimeoutExpired:
        print("[AUTO-RESPONDER] Pi run timed out after 300s.")
    except Exception as e:
        print(f"[AUTO-RESPONDER] Error invoking Pi: {e}")


def run_loop(agent_name: str, interval: float = 5.0):
    print(f"[*] Autonomous Auto-Responder active for @{agent_name}")
    print(f"[*] Monitoring {CONVO_FILE} using Pi coding agent harness (pi)...")
    sys.stdout.flush()

    while True:
        entries = load_entries()
        seen = get_seen_count(agent_name)

        if len(entries) > seen:
            new_entries = entries[seen:]
            set_seen_count(agent_name, len(entries))

            addressed = []
            for e in new_entries:
                # Don't respond to self
                first_line = e.splitlines()[0] if e.splitlines() else ""
                if f"@{agent_name}" in first_line:
                    continue
                # If addressed to agent or mentions agent
                if f"@{agent_name}" in e or "To all" in e or "to all" in e:
                    addressed.append(e)

            if addressed:
                print(f"\n[!] New message(s) addressed to @{agent_name} ({len(addressed)} entries):")
                invoke_pi_agent(agent_name, addressed)
            else:
                print(f"[*] {len(new_entries)} entry/ies ignored (not addressed to @{agent_name})")

        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="Autonomous Auto-Responder Daemon for Pi Agent")
    p.add_argument("--agent", default="Pi-Agent", help="Agent identity to respond as")
    p.add_argument("--interval", type=float, default=5.0, help="Polling interval in seconds")
    args = p.parse_args()

    try:
        run_loop(args.agent, args.interval)
    except KeyboardInterrupt:
        print("\nAuto-responder stopped.")


if __name__ == "__main__":
    main()
