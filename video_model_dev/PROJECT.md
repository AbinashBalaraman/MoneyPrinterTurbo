# Stickman Universe — PROJECT.md

## Vision
Text-to-stickman-video product. Engine generates motion, not pixels. External intelligent models direct a deterministic puppet world via MCP/API. Tiny deployment preserved.

Long-term goal: any text prompt produces a stickman video. V1 achieves this via constrained actions + composition, not single-pass unlimited generation.

## Architecture (fixed)
`prompt -> LLM director (external) -> MCP timeline JSON -> puppet engine -> video`
`puppet engine = action library (src/data_gen.py) + FK (src/rig.py) + contact fix + deterministic renderer + video encoder`
`optional: motion diffusion -> FK (replaces/augments library clips for variation/transitions only)`

- Neural net predicts skeleton motion only, never pixels.
- Renderer, bone lengths, camera, background are code, not learned.
- No LLM parser in repo for v1. Parser is keyword/synonym matching. LLM director lives outside deployment.

```mermaid
flowchart LR
    A[Any prompt] --> B[LLM director]
    B --> C[MCP timeline]
    C --> D[Puppet engine]
    D --> E[Video]
```

## V1 Scope (do not expand without asking)
- 1-2 stickmen, side view, fixed camera, plain background, 512x512, 24fps, 5s clips (120 frames).
- 15 joints/person, 2D. Root xy + sin/cos bone angles. Fixed bone lengths in renderer. 1p feat 30, 2p feat 60.
- 13 single + 4 paired: idle/walk/run/walkback/jump/punch/kick/block/wave/squat/knockdown/getup/celebrate + punch_block/kick_dodge/exchange/knockdown_getup.
- Props/actors beyond stickmen (crowd member, tree, stick sword) are renderer draw calls + transforms, not learned.
- No-limit fighting / long stories = compositional only: sequence library moves with pose/velocity/root handoff. No single-pass unlimited N-person diffusion. No pixel/latent video diffusion. No 2B pixel/LoRA models.

## Representation
- `src/rig.py`: `BONES` 14x (name, parent_joint, length), `REST_ANGLES`, `FPS=24`, `CLIP_LEN_5S=120`, `FEAT_DIM=30`. `encode(root_xy, angles)`, `decode(feat)` normalizes sin/cos pair, `forward_kinematics(root_xy, angles) -> (...,15,2)`.
- Angles as sin/cos, normalize pair before decoding. FK for joint positions. Fixed bone lengths.
- Normalize scale (fixed height ~1.0), fixed ground plane + start root. Resample to same fps. Preserve root travel. Mask padding.
- Split dataset by source motion/family (`family_id` in `src/data_gen.py`), not random clip.
- Structured controls: `{action, direction, speed, duration_seconds, amplitude, seed}`.

## Repo State
- **Core Rig & Kinematics**: `src/rig.py` (14 bones, 15 joints, forward kinematics in numpy, normalized sin/cos decode).
- **Procedural Bedrock & Smooth Stop-Motion Platform**: `src/puppet/` (`pose.py` 20+ keyframe poses, `easing.py` harmonic oscillator easing curves, `armature.py` Two-Bone analytical IK with zero drift $< 10^{-7}$ and adaptive cadence, `choreography.py` 1P actions + 2P synchronized combat).
- **2.5D Deterministic Stage Renderer**: `src/stage_renderer.py` (1280x720 HD, 4-layer depth shading, anti-tearing circular joint caps, wrist/elbow joint props: sword/staff/gavel/shield, and procedural vector VFX: impact bursts, dust puffs, speed lines).
- **Catalog & Parser**: `src/catalog.py` (13 1P + 4 2P actions frozen), `src/parser.py` (word-boundary regex matching).
- **Sequencer & MCP Server**: `src/sequencer.py` (compositional timeline), `src/mcp_server.py` (7 Puppet Engine tools over stdio JSON-RPC).
- **Stage Choreography DSL & Symbolic Player**: `src/stage/dsl.py`, `src/stage/terminal_preview.py`, `tools/play_terminal_ascii.py`.
- **Testing & Verification**: 19/19 unit tests passing (`tests/`), 100/100 eval benchmark passing at >4,000 FPS (`src/eval.py`), master showcase video generated (`out/puppet_platform_master_showcase.mp4`).

## Puppet Engine API (MCP/tools)
- `list_actions` -> catalog with args `{speed, direction, amplitude, duration_seconds, seed}`.
- `spawn_actor {kind: human|crowd, x, seed}`, `spawn_prop {kind: tree|sword|chair, x, y, parent_hand?}`.
- `play {actor, action, start_s, controls}`, `sequence {actor, steps[]}`, `blend {overlap_frames}`.
- `set_camera {fixed_side}`, `set_background {plain}`, `render_clip {timeline, fps:24, size:512} -> mp4`.
- Timeline example: `Walk right -> Stop -> Wave -> Jump -> Idle` with boundary conditions: starting pose, starting velocity, root location, contact state.
- Unsupported prompts return clear limitation, never silent wrong mapping.

## Motion Model (optional, when needed)
- Temporal transformer denoiser, 1 token/frame, up to 120 frames, hidden 256, 6-8 blocks, ~5-50M params. Predict clean motion x0.
- Losses: recon + velocity (on decoded pos) + foot-contact + ground-penetration. Mask padding.
- Train: AdamW 1e-4, batch 32-64 on Kaggle/Colab T4/P100 16GB. Select by held-out metrics + rendered review. Sample 20-50 steps first, then reduce.
- Must beat procedural baseline on variation/transitions/control to justify complexity. Do not compress/quantize/distill until uncompressed model is useful.

## Baseline First
- Build procedural baseline + shared renderer before diffusion.
- Postprocessing limited. If contact fix rewrites every frame, fix model/data.

## Compute Split
- Train on Kaggle/Colab GPU only. Dev laptop (i3-6006U, 8GB, HD520, no CUDA) is inference-only: procedural + INT8/ONNX small model.

## Roadmap
1. `renderer.py`: FK decode, contact correction, fixed world-to-canvas, line draw, encoder. Higher-res render + downsample for clean edges.
2. Freeze action catalog JSON schema from `data_gen.py`.
3. `parser.py` (keywords) + `sequencer.py` (handoff/blend).
4. `mcp_server.py` thin wrapper. No bundled LLM.
5. Eval: 100 prompts x N seeds, hidden review vs baseline. Failure tests: slow-motion jitter, jump cutoff, canvas exit, identical seeds, unsupported prompt.
6. Optional diffusion for variation. Then size/latency optimization.

## Non-Goals v1
- Multi-person single-pass diffusion, changing camera, object interaction physics, 60s single diffusion pass, free-form language understanding in-repo.
