# GOAL — LLM-drivable stickman world

**Last updated:** 2026-09-11 · **Planner:** 4.1 Agent

## Ultimate goal
A user (or an LLM) describes **any scene** — a movie moment, a short-form idea, a
script — and the system produces a finished stickman **video**.

## Locked architecture (user decisions)
1. **The LLM owns the world.** It decides who is present, what they do, which
   objects exist and where, and how the camera frames it — expressed as
   **SceneScript JSON**.
2. **The engine owns execution.** Rig, IK, ground contact, object simulation,
   camera and rendering are deterministic code. The engine **never invents** a
   world; it validates and executes one.
3. **Planner integration is bring-your-own (BYO).** The default is author-time
   (a human or this agent supplies the JSON). Cloud or local LLM backends plug
   into the same `PlannerBackend` seam with no engine changes.
4. The interface need not be literal MCP; whatever is optimal. It is exposed as
   both a Python API and an MCP-style tool registry.

## The contract (single source of truth)
```
user text
  │  planner  (src/planner.py — BYO backend; NoOp / Callable / Deterministic)
  ▼
SceneScript JSON            declared + validated by src/contract.py
  │  validate_scene()       fail-fast: unknown action/object/joint => rejected
  ▼
compile_scene()             src/scene.py (deterministic)
  │   beats   -> puppets    sequencer + choreography
  │   objects -> prop tracks src/objects.py   (spawn/attach/throw/pickup/impact)
  │   camera  -> cam track  src/camera.py     (static/auto/follow/close/wide/pan)
  ▼
renderer (512 SD / 1280x720 HD) -> ffmpeg -> video
```

## What the world can express (v1)
- **Actions:** 17 (13 single-person + 4 paired).
- **Objects:** sword, staff, shield, ball, chair, tree, crowd, box, speech_bubble,
  gavel, confetti — each with capability flags (place / attach / throw / bounce).
- **Object behaviours:** spawn/place, attach to any joint, throw (ballistic),
  pickup/drop, bounce + collision impact.
- **Joints:** 15 named (root, spine, chest, neck, head, elbows/hands, knees/
  ankles/feet) with human aliases (`hand` -> `hand_r`).
- **Camera:** static, auto, follow, close, wide, pan.
- **Stage:** light/dark themes; plain / perspective_hall / spline_web / split_screen_3.

## Entry points
- CLI: `python tools/prompt_to_video.py "<prompt>" -o out/x.mp4`
- CLI (LLM plan): `python tools/prompt_to_video.py --scene scene.json -o out/x.mp4`
- MCP tools: `get_capabilities`, `validate_scene`, `render_scene`
- Python: `src.planner.plan_scene`, `src.scene.compile_scene_dict`

## Success criteria
- [x] Text -> multi-action video, no silent single-action collapse.
- [x] LLM can discover the contract and render a validated scene.
- [x] Objects can be placed, held, thrown, picked up, and impact.
- [x] Camera is a first-class part of the plan.
- [x] Deterministic: same plan -> identical output.
- [ ] Deferred (out of v1): learned motion, N-person (>2), 3D, stylisation.
