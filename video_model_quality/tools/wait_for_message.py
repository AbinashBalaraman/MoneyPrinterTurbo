"""Reactive message listener for Antigravity / Gemini.

Sleeps locally until another agent writes a new message to conversation.md.
When a new entry appears, it prints the message and exits with 0.
This triggers Antigravity's Reactive Wakeup, automatically waking up the model!
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVO_FILE = ROOT / "conversation.md"
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--agent", default="Gemini-e48e797c")
    p.add_argument("--timeout", type=int, default=3600)  # 1 hour max
    p.add_argument("--interval", type=float, default=2.0)
    args = p.parse_args()

    start_time = time.time()
    seen = get_seen_count(args.agent)

    print(f"[*] Reactive listener waiting for incoming messages for @{args.agent} (baseline count: {seen})...")
    sys.stdout.flush()

    while time.time() - start_time < args.timeout:
        entries = load_entries()
        if len(entries) > seen:
            new_entries = entries[seen:]
            print(f"\n[!] WAKEUP TRIGGER: {len(new_entries)} new incoming message(s) detected!\n")
            for e in new_entries:
                print("=" * 60)
                print(e)
                print("=" * 60)
            sys.stdout.flush()
            return 0
        time.sleep(args.interval)

    print("[*] Timeout waiting for messages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
