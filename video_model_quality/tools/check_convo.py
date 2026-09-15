"""Turn-start hook: pi / any agent runs this FIRST every turn — no user nudge needed.
Usage: python tools/check_convo.py [--seen FILE]
- Compares conversation.md headers vs .pi-convo-seen (per-agent cursor).
- Prints ONLY new entries (full blocks) since last check.
- Updates cursor so next turn is incremental.
Exit 0 = no new, 2 = new messages (agent must read + ack).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVO = ROOT / "conversation.md"

HEADER_RE = re.compile(r"^### \[(.*?)\] @(.*?)$")
TEMPLATE_MARKERS = ("<Model-Name>", "YYYY-MM-DD")


def is_real_header(line: str) -> bool:
    return bool(HEADER_RE.match(line.strip())) and not any(t in line for t in TEMPLATE_MARKERS)


def load_entries():
    lines = CONVO.read_text(encoding="utf-8", errors="ignore").splitlines()
    idx = [i for i, l in enumerate(lines) if is_real_header(l)]
    entries = []
    for k, start in enumerate(idx):
        end = idx[k + 1] if k + 1 < len(idx) else len(lines)
        entries.append("\n".join(lines[start:end]))
    return entries


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seen", default=str(ROOT / ".pi-convo-seen"),
                    help="cursor file storing last seen count")
    ap.add_argument("--agent", default="Pi-Agent")
    args = ap.parse_args()

    if not CONVO.exists():
        print("check_convo: conversation.md missing")
        return 0
    entries = load_entries()
    seen_path = Path(args.seen)
    try:
        seen = int(seen_path.read_text().strip())
    except Exception:
        seen = 0
    # clamp: if file was compacted (count shrank), reset
    if seen > len(entries):
        seen = 0
    new = entries[seen:]
    if not new:
        print(f"check_convo: no new (seen {seen}/{len(entries)})")
        return 0
    print(f"check_convo: {len(new)} NEW entr(y/ies) [{seen}->{len(entries)}] — @{args.agent} must read + ack:")
    print("=" * 70)
    for e in new:
        print(e)
        print("-" * 70)
    seen_path.write_text(str(len(entries)))
    return 2


if __name__ == "__main__":
    sys.exit(main())
