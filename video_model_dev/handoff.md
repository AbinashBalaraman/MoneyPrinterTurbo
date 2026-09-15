# Project Handoff — Stickman Video Model

**Generated**: 2026-09-10  
**Current Branch**: `master`  
**Latest Commit**: `0947495` (`feat(foundation): rebalance stickman proportions and establish standing, squatting, and single-step primitives`)  
**Latest Tag**: `v6-foundation-primitives`  
**Evaluation Status**: 20/20 unit tests passing (17.10s) | 100/100 prompts benchmark passing at 2,896 FPS  

---

## 1. Executive Summary & Vision

The **Stickman Video Model** project is a single-purpose, tiny-deployment text-to-stickman-video animation platform.
- **Core Strategy**: Learn movement, code appearance. Neural nets (when used) predict only 2D skeletal motion features $(T, 30)$, never pixels or latent diffusion.
- **Hardware Profile**: Developed for standard laptop execution (Intel i3-6006U, 8GB RAM, integrated HD520, no CUDA). All local generation is procedural, zero-jitter, and runs at 2,800+ FPS. Training of diffusion transformers (when needed) is strictly offloaded to cloud GPUs (Kaggle/Colab).
- **Core Directive**: Move step-by-step from rock-solid anatomical and biomechanical foundations before composing complex actions:
  > *"First define the stickman structure, just standing, then squatting, then one step like that, move one by one. If we create the foundation right, we can easily puppet it around to create any video."*

---

## 2. Recent Major Milestones

### Tag `v6-foundation-primitives` (Current HEAD: `0947495`)
1. **Structural Rebalancing (Eliminated "2.0× Stilts / Lengthy Leg" & Floating)**:
   - Previously, legs totaled `0.49` world units against a torso of `0.25` (~2.0× ratio), making the stickman look like a spider/stilts figure.
   - Rebalanced to standard human/animation 50/50 proportion:
     - **Torso + Head = 0.45** (`spine` 0.14, `chest` 0.14, `neck` 0.06, `head` 0.11).
     - **Legs = 0.42** (`upperLeg` 0.22, `lowerLeg` 0.20, `foot` 0.07).
     - **Arms = 0.31** (`upperArm` 0.16, `lowerArm` 0.15).
   - Fixed ground plane at $y = -0.420$.
   - Connected neck-to-head segment `(3, 4)` in `BONE_SEGMENTS` to eliminate floating head gaps.
2. **Core Foundation Primitives Authored & Rendered**:
   - **Primitive 1: Standing** (`create_standing_sequence`):
     - Feet glued flat at $y = -0.420$, natural knee micro-flex ($2^\circ-4^\circ$), arms at sides, center of mass over feet.
     - Media: `out/foundation_1_standing.mp4`, `out/foundation_1_standing.png`.
   - **Primitive 2: Squatting** (`create_squat_sequence`):
     - Controlled lowering ($y = -0.15$), knees bend forward cleanly ($-99.5^\circ$), torso leans forward ($+25^\circ$ spine, $+12^\circ$ chest) to balance CoM over the feet, arms reach forward. Feet 100% glued flat to the floor.
     - Media: `out/foundation_2_squat.mp4`, `out/foundation_2_squat.png`.
   - **Primitive 3: The Single Step** (`create_single_step_sequence`):
     - Pure atomic step broken into 5 phases: weight shift $\to$ swing lift ($+0.04$ clearance) $\to$ forward extension $\to$ heel strike $\to$ weight transfer roll $\to$ settle.
     - Media: `out/foundation_3_one_step.mp4`, `out/foundation_3_step_pass.png`, `out/foundation_3_step_strike.png`.

### Previous Tags
- `v5-knee-fixed` (`1be801f`): Fixed knee sign convention (negative flexion) across 26 poses and choreography.
- `v4-baseline` (`0fdd705`): Functional baseline test suite, initial stop-motion puppet timeline.

---

## 3. Architecture & Codebase Map

```
video_model/
├── AGENTS.md                  # Project rules, architecture constraints, multi-agent protocol
├── conversation.md            # Multi-agent collaboration message bus
├── handoff.md                 # This document
│
├── src/
│   ├── rig.py                 # 14 bones, 15 joints, FK, decode/encode, REST_ANGLES
│   ├── renderer.py            # StickmanRenderer, render_to_video, drop shadow, contact fix
│   ├── stage_renderer.py      # StageRendererHD, 2.5D depth shading, joint props, vector VFX
│   ├── catalog.py             # Action catalog, metadata, validation (13 1P, 4 2P actions)
│   ├── parser.py              # NLP regex/keyword parser to structured controls
│   ├── data_gen.py            # Procedural baseline data generator
│   ├── sequencer.py           # Multi-action continuous root handoff & cosine blending
│   ├── video_encode.py        # Lossless ffmpeg subprocess pipe
│   ├── eval.py                # 100-prompt evaluation & physics benchmark
│   │
│   ├── puppet/
│   │   ├── armature.py        # ArmatureTimeline, Keyframe, solve_two_bone_ik, stance locking
│   │   ├── easing.py          # Easing curves (quad, cubic, snap_and_settle, moving_hold)
│   │   ├── pose.py            # Curated library of 20+ verified 14-angle keyframe poses
│   │   └── choreography.py    # Director API: PuppetChoreographer, sequence builders
│   │
│   └── stage/
│       ├── dsl.py             # Theatrical Play script parser and stage compiler
│       └── terminal_preview.py# ASCII terminal motion previewer
│
├── tests/
│   ├── test_engine.py         # Rig, catalog, data_gen, parser, contact correction tests
│   ├── test_puppet_armature.py# Easing, poses, timeline, IK, stance pinning, cadence tests
│   └── test_dsl.py            # DSL parser and terminal stage preview tests
│
└── tools/
    ├── agent_bus.py           # Multi-Agent Collaboration CLI (status, check, send, delegate)
    ├── convo_watcher.py       # Background watcher polling conversation.md every 10s
    ├── render_foundations.py  # Renders the 3 core foundation primitives (stand, squat, step)
    └── render_jump_run_v5.py  # Render script for jump & run sequence
```

---

## 4. Multi-Agent System & Task Board

The project uses `conversation.md` as the unified communication bus. All inter-agent communication and task tracking are managed via `tools/agent_bus.py`.

- **Active Agents**:
  - `@Gemini-e48e797c`: Primary architect & foundation engineer.
  - `@Pi-Agent`: Active collaborator (recently completed `TASK-001`).
  - `@OC2-Agent`: Collaborator.
  - `@Copilot-7f3a9c2e`: Collaborator.

### Task Board Status
- `[X] TASK-001` (Completed by `@Pi-Agent`): Refactored `src/stage/dsl.py` to wire `src.video_encode` and eliminate `gen_single` fallbacks.
- **Latest Bus Entry**: `@Gemini-e48e797c` posted progress update announcing `v6-foundation-primitives`.

---

## 5. Next Steps & Implementation Roadmap

Now that the **3 Foundation Primitives** (Standing, Squatting, One Step) are verified and grounded, the platform is ready to puppet complex actions cleanly:

1. **Continuous Locomotion (Walk / Run Cycles)**:
   - Build a continuous walk sequence by alternating the single-step primitive (Left Step $\to$ Right Step) with continuous forward momentum and pelvis sinusoidal down/up displacement.
   - Run cycle: wider stride ($0.34$), faster cadence ($0.26\text{s}$), forward torso lean ($15^\circ-20^\circ$), and ballistic flight phase ($+0.06$).
2. **Biomechanical Jump & Leap**:
   - Compose from the verified squat primitive:
     `stand_relaxed` $\to$ `squat_deep` (anticipation) $\to$ `jump_takeoff` (launch) $\to$ `jump_apex` (mid-air tuck) $\to$ `stride_contact` (touchdown) $\to$ `squat_deep` (landing absorption) $\to$ rise to `stand_relaxed`.
3. **Synchronized 2-Person Combat**:
   - Use the grounded stance locks to guarantee zero foot skate during high kicks, parries, exchanges, and knockdowns.
4. **Diffusion Model (Optional Kaggle / Colab Plug-in)**:
   - When required, wire `src/model.py` and `src/train.py` for cloud GPU training using the procedural data as ground truth.

---

## 6. Developer & Testing Cheatsheet

### Run All Unit Tests
```bash
python -m pytest tests/ -v
```

### Run 100-Prompt Physics & Kinematics Benchmark
```bash
python -m src.eval
```

### Render Foundation Primitives (Standing, Squat, One Step)
```bash
python tools/render_foundations.py
```

### Multi-Agent CLI Commands
```bash
# Check status of bus and task board
python tools/agent_bus.py status

# Check messages for an agent
python tools/agent_bus.py check --agent Gemini-e48e797c

# Send message to bus
python tools/agent_bus.py send --from <Name> --to <Recipient> --summary "<Title>" --body "<Text>"

# Delegate task
python tools/agent_bus.py delegate --from <Name> --to <Assignee> --task "<Title>" --details "<Details>"

# Complete task
python tools/agent_bus.py complete --task <TASK-ID> --by <Name> --notes "<Notes>"
```
