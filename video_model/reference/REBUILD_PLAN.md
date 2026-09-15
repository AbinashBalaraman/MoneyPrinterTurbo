# Rebuild Plan — one stickman, controlled properly

Status: **proposed**. Supersedes `QUALITY_PLAN.md` and the earlier adoption plan.
Date: 2026-09-11. Author: @4.1flash.

## Why this exists

The current engine has been patched for a week and is not converging. Every fix
moves a number and reveals another. That is the signature of a wrong foundation,
not of insufficient polish. The specific evidence:

- The walk **moonwalks**: foot contact is 89/136 frames (a textbook stance
  fraction) while the foot travels 42.8 cm inside a single grounded run.
- Combat feet floated for entire clips (punch foot R: 5/120 frames in contact).
- Both defects trace to **one** architectural mistake (below).

So: stop patching, rebuild the motion core on the correct foundation, and delete
everything that only existed to serve the old multi-actor scope.

## The one architectural mistake

**Root advancement is a fixed translation, and IK is expected to hold the foot.**

That is backwards. When the root translates by a fixed amount and the IK is then
asked to keep the foot at an anchor, the IK silently absorbs the residual — until
it hits the reach limit, at which point it clamps and the foot drags. This is why
`foot_slide` kept finding new instances: they are all the same instance.

**Correct:** the stance anchor is an *input*, and the root position is *derived*
from it.

```
a_k      = world anchor of the stance foot at contact k      (fixed for the stance)
S        = stride length
phi      = gait phase, 0..1
x_root   = a_k.x + S * (phi - 0.5)      # travels -S/2 -> +S/2 over the anchor
y_root   = a_k.y + sqrt(L^2 - dx^2)     # L = stance leg length, dx = ankle_x - hip_x
```

No-slide is then exact by construction, and foot-floating disappears too, because
pelvis height is *derived* from the fixed anchor rather than keyframed.

Consequence to accept: **speed becomes emergent** (`v = S · f`). To hit a target
speed, set `S = v/f` and clamp `S` to a sane range, adjusting cadence `f` when
clamped. This is stride warping done at the source instead of patched afterwards.

## Research findings that shaped this

Investigated four areas; conclusions below. Full reasoning is in `conversation.md`.

**1. Do NOT use a neural network.** PFNN (Holden 2017) is the best-known
lightweight learned locomotion: ~9.6 MB, ~1.4 ms/frame single-threaded, would
comfortably fit our CPU budget. But it needs ~1 hour of CMU MoCap with a heavy
footstep/phase-labelling preprocessing pipeline, introduces BLAS/libm
non-determinism risk, and buys weight-shift and terrain adaptivity that are
*invisible at stick-figure fidelity*. For ~12 clips (sit/stand/walk × 4 facings)
procedural is strictly better: exact control, no licence, trivial determinism,
zero cost. Revisit only past ~100 motions, and then start with a small MLP.

**2. Copy Spine's data model, not its licence.** Spine's runtime is not
open-source for our use and has no Python runtime, but its JSON schema is fully
documented and its vocabulary is the industry convergence point: bones, slots,
and **skins** (= a map of slot → attachment resolved at draw time). That skin
abstraction is exactly our "swap the outer appearance" requirement. DragonBones
JSON is permissively licensed and readable if we want a real format.

**3. Analytic two-bone IK is correct — keep it.** Compared against FABRIK, CCD
and Jacobian/DLS: analytic law-of-cosines is the only one that is exact,
deterministic, iteration-free (no max-iteration path dependence) and has an
explicit bend direction. Our existing `solve_two_bone_ik` round-trips to 0.000 cm.
The one change to make: use an explicit bend-direction vector rather than a cross
product, which goes unstable near full extension.

**4. Foot locking needs the ALS V4 ratchet, not what we have.** Capture the
world anchor when the lock curve hits 1; each frame subtract the root's per-frame
delta so the foot stays world-fixed; blend over 2–4 frames; **never unlock while
the lock weight is still rising**; release slightly before toe-off. Our current
implementation has no ratchet, which is where the residual pops come from.

**5. SIMBICON's structure is portable without physics.** Its finite state machine
(stance/swing states, contact-triggered transitions, world-frame swing-hip
targets, two-phase step) is what makes it robust. The PD torque servos and
balance feedback are not portable — they need a dynamics simulator we do not have
and do not want. Take the FSM, drop the servos, author the lean and sway.

## Skeleton: 15 → 22 joints

Agent research put the hand-authorable sweet spot at 15–25 joints, with the
warning that a joint only earns its keep if it moves ≥ ~4 px at 512×512 (≈2 cm).
Spend the new joints where they pay: a separate thorax segment, and a real
**ankle–toe–heel foot** (this is what makes a foot look planted rather than
floating — planted flat means `toe.y == heel.y == ground`).

```
pelvis (root)
├ lumbar → thorax → neck → head → head_top
├ thorax → shoulder_L → elbow_L → wrist_L → hand_L
├ thorax → shoulder_R → elbow_R → wrist_R → hand_R
├ pelvis → knee_L → ankle_L → { toe_L, heel_L }
└ pelvis → knee_R → ankle_R → { toe_R, heel_R }
```
22 joints / 24 bones. Legs stay 0.22 + 0.20 so `GROUND_Y = -0.4198` is preserved.

Note: our existing bone lengths sum to ~0.94 "metres", so they are proportional
units, not metres. Say so explicitly in `skeleton.py` and stop pretending.

## Facing: front / right / left / back

Not one 3D skeleton projected — front and back views of a sagittal walk read
badly (legs overlap, no depth cue). Use **two authored variants sharing one phase
and contact timeline**:

- **side** (mirrored for left/right): the current sagittal walk
- **front/back**: foreshortened stride amplitude + lateral foot offset

Both drive the same `phi` and the same contact events, so the no-slide guarantee
holds in all four facings.

## Scope for the rebuild

**In:** one character; sit, stand, walk; four facings; 22-joint skeleton; foot
locks with the ratchet; skin-separated renderer; the existing QA gates.

**Out (deleted):** all combat, all two-actor scenes, `interactions.py`,
`combat_ik.py`, the ML path (`model.py`, `train.py`, `data_gen.py`,
`onnx_runner.py`, `notebooks/`), `stage_renderer.py` + `src/stage/` (HD scope),
`mcp_server.py`, `audio.py`, `objects.py`, the multi-agent bus tooling, and every
one-off `tools/render_*.py`.

**Kept and reused:** `puppet/easing.py`, `puppet/armature.py` (timeline + IK),
`puppet/controllers.py` (phase-oscillator gait — closest thing we have to a real
walk cycle), `renderer.py`'s 512×512 pipeline, `camera.py`, `planner.py` (the
LLM seam), `doctor.py` / `motion_quality.py` / `visual_inspector.py`,
`video_encode.py`.

## Sequencing

Ordered so that each step is verifiable before the next begins.

| # | Step | Done when |
|---|---|---|
| 0 | Tag the current tree as the last known-good patched engine | tag exists |
| 1 | New `src/engine/` package: 22-joint skeleton + FK | FK unit tests pass, old rig untouched |
| 2 | Root-derived-from-anchor walk core | **foot travel inside a grounded run < 2 mm** |
| 3 | Foot lock with the ALS ratchet | no pop at lock/release; no float |
| 4 | `stand`, then `sit` | both clean under the same gates |
| 5 | Facing: side + front/back variants | all four facings pass the same gate |
| 6 | Skin-separated renderer (plain / thick) | same skeleton, two appearances, byte-identical joints |
| 7 | Delete the old scope | `pytest` green on the new tree alone |
| 8 | Slim `parser.py` / `contract.py` / `scene.py` to one actor | prompt → clip works end to end |

Step 2 is the one that matters. If foot travel is not under 2 mm there, stop and
fix it rather than moving on.

## Risks

- `rig.py`'s constants (14 bones / 15 joints / `FEAT_DIM=30`) are load-bearing in
  ~36 files. This is why the new core goes in a **separate package first** rather
  than editing in place — a previous agent collision in this repo left a broken
  HEAD at `47391bf` and that must not recur.
- Deleting before the new core is green would leave no working engine. Step 7 is
  deliberately late.
- No git remote exists yet, so local tags are the only rollback.
