"""Audit: find silent exception swallows in src/ (bare except / except ...: pass|return|continue).

Exit prints '<n> silent-swallow sites' and lists them.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

SILENT_NEXT = {"pass", "return", "return None", "continue", "break"}
EXC_RE = re.compile(r"^\s*except\b")


def main() -> int:
    sites = []
    for p in sorted(SRC.rglob("*.py")):
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for i, l in enumerate(lines):
            if not EXC_RE.match(l):
                continue
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            # same-line body after colon
            body = l.split(":", 1)[1].strip() if ":" in l else ""
            if not body and nxt in SILENT_NEXT:
                sites.append(f"{p.relative_to(ROOT)}:{i+1}: {l.strip()} -> {nxt}")
    print(f"{len(sites)} silent-swallow sites")
    for s in sites:
        print("  " + s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
