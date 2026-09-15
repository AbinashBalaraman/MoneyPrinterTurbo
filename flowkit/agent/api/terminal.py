"""Interactive terminal over WebSocket — a real Windows PTY running cmd.exe.

Lets you drive CLI agents (claude, codex, gemini, pytest, git, …) against the
project from inside the dashboard, instead of only talking to preconfigured
models.

This is a genuine shell running with the user's privileges — nothing is
sandboxed. It is rooted at the workspace by default and will refuse to start
outside it, but a command typed into it can do anything the user can do.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

# AutoShorts/  (…/flowkit/agent/api/terminal.py → parents[3])
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SHELL = os.environ.get("COMSPEC") or "cmd.exe"


def _resolve_cwd(raw: str | None) -> str:
    """Keep the shell inside the workspace; fall back to its root otherwise."""
    root = str(WORKSPACE_ROOT)
    if not raw:
        return root
    try:
        cand = str(Path(raw).resolve())
    except OSError:
        return root
    return cand if cand.lower().startswith(root.lower()) else root


def _decode(chunk) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return str(chunk)


async def handle_terminal_ws(websocket: WebSocket) -> None:
    await websocket.accept()

    query = dict(websocket.query_params)
    cwd = _resolve_cwd(query.get("cwd"))
    shell = query.get("shell") or DEFAULT_SHELL
    try:
        cols = max(20, int(query.get("cols", 120)))
        rows = max(5, int(query.get("rows", 30)))
    except ValueError:
        cols, rows = 120, 30

    try:
        from winpty import PtyProcess
    except ImportError as exc:  # pragma: no cover - depends on install
        await websocket.send_text(f"\r\n[terminal] pywinpty is not installed: {exc}\r\n")
        await websocket.close()
        return

    try:
        proc = PtyProcess.spawn(shell, cwd=cwd, dimensions=(rows, cols))
    except Exception as exc:
        logger.exception("terminal: failed to spawn %s", shell)
        await websocket.send_text(f"\r\n[terminal] could not start {shell}: {exc}\r\n")
        await websocket.close()
        return

    loop = asyncio.get_running_loop()
    outbox: "asyncio.Queue[str | None]" = asyncio.Queue()

    def _reader() -> None:
        """pywinpty reads block, so drain the PTY on a worker thread."""
        try:
            while True:
                try:
                    chunk = proc.read()
                except OSError:
                    break
                if not chunk:
                    break
                loop.call_soon_threadsafe(outbox.put_nowait, _decode(chunk))
        except Exception:
            logger.debug("terminal: reader stopped", exc_info=True)
        finally:
            loop.call_soon_threadsafe(outbox.put_nowait, None)

    threading.Thread(target=_reader, name="terminal-reader", daemon=True).start()

    async def _pump() -> None:
        try:
            while True:
                chunk = await outbox.get()
                if chunk is None:
                    break
                await websocket.send_text(chunk)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:
            logger.debug("terminal: pump stopped", exc_info=True)

    pump = asyncio.create_task(_pump())
    await websocket.send_text(f"[terminal] {shell} — {cwd}\r\n")

    try:
        while True:
            raw = await websocket.receive_text()
            if not raw:
                continue

            # Control frames are JSON; everything else is keystrokes.
            if raw.startswith("{"):
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    msg = None
                if isinstance(msg, dict):
                    kind = msg.get("type")
                    if kind == "resize":
                        try:
                            rows_n = max(5, int(msg.get("rows", rows)))
                            cols_n = max(20, int(msg.get("cols", cols)))
                            proc.setwinsize(rows_n, cols_n)
                        except Exception:
                            pass
                        continue
                    if kind == "input":
                        proc.write(msg.get("data", ""))
                        continue

            proc.write(raw)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("terminal: session error")
    finally:
        pump.cancel()
        try:
            if proc.isalive():
                proc.terminate()
        except Exception:
            pass
