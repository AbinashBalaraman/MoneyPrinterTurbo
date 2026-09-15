# AutoShorts — Architecture

**This is the map.** If you are new here (or you are future-you at 2am), read
this first. It states what each part owns and what it must not do.

The plan for getting the code to match this document is in
[`IMPLEMENTATION.md`](./IMPLEMENTATION.md). This file describes the **target**,
with the current location of each piece.

---

## The pipeline, end to end

```
  topic  ──►  script  ──►  stills  ──►  video  ──►  clean  ──►  published
            (Director)   (Render)   (Assembly)    (Post)     (Publish)
   ▲
   └── Ingest decides *what* to make, and guarantees it is made once
```

Six stages, each a department. Two more departments support them: **Studio**
(the human interface) and **Assistant** (the chatbot).

---

## The eight departments

| # | Department | Owns | Lives in | Entry point |
|---|---|---|---|---|
| 1 | **INGEST** | What to make next, once only. Topic sources, the dedup ledger, claiming. | `automation/` | `python -m automation.runner` |
| 2 | **DIRECTOR** | Story. Scripts, pacing, characters, continuity canon, storyboards. | `shorts_content_engine/src/{director,storyboard,storage}/` | `shorts_content_engine/src/cli.py` |
| 3 | **RENDER** | Turning prompts into media, via Google Flow. Queue, worker, extension bridge, and the client that drives it. | `flowkit/agent/` (server) + `shorts_content_engine/src/render_client/` (client) | `flowkit/agent/main.py` · `cli.py generate` |
| 4 | **ASSEMBLY** | Cutting the video: narration, subtitles, BGM, image→video concat. | `app/`, root `cli.py` | `python cli.py --batch-file …` |
| 5 | **POST** | Cleaning the artifact: watermark removal, metadata strip. | `shorts_content_engine/src/postprocess/` | `cli.py scrub` |
| 6 | **PUBLISH** | Uploading to YouTube Shorts / TikTok / Instagram Reels, and tracking it. | `shorts_content_engine/src/distribution/`, `flowkit/agent/api/publications.py` | `cli.py publish` |
| 7 | **STUDIO** | Every pixel a human sees. Dashboard, chat UI, terminal tab. | `flowkit/dashboard/` | `npm run dev` → :5173 |
| 8 | **ASSISTANT** | The chatbot: tool loop, memory, saved conversations, web search. | `flowkit/agent/services/{chat_agent,agent_memory,web_search}.py` | inside RENDER's server |

Plus **OPS** — not a stage: logging, events, database, config, the terminal PTY.
Shared by everyone, owns no pipeline state.

### The dependency rule

> **A department may call the one to its left. It may not reach right.**

INGEST → DIRECTOR → RENDER → ASSEMBLY → POST → PUBLISH. Nothing skips a stage.
STUDIO and ASSISTANT are front doors: they talk to **Control** (below) and never
reach into a department directly.

Why this matters: today the pipeline works, but nothing stops a future change
from having PUBLISH call Google Flow directly, and then the stage boundaries are
fiction. The rule is what keeps them real.

---

## Control — one operations catalog, two front doors

The layer that makes the chatbot and the API consistent by construction.
**Implemented** — see `flowkit/agent/operations/`.

```
   flowkit/agent/operations/          ← the only implementation of an operation
     ├── registry.py                  @operation, risk gate, tool specs
     ├── shell.py                     the one place that spawns a process
     ├── ingest.py   director.py   render.py   assembly.py
     └── post.py     publish.py    assistant.py   ops.py
              │
      ┌───────┴────────┐
      ▼                ▼
   REST routes     chatbot tools
   (existing)      (generated from the catalog)
```

Every operation is declared once:

```python
@operation(name="queue_status", department="render", risk="read")
async def queue_status(project_id: str | None = None) -> dict: ...
```

The declaration carries its own metadata — department, risk, argument example —
so the chatbot's tool spec, the prompt's grouping and the risk gate all come from
one place. The registry refuses an unknown department, an unknown risk, and a
**duplicate name** (a duplicate would silently shadow, which is the drift bug
this exists to prevent).

### Risk

| `risk` | Meaning | Behaviour |
|---|---|---|
| `read` | Inspects state | Always allowed |
| `write` | Local changes (memory, ledger, a scrub) | Allowed |
| `spend` | Costs money (generates media, runs a batch) | **Refused unless `AGENT_ALLOW_SPEND=1`** |
| `destructive` | Publishing — public and irreversible | Refused unless spend is on **and** a confirm token is present |

`run_command` is deliberately `write`, not `destructive`: the only confirm token
available is one the *model* sets, so requiring it would be a speed bump that
looks like a safety check while checking nothing. Its real controls are the
pinned cwd, the pattern denylist and the output cap.

### Still duplicated (known, tracked)

REST routes still call the service layer directly rather than going through the
catalog. They call the **same services**, so behaviour cannot differ — but the
route layer is not yet generated, so the "two front doors" property holds for the
chatbot and not yet for HTTP. Tracked in `IMPLEMENTATION.md`.

---

## Top-level directory reference

Every entry in the repository root, and what it is:

| Path | What it is | Status |
|---|---|---|
| `app/` | **ASSEMBLY** — MoneyPrinterTurbo core: TTS, subtitles, BGM, concat. Its HTTP API lives in `app/asgi.py` + `app/router.py` | **Live, load-bearing** |
| `cli.py` | **ASSEMBLY** entry point. Invoked by `automation/runner.py` | **Live** |
| `main.py` | Launcher for MoneyPrinterTurbo's HTTP API (`app/asgi.py`) | Not started by the pipeline — see *Open items* |
| `automation/` | **INGEST** — the unattended loop | **Live** |
| `flowkit/` | **RENDER** server + **STUDIO** dashboard + **ASSISTANT** + **OPS** | **Live** |
| `flowkit/agent/operations/` | **Control** — the operations catalog: one declaration per capability, plus the risk gate | **Live** |
| `shorts_content_engine/` | **DIRECTOR**, **POST**, **PUBLISH**, and the Render *client* (`src/render_client/`) | **Live** |
| `opencode_endpoint/` | Reference implementation for OpenCode protocol routing | Reference only |
| `config.toml`, `config.example.toml` | MoneyPrinterTurbo configuration | **Live** |
| `resource/` | Fonts, BGM, and other assembly assets | **Live** |
| `storage/` | Generated output (videos, images, audio) | Runtime data |
| `test/` | Tests for the assembly engine | **Live** |
| `tools/` | Developer utilities (npm repair, project consolidation) | Tooling |
| `docs/` | Architecture, implementation plan, chat-UI review | Docs |
| `HANDOFF.md` | Session-by-session handoff notes | Docs |
| `vscode-agentmemory-ext/` | A vendored **VS Code extension** (was `agentMemory/`). Nothing to do with the assistant | ⚠️ Unrelated — see below |
| `video_model/` | **`textanim`** — a separate Vite/TS web app | ⚠️ Not part of the pipeline |
| `video_model_dev/` | **Stickman Universe** — a separate product (smaller copy) | ⚠️ Not part of the pipeline |
| `video_model_quality/` | **Stickman Universe** — a separate product (larger copy) | ⚠️ Not part of the pipeline |

### Naming rules

These exist because the names were the single biggest source of confusion.

1. **`flowkit` means exactly one thing: the RENDER server.** The client library
   that drives it is `shorts_content_engine/src/render_client/` ✅ *renamed
   2026-09-15; it used to be `src/flowkit/`, and two different things called
   `flowkit` is what made the reference-image bug take so long to find.*
   Note the **class names stay** (`FlowKitClient`, `FlowKitPayloadAdapter`,
   `FlowKit*Create`) — they describe the *protocol*, which really is FlowKit's.
   Only the package name was ambiguous.
2. **`agent_data/`** is the assistant's memory (`memory.md`,
   `conversations/`). It is deliberately **not** under `.workbuddy-ai/`, which is
   protected project data, and deliberately **not** near `vscode-agentmemory-ext/`
   (was `agentMemory/`), which is an unrelated VS Code extension.
3. **`video_model*`** are *not* video models in the pipeline sense. They are
   standalone side-projects. They are not git-tracked, so they cannot be
   recovered if deleted — decide their fate deliberately, not casually.

### Recently removed

| Removed | Why | Recoverable |
|---|---|---|
| `webui/` (7,620 lines), `webui.bat`, `webui.sh` | A second UI (Streamlit) for the same engine. Nothing imported it — the only two "references" were a comment in `cli.py` and a string literal in `app/services/webui_task.py`. | ✅ Yes — `git checkout HEAD -- webui webui.bat webui.sh` |

---

## Where the assistant fits

The ASSISTANT is a front door, not a department that other departments call.

```
  STUDIO ──┐
           ├──► Control (operations catalog) ──► departments
  ASSISTANT┘
```

The assistant gets one tool per operation, generated from the catalog — the same
operations the dashboard uses. It therefore **cannot** do something the UI cannot
do, and cannot invent a second implementation of anything. Risk gating is shared,
so a `spend` operation is equally gated whether a human clicks it or the model
calls it.

See [`IMPLEMENTATION.md`](./IMPLEMENTATION.md) §4 for the full tool surface.

---

## Open items in this document

- **`main.py`** (MoneyPrinterTurbo's FastAPI app) appears unused by the pipeline —
  `automation/` calls `cli.py`, not the HTTP API. Confirm before removing; the
  dashboard does not talk to it.
- **`video_model*`** — three untracked side-projects. `video_model_dev/` and
  `video_model_quality/` are two copies of the same "Stickman Universe" project.
  Needs a decision, not a guess.
- **`vscode-agentmemory-ext/`** ✅ renamed 2026-09-15 (was `agentMemory/`) so it
  cannot be confused with the assistant's memory.
- **`opencode_endpoint/`** — legacy reference only (README marked). Source of truth
  is `flowkit/agent/services/opencode_models.py`.
