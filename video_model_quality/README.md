# Stickman Video Model

Text → stickman video. **Learn movement, code appearance:** the engine only ever
predicts/animate 2D skeletal motion (15 joints, 30 features/frame); the renderer,
bone lengths, camera and background are deterministic code, never learned.

Tiny by design — runs inference on a laptop (i3-6006U / 8 GB / no CUDA).

---

## Quick start

```bash
# 1. Environment (numpy + Pillow + pytest; ffmpeg must be on PATH)
python -m venv .venv
.venv/Scripts/activate            # Windows;  source .venv/bin/activate on Unix
pip install -r requirements.txt

# 2. Text -> video
python tools/prompt_to_video.py "walk forward, then punch, then celebrate" -o out/x.mp4

# 3. Review the scene as text BEFORE rendering (no mp4, token-cheap)
python tools/prompt_to_video.py "two stickmen fight" --review

# 4. LLM/author plan path (the engine only ever *executes* a validated plan)
python tools/prompt_to_video.py --scene out/scene.json -o out/x.mp4

# 5. Quality gate — run this before every commit
python tools/quality_gate.py
```

---

## Architecture

```
prompt ─► planner ─► SceneScript JSON ─► validate_scene() ─► compile_scene() ─► renderer ─► ffmpeg
 (text)   (BYO LLM)   (src/scene.py)      (src/contract.py)    (src/scene.py)    512/720p   (mp4)
```

- **The LLM owns the world.** It declares who exists, what they do, which objects
  are present, and how the camera frames it — as `SceneScript` JSON.
- **The engine owns execution.** Rig, IK, ground contact, objects, camera and
  rendering are deterministic. The engine **never invents** a world; it validates
  and executes one. Same plan → identical output.
- **No planner ever emits joint angles or raw motion.**

### Core modules

| Layer | Module | Responsibility |
|---|---|---|
| Representation | `src/rig.py` | 14 bones / 15 joints, `encode`/`decode` (sin·cos), forward kinematics, ground contact |
| Control | `src/scene.py` | `SceneScript` dataclass + deterministic `compile_scene` |
| Contract | `src/contract.py` | `validate_scene` — fail-fast on unknown action/object/joint |
| Planner | `src/planner.py` | `PlannerBackend` seam (NoOp / Callable / Deterministic) |
| Parser | `src/parser.py` | keyword/synonym text → structured controls |
| Motion | `src/puppet/choreography.py` | `build_motion_from_action`, `build_combat_pair` |
| Motion | `src/puppet/pose.py` · `easing.py` · `armature.py` | key poses, easing curves, zero-drift IK keyframe interpolation |
| Objects | `src/objects.py` | prop tracks: place / attach / throw / bounce / impact |
| Camera | `src/camera.py` | static / auto / follow / close / wide / pan |
| Render | `src/renderer.py` (512) · `src/stage_renderer.py` (720p) | deterministic draw + VFX + ffmpeg |
| Verification | `src/doctor.py` · `src/preview.py` · `tools/quality_gate.py` | pre-render defect gate, text review, CI gate |
| Interface | `src/mcp_server.py` | 10 MCP tools over stdio JSON-RPC |

---

## Scope (v1)

- 1–2 stickmen, side view, fixed camera, plain background, 24 fps.
- **17 actions** = 13 single-person (`idle, walk, run, walkback, jump, punch, kick,
  block, wave, squat, knockdown, getup, celebrate`) + 4 paired (`punch_block,
  kick_dodge, exchange, knockdown_getup`).
- Objects: sword, staff, shield, ball, chair, tree, crowd, box, speech_bubble,
  gavel, confetti. Cameras: static/auto/follow/close/wide/pan.
- **Out of scope:** pixel/latent video diffusion, N-person (>2) single-pass,
  3D, learned appearance.

---

## Testing

```bash
python -m pytest tests/ -q     # 188 tests
python -m src.eval             # 100/100 prompts, determinism + diversity + rejection
python tools/quality_gate.py   # tests + dead code + lint + contract + invariants
```

## Docs

`docs/GOAL.md` (locked architecture) · `docs/SENIOR_REVIEW.md` (code-quality audit)
· `handoff.md` (session state) · `AGENTS.md` (multi-agent protocol)
· `conversation.md` (agent message bus)
