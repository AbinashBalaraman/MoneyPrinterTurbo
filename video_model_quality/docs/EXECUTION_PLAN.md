# EXECUTION PLAN — proven-stack adoption

**Created:** 2026-09-11
**Source doc:** `C:\Users\SATHYA TRADERS\WorkBuddy AI\2026-09-11-12-39-30\stickman-engine-implementation.md`
**Repo:** `C:\Users\SATHYA TRADERS\Documents\Abi\Projects\video_model`

> **How to use this file.** This is the durable state of the work. If the context
> window was compacted, read this file first, then `git log --oneline -8`, then
> continue at the first unchecked step. Keep the status table at the bottom of
> each step up to date as you go.

---

## 0. Environment facts (re-verify if things fail)

| Thing | Value |
|---|---|
| Working Python | `"C:/Users/SATHYA TRADERS/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"` |
| Why not `python` | the managed 3.13 has **no numpy / no pytest** |
| pyflakes | `PYTHONPATH="C:/Users/SATHYA TRADERS/.workbuddy-ai/tools/pyflakes"` then `-m pyflakes` |
| ffmpeg | 8.1.2 on PATH (WinGet) |
| Test command | `<py> -m pytest -q`  → currently **200 passed** |
| Quality gate | `<py> tools/quality_gate.py` |
| Batch harness | `<py> tools/batch_harness.py [--render-worst N]` |
| Studio | `<py> tools/studio_server.py --open` → http://127.0.0.1:8770 |

---

## 1. Verification of the source doc

All six files it cites **do exist** (`src/contract.py`, `src/sequencer.py`,
`src/data_gen.py`, `src/rig.py`, `src/entity.py`, `src/planner.py`), and
`capabilities()` is real (`src/contract.py:200`). So the doc is grounded, not
hallucinated. Three corrections:

1. **§3.5's `(T, 32)` proposal is the wrong mechanism.** Widening `feat` from
   30→32 breaks a *locked* representation (AGENTS.md: "1p feat 30, 2p feat 60")
   and touches **7+ files** with hardcoded 30/60 splits (`renderer.py:416-419`,
   `doctor.py:112,334`, `audio.py:164-166`, `eval.py:122`, `interactions.py:84`,
   `sequencer.py`, `tools/quality_gate.py:181`, plus tools). Contact flags are a
   **derived** quantity, not independent data — a cached sidecar gives the same
   benefit for zero breakage. **We adopt the insight, not the mechanism.**

2. **§3.1's sketch calls `foot_contacts(feat)` as a free function on world-space
   feat.** In this repo `foot_contacts` is a *method on `StickmanEntity`*
   (`src/entity.py:174`) and works in **entity screen space (+y DOWN)**. Calling
   it on a world-space feat would silently use the wrong ground convention —
   exactly the bug class fixed in Phase 0. Treat the doc's code sketches as
   illustrative only (the doc says as much in its own footer).

3. **Several adopted components are solutions without a problem here.**
   See §4 for the reject/defer list and reasons.

**Where the doc and our own measurements AGREE (strong signal):** the doc's
§7 ranks *foot contact* as the #1 value-per-hour item. Our batch harness
independently ranked `foot_slide` the **dominant defect — 11 of 23 prompts**
(`out/batch/FAILURES.md`). Two independent analyses converge on the same first
move. That is what we execute first.

---

## 2. Gate and workflow changes (direct answer to "do our gates have to change?")

### 2.1 Gate changes

| # | Change | Kind | Why |
|---|---|---|---|
| G1 | **Contact sidecar becomes the single source of truth** for "is this foot planted" | **REPLACES** an ad-hoc threshold | Today three places derive contact independently: `doctor`/`visual_inspector` use `abs(y - GROUND_Y) < 0.008`, `audio.detect_footsteps` re-implements the same band, and `entity.foot_contacts` is a third (screen-space) method. Three implementations of one concept drift apart. |
| G2 | **`foot_slide` measured only while a foot is *declared* in contact** | **MODIFIES** existing hard defect | Today it fires whenever a foot is near the ground and moves. With real contact state we can say "this foot was planted and it slid", which is the actual defect. Changes the metric's meaning → must be re-baselined. |
| G3 | **Schema gate** — JSON Schema derived from `capabilities()`, checked before `validate_scene()` | **NEW, additive** | Phase A of the doc. Makes invalid LLM plans structurally impossible instead of merely caught. `validate_scene` stays as belt-and-braces. |
| G4 | **Coverage-rate gate** — % of a fixed prompt corpus that renders with zero hard defects | **NEW, additive** | Phase F of the doc. The project has no faithfulness/steering number; the batch harness already has everything needed. |

G1/G2 are **behaviour-changing** and will move the `foot_slide` counts. Re-baseline
`docs/scene_suite_results.md` and `out/batch/FAILURES.md` in the same commit as G2.

### 2.2 Workflow changes

| # | Change | Source |
|---|---|---|
| W1 | **One phase at a time. Each phase has an explicit gate. Do not start the next until the gate is green.** | doc §5, §6 |
| W2 | **Land each phase as its own reviewed commit** (not one giant commit). | doc §6 |
| W3 | **`src/contract.py` changes go through the agent bus first** (`tools/agent_bus.py`) because other agents may depend on it. | doc §6 + AGENTS.md |
| W4 | **This plan file is the durable state.** Update the status line of each step as it lands. Context compacts; the file does not. | new (necessitated by compaction) |
| W5 | Keep the existing gate stack unchanged and additive: `pytest` + `quality_gate.py` + SceneDoctor (`hard` blocks, `timing` advisory). New gates stack on top; none replace them. | our current state |

---

## 3. Steps

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

### Step 0 — Finish the in-flight studio frontend  `[x]`

The user's explicit ask: *"give a frontend so I can test the actual product."*
**Done and verified end-to-end over HTTP.**

**Deliverables**
- `src/service.py` — shared plan→compile→diagnose→render seam + `slowmo()`
- `src/audio.py` — event-driven sound (footsteps / whooshes / impacts / bed)
- `tools/batch_harness.py` — ranked failure list
- `tools/studio_server.py` — stdlib HTTP server, threaded jobs, Range support
- `studio/index.html` — the UI
- progress callbacks added to `render_stage_video` + `render_to_video`

**Verified:** `/api/health` (incl. host capabilities), `/api/plan` (digest +
report), `/api/render` (live frame progress, 11.7 s for a 2 s SD clip),
`/api/job`, `/api/clip` (200 + **206 Range**), all three variants; the blocked
path returns a report; the `allow` override renders and demotes the excused
codes to warnings; `max_frames` refuses before rendering. ffprobe confirms the
sound clip is h264+AAC @ 5.00 s and the slow-mo is 9.96 s.

---

### Step 0b — Deploy path  `[x] code complete, [!] push blocked on auth`

**Decision:** a **container** host (Render), not serverless. Measured: the render
is **11.7 s SD / 29 s HD** per 2 s clip and needs **ffmpeg** — Netlify/Vercel
functions cap at ~10 s and ship no ffmpeg. The cheap half
(`plan→compile→diagnose→digest`) is **0.05–0.2 s** and numpy-only, so it *could*
run serverless if a static presence is ever wanted.

**Deliverables**
- `Dockerfile` — python:3.11-slim + ffmpeg + numpy/Pillow
- `.dockerignore` — keeps out/, tests/, media and caches out of the image
- `render.yaml` — Render blueprint (Docker, health check `/api/health`)
- `DEPLOY.md` — plans, env vars, limits, honest cost expectations
- `studio_server.py` — reads `$PORT`/`STUDIO_HOST`/`STUDIO_OUT_DIR`/
  `STUDIO_DEFAULT_SD`/`STUDIO_MAX_FRAMES`; **render lock** (a 512 MB instance
  cannot survive two concurrent renders); capabilities advertised via
  `/api/health` and consumed by the UI
- `service.produce(max_frames=…)` — refuses before rendering

**Verified locally:** container env config (`PORT=8791`, SD default, 144-frame
cap) behaves correctly; the frame guard refuses a 136-frame clip at a 100-frame
limit and passes at 200.
**NOT verified:** the Docker build itself — **Docker is not installed on this
machine**, so the image has never been built. First Render deploy is the real
test.
**Blocked on:** `gh auth login` (gh is installed but unauthenticated, and there is
no git remote yet).

---

### Step 1 — Contact sidecar (Phase B core, ~1 day)  `[ ]`

**Goal:** one function decides foot contact; everyone else consumes it.

- [ ] `src/contacts.py` — `foot_contacts_world(feat, fps) -> (T, N, 2)` bool, in
      **world space (+y UP)**, derived from height-vs-`GROUND_Y` **and**
      horizontal velocity below a threshold (the doc's §5-B item 2). One
      documented convention; no second ground constant.
- [ ] Unit tests: rest pose → both feet planted; mid-jump → both airborne;
      determinism (same feat → identical array).
- [ ] Point `visual_inspector` / `doctor` at it (G1).
- [ ] Point `audio.detect_footsteps` at it (deletes the duplicate band).
- [ ] Point the stance/pinning solver at it.

**Gate:** `pytest` green; the three old derivations are gone; `foot_slide`
counts re-baselined in `docs/scene_suite_results.md` + `out/batch/FAILURES.md`.

---

### Step 2 — Contact-preserving solve (Phase B fix)  `[ ]`

**Goal:** actually reduce `foot_slide`, not just measure it better.

- [ ] While a foot is flagged in contact, lock its world position and let the
      root + other chains absorb the correction.
- [ ] A/B at 0.5× (the studio's slow-mo tab is the review tool).
- [ ] One action at a time; record before/after in the harness.

**Gate (doc §5-B):** `foot_slide` on a standard walk → ~0, and the whole corpus
in `out/batch/FAILURES.md` improves. Note: our harness shows `walk forward` is
*already* clean — the offenders are `walk back`, `jump`, `kick`, `squat`,
`get up`, `exchange`, and the multi-beat scenes. Target those, not just "a walk".

---

### Step 3 — Schema gate (Phase A, ~1 week)  `[ ]`

- [ ] Derive JSON Schema from `capabilities()` — actions → `enum`, object kinds
      → `enum`, required fields declared.
- [ ] Offer it to the planner backend (structured outputs / GBNF / outlines).
- [ ] Keep `validate_scene()` as the second gate; **log every time it fires** —
      each firing is a schema defect.
- [ ] **Bus first** (W3): announce the `src/contract.py` change.

**Gate (doc §5-A):** 0 invalid actions across a 200-prompt run; zero
`ContractError`s.

---

### Step 4 — Coverage rate (Phase F, continuous)  `[ ]`

- [ ] Add `--coverage` to `tools/batch_harness.py`: emit one headline number =
      % of corpus with zero hard defects.
- [ ] Add the doc's §3.1 trajectory features (root deltas at 0.25/0.5/0.75/1.0 s
      + contact flags) as an **evaluation** feature — we can use the design
      without a motion-matching database.
- [ ] Adopt the R-Precision *concept*: does the clip match the prompt?

**Gate:** a tracked coverage number in the harness output, printed on every run.

---

### Step 5+ — Deferred (do not start until 1–4 are green)  `[ ]`

`FABRIK` · `Motion Matching` · `VQ-VAE tokeniser` · `ControlNet style mode`.
See §4 for the trigger condition on each.

---

## 4. Rejected / deferred, with reasons

| Item | Decision | Reason |
|---|---|---|
| **FABRIK** | **REJECT** | We have an exact, deterministic analytical two-bone IK. FABRIK is iterative and only pays off on >2-bone chains — we have none. A solution without a problem. |
| **pymunk / Box2D physics** | **REJECT** | Our motion is *authored* (keyframes + easing + IK), and the strategy is "learn movement, code appearance". A physics engine fights the determinism constraint and adds a dependency for no requested capability. |
| **Cairo / Skia renderer swap** | **DEFER** | We have a working deterministic 1280×720 PIL stage renderer. No quality mandate exists. Trigger: a concrete rendering defect we cannot fix in PIL. |
| **Motion Matching (§3.1)** | **DEFER** | Its bottleneck is a motion *database*; we have 17 hand-authored actions. Steal its **feature-vector design** for eval (Step 4), revisit the search once harvesting (doc §3.2) has produced volume. |
| **VQ-VAE tokeniser (§3.4)** | **DEFER** | The doc says so itself: *"a tokenizer trained on mediocre motion reproduces mediocre motion."* Trigger: Steps 1–2 land and motion looks good. |
| **ControlNet style mode (§3.3)** | **DEFER** | Stochastic + GPU-bound → violates two hard constraints. Only ever an optional, clearly-labelled, cached, non-reproducible path. |
| **Pose harvesting (§3.2)** | **LATER, offline** | Genuinely useful for growing the vocabulary, and our metrics become the data filter. Not a gate change; not on the critical path. Licensing: only harvest footage we may use. |
| **`feat` → `(T, 32)`** | **REJECT the mechanism** | Breaks a locked representation and 7+ call sites; contact is derived data. Use the sidecar (Step 1). |

---

## 5. Repo state (updated after Step 0b)

**Branches:** `master` and `render` both at **`8f057e3`** — the deploy branch is
cut from master and is identical for now; future deploy-specific tweaks go on
`render`. No git remote yet (needs `gh auth login`).

**Landed in `8f057e3`:**

| File | Change |
|---|---|
| `src/doctor.py` | three-tier severity `hard`/`timing`/`warn`; `strict_timing` switch; uniform `allow` demotion; **auto-camera fix** (gate now judges the camera the renderer actually uses — cleared 3 false `actor_off_frame` positives) |
| `src/service.py` | **new** — shared plan→compile→diagnose→render seam, `slowmo()`, `max_frames` guard, progress callbacks |
| `src/audio.py` | **new** — derived soundtrack (footsteps/whooshes/impacts/bed) |
| `tools/batch_harness.py` | **new** — ranked failure list + `FAILURES.md` |
| `tools/studio_server.py` | **new** — studio API; env-driven, render lock, Range support |
| `studio/index.html` | **new** — the UI |
| `Dockerfile`, `.dockerignore`, `render.yaml`, `DEPLOY.md` | **new** — container deploy |
| `tools/prompt_to_video.py` | `--strict-timing` flag, timing-debt banner |
| `src/renderer.py`, `src/stage_renderer.py` | `progress_cb` on both render paths |
| `src/motion_quality.py` | **new** — linear-easing + anticipation checks |
| `src/puppet/armature.py` | sum-conserving hold-preserving velocity limiter |
| `tests/test_doctor.py` | +6 tests (severity tiers) |
| `tests/test_puppet_armature.py` | +6 tests (limiter) |
| `tests/test_audio.py`, `tests/test_service.py` | **new** — +22 tests |

**Baseline:** **222 tests pass**; pyflakes clean on all touched modules.

**Known measurement findings (do not re-derive):**
1. Every action's peak limb speed sits within **1.0–1.7× its own p90** — the
   motion has no fast-strike/slow-windup contrast. This is why a speed threshold
   cannot drive whooshes, and it *is* the Phase-2 timing problem.
2. `foot_slide` is the dominant defect (11/23 prompts).
3. Cadence stepping (animation on twos) roughly doubles instantaneous angular
   velocity — it corrupts naive velocity analysis.
4. Render cost: **11.7 s** for a 2 s SD clip, **29 s** for HD. Cheap half
   (`plan`+`diagnose`) is **0.05–0.2 s**. This is the serverless/container
   dividing line.

**Open questions:**
- Is `visual_inspector`'s `stance_tolerance = 0.010` the right plant threshold,
  or should it be derived from contact state? (Step 1 decides.)
- `foot_slide` on `squat` is suspicious — feet should be planted throughout.
  Worth a dedicated look in Step 2.
- `dead_hold` fires as "Actor 1 freezes for 120 frames (5.00s)" on multi-beat
  scenes where only actor 0 acts. That may be correct-but-unhelpful staging
  rather than a defect — worth reclassifying.
