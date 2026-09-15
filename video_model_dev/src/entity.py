"""Platform Entity: comprehensive 17-joint stickman rig (TASK-013).

Additive prototype beside the legacy 15-joint rig: joint hierarchy with
biomechanical limits, segment masses / CoM, collision capsules, accessory
anchors, foot contact sensors, and a deterministic DLS full-body IK solver
with task priorities (stance pins > reach target > balance).

Conventions: planar 2D, +x right, +y DOWN (screen space, matches renderer).
Angles are relative joint rotations (radians); FK accumulates along chains.
All solvers use fixed iteration counts: no randomness, fully deterministic.
"""

import math
import numpy as np

# ---------------------------------------------------------------- hierarchy
# parent, length (normalized height ~= 1.0), rest direction (unit xy)
_JOINTS = [
    # name,        parent,      length, rest_dir
    ("pelvis",     None,        0.0,    (0.0, 0.0)),
    ("spine",      "pelvis",    0.12,   (0.0, -1.0)),
    ("chest",      "spine",     0.12,   (0.0, -1.0)),
    ("neck",       "chest",     0.10,   (0.0, -1.0)),
    ("head",       "neck",      0.08,   (0.0, -1.0)),
    ("shoulder_l", "chest",     0.03,   (-1.0, 0.0)),
    ("elbow_l",    "shoulder_l", 0.16,  (0.0, 1.0)),
    ("hand_l",     "elbow_l",   0.15,   (0.0, 1.0)),
    ("shoulder_r", "chest",     0.03,   (1.0, 0.0)),
    ("elbow_r",    "shoulder_r", 0.16,  (0.0, 1.0)),
    ("hand_r",     "elbow_r",   0.15,   (0.0, 1.0)),
    ("hip_l",      "pelvis",    0.03,   (-1.0, 0.0)),
    ("knee_l",     "hip_l",     0.22,   (0.0, 1.0)),
    ("ankle_l",    "knee_l",    0.22,   (0.0, 1.0)),
    ("hip_r",      "pelvis",    0.03,   (1.0, 0.0)),
    ("knee_r",     "hip_r",     0.22,   (0.0, 1.0)),
    ("ankle_r",    "knee_r",    0.22,   (0.0, 1.0)),
]
NAMES = [j[0] for j in _JOINTS]
INDEX = {n: i for i, n in enumerate(NAMES)}
N = len(NAMES)
assert N == 17

# ------------------------------------------------- biomechanical limits (rad)
# (min, max) relative rotation. Hinges are one-sided; ball joints symmetric.
_d = math.radians
LIMITS = {
    "spine":      (_d(-25), _d(25)),
    "chest":      (_d(-20), _d(20)),
    "neck":       (_d(-60), _d(60)),
    "head":       (_d(-40), _d(40)),
    "shoulder_l": (_d(-170), _d(170)),
    "shoulder_r": (_d(-170), _d(170)),
    "elbow_l":    (_d(0), _d(145)),     # hinge, no hyperextension
    "elbow_r":    (_d(-145), _d(0)),    # mirrored hinge
    "hip_l":      (_d(-30), _d(120)),
    "hip_r":      (_d(-30), _d(120)),
    "knee_l":     (_d(0), _d(150)),     # hinge, no backward bend
    "knee_r":     (_d(0), _d(150)),
    "ankle_l":    (_d(-45), _d(45)),    # + foot_roll overlay composes on top
    "ankle_r":    (_d(-45), _d(45)),
}
for _n in ("pelvis", "shoulder_l", "shoulder_r", "hip_l", "hip_r",
           "hand_l", "hand_r"):
    LIMITS.setdefault(_n, (_d(-170), _d(170)))

# ------------------------------------------------------------- mass / CoM
# Segment masses (fraction of body weight) keyed by distal joint.
MASS = {
    "head": 0.08, "neck": 0.02, "chest": 0.20, "spine": 0.12,
    "elbow_l": 0.03, "hand_l": 0.02, "elbow_r": 0.03, "hand_r": 0.02,
    "knee_l": 0.10, "ankle_l": 0.05, "knee_r": 0.10, "ankle_r": 0.05,
    "pelvis": 0.18,
}
# Collision capsule radii (world units) per segment.
CAPSULE_R = {
    "head": 0.055, "chest": 0.07, "spine": 0.06,
    "elbow_l": 0.025, "hand_l": 0.022, "elbow_r": 0.025, "hand_r": 0.022,
    "knee_l": 0.04, "ankle_l": 0.032, "knee_r": 0.04, "ankle_r": 0.032,
}
# Accessory anchor joints (renderer prop system attaches here).
ANCHORS = {"sword_hand": "hand_r", "shield_hand": "hand_l",
           "hat": "head", "cape": "chest"}

# ------------------------------------------------------------------- entity
class StickmanEntity:
    """A posable, limit-checked stickman figure."""

    def __init__(self, root_xy=(0.0, 0.0), scale=1.0):
        self.root = np.array(root_xy, dtype=np.float64)
        self.scale = float(scale)
        self.angles = {n: 0.0 for n in NAMES}

    # -- kinematics --------------------------------------------------
    def fk(self):
        """Forward kinematics -> dict name -> (x, y). Deterministic."""
        pos = {"pelvis": self.root.copy()}
        ang_acc = {}  # accumulated absolute direction angle per joint chain

        def _dir(name):
            # absolute direction of bone ENDING at `name`
            for (jn, parent, length, rest) in _JOINTS:
                if jn == name:
                    break
            base = math.atan2(rest[1], rest[0]) if length > 0 else 0.0
            # accumulate relative rotations from pelvis root of this chain
            chain = []
            cur = name
            pmap = {j[0]: (j[1], j[2], j[3]) for j in _JOINTS}
            while cur is not None and cur != "pelvis":
                chain.append(cur)
                cur = pmap[cur][0]
            total = base
            for c in reversed(chain):
                total += self.angles.get(c, 0.0)
            return total, pmap[name][1]

        order = ["spine", "chest", "neck", "head",
                 "shoulder_l", "elbow_l", "hand_l",
                 "shoulder_r", "elbow_r", "hand_r",
                 "hip_l", "knee_l", "ankle_l",
                 "hip_r", "knee_r", "ankle_r"]
        pmap = {j[0]: j[1] for j in _JOINTS}
        for name in order:
            parent = pmap[name]
            total, length = _dir(name)
            dx, dy = math.cos(total) * length * self.scale, math.sin(total) * length * self.scale
            px, py = pos[parent]
            pos[name] = np.array([px + dx, py + dy])
        return pos

    def joint_array(self):
        p = self.fk()
        return np.stack([p[n] for n in NAMES])

    # -- limits ------------------------------------------------------
    def clamp_limits(self):
        """Clamps all angles into LIMITS. Returns max violation before clamp."""
        worst = 0.0
        for n, (lo, hi) in LIMITS.items():
            a = self.angles.get(n, 0.0)
            worst = max(worst, lo - a if a < lo else (a - hi if a > hi else 0.0))
            self.angles[n] = min(hi, max(lo, a))
        return worst

    # -- mass / balance ----------------------------------------------
    def com(self):
        """Center of mass from segment masses (segment midpoint weighting)."""
        p = self.fk()
        pmap = {j[0]: j[1] for j in _JOINTS}
        total, acc = 0.0, np.zeros(2)
        for name, m in MASS.items():
            parent = pmap[name]
            mid = p[name] if parent is None else (p[parent] + p[name]) / 2.0
            acc += m * mid
            total += m
        return acc / total

    def support_polygon(self, contacts):
        """Support interval [min_x, max_x] from planted foot x positions."""
        xs = [float(self.fk()[c][0]) for c in contacts]
        return (min(xs), max(xs)) if xs else (0.0, 0.0)

    def balance_correction(self, contacts, margin=0.02):
        """Root-x shift pushing CoM projection inside support (+margin)."""
        com_x = float(self.com()[0])
        lo, hi = self.support_polygon(contacts)
        if com_x < lo + margin:
            return (lo + margin) - com_x
        if com_x > hi - margin:
            return (hi - margin) - com_x
        return 0.0

    # -- contact sensors ----------------------------------------------
    def foot_contacts(self, ground_y=0.45, tol=0.02):
        """Binary foot-ground contact from ankle height vs ground plane."""
        p = self.fk()
        return {f: bool(p[f][1] >= ground_y - tol)
                for f in ("ankle_l", "ankle_r")}


# ------------------------------------------------------------------ IK DLS
def _angle_vector(ent):
    return np.array([ent.angles[n] for n in NAMES], dtype=np.float64)


def _set_angles(ent, vec):
    for i, n in enumerate(NAMES):
        ent.angles[n] = float(vec[i])
    ent.clamp_limits()


def solve_reach(entity, target_xy, end_joint="hand_r", pinned=None,
                iters=50, damping=0.08, tol=1e-4):
    """Target-driven full-body IK (damped least squares, deterministic).

    Drives `end_joint` to `target_xy` while holding `pinned` joints
    ({name: (x, y)}, heavy-weighted) and clamping LIMITS every iteration.
    Two-bone analytic IK remains the fast path for isolated limbs; use this
    when torso/hip compensation is required. Fixed iteration count.
    Returns (final_error, iters_used).
    """
    target = np.array(target_xy, dtype=np.float64)
    pinned = pinned or {}
    pin_names = list(pinned.keys())
    pin_targets = [np.array(pinned[n], dtype=np.float64) for n in pin_names]
    W_PIN = 10.0
    eps = 1e-6

    dof = [n for n in NAMES if n != "pelvis"]
    idx = {n: k for k, n in enumerate(dof)}

    def snapshot():
        p = entity.fk()
        e = np.concatenate([
            (p[end_joint] - target),
            *[W_PIN * (p[n] - t) for n, t in zip(pin_names, pin_targets)],
        ])
        return e

    for it in range(iters):
        err = snapshot()
        if float(np.linalg.norm(err[:2])) < tol:
            return float(np.linalg.norm(err[:2])), it + 1
        m = len(err)
        n = len(dof)
        J = np.zeros((m, n))
        base = _angle_vector(entity)
        for k, name in enumerate(dof):
            pert = base.copy()
            pert[INDEX[name]] += eps
            _set_angles(entity, pert)
            J[:, k] = (snapshot() - err) / eps
        _set_angles(entity, base)
        # DLS step
        A = J @ J.T + (damping ** 2) * np.eye(m)
        step = J.T @ np.linalg.solve(A, -err)
        vec = base.copy()
        for k, name in enumerate(dof):
            if name in idx:
                vec[INDEX[name]] += step[idx[name]]
        _set_angles(entity, vec)
    return float(np.linalg.norm(snapshot()[:2])), iters
