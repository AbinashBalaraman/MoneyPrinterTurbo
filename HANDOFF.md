# AutoShorts — Handoff

**Written:** 2026-09-15 · **Last updated:** 2026-09-18 (§12 upstream merge and
push, §13 the four phases and the test environment)
**Head:** `main`, and `main` is now the **only** branch. `automation` was deleted
on 2026-09-18 (it was fully contained in `main`).
**State:** `main` is a **superset of upstream MoneyPrinterTurbo** — upstream
`fdcf249` was merged in, so every file and feature upstream ships is present —
and it is **pushed**. All four planned phases are done (§13): the agent drives
MoneyPrinterTurbo's real settings surface, FlowKit is a native `video_source`,
and the Studio builds batch tasks from that same surface. Publishing is off;
**spend is ON** (§12).
**Audience:** any agent (or person) picking this up cold. Everything needed is in
this file or in the docs it points to.

---

## 1. What this project is

A fully automated short-form video pipeline. Give it a topic; it writes an
episode script, generates the stills through Google Flow (via a Chrome
extension), assembles narration + subtitles + BGM into a vertical MP4, scrubs
the AI watermark, and publishes to YouTube Shorts / TikTok / Instagram Reels.
The target is **unattended operation**.

The owner is **Abi**. He talks in shorthand, wants real opinions rather than
summaries, and explicitly values being told the hard thing over an optimistic
claim.

**This is a fork of MoneyPrinterTurbo.** That is important and easy to get wrong
— see §3.1: the MoneyPrinterTurbo code at the repo root is **not** dead legacy,
it is the assembly engine, and the pipeline depends on it.

---

## 2. How to run it

### Services

| Service | Address | PID at handoff |
|---|---|---|
| FlowKit agent (FastAPI) | `http://127.0.0.1:8100` | 15128 |
| Extension WebSocket | `ws://127.0.0.1:9223` | 15128 |
| Terminal WebSocket | `ws://127.0.0.1:8100/ws/terminal` | 15128 |
| Dashboard (Vite) | `http://127.0.0.1:5173` | 8632 |

```bash
# backend  (must run UNSANDBOXED — see §8)
cd flowkit && \
  "C:/Users/SATHYA TRADERS/.workbuddy-ai/binaries/python/envs/flowkit/Scripts/python.exe" \
  -m agent.main

# dashboard
cd flowkit/dashboard && \
  "C:/Users/SATHYA TRADERS/.workbuddy-ai/binaries/node/versions/22.22.2-2/node.exe" \
  node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173
```

Both verified HTTP 200 at handoff. `curl` needs `--noproxy '*'` (§8).

**Restarting the agent is safe.** The Chrome MV3 extension re-dials `9223` by
itself within ~6s — no manual reload in `chrome://extensions`. Verified
repeatedly.

### Interpreters — there are four, and using the wrong one wastes real time

| Purpose | Path |
|---|---|
| FlowKit agent (the server) | `.workbuddy-ai/binaries/python/envs/flowkit/Scripts/python.exe` |
| **Pipeline** (SCE: director, render client, post, publish) | `AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe` |
| **Assembly** (MoneyPrinterTurbo, root `cli.py`) | `AutoShorts/.venv/Scripts/python.exe` |
| Node | `.workbuddy-ai/binaries/node/versions/22.22.2-2/node.exe` |

The pipeline and the assembly engine have **separate virtualenvs**. A CLI wrapper
cannot use `sys.executable`. This is why `agent/operations/shell.py` exists and
why its interpreter paths are config (`PIPELINE_PYTHON`, `ASSEMBLY_PYTHON`).

Symptom of getting this wrong: `ModuleNotFoundError: No module named 'loguru'`
when importing `cli.py` with the flowkit venv. It looks like a broken repo; it is
a wrong interpreter.

### Tests

> **Run the Python suites with the safe-delete shim off.** Without this the shim
> kills pytest mid-run and the failures look random:
>
> ```bash
> CODEBUDDY_SAFE_DELETE_ENABLED=0 CODEBUDDY_TOOL_CALL_ID= pytest <args>
> ```
>
> See §13 for why, and for what remains flaky even with it.

```bash
# MoneyPrinterTurbo: assembly engine, providers, config, WebUI
.venv/Scripts/python.exe -m pytest test/services -q     # 1314 passed / 19 skipped
.venv/Scripts/python.exe -m pytest test/*.py -q         # 126 passed

cd flowkit && <flowkit-python> -m pytest tests/unit -q  # 606 passed / 0 failed

cd shorts_content_engine && <pipeline-python> -m pytest tests/unit -q
#   169 passed / 0 failed

<flowkit-python> tools/check_boundaries.py
#   boundary check passed — 6 rule(s) upheld
```

Prefer `-v --tb=line` over `-q` when redirecting: `-q` writes to a block-buffered
stream, so a redirected run shows nothing until it finishes and a hang is
indistinguishable from progress.

### The four docs

| Doc | What it is |
|---|---|
| `docs/ARCHITECTURE.md` | **The map.** Departments, the dependency rule, every top-level directory's purpose. Read this second. |
| `docs/IMPLEMENTATION.md` | The six-phase plan and its completion status. |
| `docs/CHAT_UI_REVIEW.md` | The chat UI audit against the industry checklist, and the library decision. |
| `HANDOFF.md` | This file. |

---

## 3. Architecture — the eight departments

Full detail in `docs/ARCHITECTURE.md`. The short version:

```
topic ─► script ─► stills ─► video ─► clean ─► published
       (Director) (Render) (Assembly) (Post)  (Publish)
  ▲
  └─ Ingest decides what to make, and that it is made once
```

| # | Department | Owns | Lives in | Entry point |
|---|---|---|---|---|
| 1 | **INGEST** | What to make next, once only. Topic sources, dedup ledger, claiming. | `automation/` | `python -m automation.runner` |
| 2 | **DIRECTOR** | Story: scripts, pacing, characters, continuity, storyboards. | `shorts_content_engine/src/{director,storyboard,storage}/` | SCE `cli.py` |
| 3 | **RENDER** | Prompts → media, via Google Flow. Queue, worker, extension bridge, and the client that drives it. | `flowkit/agent/` (server) + `shorts_content_engine/src/render_client/` (client) | `flowkit/agent/main.py` |
| 4 | **ASSEMBLY** | Narration, subtitles, BGM, image→video concat. | `app/`, root `cli.py` | `python cli.py --batch-file …` |
| 5 | **POST** | Watermark removal, metadata strip. | `shorts_content_engine/src/postprocess/` | SCE `cli.py scrub` |
| 6 | **PUBLISH** | Uploading, and tracking outcomes. | `shorts_content_engine/src/distribution/`, `flowkit/agent/api/publications.py` | SCE `cli.py publish` |
| 7 | **STUDIO** | Every pixel a human sees. | `flowkit/dashboard/` | `vite` → :5173 |
| 8 | **ASSISTANT** | The chatbot: tool loop, memory, search. | `flowkit/agent/services/{chat_agent,agent_memory,web_search}.py` | inside RENDER's server |

Plus **OPS** — logging, events, DB, config, the terminal PTY. Shared; owns no
pipeline state.

**The dependency rule:** a department may call the one to its left, and may not
reach right. `INGEST → DIRECTOR → RENDER → ASSEMBLY → POST → PUBLISH`. STUDIO and
ASSISTANT are front doors: they talk to Control and never reach into a department
directly.

### 3.1 Things that are easy to get wrong

- **`app/` is live and load-bearing.** It is the MoneyPrinterTurbo core: TTS,
  subtitles, BGM, concat. `automation/runner.py:353` invokes root
  `cli.py --batch-file`, which drives it. Do not delete it. Only its Streamlit UI
  (`webui/`) was dead, and that is already gone.
- **`flowkit` means exactly one thing: the RENDER server.** The client library
  that drives it is `shorts_content_engine/src/render_client/`. It used to be
  `src/flowkit/`, and two different things with one name is what made the
  reference-image bug take hours to find. Class names (`FlowKitClient`,
  `FlowKit*Create`) deliberately stayed — they name the protocol.
- **`agentMemory/` is a vendored VS Code extension.** It has nothing to do with
  the assistant. The assistant's real memory is `flowkit/agent_data/`.

### 3.2 Control — one operations catalog, two front doors

`flowkit/agent/operations/`. **21 operations across all 8 departments**, each
declared once:

```python
@operation(name="queue_status", department="render", risk="read")
async def queue_status(project_id: str | None = None) -> dict: ...
```

The chatbot's tool specs, the prompt's department grouping, and the risk gate are
all derived from that declaration. The registry **rejects a duplicate name** — a
duplicate would silently shadow, which is the drift bug this exists to prevent.

Why it exists: an operation used to be implemented twice (a REST route and a
hand-written chatbot tool) and they drifted **twice in one week** — the `tool`
SSE frame shape, and `_char_matches` vs `_matches`.

| `risk` | Behaviour |
|---|---|
| `read` | Always allowed |
| `write` | Allowed (memory, ledger, a scrub) |
| `spend` | **Refused unless `AGENT_ALLOW_SPEND=1`** |
| `destructive` | Refused unless spend is on **and** a confirm token is present |

`run_command` is `write`, **not** `destructive`, deliberately: the only confirm
token available is one the *model* sets, so requiring it would be a speed bump
that looks like a safety check while checking nothing. Its real controls are the
pinned cwd, the pattern denylist and the output cap.

**Known remaining duplication:** REST routes still call the service layer
directly rather than going through the catalog. They call the **same services**,
so behaviour cannot differ, but the route layer is not yet generated. That is the
honest status of the "two front doors" property: it holds for the chatbot, not
yet for HTTP.

---

## 4. What is DONE (all verified, not assumed)

### Pipeline correctness
- **Missing reference-image producer fixed.** 6 of 13 failed requests were
  `GENERATE_IMAGE` dying with `Waiting for reference images`. Root cause: the
  *producer* was missing — nothing ever queued `GENERATE_CHARACTER_IMAGE`;
  `to_character_batch_requests` was dead code. Fixed in the SCE orchestrator
  (idempotent, skips entities that already have a `media_id`). Proven live: the
  project went 6 failed/0 done → **9/9 completed**.
  > Gotcha: `poll_batch_resilient(orientation=None)`. Character requests have NULL
  > orientation; the default `"VERTICAL"` filter matches nothing and times out.
- **`GET /api/characters` silently ignored `project_id`.** FastAPI drops
  undeclared query params with no warning, so it returned every character in the
  DB. Now declared and filtered.
- **Reference-image failures fail fast** instead of retrying forever
  (`_prerequisites_met` defers only while a reference request is genuinely
  in-flight).

### The conditioning report — the honest version
- Abi chose **warn** over hard-fail: a scene naming characters nothing links to
  still generates. The first version of the report inferred "was this image
  conditioned?" from the project's *current* links — which **lies** in the case
  that matters, because an image generated while unlinked is un-conditioned
  *forever*.
- Fixed properly: `scene.conditioned_with` is written **at generation time**
  (`result_handler._conditioning_record`). Three states, all meaningful:
  `["arthur"]` = conditioned on exactly these · `[]` = generated with no
  conditioning (proven) · `NULL` = unknown, predates the column.
- **Deliberately not backfilled** — guessing would destroy the only honest signal.
- `unverified` (NULL) is a gap in *evidence*, not a problem, so it does **not**
  make a project `clean: false` — otherwise every pre-existing project looks
  broken and the report gets ignored.
- Live: `farmer_and_rusty` clean; `Stickman Legends` correctly flagged.

### The chatbot
- **Tool loop** (`services/chat_agent.py`): prompt-level protocol
  (`⟦tool:name {json}⟧`) because the free `muse-spark-*` models have no reliable
  native function calling. Also accepts `[[…]]` / `<<…>>` so a bracket slip is
  not fatal. Bounded rounds, balanced-brace JSON scanning (**never a regex** — a
  non-greedy `\{.*?\}` stops at the first inner brace and mangles nested args),
  streaming holdback so markers never flash on screen, malformed calls fed back
  to the model instead of dropped.
- **It can now run the pipeline**, not just inspect it: `direct_episode`,
  `storyboard`, `continuity_status`, `generate_episode`, `assemble_episode`,
  `scrub_video`, `publish_episode`, `publication_status`, `list_topics`,
  `run_batch`, `read_logs`. Each is a thin wrapper over an existing CLI verb — no
  new pipeline logic.
- **Risk gate visible end-to-end.** Frames carry `risk`; refusals carry
  `refused: true`; the UI badges `SPENDS MONEY` / `PUBLIC · IRREVERSIBLE` and
  renders a refusal as a calm *"Not run — …"* card, not a red error.
  `GET /api/agent/capabilities` + a Studio mode strip state whether the assistant
  is inspection-only.
- **TinyFish web search is live** (`GET https://api.search.tinyfish.ai`,
  `X-API-Key`, free tier). Verified end-to-end through the tool loop.
- **Conversations auto-save** server-side (debounced 1.2s) to
  `flowkit/agent_data/conversations/`, plus long-term memory and a Memory drawer.
- **Terminal tab** is a real `cmd.exe` PTY (`pywinpty`), not a chat persona.

### Architecture cleanup (all six phases)
- `docs/ARCHITECTURE.md` written — every claim checked against the tree.
- `src/flowkit/` → `src/render_client/`, 16 files + the test file renamed.
  **Acceptance: SCE stayed at 169 passed.**
- Streamlit `webui/` was deleted via `git rm` in the 2026-09-15 session, then
  **restored in full on 2026-09-18** during the upstream merge, together with
  `webui.bat` and `webui.sh`. Abi asked for the complete MoneyPrinterTurbo
  feature set, and the WebUI is its headline GUI. `streamlit 1.59.1` is already
  installed in the assembly venv. Reverting is one commit if it turns out to be
  unwanted.
- `tools/check_boundaries.py` — 6 rules, each mapping to a bug that happened.
  **Verified it is not a rubber stamp** (injected a rogue `@operation`, it fired).
- **The 9 dead `test_result_handler.py` tests now run.** They errored on
  `fixture 'mocker' not found` (`pytest-mock` not installed) and had never
  actually executed. Rewritten with `monkeypatch` — no new dependency — plus 4
  new tests for the conditioning write path. Errors went 9 → **0**.

---

## 5. Where the pipeline actually stands

- `farmer_and_rusty` (Ep 1) — **9/9 requests completed**, 6 scenes with
  `vertical_image_status: COMPLETED` and image URLs. Clean on the conditioning
  report.
- `Stickman Legends: Neon Overdrive` — 6 scenes generated **without** reference
  conditioning. Needs the fix in §7.2.
- **Video generation works. The earlier "no Veo access" conclusion was wrong and
  is superseded — do not quote it as current state.** Verified 2026-09-18
  directly from `flowkit/flow_agent.db`:
  - 7 `GENERATE_VIDEO` **FAILED**, all dated **2026-09-13**, with
    `RpcError: eb1hJf failed: [7, ... PUBLIC_ERROR_MODEL_ACCESS_DENIED]`.
  - 1 `GENERATE_VIDEO` **COMPLETED** — `417f2848-…`, created
    `2026-09-16T17:52:36Z`, finished `17:53:48Z` (**72s**), media
    `47d3a25a-…`, real signed Flow URL.

  The success is three days *newer* than the denials, so the account can generate
  video. An agent that believes the old denial will generate stills only, which
  produces exactly the looped-footage defect noted in §11.
- **Open hypothesis, not a finding:** the 6 denials share an identical
  `created_at` (a simultaneous burst), while the success was a *single* request.
  If the denial was burst/concurrency-shaped rather than account-level, ~6
  parallel video requests per episode will fail again. Untested — worth one call
  before any batch run.
- One polling timeout remains unexplained: *"Extension manifest must request
  permission to access the respective host."* Needs the live Flow tab URL to pin
  down which host. **Not guessed** — do not invent a cause.

---

## 6. Test status

**Green as of 2026-09-18**, with the caveats in §13.

| Suite | Result |
|---|---|
| `test/services` | **1314 passed / 19 skipped / 0 failed** |
| `test/*.py` (root) | 126 passed / 0 failed |
| `flowkit/tests/unit` | **606 passed / 0 failed** |
| `shorts_content_engine/tests/unit` | 169 passed / 0 failed |
| `tools/check_boundaries.py` | 6 rules upheld |

History, so the numbers make sense: the older "14 remaining failures"
(`test_video_reviewer.py` ×13, `test_cli_providers.py` ×1) were fixed on
2026-09-15. The 2026-09-18 upstream merge surfaced 7 more — 6 pre-existing
(fixed in `bca271f`) and 1 genuinely new, which caught a real `cf_worker`
whitelist bug (`d3b59b8`).

**The 4 flowkit failures are fixed** (`03229b6`). `_is_configured` in
`agent/api/opencode.py` is `OPENCODE_API_KEY or GEMINI_API_KEY or
NVIDIA_API_KEY` — a deliberate multi-provider fallback — but the autouse fixture
pinned only `OPENCODE_API_KEY`. With a Gemini key present the endpoint reported
itself configured and the "no key" tests got 200 instead of 503. The tests were
wrong, not the code.

**The last `test/services` failure is fixed** — and it was a test-isolation bug,
not a code one. `app.config` keeps settings in module-level dicts, and sixteen
test files mutate them directly (`config.app["api_key"] = …`). Most restore what
they change, but in their own `tearDown`, so one failure during `setUp` leaks a
value into every later test. The symptom: a full-suite run fails a test that
passes on its own, and *which* test fails moves between runs —
`test_configured_key_protects_task_file` did exactly that.

`test/conftest.py` now snapshots every dict on `config` before each test and
restores it in place afterwards. **Do not add per-file config restoration** — it
is handled, and that duplication is what caused the problem.

If a `test/services` failure appears again, reproduce it in isolation first, and
check §13's shim notes before assuming a regression.

---

## 7. OPEN — what is left, and exactly what to do

### 7.1 Decisions only Abi can make

**(a) ~~`video_model*` — three untracked side-projects.~~ Superseded
2026-09-18.** Commit `0f1ba7e` (`chore: remove side-projects, debug artifacts,
and generated media`) already deleted `video_model/`, `video_model_dev/`,
`video_model_quality/` and `agentMemory/`. None are present in the tree any more,
so this decision no longer has anything to act on. Worth confirming with Abi only
if the "Stickman Universe" engine behind the `Stickman Legends` project turns out
to be wanted after all.

**(b) The 3 orphan character rows.** In `flow_agent.db`, three name pairs exist.
In each, one row has a reference image and is referenced by a request; the other
has neither:

| Keep | Delete (orphan) |
|---|---|
| `4bd40ee7` Red Blade | `f705dc78` Red Blade |
| `d25e86bf` Blue Strike | `9e1dbe52` Blue Strike |
| `14494da0` The Neon Grid | `ec53e48c` The Neon Grid |

**Neither copy is linked to the project.** Destructive — list it and confirm
first.

**(c) Rotate leaked credentials.** Untouched by design: the OpenCode key in git
history `f207698`, and two GitHub PATs in `FamilyTree/.git/config` and
`Study_Guide/.git/config`.

### 7.2 The Stickman Legends fix — needs a spend go-ahead

1. Link the 3 characters that **have** a `media_id` to the project
   (`POST /api/projects/<id>/characters/<char_id>`).
2. **Regenerate the 6 stills** — linking alone does **not** retroactively
   condition an existing image. This is the whole point of §4.
3. The conditioning report goes clean once the new images record their
   conditioning.

Step 2 costs image-generation calls, so it has **not** been done. `AGENT_ALLOW_SPEND`
is now `1` (§12), so the gate this section was waiting on is open — but the work
still has not been run. It needs Abi's go-ahead on the spend, not on the flag.

### 7.3 Code work that needs no decision

- **Generate the REST routes from the operations catalog** (§3.2). Closes the
  last real duplication. ~20 route modules; do it incrementally, keeping the
  existing routes working as thin wrappers.
- **A UI-driven approval** for `destructive` operations — a button that mints the
  confirm token. Today the model is told to ask the user first, which is honest
  but not equivalent.
- **Streaming reconnect.** If the SSE stream drops mid-reply the partial answer
  is kept and an error shown, but the turn is not resumed.
- **Copy-output button on tool cards** (markdown code blocks already have one).
- **Accessibility audit** — untested, and it matters before anyone else uses this.
- **`agentMemory/`** — rename so it cannot be confused with the assistant's
  memory. **`opencode_endpoint/`** — still the reference, or superseded by
  `flowkit/agent/services/opencode_models.py`? **Root `main.py`** — appears unused
  by the pipeline (`automation/` calls `cli.py`, not the HTTP API). Confirm before
  removing.
- **Light theme** — the dashboard is hardcoded `<html class="dark">`.

---

## 8. Environment gotchas — read before debugging anything

- **`curl` needs `--noproxy '*'`.** A corporate proxy answers some paths and
  404s others, which looks exactly like a broken service.
- **The server cannot start inside the sandbox** (`WinError 10013`,
  `socket.socketpair()` blocked). Run it unsandboxed.
- **`Path.unlink()` can raise a non-`OSError`** here. `.workbuddy-ai/` is
  protected project data and this environment's safe-delete shim refuses
  deletions inside it. Never wrap a deletion in `except OSError` when a request
  handler calls it — catch broadly, and answer 404 (missing) / 409 (refused)
  rather than a blanket 200 with `deleted: false`. **Never store user-deletable
  content under `.workbuddy-ai/`.**
- **`python -m agent.main` double-imports the module** (once as `__main__`, once
  as `agent.main`), which used to duplicate every log line. Guarded by
  `_attach_log_bus_handler()`. Do **not** "simplify" it to a module-level flag —
  the two imports have separate globals.
- **`.env` changes need an agent restart.** `agent/config.py::_load_env_files()`
  runs at import time and an already-set env var wins over the file. Do not read
  "still not configured" as a broken key.
- **Secrets belong in `.env`, never `.env.example`.** `.env.example` is a tracked,
  committed template. A live `TINYFISH_API_KEY` was pasted there once; it had not
  been committed, so it was moved before it leaked. Check
  `git show HEAD:.env.example` if you suspect one has.
- **`npm install` cannot repair an interrupted extraction** — arborist validates
  version + tarball hash, never files on disk. Use
  `tools/repair_npm_package.py`.
- **`pytest-mock` is not installed** in the flowkit venv. Use `monkeypatch`.
- **A DB-backed test can hang.** Opening the shared SQLite file while the agent
  holds the lock blocks. Prefer non-DB operations in tests that are not about the
  DB.
- **`flowkit/` and `shorts_content_engine/` are untracked** (vendored) — `git
  status` will not show changes inside them.
- **The `webui/` removal has been undone.** As of 2026-09-18 `webui/`,
  `webui.bat` and `webui.sh` are all present again, restored from upstream during
  the merge. The old recovery advice (`git checkout HEAD -- webui webui.bat
  webui.sh`) no longer applies.

---

## 9. Doc map for a cold start

1. **This file** — state, open items, gotchas.
2. **`docs/ARCHITECTURE.md`** — the map. Departments, dependency rule, every
   directory's purpose.
3. **`docs/IMPLEMENTATION.md`** — the six-phase plan, all phases complete, with
   the reasoning behind each decision.
4. **`docs/CHAT_UI_REVIEW.md`** — the chat UI audit and the library decision
   (adopt nothing; the hard parts are already built).
5. **`flowkit/agent/services/chat_agent.py`** module docstring — read before
   touching the tool marker syntax.
6. **`flowkit/agent/operations/registry.py`** module docstring — read before
   adding an operation.

Project memory (session-by-session reasoning) is in
`AutoShorts/.workbuddy-ai/memory/` — `2026-09-13.md`, `2026-09-14.md`,
`2026-09-15.md`, `2026-09-18.md`, and `MEMORY.md` for durable conventions. It
records *why* decisions were made, including the ones that were wrong first.
Note there is **no log for 09-16 or 09-17** — §11 is the only record of that
work.

---

## 10. The one thing not to do

**Do not "fix" the warn-and-continue decision by throwing on an unlinked
entity.** It is a deliberate choice: hard-failing would break any scene whose
characters were legitimately renamed or removed. Warn, and report.

And relatedly: **do not replace `conditioned_with` with a check against the
current project links.** That is the bug that was already fixed once — linking a
character afterwards would make an un-conditioned image look fine.


---

## 11. 2026-09-16/17 — MoneyPrinterTurbo + FlowKit integration

### What changed

The original objective is now implemented and **proven live**: MoneyPrinterTurbo
is the assembly engine and FlowKit is its native AI-media source.

The path is:

```
FlowKit scene media (video preferred, still fallback)
  → download into storage/local_videos/<task>/
  → scrub with the project SCE ffmpeg watermark engine
  → MoneyPrinterTurbo local-material pipeline
  → TTS + subtitles + BGM + vertical final MP4
```

- `automation/flowkit_bridge.py` now supports `--from-project <id|name>` and
  `--media auto|video|still`.
  - `auto` selects a completed FlowKit vertical video per scene when available;
    otherwise it selects its completed still.
  - It stages in storyboard order, preserves scene narration, normalises still
    formats, and writes safe absolute local material paths into emitted batch
    manifests.
  - It no longer depends on the former external Node/GWR watermark package.
- Scrubbing now uses the project's existing
  `shorts_content_engine/src/postprocess/watermark.py`:
  - stills: `gemini_bottom_right` profile;
  - FlowKit video clips: `veo_bottom_right` profile.
  - Bridge scrubbing fails loudly if FFmpeg/scrub fails rather than quietly
    feeding watermarked media downstream.
- `automation/runner.py` accepts `--flowkit-project` and `--flowkit-media`.
  It stages the project once per unattended batch and applies its local media to
  every generated entry. This keeps FlowKit fully inside the regular
  MoneyPrinterTurbo workflow rather than a side script.
- `flowkit/agent/operations/assembly.py` has `build_batch_task` (write risk),
  exposing the full `VideoParams` settings object: sources, ratio, concat,
  transition, clip duration, voice, BGM, subtitles, fonts, stroke and related
  MoneyPrinterTurbo options. Its optional `flowkit_project` calls the same
  staging bridge, not duplicate download/scrub logic.
- `flowkit/agent/operations/shell.py` adds `run_bridge`, using the assembly venv
  to execute the bridge. The agent catalog is now 24 operations; spend remains
  enabled at last check (`AGENT_ALLOW_SPEND=1`).

### Live proof

1. Re-tested FlowKit video generation after the previous Sept 13 failures:
   request `417f2848-4ad8-47a4-b1ce-0bf9d49eb91` for
   `farmer_and_rusty - Ep 1: The Whispering Furrow` completed in ~70 seconds.
   It produced Flow media `47d3a25a-0c7d-49dd-98b4-4ba347ef807e`.
   Therefore the old Veo access-denied result is stale and must not be treated
   as current account state.
2. Old signed Flow image URLs had expired (403), so five scene stills were
   explicitly regenerated: all 5/5 completed.
3. Live bridge run on project `f5ce611c-3f4c-471d-8dcf-c26059defa3f` staged six
   ordered materials: one generated video plus five Flow stills. The five stills
   were visibly logged as scrubbed by the in-project engine.
4. MoneyPrinterTurbo assembled a complete final vertical episode:
   `storage/tasks/4e163a3a-45e4-4964-8ccf-253fab6efda1/final-1.mp4`
   (11.8 MB, 39 seconds) with TTS and subtitles. The CLI summary reported
   `succeeded: 1, failed: 0`.

Known output-quality detail: available source media totaled 33 seconds while
narration was 39 seconds, so the assembly engine looped two clips. Generate
more Flow video clips or shorten narration to avoid that repeat.

### Validation

- `test/test_flowkit_bridge.py`: **56 passed**.
- `test/test_flowkit_bridge.py test/test_automation_runner.py
  test/test_automation_ledger.py test/test_main.py`: **87 passed**.
- `flowkit/tests/unit/test_build_batch_task.py`, operations registry/API suites:
  **54 passed**.

### Cleanup status

- The old `automation/watermark_scrub.py` GWR/Node implementation and its test
  were removed in favor of the existing project SCE scrubber.
- A broad disk inventory was started but **do not delete side-projects or
  historic generated data blindly**. `video_model*`, `content_creation/`, and
  `storage/` require an owner-retention decision. `storage/` currently contains
  ~554 MB of caches/tasks, including the new final artifact above.
- Current tracked worktree also contains earlier Studio/OpenCode changes and
  generated FlowKit conversation/benchmark files. Do not bundle or delete them
  casually; separate the intended code changes from generated state before
  committing.

### Recommended immediate next steps

1. Add the FlowKit source controls to Studio UI (Phase 3 was intentionally
   deferred while agent + CLI parity was proven first).
2. Offer a per-scene media plan: generate missing video clips before assembly,
   then enforce enough source duration for narration to avoid looped footage.
3. Make cleanup a separate, approved task: classify every top-level folder as
   live code, side project, generated/cache, or archive; then delete only
   owner-approved generated/cache content.
4. Commit source changes separately from generated DBs, conversations, media,
   and test outputs.

---

## 12. 2026-09-18 — upstream merge, one branch, and live switch state

### One branch

`main` is now the **only** branch. `automation` was deleted because it was
**fully contained** in `main` — no work was lost. Do not recreate per-feature
branches; Abi wants everything on `main`.

### Upstream merged

`main` merged upstream `fdcf249` (65 commits), so the fork is now a **superset of
upstream**. Verified: `git diff --name-status main fdcf249 --diff-filter=A`
returns nothing.

New upstream features now present: VoxCPM voice cloning, MuAPI material source,
Fluxion AI + API Route LLM providers, Catalan WebUI locale, plus CLI fixes
(subtitle display/animation, clip speed, AI music prompt, two-thirds subtitle
position, ElevenLabs BGM mode, zoom transitions).

All 14 conflicts were `webui/` modify/delete; resolved by restoring `webui/` in
full (§4). Backup refs: `backup-pre-upstream-merge-2026-09-18` (`fcdb6e3`) and
`backup-automation-9284c8f` (`9284c8f`).

**Lesson worth keeping.** Restoring the directory was *not* enough: `webui.bat`
and `webui.sh` stayed deleted, because we deleted them and upstream never
modified them — git treats that as delete/delete, a **non-conflict**, and drops
them with no warning. The conflict list is not a completeness check. After every
upstream merge, run:

```bash
git diff --name-status main <upstream-sha> --diff-filter=A
```

It lists files upstream has that `main` does not.

### Live switches — read before running anything

| Switch | Value | Meaning |
|---|---|---|
| `AGENT_ALLOW_SPEND` | `1` | **Spend operations are NOT refused.** The assistant can burn image/video credits. |
| `AUTOSHORTS_DRY_RUN` | `true` | |
| `UPLOAD_POST_ENABLED` | `false` | Publishing is off |
| `UPLOAD_POST_AUTO_UPLOAD` | `false` | Publishing is off |

**Spend is open, publishing is closed.** Do not describe the spend gate as
closed, and do not weaken the publish flags without telling Abi.

### Pushed (2026-09-18) — and the secret that actually blocked it

`main` **is** pushed; `origin/main` is current. The push was rejected **four
times** by GitHub secret scanning, and the blocker was not the Google key.

- The Google key (`AIzaSy…`) was real and was removed from three tracked files
  (`flowkit/extension/background.js`, `flowkit/agent/config.py`,
  `flowkit/PLAN.md`). It is most likely Google's own browser-restricted Flow
  web-client key rather than Abi's — unverified, since the restrictions live in
  a Google Cloud project he does not own.
- **What actually blocked it was a Cloudflare User API Token** (`cfut_…`) inside
  a tracked conversation transcript, in a config dump that also carried Pexels
  and Pixabay keys. Cloudflare tokens have no distinctive prefix, so pattern
  scans missed it; `git grep` also skips files it treats as binary.

Both are gone from history. `flowkit/agent_data/` is now gitignored — a
transcript can capture anything the assistant printed, so tracking it is a whole
class of leak, not one file.

**Abi should still rotate** `cf_worker_image_key`, `pexels_api_keys` and
`pixabay_api_keys`. Nothing was ever pushed before the strip, so this is
precautionary rather than an active breach.

**Before any future push**, scan blobs rather than grepping text:

```bash
git rev-list --objects main | awk '{print $1}' | git cat-file --batch > all.bin
grep -acF "<needle>" all.bin
```

Validate the scanner against a ref you know is dirty, or a clean result means
nothing.

---

## 13. 2026-09-18 — the four phases, and the test environment

### Phase 1 — the agent can drive MoneyPrinterTurbo's real settings surface

`build_batch_task` took a `settings` dict and passed every key straight into the
manifest, so the model had to **guess** ~39 field names — and a guess failed deep
inside the assembly run, after TTS had been paid for.

The field list is now **derived, never copied**:

- `automation/emit_video_params_schema.py` (assembly venv) describes `VideoParams`
  as JSON — name, type, default, allowed values. The agent cannot import it
  itself: `app.models.schema` pulls in `app.config`, which needs `toml`, absent
  from the flowkit venv.
- `flowkit/agent/operations/video_params.py` loads that once per process and
  validates against it, reporting every problem at once with a `difflib`
  suggestion and the allowed values.
- New read operation **`assembly_settings_schema`**; the catalog is 25 operations.

Add a field to `VideoParams` and the agent accepts it; remove one and it stops.

### Phase 2 — FlowKit is a native `video_source`

`video_source = "flowkit"` takes an existing FlowKit project's completed media
(video preferred per scene, still fallback), scrubs it, and stages it as local
material. Download, normalisation, resolution checks, scrubbing and staging all
go through `automation/flowkit_bridge.py::stage_flowkit_project` — the single
staging implementation. Do not add a second.

It sits with the on-demand sources but does **not** share their "generate until
the duration is covered, then stop" contract: it generates nothing during the
run, so there is nothing to top up.

### Phase 3 — Studio parity

The Assembly tab exposed one control (a batch file path). It now builds a task
from a form whose field list comes from `assembly_settings_schema`, so
`ManualWorkbenchPage.tsx` hard-codes **no field names**, and enums render as
selects. Unset fields are omitted, so the manifest records intent and the engine
keeps its own defaults.

**Verified in a real browser** (Aside Browser via the `aside` MCP, 2026-09-19).
The earlier "not visually verified" note is resolved — and looking at the
rendered form found two traps that type-checking and the production build could
not:

1. `video_subject`, `video_script` and `video_terms` were rendered **twice** —
   in the dedicated inputs and again in the generated grid. `build_batch_task`
   drops them from `settings` on purpose, so editing the grid's copy did
   nothing: you would fill it in, see it accepted, and get a manifest built from
   the field above. The grid now excludes them and the header says
   *"36 fields, 3 set above"*.
2. List-typed fields were sent as **strings**. The placeholder said "JSON array"
   but the text was never parsed, so `video_materials` could not be satisfied
   from the form at all. It is now parsed on input; invalid JSON is passed
   through as text on purpose so `validate_settings` names it.

End-to-end check: the form fetched the schema, rendered 36 fields, showed
`video_aspect` as a select, tracked an override live (*"1 overridden"*), and
built a manifest that on disk is exactly

```json
[{"video_subject": "Phase 3 UI verification run", "video_aspect": "16:9"}]
```

— the override applied, no defaults dumped, no dropped fields leaked.

**To reproduce:** start the agent (`:8100`) and the dashboard (`:5173`), then
`http://127.0.0.1:5173/manual` → **4. Assembly**. The dashboard proxies `/api`
to `:8100`, so if the form says *"Could not read the settings surface"*, check
the agent is actually running before suspecting the UI — that is exactly what
happened the first time, and the UI was fine.

### Phase 4 — verification, and the environment trap

Verified live against a running agent: `assembly_settings_schema` returns 39
fields; `build_batch_task` refuses a guessed field name *and* a bad enum with
both problems reported at once; the real watermark scrubber works on a real file
(17.1 MB → 23.6 MB, still a readable 1080×1920 video).

**Not verified:** the FlowKit source end-to-end. It reaches the bridge and fails
correctly with *"flowkit is running but its Chrome extension is not connected"*,
so download → scrub → stage for a real project needs a signed-in Chrome tab.

**Update (same day, extension connected):** the extension does connect, and the
source then gets as far as the download:

```
extension connected → project resolved → 6 scenes fetched → download attempted
→ HTTP 403
```

**The 403 is expiry, not credentials.** Flow serves media through signed,
expiring URLs; the database keeps a scene marked `COMPLETED` with its URL, but
the URL dies a few days after generation. Measured: **13 of 13 signed URLs across
both projects were expired** (0 valid), `Expires` ~5 days in the past, and a
plain `curl --noproxy '*'` of the same URL also returns 403.

So the source works, and the staging window is simply short:

- it is fine for normal unattended operation, where media is generated and
  assembled promptly;
- **re-staging an old project fails and cannot be recovered** — the scene has to
  be regenerated in FlowKit. `farmer_and_rusty` and `Stickman Legends` are both
  in that state.

The bridge fails loudly rather than staging nothing, and the message now says
this outright (`_download_error`).

**Expiry is handled in three places, and the middle one was a real bug:**

1. `_download_error` explains a 403 as expiry rather than as a credential
   problem.
2. **`media="auto"` now actually falls back.** The per-scene choice used to be
   `video_status == "COMPLETED" and video_url` — but `COMPLETED` describes what
   Flow *generated*, not what is still *reachable*. A scene with a COMPLETED,
   expired video URL made `auto` fail on the download even when a live still was
   available: the exact opposite of what a fallback is for, and the state both
   projects are in. The choice now also requires the URL to be unexpired, and
   logs when it downgrades.
3. `_refuse_if_all_media_expired` refuses **before** downloading anything when
   nothing is usable, instead of walking the scenes and dying partway. It only
   refuses when *every* URL is expired — a partly-expired project is still worth
   staging. A URL with no `Expires` parameter is treated as "try it", never as
   expired.

All three came out of writing tests for the live failure. Point 2 was found
because a test disagreed with an assumption and the *code* turned out to be
wrong.

**Project references must be exact.** `farmer_and_rusty` does **not** resolve —
the project is `farmer_and_rusty - Ep 1: The Whispering Furrow`
(`f5ce611c-3f4c-471d-8dcf-c26059defa3f`). The error now suggests the full name and
lists what exists. It deliberately does not auto-resolve a prefix: silently
picking a project is how a run stages the wrong episode.

**The environment trap — read this before trusting any red suite.** This
environment's safe-delete shim breaks long test runs in two independent ways:

1. **It kills the process.** Past ~50 deletions in one tool call the bulk guard
   refuses, by `raise SystemExit(1)`. `SystemExit` derives from **`BaseException`,
   not `Exception`**, so nothing catches it and pytest dies mid-run. That is why
   the failing set differed on every run while every file passed in isolation.
2. **`os.remove()` is routed to the Recycle Bin, and the shim is fail-closed.**
   When the trash call fails (`SHFileOperationW 失败: 0x2` — file not found) it
   raises `OSError`, so any test removing an already-absent file in a `finally`
   fails for reasons unrelated to its subject.

Mitigate with `CODEBUDDY_SAFE_DELETE_ENABLED=0 CODEBUDDY_TOOL_CALL_ID= pytest …`
(§2). That took `test/services` from 19 failures to 1; the last is flaky and
unattributed (§6).

**One of those "failures" was a test lying about what it tested.**
`test_does_not_serve_symlink_to_file_outside_tasks` asserted 404 and got 200,
which reads like a path-traversal hole. It is not: on this machine
`Path.symlink_to()` returns *without raising* and leaves a 0-byte regular file
inside the tasks directory, which is legitimately served. The control is sound —
a genuine escaping symlink gets a 404. The test now skips when no link was
actually created.

### Duration guard, made general
`task.py::_report_material_shortfall` runs once per task, after materials are
fetched and before the render, so **every** source is covered — not just flowkit.
It compares against `audio_duration × video_count` (the multiplier matters;
`audio_duration` is per-video) and warns with the exact shortfall, plus a
separate warning when nothing could be measured, so "unknown" never reads as
"fine". Deliberately a warning: a shortfall can be acceptable for a given
episode, but it must not be silent.

## 14. 2026-09-19 — "the AI answered 0"

Abi asked the chat to *create new series "interesting facts" create first video*
and the assistant replied with a single character: `0`. Reproducing it found
three separate bugs, none of them in the chat UI.

### 1. The agent could not create a series

There was no operation for it. The model called `direct_episode`, was correctly
told to run `init-series` first, and had no tool that could — so it spent its
rounds on `dir` and on probing for modules that do not exist
(`python -m automation.director`, `python -m pipeline`, `python -m ledger`), and
replied with nothing at all. The UI rendered the empty reply, which is where the
`0` came from.

`init-series` had been in `shorts_content_engine/src/cli.py` the whole time. The
capability was missing from the **catalogue**, not from the project. A tool the
model cannot see is a tool it does not have. `create_series` added; the catalog
is **26 operations**.

### 2. The series data was split across two ledgers

The CLI defaults `--db-path` to `storage/ledger.db` **relative to its cwd**,
which resolves to `shorts_content_engine/storage/ledger.db`. The dashboard's
continuity panel — and therefore `continuity_status` — reads
`shorts_content_engine/continuity_ledger.db`. Two different files, measured with
a different series in each:

```
continuity_ledger.db  → farmer_and_rusty
storage/ledger.db     → interesting_facts   (just created through the agent)
```

So a series created through the agent was invisible to the status tool, and
`farmer_and_rusty` was invisible to `direct_episode`.

`flowkit/agent/services/ledger.py` is now the **single definition**, in a layer
both the API and the operations may import, and every ledger verb is passed
`--db-path` explicitly so the CLI's default never decides where data lands.

### 3. `continuity_status(series_id=…)` failed for every series

It filtered on `s.get("id")`, but the ledger's records key on `series_id` — so
`id` was always `None`, nothing matched, and asking for a series that *existed*
still answered *"No series … in the continuity ledger"*. The tool was unusable
with an argument.

### 4. `generate_episode` had never worked once

Chasing the same report further: with the first three fixed, the assistant could
create a series and direct an episode — but the step that actually renders it was
broken, so "create first video" still could not finish.

It took a `manifest_path` and ran `generate --manifest <path>`. The pipeline CLI
has **never** accepted `--manifest`, and it **requires** `--series-id`:

```
shorts_engine generate: error: the following arguments are required: --series-id
```

An argparse usage error, so it could not have succeeded even once. The manifest
comes from the ledger, not a file — `generate` resolves it with
`ledger.get_episode_manifest(series_id, episode_num)`. The op now takes
`series_id` and an optional `episode`, and passes the shared `--db-path`.

It also runs `--live` by default. The CLI defaults to `--mock`, but an operation
whose declared risk is *spend* and whose description promises generation would
otherwise simulate silently — a quiet no-op of exactly the kind this codebase
keeps removing. `live=false` gives a deliberate dry run.

`storyboard` also passes `--manifest`; that verb really does accept it, so only
this one was broken.

**Verified live, the whole chain, spending nothing:**

```
create_series   → Series Registered Successfully
direct_episode  → Episode 1 "The Cipher Protocol", 45.0s
generate_episode (live=false) → "Video Generation Completed Successfully"
                  Project ID proj_mock_cb338a78 · Video ID vid_mock_efd32b1b
```

### Verified live, all of it

- `create_series` → *"Series Registered Successfully"*;
- `continuity_status` then lists **both** `interesting_facts` and
  `farmer_and_rusty` from the same `continuity_ledger.db`;
- `continuity_status(series_id=…)` returns the right series for both, where it
  previously raised for both;
- the full **create → direct → generate** chain completes;
- re-running Abi's exact request answers with a real summary instead of `0`.

### The bug class is now checked, not hand-caught

`generate_episode` was found by hand. Its class — an operation calling the CLI
with arguments the CLI rejects — is now a **sixth boundary rule**,
`check_operation_argv_matches_the_cli`. It reads both sides statically (the
CLI's `add_parser`/`add_argument` setup, and the argv each operation builds), so
it needs no interpreter, no cwd and no subprocess.

Nothing else caught it: the op was registered, its handler was async, and every
declared argument was a real parameter. Only the argv was never checked.

Validated by reintroducing the original bug, which it reports as:

```
[operation-argv] flowkit\agent\operations\render.py
    generate_episode passes '--manifest' to 'generate', which does not accept it.
    Valid: --db-path, --episode, --live, --material, --mock, --output-dir,
           --series-id, --skip-video-render.
```

It stays quiet when it cannot pin an argv to exactly one known subcommand —
a check that cries wolf gets deleted.

**Worth knowing:** the publish gate is sound and already tested.
`check_allowed` requires `allow_spend` *and* an out-of-band confirm token for
`destructive`, the gate sits at the tool-invocation boundary so it cannot be
gone around, and `test_destructive_rejects_model_confirm_in_args` pins that the
model's own `{"confirm": true}` is refused. Verified rather than assumed — it
was the first thing worth checking for a pipeline that publishes publicly.

**Known, not fixed:** `shorts_content_engine/*.db` are **tracked** files, so any
agent action that creates a series or directs an episode leaves the working tree
dirty. `storage/ledger.db` is now an orphan from the old split. Both are
pre-existing repository choices rather than bugs, but a ledger of runtime state
in git will keep showing up as noise.

**Also observed, not addressed:** for a non-fiction series like
*Interesting Facts*, `direct_episode` still produced a narrative-fiction episode
(Detective Rex Vance), because the director engine writes 5-phase story arcs. And
the task manifest the model built used its own script rather than the directed
episode's. The "create series → direct → generate" chain is not yet joined up;
the model improvises it.
