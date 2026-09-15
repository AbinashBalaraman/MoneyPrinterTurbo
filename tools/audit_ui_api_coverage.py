#!/usr/bin/env python
"""Cross-check the dashboard against the agent's live API surface.

Answers two questions that are otherwise tedious to answer by hand, and that
map directly onto the two ways a GUI lies to its user:

1. **Dead controls.** Does every endpoint the dashboard calls actually exist on
   the agent? A call to a route that was renamed or never built produces a
   button that reports success and does nothing -- the failure mode this check
   exists to catch.
2. **Invisible capability.** Which server routes does the dashboard never call?
   Not all of those are bugs: `/api/flow/*` is the internal worker/extension
   surface and `/api/ext/callback` belongs to the Chrome extension, so neither
   belongs in the dashboard. The point is to make the gap explicit and let a
   human decide which of the rest deserve a UI.

Requires the agent to be running (it reads `/openapi.json`).

    python tools/audit_ui_api_coverage.py
    python tools/audit_ui_api_coverage.py --port 8100 --dashboard flowkit/dashboard
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Client helpers the dashboard actually routes requests through, plus raw fetch.
# Backtick and quoted literals are captured separately: a template literal may
# legitimately contain quotes (`/models${refresh ? '?x=1' : ''}`), so treating
# them as one character class would truncate the path at the first inner quote.
CALL_PATTERN = re.compile(
    r"""(?:fetchAPI|patchAPI|postAPI|putAPI|deleteAPI|fetch)\s*(?:<[^>]*>)?\s*\(\s*"""
    r"""(?:`([^`]+)`|'([^']+)'|"([^"]+)")"""
)

# Routes owned by something other than the dashboard. Listing them explicitly
# keeps the "unused" report honest instead of flagging by-design omissions as
# oversights.
OTHER_CONSUMERS = {
    "/api/flow/": "internal worker/extension surface (driven via POST /api/requests)",
    "/api/ext/": "Chrome extension callback",
    "/api/music/callback": "Suno provider callback",
    "/api/logs": "delivered over the WebSocket log bus instead",
    "/api/publications/pending": "internal publish queue",
}


def _normalise(path: str) -> str:
    """Collapse any path parameter to `{p}` so shapes can be compared."""
    return re.sub(r"\{[^}]*\}", "{p}", path)


def _extract_calls(dashboard: Path) -> dict[str, set[str]]:
    """Map each API path the UI calls to the files that call it."""
    src = dashboard / "src"
    calls: dict[str, set[str]] = {}

    for path in list(src.rglob("*.tsx")) + list(src.rglob("*.ts")):
        if "node_modules" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CALL_PATTERN.finditer(text):
            target = match.group(1) or match.group(2) or match.group(3)
            if not target or not target.startswith("/"):
                continue
            # Template literals need care. A `${…}` that follows a `/` is a path
            # parameter (`/api/videos/${vid}/publications`), while one that does
            # not is a suffix such as a query string
            # (`/api/opencode/models${refresh ? '?refresh=true' : ''}`). Collapse
            # the first to `{p}` and drop the second, then strip any real query.
            target = re.sub(r"/\$\{[^}]*\}", "/{p}", target)
            target = re.sub(r"\$\{[^}]*\}", "", target)
            target = target.split("?")[0].rstrip("/") or "/"
            rel = path.relative_to(src).as_posix()
            calls.setdefault(target, set()).add(rel)

    return calls


def _fetch_openapi(host: str, port: int, timeout: float = 10.0) -> dict:
    # Proxy handlers are cleared: http_proxy is often set on this machine and
    # would otherwise be used for a loopback address.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f"http://{host}:{port}/openapi.json"
    with opener.open(url, timeout=timeout) as response:
        return json.load(response)


def _owner_of(path: str) -> str | None:
    for prefix, reason in OTHER_CONSUMERS.items():
        if path.startswith(prefix):
            return reason
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit dashboard vs agent API coverage")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--dashboard", default="flowkit/dashboard")
    args = ap.parse_args()

    dashboard = Path(args.dashboard)
    if not dashboard.is_absolute():
        dashboard = (REPO_ROOT / dashboard).resolve()
    if not (dashboard / "src").is_dir():
        print(f"no src/ under {dashboard}")
        return 2

    try:
        spec = _fetch_openapi(args.host, args.port)
    except Exception as exc:
        print(f"could not reach the agent at {args.host}:{args.port} -- {exc}")
        print("start it first: cd flowkit && python -m agent.main")
        return 2

    server_paths = set(spec.get("paths", {}))
    server_norm = {_normalise(p) for p in server_paths}

    calls = _extract_calls(dashboard)
    called_norm = {_normalise(c) for c in calls}

    print(f"dashboard calls {len(calls)} path(s); agent exposes {len(server_paths)}")
    print()

    dead = []
    for path in sorted(calls):
        if _normalise(path) in server_norm:
            continue
        dead.append(path)

    print("== dashboard calls with NO matching agent route ==")
    if dead:
        for path in dead:
            who = ", ".join(sorted(calls[path]))
            print(f"  DEAD  {path}   <- {who}")
        print()
        print(f"  {len(dead)} dead call(s). These render as controls that appear to")
        print("  work and do nothing. Fix or remove them.")
    else:
        print("  none -- every call resolves to a real route")
    print()

    unused_by_design: list[str] = []
    unused_real: list[str] = []
    for path in sorted(server_paths):
        if _normalise(path) in called_norm:
            continue
        (unused_by_design if _owner_of(path) else unused_real).append(path)

    print("== agent routes the dashboard never calls ==")
    print(f"  by design ({len(unused_by_design)}):")
    for path in unused_by_design:
        print(f"      {path}   ({_owner_of(path)})")
    print()
    print(f"  unclaimed ({len(unused_real)}):")
    groups: dict[str, list[str]] = {}
    for path in unused_real:
        group = "/".join(path.split("/")[:3]) or path
        groups.setdefault(group, []).append(path)
    for group in sorted(groups):
        print(f"      {group}  ({len(groups[group])})")
        for path in groups[group]:
            methods = ",".join(sorted(m.upper() for m in spec["paths"][path]))
            print(f"          {methods:24s} {path}")
    print()
    print(f"  {len(unused_real)} route(s) with no UI and no other known caller.")
    print("  Decide per group: surface it, or delete it.")

    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
