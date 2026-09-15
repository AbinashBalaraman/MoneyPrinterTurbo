# Project Map, Audit & Test Log — living document

**Owner:** 4.1 Agent (Head, Herdr pane `w1:p6`)
**Last updated:** 2026-09-10
**Purpose:** Durable single source of truth. Read this first; it should save you from
re-reading the whole repo. Update it when structure, defects, or verification change.

---

## 1. Project mandate (do not violate)

- **2D stickman animation platform, platform-first, video second.** Neural nets would
  predict skeleton motion only — never pixels. Renderer, bone lengths, camera, background
  are **code, not learned**.
- Deterministic procedural motion. **No pixel/latent diffusion** for v1.
- **Never delete/disable a broken action — fix the root cause** (project charter).
- Ground plane `WORLD_GROUND_Y = -0.42`; character height ≈ 1.0 world unit.
- 24 fps (`FPS = 24`). 15-joint legacy rig (`src/rig.py`), 17-joint entity (`src/entity.py`).

## 2. Coordination & roles

- **Head: 4.1 Agent** = pane `w1:p6` (this session).
- Team panes: **OC2** `w1:p1`, **Pi** `w1:p2`, **Gemini Lead** `w1:p4`.
- **Herdr-direct only. No agent-bus posting.** `conversation.md` is read-only context.
- Dispatch policy: **own subagents first; Gemini handles visual inspection; OC2/Pi last.**
- **This model has NO vision** (verified via `read` on a PNG → "does not support image input").
  Gemini is the visual authority. `read` on images will always fail here.

### Herdr command cheatsheet
```powershell
herdr agent list                                   # roster + status + pane_id
herdr agent prompt <paneID> "<message>"            # send text+Enter (PRIMARY)
herdr agent read   <paneID> --source recent-unwrapped --lines 40
herdr agent send-keys <paneID> <key>               # keys only (enter/esc/ctrl+c)
```
Use pane IDs (`w1:p2`), never bare kind names (`pi`/`opencode` → `agent_not_found`).

## 3. Repository map

### `src/` (engine)
| Path | Lines | Purpose |
|------|------:|---------|
| `rig.py` | ~91 | 15-joint rig, 14 bones, `encode/decode` (sin/cos), `forward_kinematics`, `GROUND_Y`, **`enforce_ground_contact`** (new) |
| `entity.py` | 215 | **17-joint entity**: hierarchy, `LIMITS`, `MASS`/CoM, `CAPSULE_R`, `ANCHORS`, deterministic **DLS `solve_reach`**, `balance_correction`, `foot_contacts` |
| `renderer.py` | 503 | 512 renderer: `StickmanRenderer`, camera track, **VFX** (`impact_burst`, `speed_lines`, dust), joint props, `apply_contact_correction`, `apply_camera_impulses`, `render_to_video` |
| `stage_renderer.py` | 417 | HD 720p `StageRendererHD` + `render_stage_video`; reuses renderer helpers |
| `sequencer.py` | ~210 | `blend_feature_clips`, `ActorTrack`/`PuppetSequencer` (timeline VFX shift), `sequence_prompts` |
| `parser.py` | 156 | keyword prompt → `{action,direction,speed,duration_seconds,amplitude,seed}` |
| `catalog.py` | 227 | action registry (1P + 2P) |
| `data_gen.py` | 160 | **legacy** `gen_single` / `gen_pair` (sine primitives) — still referenced by `eval.py` fallback + determinism check |
| `eval.py` | 237 | 100-prompt benchmark + determinism/diversity/rejection |
| `visual_inspector.py` | ~250 | quality auditor (floor/jerk/slide/dead-hold/capsules) + `remediate_motion` + filmstrip |
| `mcp_server.py` | 319 | MCP tool surface (render_prompt_clip, render_action, sequence_timeline) |
| `video_encode.py` | 43 | ffmpeg writer helpers |
| `model.py` / `train.py` / `onnx_runner.py` | 161/213/77 | neural track — **orphaned** (only `train.py` imports `model.py`; not needed for v1) |
| `stage/` | — | `dsl.py` (StageScript/compile), `theme.py`, `props.py`, `panels.py`, `perspective.py`, `text_overlay.py`, `terminal_preview.py` |

### `src/puppet/` (motion brain)
| Path | Lines | Purpose |
|------|------:|---------|
| `choreography.py` | ~776 | action→timeline builders (`create_*_sequence`), `build_motion_from_action`, `build_combat_pair`, `PuppetChoreographer`, `get_combat_props` |
| `armature.py` | 387 | `ArmatureTimeline.compile` (keyframes, easing, moving hold, **two-bone IK stance pinning**) |
| `pose.py` | 412 | `POSES` library + `get_pose_angles`/`get_pose_root_y`, `stance_anchor` |
| `easing.py` | 84 | easing functions incl. `snap_and_settle`, `moving_hold` |
| `controllers.py` | 142 | parametric locomotion (signed gait), lean, split-body layering |
| `director.py` | 150 | fluent `Director` API (locomote, strike_at, …) |
| `combat_ik.py` | 319 | `capsule_matrix`/`capsule_contacts`, `HitTracker` (edge-triggered), strike/recoil tiers |

### `tools/` (drivers)
`render_scene_suite.py` (16 scenes + `_build`, `_run_and_leap`, `_narrative_martial_artist`),
`audit_16_scenes.py` (visual audit runner), `render_*` (showcase/cinematic/narrative/foundations/jump),
`demo_combat_arena.py`, `prompt_to_video.py`, `play_terminal_ascii.py`,
plus **legacy/agent-infra**: `agent_bus.py`, `convo_watcher.py`, `check_convo.py`, `auto_responder.py`, `wait_for_message.py`, `inspect_opencode_history.py`.

### `tests/` (56 tests, all green)
`test_engine.py` (11), `test_entity.py` (7), `test_puppet_armature.py` (13),
`test_controllers.py` (7), `test_combat_ik.py` (9), `test_dsl.py` (4), `test_visual_inspector.py` (4).

### `docs/`
`hardening_plan.md` (audit workstreams + visual baseline table), `rfc_entity_dls_ik.md`,
`implementation_plan.md`, `gemini_system_prompt.md`, `cinematic_60s_report.md`, **this file**.

### `out/` (artifacts — mostly untracked)
`inspect_scenes/`, `cinematic_stills/`, `inspections/`, `scenes/`, `f3check/`,
plus my probes: **`probe_defects.py`**, **`probe_jerk.py`**, `audit_fixes/` (if present).

## 4. Verification commands (the standard gate)

```powershell
python -m pytest tests/ -q                                   # expect: 56 passed
python -m src.eval                                           # expect: 100/100, determinism True
python tools/audit_16_scenes.py                              # visual quality table
python tools/render_scene_suite.py                           # renders out/scenes + stills
python out/probe_defects.py                                  # joint/frame penetration + jerk probe
python out/probe_jerk.py                                     # wrap-vs-real jerk check
```
Strip ANSI when capturing audit output:
`... | ForEach-Object { $_ -replace "\x1b\[[0-9;]*m","" }`

## 5. Confirmed findings (audit, 2026-09-10)

### 5.1 FALSE POSITIVE — "P0 angular jerk explosion" (3,619 rad/s²)
`decode()` returns `arctan2` angles in (−π, π]. The auditor diffed them raw, so crossings
at the ±π branch cut fabricate huge derivatives. Example `jump` upperArmL: −3.01 → +2.67
= fake **+5.68 rad** (true −0.60). After `np.unwrap`: **3619 → 410** (below the 450 limit).
**Fixed:** `src/visual_inspector.py` now unwraps in `audit_motion` (jerk + dead-hold) and
in `remediate_motion`. Residual >450 spikes are **real** (e.g. punch lowerLeg 670).

### 5.2 Ground penetration (was the dominant score killer)
Raw builder output dropped joints below `-0.42` (toeR −0.61 in jump/run_and_leap; ankleR in
slide/distress). Both existing fixes (`apply_contact_correction`, `remediate_motion`) run
**downstream of the audit**, so the audit measured raw output.
**Fixed:** author-time `enforce_ground_contact` (angles preserved; root lifted by per-frame
penetration) applied in `PuppetChoreographer.compile`, `ArmatureTimeline`-users via
`build_combat_pair`, and `sequencer.ActorTrack.compile`.

### 5.3 Dead-hold collapse (largest remaining defect) — FIXED
Frozen frames >0.35s: narrative **77**, sword_duel **56**, distress 29, punch 24, kick 23,
punch_block 19, kick_dodge 18, knockdown 17, slide 11. Two root causes:
1. `moving_hold` was a half-sine **normalized over the whole hold**, so long holds became
   near-static. Replaced with continuous 1.2 Hz `hold_breath` (ramp-in) in `armature.py`
   hold + tail paths.
2. `ch.hold()`/`wait()` appends a **same-pose keyframe at the tail**, compiled as a
   zero-difference *transition* (not a hold), so it never got breathing. `armature.py`
   transition path now detects zero-diff segments >0.35s and applies breathing.
3. sword_clash Person B had **no recovery keyframe** after its hit-stop → frozen remainder.
   Added recovery to `stand_relaxed` in `build_combat_pair`.
4. `hold_breath` amplitude 0.035 rad at 1.2 Hz clears the `1e-4` energy threshold.

### 5.4 Foot sliding — REFRAMED & metric fixed
The auditor counted slides on toes (11/14) too. The **IK-pinned ankles (10/13) have zero
drift**; the toe is an articulated foot-roll pivot (heel→ball→toe legitimately travels).
Auditor now measures ankles only. Residual ankle slides are **transition artefacts** where
`blend_feature_clips` interpolates a planted foot (narrative 78, slide 83.5). **Open (minor).**

### 5.5 Real jerk spikes (post-unwrap)
Genuine reversals >450: punch lowerLeg 670, exchange/knockdown/sword spine 600–690.
These are real (fast direction changes), lower severity. **Open.**

### 5.6 Structural notes
- `eval.py` still catches exceptions and falls back to legacy `data_gen.gen_single/gen_pair`
  (TASK-001 removed this elsewhere) — masks puppet failures; the determinism check deliberately
  uses `gen_single`. **Open (decide: intentional vs. fail-fast).**
- `renderer.py` / `stage_renderer.py` duplicate prop/VFX/camera logic; `stage_renderer` already
  imports several helpers from `renderer` — divergence risk. **Watch.**
- Orphaned: `model.py`, `train.py`, `onnx_runner.py`, `generate_goal_demos.py`, `render_showcase.py`.
- `except Exception: proc.kill(); raise` occurrences are correct (no silent swallow).

## 6. Changes applied (this hardening pass, uncommitted)

| File | Change |
|------|--------|
| `src/rig.py` | `+GROUND_Y`, `+enforce_ground_contact(feat)` (angles preserved, root lifted; rank-preserving) |
| `src/puppet/easing.py` | `+hold_breath(t_sec)` — continuous 1.2 Hz ramp-in breathing (moving_hold unchanged) |
| `src/puppet/armature.py` | hold + tail paths use `hold_breath`; transition path breathes zero-diff segments >0.35s |
| `src/puppet/choreography.py` | `PuppetChoreographer.compile` + `build_combat_pair` pass `enforce_ground_contact`; sword_clash B recovery keyframe |
| `src/sequencer.py` | `ActorTrack.compile` outputs pass `enforce_ground_contact` |
| `src/visual_inspector.py` | `np.unwrap` angles before jerk/dead-hold (audit + remediate); foot-slide measured at ankles (10/13) only |
| `docs/hardening_plan.md`, `docs/HEAD_STATE.md` | this record |
| `out/probe_defects.py`, `probe_jerk.py`, `probe_holds.py`, `probe_slide.py` | diagnostics (keep) |

### Before / after (audit avg)
| Metric | Before | After |
|--------|-------:|------:|
| Suite average | 76.0 | **94.8** |
| Perfect scenes (100) | 1 | **4** (walk_forward, combat_kick, kick_dodge, celebrate) |
| narrative | 53.0 | **78.0** |
| acrobatic_slide | 67.2 | **83.5** |
| jump_acrobatic | 61.0 | **97.0** |
| run_and_leap | 48.5 | **95.0** |
| combat_pair_exchange | 87.0 | **99.0** |
| combat_pair_sword_duel | 71.4 | **95.0** |
| expressive_distress | 65.4 | **98.5** |
| pytest | 56/56 | **56/56** |
| eval | 100/100 | **100/100** (det/diversity/rejection: True) |

## 7. Open work / next steps
1. **Composite foot-slide** (minor, narrative 78 / slide 83.5): planted contact drifts during
   `blend_feature_clips` transitions — re-pin the stance foot across blend seams.
2. **Real jerk spikes** (P1): soften genuine reversals (punch lowerLeg 670; spine 600–690 in
   combat/exchange/sword) via smoother interpolation.
3. Decide `eval.py` legacy `gen_single/gen_pair` fallback (fail-fast vs. intentional).
4. Re-render suite → hand stills to **Gemini** for the visual verdict, then commit.

### Attempted and reverted (do not repeat)
- **Acceleration-capped rate limiter** in `armature.py`: capping per-frame Δvelocity set
  `max_angular_accel=4` rad/s², which is far below natural motion (a 0.60 rad/frame step is
  14 400 rad/s²). The cap clamped everything → audit crashed to 85, 3 tests failed. Reverted.
  (The limiter is **not** the source of the 691 spikes: disabling it entirely left jerk unchanged.)
- **Short-transition `snap_and_settle` → `ease_in_out` swap** (`trans_duration < 0.20`):
  broke `test_13_hit_stop_freeze_zero_shimmer` and did not reduce the spike. Reverted.
- **Restoring IK-pinned angles after the limiter**: bound to the accel-cap experiment; never
  isolated. Abandoned with the revert.

### Jerk-spike true root cause (analysis)
The residual 600–690 rad/s² spikes are **not** the rate limiter. They are real one-frame
velocity reversals from sampled poses (e.g. punch lowerLeg: −0.56 then +0.60 rad/frame).
Ideas not yet tried safely: smoother intermediate keyframes at the reversal, or a
slope-limited *post-hoc* filter (moves planted feet — needs re-pin).

## 8. Gotchas / tribal knowledge
- Angle wrap (±π) will fake jerk — **always unwrap before differentiating**.
- Ground pass is intentionally **at author time** (builder/sequencer) so the audit sees valid
  motion; a later stage-1 fix had to be moved after realizing probes still showed raw dives.
- `enforce_ground_contact` preserves joint angles ⇒ two-bone IK pinning/`<1e-6` drift is untouched.
- Feature layout is fixed: `(T,30)` = root xy(2) + 14×(sin,cos). `decode` **normalizes** sin/cos pairs.
- Pair features are `(T,60)` = A(30) ‖ B(30); `audit_combat_pair` splits at 30.
- Rig joint indices (legacy 15): 10/11 = L ankle/toe, 13/14 = R ankle/toe; 6/8 = hands; root=0.
- `snap_and_settle` / `moving_hold` override normal interpolation — check `armature.py` before
  changing holds.
