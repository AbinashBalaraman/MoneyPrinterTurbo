# AGENTS.md — stickman video model

## Goal
Single-purpose text-to-stickman-video. Tiny deployment. Strategy: learn movement, code appearance. Do NOT build pixel/latent video diffusion for v1.

## Architecture (fixed)
`prompt -> parser -> structured controls -> motion diffusion -> FK + contact fix -> deterministic renderer -> video encoder`
- Neural net predicts only skeleton motion, never pixels.
- Renderer, bone lengths, camera, background are code, not learned.

## V1 scope (do not expand without asking)
- 1-2 stickmen, side view, fixed camera, plain background, 512x512, 24fps, 5s clips (120 frames).
- ~15 joints/person, 2D. Root xy + sin/cos bone angles. Fixed bone lengths in renderer. 1p feat 30, 2p feat 60.
- 13 single + 4 paired actions: idle/walk/run/walkback/jump/punch/kick/block/wave/squat/knockdown/getup/celebrate + punch_block/kick_dodge/exchange/knockdown_getup.
- Parser is keyword/synonym matching to `{action, direction, speed, duration_seconds, amplitude, seed}`. No LLM for parsing in v1.
- No-limit fighting = compositional only: sequence library moves with pose/velocity/root handoff. No single-pass unlimited N-person diffusion. No 2B pixel/LoRA models (breaks tiny + laptop inference).

## Representation rules
- Angles as sin/cos, normalize pair before decoding. Forward kinematics for joint positions.
- Normalize scale (fixed height), fixed ground plane + start root. Resample to same fps. Preserve root travel. Mask padding.
- Split dataset by source motion/family, not random clip, to avoid leakage.

## Baseline first
- Build procedural baseline + shared renderer before any diffusion model.
- Learned model must beat baseline on variation/transitions/control to justify complexity.
- Do not compress/quantize/distill until uncompressed model produces useful motion.

## Motion model starting point (when needed)
- Temporal transformer denoiser, 1 token/frame, up to 120 frames, hidden 256, 6-8 blocks, ~5-50M params target. Predict clean motion x0.
- Losses: recon + velocity (on decoded pos) + foot-contact + ground-penetration. Mask padding. Tune weights after checking scales.
- Train: AdamW 1e-4, batch 32-64 on Kaggle/Colab T4/P100 16GB. Select checkpoints by held-out metrics + rendered review.
- Sample 20-50 steps first, then reduce and measure quality/latency together.

## Compute split
- Train on Kaggle/Colab GPU only. Dev laptop (i3-6006U, 8GB, HD520, no CUDA) is inference-only: procedural + INT8/ONNX small model.
- Repo state: `src/rig.py` + `src/data_gen.py` done (numpy-only). Next: `src/renderer.py`, then `src/model.py` + `src/train.py`.

## Multi-agent auto-sync & task delegation (no user nudge)
- `conversation.md` is the bus. No agent DMs another directly.
- Multi-Agent Collaboration CLI: `python tools/agent_bus.py [status|check|send|delegate|complete|live]`
  - Check messages at turn start: `python tools/agent_bus.py check --agent <YourName>`
  - View board & cursors: `python tools/agent_bus.py status`
  - Delegate tasks (cost-saving): `python tools/agent_bus.py delegate --from <Name> --to <Assignee> --task <Title> --details <Details>`
  - Complete tasks: `python tools/agent_bus.py complete --task <TASK-ID> --by <Name> --notes <Notes>`
  - Live interactive console: `python tools/agent_bus.py live [--agent <Name>]`
- Parallel watcher (background, 10s poll): `python tools/convo_watcher.py`. Logs to `out/watch.log`, state to `out/convo_state.json`.
- Ack rule: when you act on another agent's message, start your `conversation.md` entry with `To @<Name>:` so the watcher shows the handshake.
- Turn-start hook: `python tools/check_convo.py --agent <YourName>` remains supported as lightweight hook.
