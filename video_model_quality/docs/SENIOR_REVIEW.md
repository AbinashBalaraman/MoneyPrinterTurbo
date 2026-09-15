# Senior Developer Review — Stickman Video Model

**Reviewer:** Senior Developer (external audit)
**Date:** 2026-09-11
**Scope:** full repository — `src/` (41 modules), `tools/`, `tests/`, docs, git history
**HEAD at review:** `5d6e1ef` → `0259381` *(a commit landed mid-review — see Finding 12)*
**Method:** source read-through, import-graph reachability analysis, AST dead-code scan,
pyflakes static analysis, full test + eval run, contract/invariant probing, git archaeology

---

## 1. Verdict

> **The project is on the correct path — technically and literally — and the engineering
> core is genuinely strong. The risk is not correctness, it is *coherence*: five
> overlapping ways to author motion, two renderers, and contract knowledge duplicated
> across modules. Fix coherence and this is a well-built system.**

| Dimension | Grade | Note |
|---|---|---|
| Architecture direction | **A−** | Correct, principled, and honest about scope. Matches the stated goal. |
| Core engine quality | **A−** | 188 tests green, 100/100 eval, zero ground penetration, deterministic. |
| API coherence | **C+** | 5 motion-authoring front doors, 2 renderers, duplicated contract. |
| Contract enforcement | **C** (was) → **B+** (now) | One silent-wrong-mapping hole; now closed. |
| Code hygiene | **C** | 180 lint warnings, 19 lines dead code, repo bloat, no README, no gate. |
| Operational safety | **D** | **No git remote — zero off-machine backup.** |
| Documentation | **C+** | Excellent docs volume, but `AGENTS.md` contradicts `GOAL.md`. |

**One-line summary:** a high-velocity, well-tested, correctly-aimed system that has
outgrown its own structure and needs a consolidation pass, not a rewrite.

---

## 2. What this project actually is

A **tiny-deployment text→stickman-video engine**. The non-negotiable strategy is
**"learn movement, code appearance"**:

- The engine animates only a **2D skeleton** — 15 joints, 14 bones, 30 features/frame
  (`root_xy` + 14 × sin/cos angle pairs).
- **Renderer, bone lengths, camera, background are code, not learned.**
- Inference runs on a laptop (i3-6006U, 8 GB, HD520, no CUDA). Training, if ever
  needed, is offloaded to cloud GPU.
- No pixel/latent diffusion. No 2B LoRA. No N-person single-pass generation.

The world model is split deliberately:

> **The LLM owns the *world*. The engine owns *execution*.**
> A planner emits declarative `SceneScript` JSON; the engine validates it and
> executes it deterministically. **No planner ever emits joint angles or raw motion.**

This is a sound, defensible architecture — and critically, it is the *right* one for
the hardware constraint. The project did not drift into the standard trap
(trying to diffuse pixels on a laptop).

---

## 3. Core function breakout

### 3.1 The live pipeline (verified by tracing imports from the entry points)

```
                       ┌──────────────────────────────────────────────┐
  text prompt ────────►│ parser.py      keyword/synonym → controls    │
                       │ planner.py     PlannerBackend seam (BYO LLM) │
                       └───────────────────┬──────────────────────────┘
                                           ▼
                       ┌──────────────────────────────────────────────┐
                       │ contract.py    validate_scene()  fail-fast   │
                       └───────────────────┬──────────────────────────┘
                                           ▼  SceneScript JSON
                       ┌──────────────────────────────────────────────┐
                       │ scene.py       compile_scene()  DETERMINISTIC│
                       │  ├─ beats   → sequencer / choreography       │
                       │  ├─ objects → objects.py   (prop tracks)     │
                       │  └─ camera  → camera.py    (camera track)    │
                       └───────────────────┬──────────────────────────┘
                                           ▼  feat (T,30|60) + vfx/props/camera
                       ┌──────────────────────────────────────────────┐
                       │ renderer.py (512) │ stage_renderer.py (720p) │
                       └───────────────────┬──────────────────────────┘
                                           ▼
                                    video_encode.py → ffmpeg → mp4
```

### 3.2 Module responsibility map

| Layer | Module | Public surface | Role |
|---|---|---|---|
| **Representation** | `rig.py` (127 L) | `encode`, `decode`, `forward_kinematics`, `enforce_ground_contact`, `BONES`, `REST_ANGLES`, `FEAT_DIM=30`, `GROUND_Y=-0.42` | The single source of truth for the body. Excellent: tiny, numpy-only, no deps. |
| **Puppet motion** | `puppet/pose.py` (455) | `POSES`, `get_pose_angles`, `get_pose_root_y` | 20+ hand-verified key poses. |
| | `puppet/easing.py` (137) | `ease_*`, `snap_and_settle`, `moving_hold`, `hold_breath` | Animation timing curves. |
| | `puppet/armature.py` (460) | `ArmatureTimeline`, `Keyframe`, `TimelineEvent`, `solve_two_bone_ik` | Keyframe→24 fps interpolator with zero-drift stance pinning. **The heart of the "no shaking" fix.** |
| | `puppet/choreography.py` (899) | `build_motion_from_action`, `build_combat_pair`, `PuppetChoreographer` | Action → motion. **The workhorse** (71 call sites). |
| | `puppet/combat_ik.py` (361) | `capsule_contacts`, `HitTracker`, `classify_recoil`, `solve_aimed_limb` | Capsule collision, edge-triggered hits, recoil tiers. |
| | `puppet/controllers.py` (161) | `GaitCommand`, `LocomotionController`, `layer_timelines` | Parametric signed-speed gait + split-body layering. |
| | `puppet/director.py` (166) | `Director` | Fluent L3 API. **Only used by one demo + tests.** |
| **Control** | `scene.py` (514→495) | `SceneScript`, `Beat`, `Character`, `compile_scene`, `compile_scene_dict`, `parse_script` | **Canonical compiler.** |
| | `sequencer.py` (241) | `PuppetSequencer`, `ActorTrack`, `blend_feature_clips` | Multi-actor tracks + root handoff blending. |
| | `contract.py` (491) | `validate_scene`, `capabilities`, `resolve_joint`, `resolve_object` | LLM-facing contract; fail-fast validation. |
| | `planner.py` (201) | `PlannerBackend`, `NoOp/Callable/DeterministicPlanner`, `plan_scene`, `llm_system_prompt` | The BYO-LLM seam. |
| | `parser.py` (403) | `parse_prompt`, `match_actions` | Keyword/synonym text→controls. |
| **Simulation** | `objects.py` (273) | `evaluate_objects` | spawn / attach / throw / bounce / impact. |
| | `camera.py` (168) | `compute_camera` | static/auto/follow/close/wide/pan. |
| | `entity.py` (242) | `StickmanEntity`, `solve_reach`, `balance_correction` | Physics-ish body entity + DLS IK. |
| **Render** | `renderer.py` (607) | `StickmanRenderer`, `render_to_video`, `decode_motion_features`, `apply_contact_correction`, camera impulse helpers | 512 SD arena + VFX. |
| | `stage_renderer.py` (553) | `render_stage_video` | 1280×720 HD stage, 2.5D depth. |
| | `stage/` (7 modules) | theme, perspective, props, panels, text_overlay, dsl, terminal_preview | Scenery + theatrical DSL. |
| | `video_encode.py` (42) | `open_ffmpeg_writer`, `close_ffmpeg_writer` | Lossless ffmpeg pipe. |
| **Quality** | `doctor.py` (316) | `diagnose`, `format_report` | Pre-render hard-defect gate. |
| | `preview.py` (397) | `render_timeline_preview`, `motion_stats`, `interaction_stats` | Text review before mp4. |
| | `visual_inspector.py` (297) | — | Still/audit inspection. |
| | `eval.py` (254) | `run_benchmark_suite`, `evaluate_motion_features` | 100-prompt benchmark. |
| **Interface** | `mcp_server.py` (415) | 10 MCP tools | `list_actions, parse_text_prompt, render_prompt_clip, render_action, sequence_timeline, preview_stage_ascii, render_stage_script, get_capabilities, validate_scene, render_scene` |
| **Team ops** | `tools/agent_bus.py` (379), `convo_watcher.py` | bus CLI | `conversation.md` as the multi-agent message bus. |

**Verified health of the core:**

```
188 passed in ~20 s                        (tests/)
100/100 prompts passed @ 3,164 FPS         (src/eval — determinism ✓ diversity ✓ rejection ✓)
17/17 catalog actions build, correct dims  (probe)
0 ground-penetration violations            (probe)
```

---

## 4. "Is the project in the correct path?" — answered both ways

### 4.1 Literally (filesystem / repository) — **YES**

- Workspace: `C:\Users\SATHYA TRADERS\Documents\Abi\Projects\video_model`
- **Single canonical copy** — no duplicates under `Documents/`, `Downloads/`, `Desktop/`,
  no nested `video_model/video_model`. Layout is conventional and correct
  (`src/ tests/ tools/ docs/ out/`).
- It is a real git repo (43 commits) with a sensible `.gitignore`.

**Caveats (not path errors, but they undermine the path):**

1. **No git remote configured.** `git remote -v` is empty. 15.8k LOC and 43 commits of
   intense work exist on exactly **one disk with no backup**. This is the single
   highest-consequence risk in the whole review.
2. `out/` is doing double duty as artifact store *and* the team's diagnostics scratch
   pad (11 `.py` probe scripts, 128 top-level entries). It works, but it is why
   `git status` is permanently noisy.

### 4.2 Architecturally (is the direction right?) — **YES, with 5 drifts**

The direction is correct and consistent with the goal. But the codebase has drifted
in five specific, fixable ways:

| # | Drift | Symptom |
|---|---|---|
| D1 | **5 motion-authoring front doors** | `SceneScript`, `PuppetSequencer`, `PuppetChoreographer`, `Director`, `StageScript` — a newcomer cannot tell which is canonical |
| D2 | **2 renderers, barely shared** | `renderer.py` (607 L) and `stage_renderer.py` (553 L) share only 3 symbols |
| D3 | **Contract knowledge duplicated** | `catalog.ACTIONS_1P` vs a 60-line `if/elif` chain in `choreography.py` |
| D4 | **Two generations of motion code** | `data_gen.py` (v1 procedural sines) still present alongside `puppet/` (v2 stop-motion) |
| D5 | **Docs contradict each other** | `AGENTS.md` says "No LLM for parsing in v1"; `GOAL.md` says "The LLM owns the world" |

**Drift D5 detail (doc drift, verified):**

- `AGENTS.md:36` — *"Repo state: `src/rig.py` + `src/data_gen.py` done (numpy-only).
  Next: `src/renderer.py`, then `src/model.py` + `src/train.py`."* → **stale by ~15
  milestones**; `renderer.py` exists and the project is far past it.
- `AGENTS.md` — *"No LLM parser in repo for v1"* vs `GOAL.md` — *"The LLM owns the
  world"* + `src/planner.py::llm_system_prompt()`. These describe different products.

---

## 5. Code-quality findings

Severity: **H** = correctness/contract, **M** = maintainability, **L** = hygiene.

| # | Sev | Finding | Evidence | Status |
|---|---|---|---|---|
| 1 | **H** | **Silent wrong mapping** — unknown actions returned an idle pose instead of failing, violating `PROJECT.md:54` ("never silent wrong mapping"). | `build_motion_from_action('floss_dance')` → `(24,30)` idle, no error. Same for `''`, `'fly_to_moon'`. | ✅ **Fixed** |
| 2 | **M** | **19 lines of unreachable dead code** — a copy-paste artifact after `return result`. | `src/scene.py:414–432`; AST scan found 6 unreachable blocks. | ✅ **Fixed** |
| 3 | **M** | **No onboarding entry point and no quality gate** — nothing told a new agent how to set up, run, or verify. | No `README.md`; no CI; no lint config; the managed Python lacks numpy/pytest so the naive `python -m pytest` fails. | ✅ **Fixed** |
| 4 | **H** | **Five overlapping motion-authoring APIs** with no declared canonical one. | `PuppetChoreographer` (choreography), `Director` (director — used *only* by `tools/demo_combat_arena.py` + tests), `PuppetSequencer`, `SceneScript`, `StageScript`. | ⬜ Open |
| 5 | **H** | **Renderer divergence** — two full renderers sharing 3 symbols; VFX/prop/camera logic is duplicated and will drift. | `stage_renderer.py:19` imports only `BONE_SEGMENTS, apply_contact_correction, apply_camera_impulses` from `renderer.py`. | ⬜ Open |
| 6 | **M** | **Duplicated action contract** — the catalog is the declared source of truth, but the dispatcher is a hand-maintained `if/elif` chain that never consults it. | `catalog.ACTIONS_1P` vs `choreography.py:677–741` (~60 lines). | ⬜ Open |
| 7 | **M** | **180 lint warnings** — 174 unused imports/locals, 6 benign nits (f-string without placeholders, `moving_hold` field shadowing the easing import, `PuppetSequencer` re-import). Zero hard errors. | `pyflakes src/ tools/ tests/` | ⬜ Open |
| 8 | **M** | **No off-machine backup.** | `git remote -v` → empty. | ⬜ Open |
| 9 | **M** | **Doc drift** — `AGENTS.md` contradicts `GOAL.md` and is ~15 milestones stale. | see §4.2 D5 | ⬜ Open |
| 10 | **L** | **6 orphan modules** unreachable from any live entry point: `eval.py`, `generate_goal_demos.py`, `onnx_runner.py`, `render_showcase.py`, `train.py`, `model.py`. Several are the intentionally-deferred ML path. | import-graph reachability analysis | ⬜ Open |
| 11 | **L** | **Repo bloat** — 78 PNGs (8.9 MB) are *tracked* despite `out/*.png` in `.gitignore` (the rule only affects untracked files); `.git` is 28 MB for 1.3 MB of source. | `git ls-files out/` | ⬜ Open |
| 12 | **L** | **No branch discipline under concurrency.** A commit landed mid-review (`5d6e1ef` → `0259381`), i.e. agents commit directly to `master` while another agent is reading it. | `git reflog` | ⬜ Open |
| 13 | **L** | **Parser over-maps acrobatics.** `"do a backflip into a handstand"` → `{action: jump, supported: True}`. A backflip is not a jump; "handstand" is silently dropped. | `parse_prompt` probe; synonym table `parser.py:104–110` | ⬜ Open (deliberate?) |

### The most instructive finding (1)

`PROJECT.md` promised *"Unsupported prompts return clear limitation, never silent wrong
mapping"* — but the builder's final branch was:

```python
else:
    # Default: idle / stand with subtle life
    ch.timeline.add_keyframe(t=0.0, pose="stand_relaxed", ...)
```

So **any** unrecognised action — a typo, an LLM hallucination, an unimplemented move —
produced a confident, plausible, *wrong* video with no error. The guard already existed
elsewhere (`catalog.validate_action_params` raises correctly, and `mcp_server` calls it),
which is exactly why this class of bug is dangerous: **the check existed, it just wasn't
on the path everyone used.** The fix was to put the invariant where the data is.

---

## 6. What was fixed in this review

| Fix | File | Verification |
|---|---|---|
| Unknown actions now raise `ValueError` listing supported actions (idle made explicit) | `src/puppet/choreography.py` | `tools/quality_gate.py` → *"13+4 actions build, unknowns rejected"* |
| Removed 19 lines of unreachable dead code | `src/scene.py:414–432` | AST dead-code scan → **clean** |
| Added a runnable quality gate (tests + dead code + lint + contract + invariants + hygiene) | `tools/quality_gate.py` *(new)* | Gate now exits **0 = PASS** |
| Added a single onboarding entry point | `README.md` *(new)* | — |

**Gate result after the fixes:**

```
[PASS] unit tests             188 passed in 22.16s
[PASS] dead code (unreachable) clean
[WARN] static analysis        180 issue(s): 180 warning, 0 hard
[PASS] action contract        13+4 actions build, unknowns rejected
[PASS] motion invariants      13 actions: dims OK, no ground penetration
[WARN] repo hygiene           1 advisory note(s)
[PASS] 100-prompt eval        Benchmark Results: 100/100 passed (100.0%)
RESULT: PASS (with 2 warning(s))
```

> Note: `pyflakes` is not in the project's runtime deps. `pip install pyflakes`
> (or `ruff`) enables check #3; the gate degrades gracefully to a warning if absent.

---

## 7. Prioritised action plan

### P0 — this week (protect the work)
1. **Add a git remote and push.** `git remote add origin <url> && git push -u origin master`.
   Nothing else in this document matters if the disk dies.
2. **Adopt the quality gate as the definition of done.**
   `python tools/quality_gate.py` must be green before any agent calls
   `agent_bus.py complete`.
3. **Reconcile `AGENTS.md` with `GOAL.md`** — delete the stale repo-state block and the
   "no LLM parsing" claim, or move them into a clearly-labelled history section.

### P1 — coherence pass (the real technical debt)
4. **Declare `SceneScript` / `compile_scene` the one canonical authoring API.**
   Then: mark `Director` and `stage/dsl.py::StageScript` `@deprecated`, migrate their
   two call sites, and delete them. That takes 5 front doors down to 2
   (`SceneScript` + the shared `build_motion_from_action` primitive).
5. **Extract a shared `render_common.py`** (VFX, props, joint caps, camera impulses)
   consumed by both `renderer.py` and `stage_renderer.py`. Do it *before* the next
   feature lands in only one of them.
6. **Drive the action dispatcher from `catalog`** — one dict
   `{action: builder}` and let the catalog be the only place actions are listed.

### P2 — hygiene (cheap, do it in one pass)
7. Run `ruff check --fix` (or `autoflake`) to clear the 174 unused imports, then add
   `ruff` to `requirements.txt` and a pre-commit hook.
8. `git rm --cached out/*.png` and tighten `.gitignore` (`out/**` except a keep-list).
9. Move the 11 diagnostics to `tools/diagnostics/` and update `HEAD_STATE.md`.
10. Triage the 6 orphan modules: keep + document `model.py`/`train.py`/`onnx_runner.py`
    as the explicitly-deferred ML path; delete or relocate the rest.

---

## 8. Engineering standards to adopt (the "elevate the team" part)

The team's velocity is real — 43 commits and 15.8k LOC of *working* code in about a
day. What is missing is not skill, it is **discipline at the boundaries**. Five rules:

**1. One canonical path per concern.**
Every concern gets exactly one blessed entry point, listed in `README.md`. Anything
else is either an internal helper or explicitly `@deprecated`. *Five ways to author
motion is how a codebase becomes unmaintainable without a single bug being introduced.*

**2. Invariants live where the data is.**
Finding 1 happened because the validator was in `catalog.py` while the builder was in
`choreography.py`. **If a module can produce a value that another module must reject,
validate at the producer.** Prefer `assert`/`raise` at the source over defensive checks
at the call sites.

**3. Definition of Done — non-negotiable.**
A task is complete only when: (a) `tools/quality_gate.py` is green, (b) the change is
committed on a branch, (c) the doc that describes the touched area is updated in the
same commit. *"Tests pass" is necessary, not sufficient.*

**4. Branch, don't race.**
Finding 12: a commit landed on `master` mid-audit. One branch per task
(`feat/task-016-...`), merge when the gate is green. Direct-to-master commits under
concurrency make reviews meaningless and bisects unreliable.

**5. Docs are code — and they must not contradict.**
`AGENTS.md` and `GOAL.md` currently describe different products. Rule: **`GOAL.md` is
the single source of architectural truth**; everything else links to it. A doc that
contradicts the code is worse than no doc, because agents *believe* it.

### Suggested gate wiring

```bash
# Before completing any task on the bus
python tools/quality_gate.py || exit 1
python tools/agent_bus.py complete --task TASK-0NN --by <Agent> --notes "gate green"
```

---

## 9. Metrics snapshot

| Metric | Value |
|---|---|
| Source size | **15,841 LOC** across `src/` + `tools/` + `tests/` |
| Largest modules | `puppet/choreography.py` 899 · `renderer.py` 607 · `stage_renderer.py` 553 |
| Tests | **188 passing** in ~20 s |
| Eval benchmark | **100/100** @ 3,164 FPS; determinism ✓ diversity ✓ rejection ✓ |
| Catalog actions | **17** (13 single + 4 paired) — all build, 0 ground penetration |
| Lint warnings | **180** (0 hard) |
| Unreachable code | **0** (was 6 blocks) |
| Motion-authoring APIs | **5** → target 2 |
| Renderers | **2** (share 3 symbols) |
| Orphan modules | **6** |
| Commits | **43** (≈1 day of work) |
| Git remote / backup | **none** ⚠ |
| `.git` size | **28 MB** (1.3 MB of source; 8.9 MB of tracked PNGs) |

---

## 10. Bottom line

This is a **well-aimed, well-tested engine** with a genuinely correct core idea —
predict only the skeleton, code everything else, keep it tiny. It is *not* in the wrong
place, and it is *not* going the wrong way. The three things standing between it and
"senior-grade" are: **one canonical API per concern, invariants at the producer, and a
green gate before every commit.** All three are cheap to adopt now and expensive to
retrofit later.

**Do P0 today** (remote + gate + doc reconciliation). Everything else can wait for a
planned consolidation sprint.
