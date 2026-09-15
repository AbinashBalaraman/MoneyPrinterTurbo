"""Target-driven dynamic combat: capsule hit detection, recoil tiers, aimed strikes.

TASK-015 (Brain side). Combines the three research lines:
- striking: analytic 2-bone limb + torso-lean pre-pass at runtime (exact bone
  lengths, <5us); Pi's DLS solve_reach is the offline/authoring cross-check.
- collision: brute-force vectorized 2D capsules, no broadphase, edge-triggered
  HIT events with hysteresis (no 24x retrigger).
- recoil: capture-point tier classifier -> keyframed recovery (no sim);
  corrective shifts computed THROUGH Pi's entity.balance_correction().
New file only; existing modules untouched.
"""
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from src.rig import FPS

# Rig bone order (src/rig.py BONES) and parent joints.
_BONE_PARENT = (0, 1, 2, 3, 2, 5, 2, 7, 0, 9, 10, 0, 12, 13)
# Capsule radii per rig bone (world units, H=1): torso core, head circle,
# limbs slim, striker segments (lowerArm/foot) inflated ~20% for game feel.
RIG_CAPSULE_R = np.array([
    0.030, 0.030, 0.020, 0.040,   # spine, chest, neck, head
    0.018, 0.022, 0.018, 0.022,   # upperArmL, lowerArmL, upperArmR, lowerArmR
    0.018, 0.016, 0.022,          # upperLegL, lowerLegL, footL
    0.018, 0.016, 0.022,          # upperLegR, lowerLegR, footR
], dtype=np.float64)
_RSUM = RIG_CAPSULE_R[:, None] + RIG_CAPSULE_R[None, :]

# Striker end-effector joints (rig joint indices).
STRIKERS = {"hand_l": 6, "hand_r": 8, "foot_l": 11, "foot_r": 14}

# Capture-point constants (normalized height H=1).
_OMEGA0 = 3.3
_SUPPORT_HALF = 0.22
_MARGIN = 0.03
_LEAN_LIMIT = 0.10
_STEP_REACH = 0.45


def _point_seg(p, a, b):
    """Closest distance between points p and segments a->b (broadcastable, (...,2))."""
    ab = b - a
    denom = np.maximum((ab * ab).sum(axis=-1, keepdims=True), 1e-12)
    t = np.clip(((p - a) * ab).sum(axis=-1, keepdims=True) / denom, 0.0, 1.0)
    c = a + t * ab
    return np.linalg.norm(p - c, axis=-1), c


def _seg_intersect(p1, q1, p2, q2):
    """Boolean segment intersection via orient2d signs, broadcastable."""
    def orient(a, b, c):
        return (b[..., 0] - a[..., 0]) * (c[..., 1] - a[..., 1]) - \
               (b[..., 1] - a[..., 1]) * (c[..., 0] - a[..., 0])
    o1, o2 = orient(p1, q1, p2), orient(p1, q1, q2)
    o3, o4 = orient(p2, q2, p1), orient(p2, q2, q1)
    return ((o1 > 0) != (o2 > 0)) & ((o3 > 0) != (o4 > 0))


def capsule_matrix(ja: np.ndarray, jb: np.ndarray):
    """All-pairs capsule distances between fighter A and B skeletons.

    Args: ja, jb (15, 2) joint arrays. Returns (hit(14,14) bool, dmin(14,14)).
    """
    a1_seg = ja[np.array(_BONE_PARENT)]
    a2_seg = ja[1:]
    b1_seg = jb[np.array(_BONE_PARENT)]
    b2_seg = jb[1:]
    a1 = a1_seg[:, None, :]
    a2 = a2_seg[:, None, :]
    b1 = b1_seg[None, :, :]
    b2 = b2_seg[None, :, :]
    d1, _ = _point_seg(a1, b1, b2)
    d2, _ = _point_seg(a2, b1, b2)
    d3, _ = _point_seg(b1, a1, a2)
    d4, _ = _point_seg(b2, a1, a2)
    dmin = np.minimum(np.minimum(d1, d2), np.minimum(d3, d4))
    crossed = _seg_intersect(a1, a2, b1, b2)
    dmin = np.where(crossed, 0.0, dmin)
    return dmin < _RSUM, dmin


def capsule_contacts(ja: np.ndarray, jb: np.ndarray) -> List[Dict[str, Any]]:
    """Contact descriptors (bone pair, depth, normal, points) for active hits."""
    a1_seg = ja[np.array(_BONE_PARENT)]
    a2_seg = ja[1:]
    b1_seg = jb[np.array(_BONE_PARENT)]
    b2_seg = jb[1:]
    a1 = a1_seg[:, None, :]
    a2 = a2_seg[:, None, :]
    b1 = b1_seg[None, :, :]
    b2 = b2_seg[None, :, :]
    pairs = [(_point_seg(a1, b1, b2), 0), (_point_seg(a2, b1, b2), 1),
             (_point_seg(b1, a1, a2), 2), (_point_seg(b2, a1, a2), 3)]
    dstack = np.stack([p[0][0] for p in pairs], axis=-1)
    order = np.argmin(dstack, axis=-1)
    dmin = np.take_along_axis(dstack, order[..., None], axis=-1)[..., 0]
    crossed = _seg_intersect(a1, a2, b1, b2)
    dmin = np.where(crossed, 0.0, dmin)
    out = []
    ii, jj = np.where(dmin < _RSUM)
    for i, j in zip(ii.tolist(), jj.tolist()):
        k = int(order[i, j])
        c1 = pairs[k][0][1][i, j]
        # Counterpart point on the other segment.
        if k in (0, 1):
            _, c2 = _point_seg(c1, b1_seg[j], b2_seg[j])
        else:
            _, c2 = _point_seg(c1, a1_seg[i], a2_seg[i])
        d = float(dmin[i, j])
        if d > 1e-9:
            n = (c1 - c2) / d
        else:  # degenerate crossing: defender-segment perpendicular, facing attacker
            seg = (b2_seg[j] - b1_seg[j])
            n = np.array([-seg[1], seg[0]])
            nrm = float(np.linalg.norm(n))
            n = n / nrm if nrm > 1e-9 else np.array([1.0, 0.0])
            if float(np.dot(n, c1 - c2)) < 0:
                n = -n
        out.append({"bone_a": int(i), "bone_b": int(j), "depth": float(_RSUM[i, j] - d),
                    "normal": n.astype(float), "point_a": c1.astype(float),
                    "point_b": c2.astype(float)})
    return out


class HitTracker:
    """Edge-triggered HIT events: ARMED (attack + closing speed) -> contact -> cooldown."""

    def __init__(self, v_min: float = 0.5, cooldown_s: float = 0.3, fps: int = FPS):
        self.v_min = float(v_min)
        self.cooldown = int(round(cooldown_s * fps))
        self._state = {s: "IDLE" for s in STRIKERS}
        self._cool = {s: 0 for s in STRIKERS}
        self._prev = {}

    def update(self, frame_idx: int, ja: np.ndarray, jb: np.ndarray,
               armed: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
        """One step; armed maps striker name -> attack-active flag (default all True)."""
        armed = armed or {}
        hits = []
        cur = {s: np.asarray(ja[j], dtype=float) for s, j in STRIKERS.items()}
        prev = self._prev or {s: p.copy() for s, p in cur.items()}
        hit, dmin = capsule_matrix(np.asarray(ja, dtype=float), np.asarray(jb, dtype=float))
        contacts = {(c["bone_a"], c["bone_b"]): c for c in capsule_contacts(
            np.asarray(ja, dtype=float), np.asarray(jb, dtype=float))}
        striker_bones = {"hand_l": 5, "hand_r": 7, "foot_l": 10, "foot_r": 13}
        for s, j in STRIKERS.items():
            vel = (cur[s] - prev[s]) * FPS
            speed = float(np.linalg.norm(vel))
            touching = any((striker_bones[s] == c["bone_a"]) for c in contacts.values())
            if self._cool[s] > 0:
                self._cool[s] -= 1
                if self._cool[s] == 0 and self._state[s] == "CONTACT":
                    self._state[s] = "COOLDOWN"
                continue
            if self._state[s] == "COOLDOWN":
                # Re-arm only after observed separation (no dwell retrigger).
                if not touching:
                    self._state[s] = "IDLE"
                continue
            if self._state[s] == "IDLE":
                attack_active = armed.get(s, True)
                # Explicit caller flags mean "attack in progress" (trust + contact
                # confirms); auto-detect (absent flag) additionally needs speed.
                if attack_active and (speed > self.v_min or s in armed):
                    self._state[s] = "ARMED"
            elif self._state[s] == "ARMED":
                if touching:
                    self._state[s] = "CONTACT"
                    self._cool[s] = self.cooldown
                    hits.append({"frame": int(frame_idx), "striker": s,
                                 "speed": speed, "joint": int(j)})
                elif speed <= self.v_min * 0.5:
                    self._state[s] = "IDLE"
        self._prev = cur
        return hits


# ------------------------------------------------------- rig <-> entity bridge
def rig_to_entity(root_xy, angles14):
    """Approximate rig pose -> Pi Body entity (documents its three approximations).

    1. Lateral shoulder/hip offsets (0.03) zeroed: upperArm->elbow hinge,
       lowerArm->hand, thigh->knee hinge, shin->ankle.
    2. Foot/toe segments have no entity counterpart and are dropped.
    3. Shin length 0.20 (rig) vs 0.22 (entity): angles transfer, positions
       re-derived per skeleton, so ~cm-level FK differences are expected.
    Used for balance math and DLS cross-checks, never for rendered output.
    """
    from src.entity import StickmanEntity
    a = np.asarray(angles14, dtype=float).reshape(14)
    ent = StickmanEntity(root_xy=tuple(map(float, np.asarray(root_xy).reshape(2))))
    ent.angles.update({
        "spine": float(a[0]), "chest": float(a[1]), "neck": float(a[2]), "head": float(a[3]),
        "shoulder_l": 0.0, "elbow_l": float(a[4]), "hand_l": float(a[5]),
        "shoulder_r": 0.0, "elbow_r": float(a[6]), "hand_r": float(a[7]),
        "hip_l": 0.0, "knee_l": float(a[8]), "ankle_l": float(a[9]),
        "hip_r": 0.0, "knee_r": float(a[11]), "ankle_r": float(a[12]),
    })
    ent.clamp_limits()
    return ent


def balance_shift(root_xy, angles14, contacts, margin: float = 0.02) -> float:
    """Root-x correction computed THROUGH entity.balance_correction()."""
    ent = rig_to_entity(root_xy, angles14)
    contact_names = []
    for c in contacts:
        contact_names.append({"left_foot": "ankle_l", "right_foot": "ankle_r",
                              "both_feet": None}.get(c, c))
    flat = []
    for c in contact_names:
        flat.extend(["ankle_l", "ankle_r"] if c is None else [c])
    return float(ent.balance_correction(flat, margin=margin))


# ------------------------------------------------------- recoil tiers (no sim)
@dataclass
class RecoilPlan:
    tier: str            # "lean" | "stagger" | "fall"
    x_cap: float
    pelvis_shift: float  # world units along push direction
    lean_deg: float
    dip: float           # pelvis drop (world units, positive number)
    step_x: Optional[float] = None  # stagger target, None when no step


def classify_recoil(push_p: float, com_x: float = 0.0,
                    support: Tuple[float, float] = (-0.22, 0.22)) -> RecoilPlan:
    """Capture-point tier classifier (one-shot, no integration).

    push_p: imparted velocity in heights/s (jab .3 / cross .6 / heavy 1.2 / KO >1.8).
    """
    lo, hi = support
    x_cap = float(com_x) + float(push_p) / _OMEGA0
    offset = abs(float(push_p)) / _OMEGA0
    direction = 1.0 if push_p >= 0 else -1.0
    if offset <= _LEAN_LIMIT and (lo + _MARGIN) <= x_cap <= (hi - _MARGIN):
        return RecoilPlan("lean", x_cap,
                          pelvis_shift=direction * float(np.clip(0.12 * abs(push_p), 0.03, 0.25)),
                          lean_deg=direction * float(np.clip(15 * abs(push_p), 5.0, 22.0)),
                          dip=0.0)
    if offset <= _STEP_REACH:
        step_x = float(x_cap) + direction * 0.05
        return RecoilPlan("stagger", x_cap,
                          pelvis_shift=direction * float(np.clip(0.12 * abs(push_p), 0.03, 0.25)),
                          lean_deg=direction * float(np.clip(15 * abs(push_p), 5.0, 22.0)),
                          dip=0.012, step_x=step_x)
    return RecoilPlan("fall", x_cap, pelvis_shift=direction * 0.25,
                      lean_deg=direction * 22.0, dip=0.012, step_x=None)


def recoil_keyframes(start_x: float, plan: RecoilPlan, direction: float = 1.0,
                     fps: int = FPS):
    """Keyframe list (dicts) for the recoil recipe @24fps; stance-safe holds.

    Tier lean: recoil-out (8f) -> hold (4f) -> spring-back (24f, 10% overshoot).
    Tier stagger: recoil-out -> hold -> swing step (14f) -> re-center (30f).
    Tier fall: recoil-out, then caller chains the knockdown clip.
    """
    s = 1.0 if direction >= 0 else -1.0
    kfs = [
        {"t": 0.0, "pose": "stand_relaxed", "root_x": float(start_x),
         "hold_duration_s": 0.0, "easing": "ease_in"},
        {"t": 8 / fps, "pose": "hit_recoil", "root_x": float(start_x) + s * plan.pelvis_shift,
         "root_y": -plan.dip, "hold_duration_s": 4 / fps, "easing": "ease_out",
         "moving_hold": False},
    ]
    if plan.tier == "lean":
        kfs.append({"t": 36 / fps, "pose": "stand_relaxed",
                    "root_x": float(start_x) - s * plan.pelvis_shift * 0.10,
                    "hold_duration_s": 0.25, "easing": "ease_in_out"})
        kfs.append({"t": 42 / fps, "pose": "stand_relaxed", "root_x": float(start_x),
                    "hold_duration_s": 0.5, "easing": "ease_in_out"})
    elif plan.tier == "stagger" and plan.step_x is not None:
        kfs.append({"t": 16 / fps, "pose": "hit_recoil",
                    "root_x": float(start_x) + s * plan.pelvis_shift,
                    "root_y": -plan.dip, "hold_duration_s": 0.0, "easing": "ease_in",
                    "moving_hold": False})
        kfs.append({"t": 30 / fps, "pose": "stride_pass_L" if s > 0 else "stride_pass_R",
                    "root_x": float(start_x) + plan.step_x, "hold_duration_s": 0.0,
                    "easing": "ease_in_out"})
        kfs.append({"t": 60 / fps, "pose": "stand_relaxed",
                    "root_x": float(start_x) + plan.step_x * 0.6,
                    "hold_duration_s": 0.5, "easing": "ease_in_out"})
    return kfs


# ------------------------------------------------------- analytic aimed strike
_LIMB = {
    # end_joint: (proximal bone idx, distal bone idx, l1, l2, abs-parent bone idx|None, bend)
    "hand_r": (6, 7, 0.16, 0.15, 1, True),
    "hand_l": (4, 5, 0.16, 0.15, 1, True),
    "foot_l": (8, 9, 0.22, 0.20, None, True),
    "foot_r": (11, 12, 0.22, 0.20, None, True),
}


def _abs_angles(ang14: np.ndarray) -> np.ndarray:
    """Absolute bone angles under rig FK convention (parents chain)."""
    from src.rig import BONES
    a = np.asarray(ang14, dtype=float).reshape(14)
    parents_bone = [-1, 0, 1, 2, 1, 4, 1, 6, -1, 8, 9, -1, 11, 12]
    out = np.zeros(14)
    for i in range(14):
        p = parents_bone[i]
        out[i] = a[i] if p == -1 else out[p] + a[i]
    return out


def solve_aimed_limb(root_xy, base_angles, target_xy, end_joint="hand_r",
                     max_lean: float = 0.25):
    """Analytic strike solver: torso-lean pre-pass + 2-bone limb (runtime path).

    Returns (angles14, residual, lean_used). Residual > 0 = target beyond reach
    (end-effector stalls honestly on the S->T ray); never NaN.
    """
    from src.rig import BONES, forward_kinematics
    if end_joint not in _LIMB:
        raise ValueError(f"unsupported end_joint {end_joint!r}")
    pb, db, l1, l2, parent_bone, bend = _LIMB[end_joint]
    ang = np.asarray(base_angles, dtype=float).reshape(14).copy()
    root = np.asarray(root_xy, dtype=float).reshape(2)
    target = np.asarray(target_xy, dtype=float).reshape(2)

    def shoulder_of(ang_v):
        j = forward_kinematics(root[None, :], ang_v[None, :])[0]
        return j[_BONE_PARENT[pb]], j

    abs_ang = _abs_angles(ang)
    lean_used = 0.0
    S, _ = shoulder_of(ang)
    vec = target - S
    dist = float(np.linalg.norm(vec))
    reach = l1 + l2
    if dist > reach and dist > 1e-9:
        lean = float(np.clip(0.8 * (dist - reach), -max_lean, max_lean))
        lean *= 1.0 if vec[0] >= 0 else -1.0
        ang[0] += 0.4 * lean
        ang[1] += 0.6 * lean
        lean_used = lean
        abs_ang = _abs_angles(ang)
        S, _ = shoulder_of(ang)
        vec = target - S
        dist = float(np.linalg.norm(vec))

    if dist < 1e-9:
        return ang, 0.0, lean_used
    d_cl = float(np.clip(dist, abs(l1 - l2) + 1e-6, (l1 + l2) * 0.9999))
    ux, uy = vec / dist
    psi = float(np.arctan2(ux, -uy))
    cos_a = float(np.clip((l1 * l1 + d_cl * d_cl - l2 * l2) / (2 * l1 * d_cl), -1.0, 1.0))
    cos_g = float(np.clip((l1 * l1 + l2 * l2 - d_cl * d_cl) / (2 * l1 * l2), -1.0, 1.0))
    alpha, gamma = float(np.arccos(cos_a)), float(np.arccos(cos_g))
    abs_prox = psi + (alpha if bend else -alpha)
    rel_dist = -(float(np.pi) - gamma)
    abs_parent = float(abs_ang[parent_bone]) if parent_bone is not None else 0.0
    ang[pb] = abs_prox - abs_parent
    ang[db] = rel_dist
    return ang, max(0.0, dist - (l1 + l2)), lean_used
