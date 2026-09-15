# PLAN — General "any scene" stickman pipeline

**Author:** 4.1 Agent (planner) · **Date:** 2026-09-11
**Status:** handoff / continuation plan. Read this first after a context reset.

---

## 1. The actual goal (do not lose this)

The project must accept **any scene** — a movie moment, a short-form idea, a full
script — and produce a correct stickman video through **one general pipeline**.

> The 30s "Courtyard Duel" was only the sample that exposed general defects.
> Do NOT patch that one video. Fix the **engine's general capabilities** so the
> next, different scene also works.

Locked scope for "any scene" (user decisions):

1. **N actors (1–4)** that can **interact / aim at each other** (not soloists).
2. **Objects / props** with lifecycle (place, hold, throw, pickup, drop, impact).
3. **Camera / staging** that keeps subjects framed and un-occluded.
4. **Environments / sets** per scene (declarative background parts).
5. **Time / editing** — multi-shot sequencing (cut between shots/angles).

**Review gate:** every compile runs a doctor; **hard defects BLOCK the mp4**
until fixed. Warnings are shown but do not block.

**First work item:** general interaction + SceneDoctor, then a multi-scene proof.

---

## 2. Architecture (locked)

```
any input (text / script / scene JSON)
  │  planner (src/planner.py — BYO LLM backend; NoOp / Callable / Deterministic)
  ▼
SceneScript JSON                declared + validated by src/contract.py
  │  validate_scene()           fail-fast: unknown action/object/joint -> reject
  ▼
compile_scene()                 src/scene.py (deterministic)
  │   shots   -> segments       (time/editing)
  │   beats   -> puppets        (sequencer + choreography)
  │   target  -> interaction    src/interactions.py  (NEW: aim, sync impact, react)
  │   objects -> prop tracks    src/objects.py
  │   camera  -> cam track      src/camera.py
  ▼
SceneDoctor                     src/doctor.py  (NEW: general defect checks)
  │  hard defects => BLOCK; warnings => show
  ▼
review (src/preview.py)  -> text digest + playable animation   [ALWAYS]
  ▼
renderer (512 SD / 1280x720 HD) -> ffmpeg -> video
```

**Golden rules**
- Only `src/contract.py` defines what is expressible. The LLM targets
  `capabilities()`; `validate_scene()` is the gate.
- The engine never invents semantics; it executes a validated plan.
- Every compile is reviewed; hard defects block render.

---

## 3. Current state (what already exists — verified)

### Committed and working
- `src/contract.py` — capability registry (objects/joints/themes/camera) +
  `validate_scene()` fail-fast gate. **Frozen interface; change only with care.**
- `src/planner.py` — `PlannerBackend`, `NoOpPlanner`, `CallablePlanner` (BYO LLM
  seam), `DeterministicPlanner`, `plan_scene()`, `llm_system_prompt()`,
  `parse_scene_json()` (handles ``` fences).
- `src/objects.py` — deterministic object runtime -> per-frame props. Supports
  spawn/despawn, place, attach, throw+bounce (settles; no energy pump), pickup,
  drop, collision impacts. `evaluate_objects(objects, joints, fps, T)`.
- `src/camera.py` — `compute_camera(joints, spec)` ->
  `{camera_x, zoom, mode}`; modes static/auto/follow/close/wide/pan.
- `src/scene.py` — `SceneScript`, `compile_scene()`, `compile_scene_dict()`;
  wires objects + camera + impacts. **Currently compiles each actor's beats
  INDEPENDENTLY — this is the core defect that makes fights into soloists.**
- `src/preview.py` — pre-render review. `interaction_stats()` (min inter-actor
  joint distance + contact ratio; flags "two solo actors"), `motion_stats()`,
  `image_to_text()` (half-block/braille/ascii, auto-crop),
  `render_timeline_preview()` -> digest + full animation file.
- `src/stage/terminal_preview.py` — skeleton ASCII renderer; now accepts
  `x_bounds` (tight framing) and `actor_labels` (A/B).
- `src/mcp_server.py` — tools: list_actions, parse_text_prompt,
  render_prompt_clip, render_action, sequence_timeline, preview_stage_ascii,
  render_stage_script, **get_capabilities, validate_scene, render_scene**.
- `tools/prompt_to_video.py` — CLI. `--scene <json>` (LLM plan) or prompt;
  **`--review`** prints the text digest and STOPS before rendering;
  `--review-mode/cols/sample/full`.

### Verification commands
```
python -m pytest tests/ -q            # 163 passed (current)
python -m src.eval                    # 100/100 det/diversity/rejection True
python tools/audit_16_scenes.py       # avg 94.8 (strip ANSI)
python tools/prompt_to_video.py --scene out/scene_30s.json --review
```

### Existing building blocks to REUSE (other agents built these)
- `src/entity.py` — `StickmanEntity`, `solve_reach(...)`, `CAPSULE_R`,
  `ANCHORS`, `LIMITS`, `MASS`, joint `NAMES/INDEX`. Body/physics side.
- `src/puppet/director.py` — fluent `Director`:
  `locomote(speed,duration_s)`, `hold()`, `gesture(action,at,dur)`,
  `strike(action,at,dur)`, `strike_at(target_xy, end_joint)`, `compile()`.
- `src/puppet/controllers.py` — `LocomotionController`, `GaitCommand`,
  `layer_timelines`, `UPPER_BODY_BONES` (split-body layering: legs=locomotion,
  upper body=gesture).
- `src/puppet/combat_ik.py` — `solve_aimed_limb` (aimed strikes).
- `src/puppet/choreography.py` — `build_motion_from_action`,
  `build_combat_pair` (SYNCHRONIZED pair combat with impact alignment — the
  reference for how interaction SHOULD be compiled).
- `src/visual_inspector.py` — jerk/floor/dead-hold/foot-slide metrics.

---

## 4. The core defect to fix (general interaction)

**Symptom:** in any multi-actor scene, actors run their own beat lists and never
engage. Verified by `interaction_stats`: 30s duel -> A0 root range [-0.45, 5.06],
A1 [0.19, 1.96], contact ratio 0.11 -> "two solo actors".

**Root cause:** `compile_scene()` (src/scene.py) loops beats, appends each to its
actor's `ActorTrack`, then `PuppetSequencer.build()` pads + concatenates tracks.
There is no cross-actor coordination, no targeting, no reaction.

**Fix design (general, not duel-specific):**
1. **Schema (src/contract.py):** a beat may carry
   - `target`: actor id (who is being interacted with), and
   - `interaction`: one of {strike, block, dodge, grab, knockdown, assist, talk}
   (optional; absent = solo beat).
   Add `shots[]` for time/editing (§6). Keep backward compatibility (old scenes
   without these still validate).
2. **New module `src/interactions.py`:**
   - `resolve_interactions(beats, actors)` -> for each targeted beat, compute the
     impact time and produce a paired, synchronized beat for the target actor
     (reaction), mirroring how `build_combat_pair` aligns frames.
   - `stage_for_interaction(actors, beat)` -> place the two actors within
     striking range (e.g. gap ~0.45–0.6 world units) at the beat's start, using a
     deterministic offset, so the strike can physically connect.
   - Reuse `Director.strike_at(target_xy)` + `solve_aimed_limb` so the limb
     actually aims at the target joint, and emit `impact_burst` at the contact
     frame.
   - Reaction table: strike->block|dodge|knockdown; kick->dodge; etc.
3. **compile_scene:** for beats with `target`, compile the two actors together
   for that segment (synced), not independently. Preserve root handoff between
   segments per actor. Keep the pure-solo path unchanged.

**Acceptance:** a scene with `{actor:a, action:punch, target:b, interaction:strike}`
yields `interaction_stats(...).interacting == True` (contact ratio > 0.20) and an
`impact_burst` at the contact frame.

---

## 5. SceneDoctor (general review gate) — NEW `src/doctor.py`

`diagnose(timeline, scene) -> report` where report = {hard: [...], warn: [...],
metrics: {...}}. Runs on EVERY compile. Hard defects block render.

**HARD (block):**
- `actor_off_frame` — any actor's x-bbox outside the camera viewport for > N frames.
- `ground_penetration` — any joint below `GROUND_Y` beyond a small epsilon.
- `targeted_interaction_absent` — a beat declares `target` but
  `interaction_stats.contact_ratio` for that pair is ~0.
- `object_never_lives` — declared object never appears in `prop_tracks`
  (or attached prop never tracks its joint).
- `numeric_instability` — NaN/Inf in feat/joints/camera.

**WARN:**
- `occlusion` — actor x-overlaps a scenery prop (e.g. colonnade column).
- `dead_hold` / `foot_slide` / `jerk_spike` — reuse `src/visual_inspector.py`.
- `camera_jump` — camera_x frame delta above threshold.
- `empty_frame` — no actor and no object visible for a stretch.

Wire into `prompt_to_video.py`: always run doctor; if `hard`, print report and
exit non-zero WITHOUT rendering (unless `--force`). `src/preview.py` prints the
doctor report at the top of the digest.

**Acceptance:** the 30s duel reports `targeted_interaction_absent` (or, for a
properly-authored fight, passes hard checks); a broken camera scene reports
`actor_off_frame`.

---

## 6. Environments / sets + time / editing

- **Sets:** `scenery` already supports plain/perspective_hall/spline_web/
  split_screen_3. Generalise to `scenery.props` (declarative background parts:
  columns, trees, rubble, cage) with world positions, and make the renderer draw
  them behind actors (z-order) and **grounded** (bases at GROUND_Y). Fix the
  "pillars float + occlude actors" finding from Gemini.
- **Shots (time/editing):** add `shots: [{id, duration_s, scenery, camera,
  actors:[ids], beats:[...]}]`. `compile_scene` compiles each shot then
  concatenates with optional transitions (cut/hard by default). Per-shot camera.
  Keep beats-at-root as a single implicit shot for backward compatibility.

---

## 7. Camera / staging generality (Gemini's verified findings)

- Camera `auto`/`follow` must keep **all active actors** in frame: bind to the
  actors' centroid and **expand the viewport/zoom** so no actor leaves the
  envelope. (Currently camera loses actors ~s8–15.)
- **Staging:** do not place actors on the colonnade's x-coordinates
  (±1.2) — the columns occlude them. Auto-place into the clear central corridor,
  and/or render scenery behind actors.
- Ground the columns (extend geometry to ground_y).
- Add doctor checks: `actor_off_frame`, `occlusion`.

---

## 8. Multi-scene proof (definition of done for this phase)

Author 4–6 **different** scene JSONs under `out/scenes/` and run each through:
`validate -> compile -> doctor -> review`. All must pass hard checks; render at
least 3 to mp4. Suggested set:
1. **Solo** — 1 actor: walk → wave → idle (object: none).
2. **Duel** — 2 actors, targeted strikes/blocks/dodges (interaction).
3. **Object play** — pickup sword, throw ball, bounce, confetti.
4. **Crowd** — 3–4 actors, some interacting, some idling; crowd prop.
5. **Multi-shot** — 2 shots with different camera/scenery (time/editing).
6. **Environment** — perspective_hall, actors clear of columns, camera keeps all
   in frame.

Deliverable: a table of scene × doctor verdict + rendered files. This is the
"proof it generalises" artifact.

---

## 9. Task breakdown (ordered)

**T1. Contract schema additions** (`src/contract.py`)
- beat: `target`, `interaction` (enum); actor: optional `role`; scene: `shots[]`
  with per-shot `scenery`/`camera`/`beats`. Back-compat + tests.
- Extend `capabilities()`/`SCENE_SCHEMA`.

**T2. Interaction engine** (`src/interactions.py`, new)
- `resolve_interactions`, `stage_for_interaction`; sync impact frames; reactions.
- Reuse `Director.strike_at` + `solve_aimed_limb` + `build_combat_pair` patterns.

**T3. compile_scene integration** (`src/scene.py`)
- Compile targeted beats jointly; per-actor root handoff; shots concatenation.

**T4. SceneDoctor** (`src/doctor.py`, new) + wire into CLI/preview; block on hard.

**T5. Staging + camera generality** (`src/scene.py`, `src/camera.py`,
`src/stage_renderer.py`) — framing all actors, grounding columns, z-order.

**T6. Multi-scene proof** (`out/scenes/*.json`, a `tools/scene_suite.py` runner).

**T7. Docs/tests** — update GOAL/GATES; pytest for every new module.

---

## 10. Conventions, gotchas, environment

- **Platform:** Windows, PowerShell (no `&&`). Console is cp1252 — when printing
  unicode (braille/half-block) write to a UTF-8 file and read it, or
  `.encode("ascii","replace")`.
- **Repo had a broken HEAD once** (`47391bf` called an uncommitted
  `parser.match_actions`). Before assuming, `git status` + run pytest. A dead
  agent left inconsistent uncommitted edits; restored via `git checkout HEAD --`.
- **Never delete/disable working actions.** Fix root causes.
- **Determinism is a hard requirement:** same plan -> identical feat/props/camera.
- **Frames:** 24 fps; 5s = 120 frames; ground `GROUND_Y = -0.42`; feat `(T,30)`
  per actor (root xy + 14 sin/cos), pair `(T,60)`.
- **Joints:** 0 root, 1 spine, 2 chest, 3 neck, 4 head, 5/6 L elbow/hand,
  7/8 R elbow/hand, 9/10/11 L knee/ankle/foot, 12/13/14 R knee/ankle/foot.
- **Verification gates each step:** pytest green, eval 100/100, audit not
  regressed, doctor passes, and `--review` digest looks right **before** render.

## 11. Agent coordination (optional)
- herdr panes: **w1:p1** opencode (provider session once expired — unreliable),
  **w1:p2** pi (objects/body), **w1:p4** agy/Gemini (visual reviewer; sometimes
  "out of credits"), **w1:p6** this planner.
- Bus: `conversation.md`; CLI `python tools/agent_bus.py [status|check|send|...]`.
- Visual inspection: Gemini is the authority (this model has NO image input).
  Read its pane with `herdr agent read w1:p4 --source recent-unwrapped --lines 40`.
- Collision rule: each agent edits only its owned files; shared files via planner.

## 12. Immediate next action after reset
1. `git log --oneline -5` + `python -m pytest tests/ -q` (confirm 163 passed).
2. Start **T1** (contract schema) then **T2** (interactions), with tests.
3. Prove with a targeted duel: `--review` must show `interacting=True`.
4. Then **T4** (doctor) and **T6** (multi-scene proof).
