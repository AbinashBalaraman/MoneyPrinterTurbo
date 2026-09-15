"""Parallel convo watcher — polls conversation.md, prints NEW entries when any agent edits.
Run as background parallel agent:
  python tools/convo_watcher.py              # foreground, 10s poll
  python tools/convo_watcher.py --interval 15 --once   # single check (for CI/hooks)

State: out/convo_state.json {last_hash, last_headers, updated_at}
Log:   out/watch.log
This does NOT need the user to say 'read the convo' — any agent that runs
`python tools/check_convo.py` at turn start auto-sees new messages.
"""
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONVO = ROOT / "conversation.md"
STATE = ROOT / "out" / "convo_state.json"
LOG = ROOT / "out" / "watch.log"
HEADER_RE = re.compile(r"^### \[(.*?)\] @(.*?)$")
TEMPLATE_MARKERS = ("<Model-Name>", "YYYY-MM-DD")


def is_real_header(line: str) -> bool:
    m = HEADER_RE.match(line.strip())
    if not m:
        return False
    return not any(t in line for t in TEMPLATE_MARKERS)


def file_hash() -> str:
    h = hashlib.sha256()
    h.update(CONVO.read_bytes())
    return h.hexdigest()


def get_headers():
    headers = []
    try:
        for line in CONVO.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if HEADER_RE.match(s) and not any(t in s for t in TEMPLATE_MARKERS):
                headers.append(s)
    except FileNotFoundError:
        pass
    return headers


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_hash": "", "last_headers": [], "updated_at": ""}


def save_state(hash_, headers):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "last_hash": hash_,
        "last_headers": headers,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(headers),
    }, indent=2), encoding="utf-8")


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} [convo-watch] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def check_once(verbose=True) -> list:
    """Returns list of NEW header lines since last state. Updates state."""
    if not CONVO.exists():
        if verbose:
            log("conversation.md missing!")
        return []
    h = file_hash()
    headers = get_headers()
    st = load_state()
    old = set(st.get("last_headers", []))
    new = [x for x in headers if x not in old]
    if st.get("last_hash") == "" and old == set():
        # first run — baseline, don't spam
        save_state(h, headers)
        if verbose:
            log(f"baseline: {len(headers)} entries, hash {h[:8]}")
        return []
    if new or st.get("last_hash") != h:
        save_state(h, headers)
        if new and verbose:
            log(f"CHANGE: {len(new)} new entr(y/ies)")
            for n in new:
                log(f"  NEW >> {n}")
        elif verbose:
            log("content edited (no new headers)")
        return new
    return []


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=10, help="poll seconds")
    ap.add_argument("--once", action="store_true", help="single check then exit")
    args = ap.parse_args()
    log(f"started, polling {CONVO} every {args.interval}s")
    check_once(verbose=True)  # baseline
    if args.once:
        new = check_once(verbose=True)
        sys.exit(0 if not new else 2)
    try:
        while True:
            time.sleep(args.interval)
            new = check_once(verbose=True)
            if new:
                # also dump last 25 lines so async terminal shows context
                try:
                    tail = CONVO.read_text(encoding="utf-8", errors="ignore").splitlines()[-25:]
                    for t in tail:
                        print(f"    | {t}")
                except Exception:
                    pass
    except KeyboardInterrupt:
        log("stopped by user")


if __name__ == "__main__":
    main()
