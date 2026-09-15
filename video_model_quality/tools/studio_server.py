"""Studio server: a local web UI for testing the actual product.

Serves a small single-page app plus a JSON API over the same
``src.service`` pipeline the CLI uses, so what you see in the browser is exactly
what the engine produces -- no parallel code path, no mock.

Run:
    python tools/studio_server.py            # then open http://127.0.0.1:8770
    python tools/studio_server.py --port 9000 --sd

API:
    POST /api/plan              {prompt, seed}          -> digest + doctor report (fast)
    POST /api/render            {prompt, ...options}    -> {job_id}
    GET  /api/job/<id>                                  -> {state, stage, progress, result}
    GET  /api/clip/<id>?v=main|slowmo|silent            -> mp4 (Range supported)
    GET  /api/health

Renders run on a background thread and report real frame progress, because
"describe -> preview -> tweak one word -> re-render" only feels good if the UI
can tell you what is happening.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

STUDIO_DIR = ROOT / "studio"

# Config comes from the environment so the SAME server runs on a laptop and in a
# container (Render/Fly). Nothing below is hardcoded to a host.
OUT_DIR = Path(os.environ.get("STUDIO_OUT_DIR") or (ROOT / "out" / "studio"))
_max_frames_env = int(os.environ.get("STUDIO_MAX_FRAMES") or 0)
MAX_FRAMES: Optional[int] = _max_frames_env or None
DEFAULT_SD = os.environ.get("STUDIO_DEFAULT_SD", "").lower() in ("1", "true", "yes")

_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()

# One render at a time. A free container has ~0.1 CPU / 512 MB -- two concurrent
# renders will OOM it. Extra requests queue instead of dying.
# A Lock (not a Semaphore): Lock has .locked(), which /api/health reports.
_RENDER_SLOT = threading.Lock()


def _new_job(prompt: str) -> str:
    jid = uuid.uuid4().hex[:12]
    with _JOBS_LOCK:
        _JOBS[jid] = {
            "id": jid, "prompt": prompt, "state": "queued", "stage": "queued",
            "progress": 0.0, "elapsed": 0.0, "started": time.time(),
            "result": None, "error": None,
        }
    return jid


def _update(jid: str, **fields: Any) -> None:
    with _JOBS_LOCK:
        if jid in _JOBS:
            _JOBS[jid].update(fields)


def _run_render(jid: str, opts: Dict[str, Any]) -> None:
    from src.service import produce

    started = time.time()

    def on_progress(stage: str, frac: float) -> None:
        _update(jid, stage=stage, progress=round(float(frac), 4),
                elapsed=round(time.time() - started, 2))

    if _RENDER_SLOT.locked():
        _update(jid, state="queued", stage="queued (another render is running)",
                elapsed=round(time.time() - started, 2))

    with _RENDER_SLOT:
        _update(jid, state="running", stage="planning", progress=0.0)
        try:
            res = produce(
                opts["prompt"], OUT_DIR, sd=bool(opts.get("sd", DEFAULT_SD)),
                seed=int(opts.get("seed", 0)),
                strict_timing=bool(opts.get("strict_timing", False)),
                allow=opts.get("allow") or None,
                want_slowmo=bool(opts.get("slowmo", True)),
                with_sound=bool(opts.get("sound", True)),
                name=jid, max_frames=MAX_FRAMES,
                progress_cb=on_progress,
            )
            state = "done" if res.get("ok") else "blocked"
            _update(jid, state=state, stage="done", progress=1.0,
                    elapsed=round(time.time() - started, 2), result=res)
        except Exception as e:  # noqa: BLE001 -- a crash must surface in the UI
            _update(jid, state="error", stage="error", progress=1.0,
                    elapsed=round(time.time() - started, 2),
                    error=f"{type(e).__name__}: {e}",
                    result={"ok": False, "error": str(e),
                            "traceback": traceback.format_exc()[-2000:]})


class Handler(BaseHTTPRequestHandler):
    server_version = "StickmanStudio/1.0"

    # -- plumbing ---------------------------------------------------------- #
    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        if "/api/job/" in (self.path or ""):
            return
        sys.stderr.write("  %s\n" % (fmt % args))

    def _json(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def _send_file(self, path: Path, ctype: Optional[str] = None,
                   cache: str = "no-store") -> None:
        """Serve a file, honouring Range so <video> can scrub."""
        if not path.exists() or not path.is_file():
            self._json({"error": "not found", "path": path.name}, 404)
            return
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        partial = False
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                if m.group(2):
                    end = min(int(m.group(2)), size - 1)
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                partial = True

        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionAbortedError):
                    return
                remaining -= len(chunk)

    # -- routes ------------------------------------------------------------ #
    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0]
        query = (self.path.split("?", 1) + [""])[1]

        if path in ("/", "/index.html"):
            return self._send_file(STUDIO_DIR / "index.html", "text/html; charset=utf-8")
        if path == "/api/health":
            return self._json({
                "ok": True, "service": "studio", "out_dir": str(OUT_DIR),
                "capabilities": {
                    "default_sd": DEFAULT_SD,
                    "max_frames": MAX_FRAMES,
                    "busy": _RENDER_SLOT.locked(),
                },
            })

        m = re.match(r"^/api/job/([0-9a-f]+)$", path)
        if m:
            with _JOBS_LOCK:
                job = _JOBS.get(m.group(1))
            if not job:
                return self._json({"error": "unknown job"}, 404)
            return self._json(job)

        m = re.match(r"^/api/clip/([0-9a-f]+)$", path)
        if m:
            jid = m.group(1)
            variant = "main"
            for part in query.split("&"):
                if part.startswith("v="):
                    variant = part[2:]
            names = {"main": f"{jid}_sound.mp4", "silent": f"{jid}.mp4",
                     "slowmo": f"{jid}_slowmo.mp4"}
            target = names.get(variant)
            if not target:
                return self._json({"error": "bad variant"}, 400)
            return self._send_file(OUT_DIR / target, "video/mp4")

        if path == "/api/examples":
            from tools.batch_harness import CORPUS
            return self._json({"examples": CORPUS})

        # Static assets from studio/ (flat, no traversal).
        rel = path.lstrip("/")
        if rel and ".." not in rel and "/" not in rel:
            cand = STUDIO_DIR / rel
            if cand.is_file():
                return self._send_file(cand)
        return self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = (self.path or "").split("?", 1)[0]
        body = self._read_json()

        if path == "/api/plan":
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                return self._json({"ok": False, "error": "empty prompt"}, 400)
            try:
                from src.service import diagnose_timeline, plan_prompt
                planned = plan_prompt(prompt, seed=int(body.get("seed", 0)))
                timeline = planned["timeline"]
                report = diagnose_timeline(timeline, planned["scene_dict"])
                digest = ""
                try:
                    from src.preview import render_timeline_preview
                    tmp = OUT_DIR / "_digest"
                    tmp.mkdir(parents=True, exist_ok=True)
                    timeline.setdefault("scene_dict", planned["scene_dict"])
                    r = render_timeline_preview(timeline, cols=76, mode="half",
                                                sample=6, out_dir=str(tmp),
                                                name="digest", write_animation=False)
                    digest = r.get("digest", "")
                except Exception as e:  # digest is a nicety
                    digest = f"(digest unavailable: {e})"
                return self._json({
                    "ok": True, "mode": planned["mode"], "action": planned["action"],
                    "n_person": planned["n_person"], "T": planned["T"],
                    "duration_seconds": planned["duration_seconds"],
                    "report": report, "digest": digest,
                })
            except Exception as e:  # noqa: BLE001
                return self._json({"ok": False, "error": str(e)}, 200)

        if path == "/api/render":
            prompt = str(body.get("prompt") or "").strip()
            if not prompt:
                return self._json({"ok": False, "error": "empty prompt"}, 400)
            jid = _new_job(prompt)
            opts = dict(body)
            opts["prompt"] = prompt
            threading.Thread(target=_run_render, args=(jid, opts), daemon=True).start()
            return self._json({"ok": True, "job_id": jid})

        return self._json({"error": "not found"}, 404)


def main() -> int:
    ap = argparse.ArgumentParser(description="Stickman video studio (local web UI)")
    # A container platform injects $PORT and expects a 0.0.0.0 bind; a laptop
    # wants neither. Both fall out of the same defaults.
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8770))
    ap.add_argument("--host", type=str,
                    default=os.environ.get("STUDIO_HOST")
                    or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1"))
    ap.add_argument("--open", action="store_true", help="Open the browser on start.")
    args = ap.parse_args()

    # Fail loudly and usefully if the interpreter lacks the deps.
    import importlib
    for _mod in ("numpy", "PIL"):
        try:
            importlib.import_module(_mod)
        except ImportError:
            print(f"[ERROR] Missing dependency: {_mod}")
            print("        Run this server with the project interpreter, e.g.:")
            print('        "C:/Users/SATHYA TRADERS/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe" '
                  "tools/studio_server.py")
            return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not (STUDIO_DIR / "index.html").exists():
        print(f"[ERROR] Missing UI: {STUDIO_DIR / 'index.html'}")
        return 1

    url = f"http://{args.host}:{args.port}"
    print("=" * 68)
    print("  STICKMAN STUDIO")
    print(f"  {url}")
    print(f"  clips     -> {OUT_DIR}")
    print(f"  default   -> {'SD 512' if DEFAULT_SD else 'HD 1280x720'}")
    print(f"  max frames-> {MAX_FRAMES if MAX_FRAMES else 'unlimited'}")
    print("  Ctrl-C to stop")
    print("=" * 68)
    if args.open:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    os.chdir(ROOT)
    sys.exit(main())
