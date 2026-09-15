# AutoShorts — Departments & Tool Surface

**Status:** proposal for review · **Author:** Jarvis · **Date:** 2026-09-14
**Subject:** clean up the pipeline architecture, give it real departmental
boundaries, and connect each department to the chatbot as a tool.

---

## 0. What I understand you to be asking

Restating it so you can correct me before anything gets built:

1. **Audit, honestly** — is the pipeline and architecture actually clean, or does
   it look like an accident? You want a professional verdict, not reassurance.
2. **Give it departments** — organise the app the way a real organisation is
   organised: each part has a clear job, a clear owner, and a clear boundary.
   No two parts doing the same thing, no part that nobody can name.
3. **Connect the departments to the chatbot** — the assistant should be the front
   desk: able to *operate* every department through tools, instead of only being
   able to inspect a couple of database tables.
4. **No confusion** — a person (or a future you) should be able to look at the
   tree and know what each thing is for without reading the code.
5. **Then produce the implementation document** — the plan, not the code, first.

If any of that is wrong, the rest of this file is wrong too — tell me and I will
redo it. Two things I assumed and want to flag, because they change the plan:

- **`app/` (MoneyPrinterTurbo) is NOT dead code.** It is your **video assembly
  engine** — TTS, subtitles, BGM, and the image→video concat. `automation/runner.py`
  invokes root `cli.py --batch-file`, which drives it. So it gets a department, it
  does not get deleted. Only its **Streamlit `webui/`** is retirable.
- **This is a documentation-and-wiring change, not a rewrite.** The parts are
  mostly in the right places already; what is missing is the boundary rules, the
  names, and the tool surface. I am not proposing to move everything into new
  folders for the sake of it.

---

## 1. The honest verdict: not clean — but closer than it looks

Every claim below was checked against the tree rather than recalled, and the
counts are stated so you can re-check them yourself:

```bash
ls -1 flowkit/agent/api/*.py | wc -l          # 20 route modules
grep -rln "watermark" --include="*.py" …      # 3 separate implementations
wc -l webui/Main.py                           # 7620
grep -n "cli.py" automation/runner.py         # line 353 — the runner drives it
```

It is not a mess. It is **an unlabelled** system. The pieces are mostly sound;
what is missing is any statement of what each piece owns, so several of them
look interchangeable. Concretely, the confusions that cost real time:

### 1.1 Two different things are both called `flowkit`

| Path | What it actually is |
|---|---|
| `flowkit/` | The **server** — REST API, worker queue, Chrome extension bridge, dashboard |
| `shorts_content_engine/src/flowkit/` | A **client library** that talks to that server |

Same word, opposite roles. This is the single most confusing thing in the tree.
It already caused a real bug: `poll_batch_resilient(orientation=None)` was
learned the hard way, and the missing reference-image producer lived in the
client while the failure appeared in the server's queue.

### 1.2 Two UIs, one of them abandoned

- `flowkit/dashboard/` — React. The real one.
- `webui/Main.py` — Streamlit, **7,620 lines**, from the MoneyPrinterTurbo fork.

Nothing says which is current. Both start.

### 1.3 Two CLIs and two FastAPI apps

- `cli.py` (root) — the assembly task runner. **Live.**
- `shorts_content_engine/src/cli.py` — the pipeline CLI (`direct`, `generate`,
  `scrub`, `publish`, `storyboard`, `status`…). **Live.**
- `main.py` (root) + `app/` — FastAPI app for MoneyPrinterTurbo. **Live.**
- `flowkit/agent/main.py` — FastAPI app for the FlowKit server. **Live.**

All four are legitimate. Nothing distinguishes "entry point for the assembly
engine" from "entry point for the media server".

### 1.4 Three video-model directories

`video_model/` (29 files), `video_model_dev/` (167), `video_model_quality/` (517).
No README says which is used or when.

### 1.5 A name collision on memory

- `agentMemory/` — a **vendored VS Code extension**, unrelated to the assistant.
- `flowkit/agent_data/` — the assistant's real memory (`memory.md`,
  `conversations/`).

The assistant's memory had to be moved *out* of `.workbuddy-ai/` this session
because the name sat next to an unrelated extension. That is a naming problem,
not a filesystem one.

### 1.6 The chatbot's tools do not map to the pipeline

The 10 current tools are a flat, ad-hoc list: `web_search`, `project_list`,
`project_status`, `queue_status`, `consistency_check`, `run_command`,
`validate_script`, `memory_read/append/write`.

There is **no tool to direct an episode, generate media, assemble, scrub, or
publish**. The assistant can *look at* the pipeline but cannot *run* it. And
`project_status` duplicates the `/api/projects` endpoint — two implementations of
one operation, which is the exact drift class we have already been bitten by
twice this week:

- the frontend's `AgentToolEvent` contract vs the backend's frame shape;
- `operations.py::_char_matches` vs `consistency.py::_matches`.

### 1.7 What is already good, and must not be broken

- `agent/services/` is genuinely well-factored: `chat_agent`, `web_search`,
  `agent_memory`, `consistency`, `log_bus`, `event_bus` are dependency-light and
  unit-testable without a server.
- The tool-loop protocol is documented, tested (57 tests) and works on models
  without function calling.
- `agent/utils/entity_match.py` proved the pattern: one rule, one place, three
  callers.
- The worker/queue separation (server-side) vs the pipeline client (SCE) is the
  right shape — it just needs naming.

---

## 2. Target: eight departments

A department is defined by **what it owns**. The rule that makes the boundaries
real:

> **A department may be called by the department to its left, and may not reach
> right.** Dependencies flow one way, down the pipeline. Nothing skips.

```
  ┌──────────────────────────────────────────────────────────────┐
  │  STUDIO        React dashboard — the only UI                  │
  └───────────────────────────┬──────────────────────────────────┘
                              │  HTTP / WS  (one contract)
  ┌───────────────────────────▼──────────────────────────────────┐
  │  CONTROL       the operations catalog + REST + chatbot tools   │
  │                one implementation, two front doors             │
  └───┬──────────┬──────────┬──────────┬──────────┬──────────┬───┘
      │          │          │          │          │          │
  ┌───▼───┐ ┌────▼───┐ ┌────▼───┐ ┌────▼───┐ ┌────▼───┐ ┌────▼───┐
  │INGEST │ │DIRECTOR│ │ RENDER │ │ASSEMBLY│ │  POST  │ │PUBLISH │
  └───────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
                              ▲
                    ┌─────────┴─────────┐
                    │  ASSISTANT        │  talks to Control only,
                    │  tool loop+memory │  never to a department directly
                    └───────────────────┘
```

### Department 1 — INGEST

| | |
|---|---|
| **Owns** | Where episode ideas come from: topic sources, the dedup ledger gate, claiming, scheduling. |
| **Code today** | `automation/` (`runner.py`, `ledger.py`, `sources/`, `topics.txt`) |
| **Entry point** | `python -m automation.runner` |
| **Never** | Generates media, writes scripts, talks to FlowKit. |
| **Depends on** | Director (hands it a claimed topic). |

### Department 2 — DIRECTOR

| | |
|---|---|
| **Owns** | Story. Episode scripts, the 5-phase retention arc, pacing, characters, continuity canon. |
| **Code today** | `shorts_content_engine/src/director/`, `storyboard/`, `storage/ledger.py` |
| **Entry point** | `shorts_content_engine/src/cli.py` → `direct`, `storyboard`, `status`, `validate` |
| **Never** | Calls Google Flow, uploads anything. |
| **Depends on** | Render (asks for stills). |

### Department 3 — RENDER

| | |
|---|---|
| **Owns** | Turning prompts into media. The FlowKit **server** (queue, worker, Chrome extension bridge) and the SCE **client** that drives it. |
| **Code today** | `flowkit/agent/{api,worker,sdk,services}` + `shorts_content_engine/src/flowkit/` |
| **Entry point** | `flowkit/agent/main.py` (server) · SCE `cli.py generate` (client) |
| **Naming fix** | SCE's client becomes `shorts_content_engine/src/render_client/`. **`flowkit` is reserved for the server alone.** |
| **Never** | Publishes, edits the ledger. |
| **Depends on** | Assembly (hands it stills + video clips). |

### Department 4 — ASSEMBLY

| | |
|---|---|
| **Owns** | Cutting the final video: narration (TTS), subtitles, BGM, image→video concat, the `--batch-file` task runner. |
| **Code today** | root `cli.py`, `app/services/video.py`, `app/services/task.py`, `app/models/` |
| **Entry point** | `python cli.py --batch-file …` |
| **Note** | This is the MoneyPrinterTurbo core. It is live and load-bearing. |
| **Never** | Talks to Google Flow, publishes. |
| **Depends on** | Post (hands it a finished mp4). |

### Department 5 — POST

| | |
|---|---|
| **Owns** | Cleaning the artifact: watermark removal, container metadata strip, thumbnail/metadata generation. |
| **Code today** | `shorts_content_engine/src/postprocess/` (`watermark.py`, `metadata.py`), `automation/watermark_scrub.py`, `flowkit/agent/services/post_process.py` |
| **Consolidation needed** | Watermark removal is implemented in **three** places (verified): `postprocess/watermark.py`, `automation/watermark_scrub.py`, `flowkit/agent/services/post_process.py`. One implementation, called by the others. |
| **Never** | Uploads. |
| **Depends on** | Publish. |

### Department 6 — PUBLISH

| | |
|---|---|
| **Owns** | Getting the video onto YouTube Shorts / TikTok / Instagram Reels, and tracking the outcome. |
| **Code today** | `shorts_content_engine/src/distribution/` (`manager.py`, `adapters/`, `credentials.py`), `flowkit/agent/api/publications.py` |
| **Never** | Generates or edits media. |
| **Depends on** | Nothing. Terminal department. |

### Department 7 — STUDIO

| | |
|---|---|
| **Owns** | Every pixel a human sees: the React dashboard, chat UI, terminal tab, pipeline views. |
| **Code today** | `flowkit/dashboard/` |
| **Retire** | `webui/` (Streamlit, 7,620 lines). Keep at parity or delete — a decision for you, not for me. |
| **Rule** | Talks to Control over HTTP/WS. **Never** reads the DB, never shells out. |

### Department 8 — ASSISTANT

| | |
|---|---|
| **Owns** | The chatbot: the tool loop, long-term memory, saved conversations, web search. |
| **Code today** | `flowkit/agent/services/{chat_agent,agent_memory,web_search}.py` + `api/agent_tools.py` |
| **Rule** | Calls **Control's operations catalog** — the same operations the REST API exposes. It never reaches into a department's internals. |

### Shared — OPS

Not a pipeline stage; the substrate every department uses: logging (`log_bus`),
events (`event_bus`), the database (`db/`), config, the terminal PTY. Lives in
`flowkit/agent/{db,utils,services/log_bus,services/event_bus}` and is imported
freely, because it owns no pipeline state.

---

## 3. The core idea: one operations catalog, two front doors

This is what removes the confusion in §1.6 and prevents the drift we keep
hitting.

Today an operation like "get project status" is implemented **twice** — once as
a FastAPI route, once as a chatbot tool — and they can disagree. Instead:

```
   agent/operations/            ← the only implementation
     ├── registry.py            name, department, args, risk, handler
     ├── director.py            direct_episode, validate_script, continuity_status
     ├── render.py              project_status, queue_status, consistency_check
     ├── assembly.py            assemble_episode
     ├── post.py                scrub_video
     ├── publish.py             publish_episode, publication_status
     └── ingest.py              list_topics, run_batch
              │
      ┌───────┴────────┐
      ▼                ▼
   REST routes     chatbot tools
   (generated)     (generated)
```

Each operation declares its own metadata **once**:

```python
@operation(
    name="queue_status",
    department="render",
    risk="read",            # read | spend | destructive
    args={"project_id": "optional"},
)
async def queue_status(project_id: str | None = None) -> dict: ...
```

From that single declaration you get, automatically:

- the REST route,
- the chatbot tool spec (description + JSON args + availability),
- the dashboard's tool card name (`_UI_TOOL` stops being a hand-maintained map),
- **and a risk gate**: `spend` operations are refused unless explicitly enabled,
  `destructive` ones require confirmation.

That last point closes the open "approval flows" gap from the chat-UI review
without inventing a mechanism — it falls out of the catalog.

---

## 4. Tool surface per department

What the assistant should be able to do, grouped by the department that owns it.
**Bold** = does not exist today.

### INGEST
| Tool | Risk | Does |
|---|---|---|
| `list_topics` | read | Unclaimed topics from the configured sources |
| `run_batch` | spend | Run N episodes through the whole pipeline (dry-run first) |

### DIRECTOR
| Tool | Risk | Does |
|---|---|---|
| `direct_episode` | read | Produce an EpisodeManifest for the next episode |
| `validate_script` | read | 4–6 scenes, ≤10s each, 30–50s total, 5-phase arc |
| `continuity_status` | read | Series state, last cliffhanger, next hook |
| **`storyboard`** | read | Still-image prompts + PDF storyboard |

### RENDER
| Tool | Risk | Does |
|---|---|---|
| `project_list` | read | Projects (id, name, status) |
| `project_status` | read | Scenes, per-status request counts, recent failures |
| `queue_status` | read | Queue counts only |
| `consistency_check` | read | Scenes generated without reference conditioning |
| **`generate_episode`** | **spend** | Queue stills/videos for a manifest |

### ASSEMBLY
| Tool | Risk | Does |
|---|---|---|
| **`assemble_episode`** | **spend** | Stills + narration → final mp4 (TTS, subs, BGM, concat) |

### POST
| Tool | Risk | Does |
|---|---|---|
| **`scrub_video`** | write | Remove watermark + container metadata |

### PUBLISH
| Tool | Risk | Does |
|---|---|---|
| **`publish_episode`** | **destructive** | Upload to the enabled platforms |
| **`publication_status`** | read | What was published, where, and whether it succeeded |

### ASSISTANT (self)
| Tool | Risk | Does |
|---|---|---|
| `web_search` | read | TinyFish live web search |
| `memory_read` / `memory_append` / `memory_write` | write | Long-term memory |

### OPS
| Tool | Risk | Does |
|---|---|---|
| `run_command` | destructive | Shell in the workspace (already exists) |
| **`read_logs`** | read | Recent log records from the log bus |

Net: from 10 inspection tools to ~19, and the assistant goes from *reading the
pipeline* to *running it* — with the risky operations gated by the risk field
rather than by my judgement at 2am.

---

## 5. Implementation plan

Six phases. Each is independently shippable and reversible.

**Progress: ✅ ALL PHASES DONE** — 0, 1, 2, 3, 4, 5 (webui), 6.

### Phase 0 — Say what things are (no code moves) · ✅ DONE
- `docs/ARCHITECTURE.md` written: the department table, the dependency rule, and
  a purpose line for every top-level directory.
- Every factual claim in it was checked against the tree, with the command shown
  so you can re-verify.
- **No behaviour change.**

### Phase 1 — Kill the name collision · ✅ DONE
- `shorts_content_engine/src/flowkit/` → `src/render_client/`. **`flowkit` now
  means exactly one thing: the server.**
- 16 files updated, and `tests/unit/test_flowkit.py` → `test_render_client.py`.
- Class names deliberately **kept** (`FlowKitClient`, `FlowKitPayloadAdapter`,
  `FlowKit*Create`) — they name the protocol, which really is FlowKit's. Only the
  package name was ambiguous.
- **Acceptance met:** SCE suite `169 passed / 0 failed`, unchanged from the
  pre-rename baseline; `src/cli.py --help` loads all 9 subcommands.

### Phase 2 — The operations catalog · ✅ DONE
`flowkit/agent/operations/` — **21 operations across all 8 departments**, each
declared once:

```python
@operation(name="queue_status", department="render", risk="read")
async def queue_status(project_id: str | None = None) -> dict: ...
```

- `registry.py` — the `@operation` decorator, the `Operation` record, and
  `check_allowed`. Rejects an unknown department, an unknown risk, and a
  **duplicate name** (a duplicate would silently shadow, which is the drift bug).
- Department modules: `ingest`, `director`, `render`, `assembly`, `post`,
  `publish`, `assistant`, `ops`.
- `shell.py` — the one place that spawns a process. Owns the pinned cwd, the
  timeout, the output cap and the refusal list, so no operation can silently opt
  out of them. Also knows the two interpreters (the pipeline and the assembly
  engine have **separate virtualenvs**).
- `chat_agent.tool_specs()` and `chat_agent.TOOLS` are now **derived from the
  catalog**; the hardcoded list is gone. The prompt groups tools by department.

### Phase 3 — The risk gate · ✅ DONE
- `risk` is `read` / `write` / `spend` / `destructive`.
- `spend` is refused unless `AGENT_ALLOW_SPEND=1`; `destructive` additionally
  needs a confirm token. Verified **live** through the real endpoint: the model
  called `generate_episode`, was refused, and the refusal tells the user exactly
  how to enable it.
- **`run_command` is `write`, not `destructive`** — deliberately. The only
  confirm token available is one the *model* sets, so requiring it would be a
  speed bump that looks like a safety check while checking nothing. The controls
  that actually bind are the pinned cwd, the pattern denylist and the output cap;
  the Terminal tab is already a full unsandboxed shell, so gating only the chat
  would be inconsistent theatre.
- Default is **opt-in** (`AGENT_ALLOW_SPEND=0`), as you chose.

**And it is visible** — a gate the user cannot see is indistinguishable from a
broken assistant:

- every `tool` frame carries `risk`, so a card can badge `SPENDS MONEY` /
  `PUBLIC · IRREVERSIBLE` **before** the result is read;
- a refusal sets `refused: true`, and the dashboard renders it as a calm
  *"Not run — …"* card with the reason, not as a red failure. Verified live:
  the frame came back with `"risk": "spend"` and `"refused": true`;
- `GET /api/agent/capabilities` reports `allow_spend`, the operation count, the
  risk breakdown and the departments, and the Studio shows a mode strip —
  *"inspection only — 3 spending and 1 publishing tool are refused"* — with the
  switch to change it.

This closes the approval-flow gap from `docs/CHAT_UI_REVIEW.md` §4 for the
**refusal** half. A UI-driven approval (a button that mints the token for a
`destructive` call) is still not built; the model is instructed to ask the user
first instead.

### Phase 4 — Give the assistant hands · ✅ DONE
Added: `direct_episode`, `storyboard`, `continuity_status`, `generate_episode`,
`assemble_episode`, `scrub_video`, `publish_episode`, `publication_status`,
`list_topics`, `run_batch`, `read_logs`.

Each is a **thin wrapper over an existing CLI verb or service** — no new pipeline
logic. That is what keeps the assistant from diverging from the unattended
runner, which drives the same verbs.

Two live-verified end-to-end: `read_logs` returned real records and the model
reported the level correctly; `generate_episode` was refused by the gate.

### Phase 5 — Retire the duplicate UI · ✅ DONE for webui
- ✅ `webui/` (Streamlit, 7,620 lines) + `webui.bat` + `webui.sh` deleted via
  `git rm`, so they are recoverable from history. Verified nothing imported it.
- ⚠️ **`video_model*` — needs your decision, not mine.** I checked, and they are
  *not* useless, so I did not delete them:

  | Path | What it actually is |
  |---|---|
  | `video_model/` | A different project entirely — `textanim`, a Vite/TypeScript web app (29 files) |
  | `video_model_dev/` | **Stickman Universe** — a separate product, *smaller copy* (167 files) |
  | `video_model_quality/` | **Stickman Universe** — a separate product, *larger copy* (517 files) |

  `video_model_dev/` and `video_model_quality/` have **identical `PROJECT.md`
  headers** — they are two copies of one project ("text-to-stickman-video
  product"). None of the three is referenced by any live AutoShorts code.

  **Why I stopped:** they are **not git-tracked**, so deleting them is
  unrecoverable — and "Stickman Universe" may be the engine behind the
  `Stickman Legends` FlowKit project, which would make it wanted. My
  recommendation: keep `video_model_quality/` (the larger, later copy), delete
  `video_model_dev/`, and move both survivors out of the repo root into
  `side-projects/`. **Your call.**

### Phase 6 — Guard the boundaries · ✅ DONE
`tools/check_boundaries.py` — 5 rules, each mapping to a bug that actually
happened:

| Rule | Catches |
|---|---|
| `operations-live-in-one-place` | an `@operation` outside `agent/operations/` (invisible to the registry, so ungated) |
| `tools-come-from-the-catalog` | a hand-written tool list returning to `chat_agent` |
| `no-direct-subprocess` | an operation spawning a process itself, opting out of the cwd pin/timeout/cap |
| `no-api-imports` | a department importing the HTTP layer (one documented exception) |
| `flowkit-is-the-server-only` | the client package being renamed back to `flowkit` |

Verified it is **not a rubber stamp**: I injected a rogue `@operation` and
confirmed the checker fired. It also caught a false positive in itself on the
first run (matching `"name": op.name` as a hardcoded name) — tightened, because
a checker that cries wolf gets switched off.

---

## 6. What I will NOT do

Saying this explicitly, because "clean architecture" is a phrase that often ends
in a rewrite nobody asked for:

- **No folder reshuffle for aesthetics.** `app/` stays where it is; it works.
- **No rewriting the working pipeline.** The reference-image fix, the tool loop,
  the consistency report — all stay.
- **No new framework or dependency.** No DI container, no event-sourcing layer,
  no plugin system.
- **No deleting `app/` or the MMT core.** It is the assembly engine.
- **No touching `webui/`, the credentials, or the DB schema** without you saying
  so — those are yours to call.

---

## 7. Decisions

### Answered

| # | Question | Answer |
|---|---|---|
| 2 | `webui/` (Streamlit) | **Delete** — done, via `git rm` (recoverable) |
| 3 | Which `video_model*` is live | **I checked.** None is referenced by live code; `_dev` and `_quality` are two copies of one product. Not deleted — untracked means unrecoverable. See Phase 5. |
| 4 | Risk gate default | **Opt-in.** `spend` operations refused unless explicitly enabled. |
| 5 | Rename `flowkit` → `render_client` | **Approved and done.** |

### INGEST — my recommendation (you said you did not know it)

**Keep it, as a department — but it is the only optional one.**

What it is: `automation/` is the **unattended loop**. It fetches topics, checks
them against a dedup ledger, *claims* them (so a crash cannot double-submit), and
invokes the pipeline. It owns two things nothing else owns:

- **the ledger** — the record of what has already been made. Without it, a feed
  that returns the same item every poll would regenerate it every poll.
- **the claim** — marking a topic in-flight before handing it over.

Why it is a department and not just a script: it holds state that outlives a run,
and it is the only place that decides *what to make*. That is a real
responsibility, not a utility.

**But**: if you never run the pipeline unattended — if you always trigger
episodes by hand from the dashboard — then this department is dead weight and can
be deleted entirely, along with its ledger. That is a genuine fork in the road,
and only you know which side you are on. My recommendation is to keep it: the
whole point of this project is unattended publishing, and this is the department
that does the "unattended" part.

### Still open

- **`video_model*`** — keep `video_model_quality/`, delete `video_model_dev/`,
  and move survivors to `side-projects/`? (See Phase 5.)
- **`agentMemory/`** — rename so it cannot be confused with the assistant's
  memory (`flowkit/agent_data/`).
- **`opencode_endpoint/`** — still the reference, or superseded by
  `flowkit/agent/services/opencode_models.py`?
