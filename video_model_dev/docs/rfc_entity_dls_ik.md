# RFC: Platform Stickman Entity & Target-Driven DLS IK (TASK-013)

Status: prototype implemented (`src/entity.py`), 7/7 unit tests green.
Supersedes ad-hoc posing for all future control work. Legacy 15-joint
`src/rig.py` stays untouched until migration.

## 1. Why an entity model

Video-first scripting produced brittle one-off timelines (dead-air holds,
moonwalk dispatch bugs, missing recipient reactions). A shared body model
with enforced biomechanics makes bad motion unrepresentable instead of
merely discouraged. Controllers (OC2) target the entity API; the renderer
draws whatever the entity holds. Nothing learns pixels.

## 2. Rig specification (17 joints, planar 2D, +x right, +y DOWN)

Hierarchy (parent, length, rest direction), normalized height ~= 1.0:

| Joint | Parent | Len | Notes |
|---|---|---|---|
| pelvis | — | 0 | root, translation only |
| spine | pelvis | 0.12 | NEW vs legacy rig |
| chest | spine | 0.12 | NEW vs legacy rig |
| neck | chest | 0.10 | |
| head | neck | 0.08 | |
| shoulder_l/r | chest | 0.03 | clavicle nub |
| elbow_l/r | shoulder | 0.16 | |
| hand_l/r | elbow | 0.15 | end effectors |
| hip_l/r | pelvis | 0.03 | |
| knee_l/r | hip | 0.22 | |
| ankle_l/r | knee | 0.22 | feet via foot_roll overlay (no toe joints by design) |

### Biomechanical limits (radians, enforced by `clamp_limits`)

Hinges are one-sided (knee/elbow never hyperextend); ball joints symmetric.
Ankle range composes with the Phase-3 `foot_roll` overlay (bounded ±0.5).

- spine ±25°, chest ±20°, neck ±60°, head ±40°
- shoulder ±170°, elbow 0..145° (mirrored per side)
- hip −30°..+120°, knee 0..150°, ankle ±45°

### Mass, CoM, capsules, anchors, sensors

- Segment masses sum to 1.0; `com()` = midpoint-weighted centroid.
- Collision capsule radii per segment (e.g. chest 0.07, hand 0.022).
- Accessory anchors: sword→hand_r, shield→hand_l, hat→head, cape→chest
  (extends the existing joint-prop renderer contract).
- `foot_contacts(ground_y, tol)` = binary ankle-vs-ground sensors.

## 3. IK design: two layers

- **Fast path (kept):** analytical two-bone IK per limb (`armature.py`).
  O(1), exact, zero-drift stance pinning. Unchanged.
- **Full-body (new):** `solve_reach(entity, target, end_joint, pinned,
  iters=50, damping=0.08, tol=1e-4)` — damped-least-squares Jacobian
  (numeric, eps 1e-6), joint clamp every iteration, stance pins as
  heavy-weighted rows (task priority by construction), FIXED iteration
  count: deterministic, no randomness. Measured: reachable hand target
  converges in 6 iters (<1e-3); pins hold at 0.0 drift; out-of-workspace
  targets stall honestly at the boundary (no wild solutions).

## 4. Balance solver

`support_polygon(contacts)` from planted feet; `balance_correction()`
returns the root-x shift pushing the CoM projection inside support+margin.
Kinematic only by decision: no dynamics engine in v1 (momentum and
follow-through stay in easing/controllers, not simulation).

## 5. Controller contract (for OC2)

```python
solve_reach(entity, target_xy, end_joint="hand_r",
            pinned=None, iters=50, damping=0.08, tol=1e-4) -> (err, iters)
entity.com() / .support_polygon(c) / .balance_correction(c, margin)
entity.foot_contacts() / .clamp_limits() / .fk() / .joint_array()
```

Signature versioned (v1). `pinned` drift tolerance: 1e-6 (project standard).

## 6. Known limits / follow-ups

- `_append_sub_timeline` drops `foot_roll_*` (flagged earlier, unowned card).
- Event `x` coords ignore `initial_x` track shift (pre-existing, minor).
- Migration of legacy 15-joint consumers to the entity: separate card.
- Muscle/strength limits, terrain heightfields: deferred to v2.
