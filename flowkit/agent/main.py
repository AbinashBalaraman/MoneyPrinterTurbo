"""Flow Kit — FastAPI + WebSocket server entry point."""
import asyncio
import json
import logging
import signal
from contextlib import asynccontextmanager

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent.config import API_HOST, API_PORT, WS_HOST, WS_PORT
from agent.db.schema import init_db, close_db
from agent.api.agent_tools import router as agent_tools_router
from agent.api.characters import router as characters_router
from agent.api.projects import router as projects_router
from agent.api.videos import router as videos_router
from agent.api.scenes import router as scenes_router
from agent.api.requests import router as requests_router
from agent.api.flow import router as flow_router
from agent.api.reviews import router as reviews_router
from agent.api.tts import router as tts_router
from agent.api.materials import router as materials_router
from agent.api.music import router as music_router
from agent.api.models import router as models_router
from agent.api.providers import router as providers_router
from agent.api.active_project import router as active_project_router
from agent.api.continuity import router as continuity_router
from agent.api.logs import router as logs_router
from agent.api.publications import router as publications_router
from agent.api.opencode import router as opencode_router
from agent.worker.processor import get_worker_controller
from agent.services.flow_client import get_flow_client
from agent.services.event_bus import event_bus
from agent.services.log_bus import log_bus, LogBusHandler
from agent.sdk import init_sdk

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Bridge the stdlib logging tree into the log bus. Every existing
# ``logger.info(...)`` call in the codebase becomes visible in the dashboard
# without editing a single call site. HTTP access logs and file-watcher chatter
# are excluded so they do not drown the pipeline lines a user is watching for.
_bus_handler = LogBusHandler(
    log_bus,
    level=logging.INFO,
    exclude=("uvicorn.access", "watchfiles", "watchgod"),
)


def _attach_log_bus_handler() -> None:
    """Attach the log-bus bridge to the root logger exactly once.

    Running this file as ``python -m agent.main`` executes it once under the
    name ``__main__``; ``uvicorn.run("agent.main:app")`` then imports it again
    under its real name, which re-runs all of this module-level code. A bare
    ``addHandler`` therefore runs twice and every log line appears twice in the
    dashboard -- each copy with its own ``seq``, so the client's de-duplication
    cannot catch it.

    Guarding on the root logger's existing handlers makes this idempotent no
    matter how the module gets loaded.
    """
    root = logging.getLogger()
    if any(isinstance(handler, LogBusHandler) for handler in root.handlers):
        return
    root.addHandler(_bus_handler)


_attach_log_bus_handler()


# ─── WebSocket Server for Extension ─────────────────────────

async def ws_handler(websocket):
    """Handle a Chrome extension WebSocket connection."""
    client = get_flow_client()
    client.set_extension(websocket)
    logger.info("Extension connected from %s", websocket.remote_address)

    # Send callback secret so extension can authenticate HTTP callbacks
    await websocket.send(json.dumps({"type": "callback_secret", "secret": _CALLBACK_SECRET}))

    try:
        async for raw in websocket:
            try:
                data = json.loads(raw)
                await client.handle_message(data, websocket)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from extension")
            except Exception as e:
                logger.exception("Error handling extension message: %s", e)
    except websockets.ConnectionClosed:
        pass
    finally:
        client.clear_extension(websocket)
        logger.info("Extension disconnected")


async def run_ws_server():
    """Run WebSocket server for extension connections."""
    try:
        async with websockets.serve(ws_handler, WS_HOST, WS_PORT):
            logger.info("WebSocket server listening on ws://%s:%d", WS_HOST, WS_PORT)
            await asyncio.Future()  # run forever
    except Exception as e:
        logger.exception("Failed to start WebSocket server on ws://%s:%d: %s", WS_HOST, WS_PORT, e)


# ─── FastAPI App ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    # Load custom materials from DB into in-memory registry
    from agent.db.crud import list_materials as db_list_materials
    from agent.materials import register_material, _BUILTIN_IDS
    try:
        custom_materials = await db_list_materials()
        for m in custom_materials:
            if m["id"] not in _BUILTIN_IDS:
                register_material(m)
                logger.info("Loaded custom material from DB: %s", m["id"])
    except Exception as e:
        logger.warning("Failed to load custom materials: %s", e)

    ops = init_sdk(get_flow_client())
    logger.info("SDK initialized (OperationService ready)")
    logger.info("Flow Kit starting on %s:%d", API_HOST, API_PORT)

    controller = get_worker_controller()

    # SIGTERM handler for graceful shutdown (Unix only)
    try:
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGTERM, controller.request_shutdown)
    except (NotImplementedError, AttributeError):
        pass

    # Start background tasks
    ws_task = asyncio.create_task(run_ws_server())
    worker_task = asyncio.create_task(controller.start())
    logger.info("WS server + worker started")

    yield

    controller.request_shutdown()
    await controller.drain()
    ws_task.cancel()
    worker_task.cancel()
    await close_db()
    logger.info("Flow Kit stopped")


app = FastAPI(title="Flow Kit", version="1.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(characters_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(videos_router, prefix="/api")
app.include_router(scenes_router, prefix="/api")
app.include_router(requests_router, prefix="/api")
app.include_router(flow_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")
app.include_router(tts_router, prefix="/api")
app.include_router(materials_router, prefix="/api")
app.include_router(music_router, prefix="/api")
app.include_router(models_router)
app.include_router(providers_router)
app.include_router(active_project_router)
app.include_router(continuity_router, prefix="/api")
app.include_router(logs_router)
app.include_router(publications_router, prefix="/api")
# No prefix here: the router already declares /api/opencode, and it is the
# server-side owner of the OpenCode key and the model catalogue.
app.include_router(opencode_router)
app.include_router(agent_tools_router, prefix="/api")


import secrets as _secrets
_CALLBACK_SECRET = _secrets.token_urlsafe(32)


@app.post("/api/ext/callback")
async def ext_callback(request: Request):
    """HTTP callback for extension to deliver API responses.

    Replaces ws.send() for response delivery — immune to WS disconnect.
    Extension POSTs {id, status, data, error} here instead of sending via WS.
    Requires X-Callback-Secret header matching the secret sent to extension on WS connect.
    """
    data = await request.json()
    client = get_flow_client()
    req_id = data.get("id")
    logger.info("ext/callback: id=%s pending=%d match=%s",
                str(req_id)[:8] if req_id else "none",
                len(client._pending),
                "yes" if req_id and req_id in client._pending else "no")
    if req_id and req_id in client._pending:
        future = client._pending[req_id]
        try:
            future.set_result(data)
        except asyncio.InvalidStateError:
            pass
        return {"ok": True}
    return {"ok": False, "reason": "no matching pending request"}


@app.get("/health")
async def health():
    client = get_flow_client()
    return {
        "status": "ok",
        "version": "0.2.0",
        "extension_connected": client.connected,
        "ws": client.ws_stats,
    }


# ─── Terminal WebSocket (real cmd.exe PTY) ────────────────────

@app.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    """Interactive shell for driving CLI agents against the project.

    A genuine Windows PTY (pywinpty) rooted at the workspace — this is how you
    run claude/codex/gemini CLI, pytest or git from the dashboard instead of
    only talking to the preconfigured chat models.
    """
    origin = (websocket.headers.get("origin") or "").lower()
    if origin and not any(origin.startswith(p) for p in (
        "http://127.0.0.1", "http://localhost", "chrome-extension://",
    )):
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    from agent.api.terminal import handle_terminal_ws
    await handle_terminal_ws(websocket)


# ─── Dashboard WebSocket ──────────────────────────────────────

@app.websocket("/ws/dashboard")
async def dashboard_ws(websocket: WebSocket):
    """WebSocket endpoint for dashboard clients (Chrome extension side panel).

    Carries two streams: state events from ``event_bus`` and log records from
    ``log_bus``. A reconnecting client may pass ``?since=<last seq it saw>`` to
    receive exactly the log records it missed.
    """
    # Reject cross-origin connections (only allow localhost)
    origin = (websocket.headers.get("origin") or "").lower()
    if origin and not any(origin.startswith(p) for p in (
        "http://127.0.0.1", "http://localhost", "chrome-extension://",
    )):
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    await websocket.accept()

    event_q = event_bus.subscribe()
    log_q = log_bus.subscribe()

    # Both buses feed one queue so the main loop has a single read point and the
    # keepalive timeout stays simple.
    out: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def _pump(src: asyncio.Queue):
        while True:
            item = await src.get()
            try:
                out.put_nowait(item)
            except asyncio.QueueFull:
                pass  # the main loop is behind; a log line is worth dropping

    pumps = [asyncio.create_task(_pump(event_q)), asyncio.create_task(_pump(log_q))]

    try:
        # Send initial snapshot
        client = get_flow_client()
        controller = get_worker_controller()
        from agent.db import crud
        pending_requests = await crud.list_requests(status="PENDING")
        processing_requests = await crud.list_requests(status="PROCESSING")
        snapshot = {
            "type": "snapshot",
            "health": {
                "status": "ok",
                "extension_connected": client.connected,
            },
            "requests": pending_requests + processing_requests,
            "worker": {
                "active": controller.active_count,
                "slots": max(0, 5 - controller.active_count),
            },
        }
        await websocket.send_text(json.dumps(snapshot))

        # Replay the gap. We subscribed before reading history, so no record can
        # slip between the two — at worst a record appears in both the replay and
        # the live tail. ``latest_seq`` lets the client drop those duplicates by
        # sequence number, which is strictly better than losing lines.
        raw_since = websocket.query_params.get("since")
        since = int(raw_since) if raw_since and raw_since.isdigit() else None
        missed = log_bus.history(since=since, limit=1000)
        if missed:
            await websocket.send_text(json.dumps({
                "type": "log_replay",
                "data": {
                    "records": missed,
                    "latest_seq": log_bus.latest_seq,
                    "retained": log_bus.count,
                    "dropped": log_bus.dropped,
                },
            }))

        # Forward events from both buses to this client
        while True:
            try:
                msg = await asyncio.wait_for(out.get(), timeout=30.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                # Send keepalive ping
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("Dashboard WS client disconnected: %s", e)
    finally:
        for task in pumps:
            task.cancel()
        event_bus.unsubscribe(event_q)
        log_bus.unsubscribe(log_q)


if __name__ == "__main__":
    import os
    import uvicorn
    reload_enabled = os.environ.get("GLA_RELOAD", "0") == "1"
    uvicorn.run(
        "agent.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=reload_enabled,
        reload_excludes=["*.db", "*.db-wal", "*.db-shm", "output/*"],
    )
