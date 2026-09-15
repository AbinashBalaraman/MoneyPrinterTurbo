"""Multi-Agent Live Conversation & Delegation Bus.

Enables instant peer-to-peer communication, task delegation, and live interactive
terminal collaboration between @Gemini-e48e797c, @Pi-Agent, @OC2-Agent, and subagents.

Usage:
  python tools/agent_bus.py status
  python tools/agent_bus.py check --agent Gemini-e48e797c
  python tools/agent_bus.py send --from Gemini-e48e797c --to Pi-Agent --summary "Summary" --body "Message text"
  python tools/agent_bus.py delegate --from Gemini-e48e797c --to Pi-Agent --task "Task title" --details "Details..."
  python tools/agent_bus.py complete --task TASK-001 --by Pi-Agent --notes "Verified 20/20 tests"
  python tools/agent_bus.py live [--agent Gemini-e48e797c]
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
CONVO_FILE = ROOT / "conversation.md"
TASK_BOARD_FILE = ROOT / "out" / "task_board.json"

HEADER_RE = re.compile(r"^### \[(.*?)\] @(.*?)$")
TEMPLATE_MARKERS = ("<Model-Name>", "YYYY-MM-DD")


def get_timestamp_str() -> str:
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M")


def load_task_board() -> Dict:
    if TASK_BOARD_FILE.exists():
        try:
            return json.loads(TASK_BOARD_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"tasks": [], "last_id": 0}


def save_task_board(board: Dict) -> None:
    TASK_BOARD_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASK_BOARD_FILE.write_text(json.dumps(board, indent=2), encoding="utf-8")


def is_real_header(line: str) -> bool:
    s = line.strip()
    return bool(HEADER_RE.match(s)) and not any(t in s for t in TEMPLATE_MARKERS)


def load_all_entries() -> List[str]:
    if not CONVO_FILE.exists():
        return []
    lines = CONVO_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    starts = [i for i, l in enumerate(lines) if is_real_header(l)]
    entries = []
    for k, s_idx in enumerate(starts):
        e_idx = starts[k + 1] if k + 1 < len(starts) else len(lines)
        entries.append("\n".join(lines[s_idx:e_idx]).strip())
    return entries


def get_cursor_file(agent_name: str) -> Path:
    clean = agent_name.strip().lstrip('@')
    lower = clean.lower()
    if lower.startswith("gemini"):
        return ROOT / ".gemini-convo-seen"
    if lower.startswith("pi"):
        return ROOT / ".pi-convo-seen"
    if lower.startswith("oc2"):
        return ROOT / ".oc2-convo-seen"
    slug = re.sub(r'[^a-zA-Z0-9_]', '_', lower)
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


def cmd_status() -> None:
    """Displays overview of conversation bus, agent cursors, and active tasks."""
    entries = load_all_entries()
    board = load_task_board()

    print("\n" + "=" * 70)
    print("  MULTI-AGENT CONVERSATION BUS & TASK BOARD")
    print("=" * 70)
    print(f"Total conversation entries: {len(entries)}")

    # Discover all agents with cursor files + known defaults
    known_agents = ["Gemini-e48e797c", "Pi-Agent", "OC2-Agent", "Copilot-7f3a9c2e"]
    discovered = []
    for cf in ROOT.glob(".*-convo-seen"):
        base = cf.name[1:-len("-convo-seen")]
        matched = False
        for ka in known_agents:
            if base in ka.lower():
                matched = True
                break
        if not matched:
            discovered.append(base.capitalize() + "-Agent")
    agents = sorted(set(known_agents + discovered))

    print("\n[Agent Read Status]")
    for ag in agents:
        seen = get_seen_count(ag)
        unread = max(0, len(entries) - seen)
        badge = "UP TO DATE" if unread == 0 else f"{unread} UNREAD"
        print(f"  - @{ag:20s}: seen {seen}/{len(entries)} [{badge}]")

    print("\n[Task Board]")
    tasks = board.get("tasks", [])
    if not tasks:
        print("  No tasks currently recorded.")
    else:
        for t in tasks:
            status_symbol = {
                "PENDING": "[ ]",
                "IN_PROGRESS": "[*]",
                "COMPLETED": "[X]"
            }.get(t.get("status"), "[?]")
            print(f"  {status_symbol} {t['id']} [{t['status']}] -> @{t['assignee']}: {t['title']}")
            if t.get("notes"):
                print(f"      Notes: {t['notes']}")
    print("=" * 70 + "\n")


def cmd_check(agent_name: str) -> List[str]:
    """Reads unread messages for agent and advances cursor."""
    entries = load_all_entries()
    seen = get_seen_count(agent_name)
    if seen > len(entries):
        seen = 0
    new_entries = entries[seen:]
    set_seen_count(agent_name, len(entries))

    if not new_entries:
        print(f"[@{agent_name}] All clear! (seen {len(entries)}/{len(entries)})")
        return []

    print(f"[@{agent_name}] {len(new_entries)} NEW message(s):")
    print("-" * 70)
    for entry in new_entries:
        print(entry)
        print("-" * 70)
    return new_entries


def post_to_convo(author: str, status: str, summary: str, body_lines: List[str]) -> None:
    """Appends a new formatted entry to conversation.md and updates author cursor."""
    ts = get_timestamp_str()
    header = f"### [{ts}] @{author}"
    meta = f"**Status**: {status}\n**Summary**: {summary}\n"
    body_text = "\n".join(body_lines)

    full_entry = f"\n{header}\n{meta}\n{body_text}\n"

    with open(CONVO_FILE, "a", encoding="utf-8") as f:
        f.write(full_entry)

    # Advance author's cursor so they don't re-read their own message
    entries = load_all_entries()
    set_seen_count(author, len(entries))
    print(f"[+] Posted to conversation.md as @{author}")


def cmd_send(from_agent: str, to_agent: str, summary: str, body: str) -> None:
    """Posts a direct message to another agent on the bus."""
    body_lines = [
        f"- **To @{to_agent}**:",
        f"  {body}"
    ]
    post_to_convo(from_agent, "Message", summary, body_lines)


def cmd_delegate(
    from_agent: str,
    to_agent: str,
    task_title: str,
    details: str,
    priority: str = "P1",
    acceptance: Optional[str] = None
) -> str:
    """Creates a task on the board, delegates to target agent, and posts to bus."""
    board = load_task_board()
    next_num = board.get("last_id", 0) + 1
    board["last_id"] = next_num
    task_id = f"TASK-{next_num:03d}"

    task_record = {
        "id": task_id,
        "title": task_title,
        "assignee": to_agent,
        "delegated_by": from_agent,
        "status": "PENDING",
        "priority": priority,
        "created_at": get_timestamp_str(),
        "details": details,
        "acceptance": acceptance or "Pass all unit tests and update status"
    }
    board.setdefault("tasks", []).append(task_record)
    save_task_board(board)

    # Post delegation card to conversation bus
    body_lines = [
        f"- **To @{to_agent}**:",
        f"  - **Task ID**: `{task_id}` [{priority}]",
        f"  - **Assignment**: {task_title}",
        f"  - **Details**: {details}",
        f"  - **Acceptance Criteria**: {task_record['acceptance']}",
        f"  - *Please start your acknowledgment with `To @{from_agent}:` and run `python tools/agent_bus.py complete --task {task_id}` once verified.*"
    ]
    summary = f"Delegated [{task_id}] to @{to_agent}: {task_title}"
    post_to_convo(from_agent, "Delegation", summary, body_lines)
    print(f"[+] Task {task_id} successfully registered and delegated to @{to_agent}!")
    return task_id


def cmd_complete(task_id: str, by_agent: str, notes: str) -> None:
    """Marks a task completed on the board and notifies bus."""
    board = load_task_board()
    found = False
    for t in board.get("tasks", []):
        if t.get("id") == task_id:
            t["status"] = "COMPLETED"
            t["completed_at"] = get_timestamp_str()
            t["completed_by"] = by_agent
            t["notes"] = notes
            found = True
            break
    if not found:
        print(f"[!] Task {task_id} not found on board.")
        return
    save_task_board(board)

    summary = f"Completed [{task_id}]: {notes[:60]}"
    body_lines = [
        f"- **Task Complete**: `{task_id}` marked COMPLETED by @{by_agent}.",
        f"  - **Verification Notes**: {notes}"
    ]
    post_to_convo(by_agent, "Execution Complete", summary, body_lines)
    print(f"[SUCCESS] Task {task_id} marked COMPLETED.")


def cmd_live(agent_name: str, poll_interval: float = 3.0) -> None:
    """Interactive live console: monitors bus in background and accepts user input."""
    print("\n" + "=" * 70)
    print(f"  LIVE CONVERSATION CONSOLE — @{agent_name}")
    print("  Commands:")
    print("    /send <to_agent> <message>     - Send instant message")
    print("    /delegate <to_agent> <task>    - Delegate task card")
    print("    /status                        - View task board")
    print("    /check                         - Force check new messages")
    print("    /quit                          - Exit console")
    print("=" * 70 + "\n")

    cmd_check(agent_name)

    import threading
    stop_event = threading.Event()

    def watcher():
        while not stop_event.is_set():
            entries = load_all_entries()
            seen = get_seen_count(agent_name)
            if len(entries) > seen:
                new_entries = entries[seen:]
                set_seen_count(agent_name, len(entries))
                print(f"\n\a[LIVE ALERT] {len(new_entries)} incoming message(s):")
                print("-" * 50)
                for e in new_entries:
                    print(e)
                    print("-" * 50)
                print(f"[@{agent_name}] > ", end="", flush=True)
            time.sleep(poll_interval)

    t = threading.Thread(target=watcher, daemon=True)
    t.start()

    try:
        while True:
            cmd_input = input(f"[@{agent_name}] > ").strip()
            if not cmd_input:
                continue
            if cmd_input == "/quit":
                break
            elif cmd_input == "/status":
                cmd_status()
            elif cmd_input == "/check":
                cmd_check(agent_name)
            elif cmd_input.startswith("/send "):
                parts = cmd_input[6:].split(" ", 1)
                if len(parts) == 2:
                    to_ag, text = parts
                    cmd_send(agent_name, to_ag, f"Live msg to @{to_ag}", text)
                else:
                    print("Usage: /send <to_agent> <message>")
            elif cmd_input.startswith("/delegate "):
                parts = cmd_input[10:].split(" ", 1)
                if len(parts) == 2:
                    to_ag, task_text = parts
                    cmd_delegate(agent_name, to_ag, task_text, task_text)
                else:
                    print("Usage: /delegate <to_agent> <task description>")
            else:
                post_to_convo(agent_name, "Update", cmd_input[:60], [f"- {cmd_input}"])
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        stop_event.set()
        print("\nExiting live console.")


def main():
    p = argparse.ArgumentParser(description="Multi-Agent Live Bus & Task Delegation")
    sub = p.add_subparsers(dest="subcmd")

    sub.add_parser("status", help="Show active task board and unread status")

    p_check = sub.add_parser("check", help="Check and print unread messages")
    p_check.add_argument("--agent", default="Gemini-e48e797c")

    p_send = sub.add_parser("send", help="Send a message to another agent")
    p_send.add_argument("--from", dest="from_agent", default="Gemini-e48e797c")
    p_send.add_argument("--to", dest="to_agent", required=True)
    p_send.add_argument("--summary", required=True)
    p_send.add_argument("--body", required=True)

    p_del = sub.add_parser("delegate", help="Delegate a task card to another agent")
    p_del.add_argument("--from", dest="from_agent", default="Gemini-e48e797c")
    p_del.add_argument("--to", dest="to_agent", required=True)
    p_del.add_argument("--task", required=True)
    p_del.add_argument("--details", required=True)
    p_del.add_argument("--priority", default="P1")
    p_del.add_argument("--acceptance", default=None)

    p_done = sub.add_parser("complete", help="Mark a task completed on the board")
    p_done.add_argument("--task", required=True)
    p_done.add_argument("--by", dest="by_agent", default="Pi-Agent")
    p_done.add_argument("--notes", default="Verified and passing")

    p_live = sub.add_parser("live", help="Launch live interactive console")
    p_live.add_argument("--agent", default="Gemini-e48e797c")
    p_live.add_argument("--interval", type=float, default=3.0)

    args = p.parse_args()
    if not args.subcmd or args.subcmd == "status":
        cmd_status()
    elif args.subcmd == "check":
        cmd_check(args.agent)
    elif args.subcmd == "send":
        cmd_send(args.from_agent, args.to_agent, args.summary, args.body)
    elif args.subcmd == "delegate":
        cmd_delegate(args.from_agent, args.to_agent, args.task, args.details, args.priority, args.acceptance)
    elif args.subcmd == "complete":
        cmd_complete(args.task, args.by_agent, args.notes)
    elif args.subcmd == "live":
        cmd_live(args.agent, args.interval)


if __name__ == "__main__":
    main()
