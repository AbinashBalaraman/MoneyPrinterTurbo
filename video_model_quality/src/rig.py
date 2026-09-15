"""Rig definition + forward kinematics (numpy only, runs anywhere)."""
import numpy as np

FPS = 24
CLIP_LEN_5S = 120  # 5s x 24fps

# 14 bones: (name, parent_joint, length)
# True joint map (verified via FK probe 2026-09-10):
# 0 pelvis(root), 1 abdomen, 2 chest, 3 neck-base, 4 head-center,
# 5 elbowL, 6 handL, 7 elbowR, 8 handR,
# 9 kneeL, 10 ankleL, 11 toeL, 12 kneeR, 13 ankleR, 14 toeR
# (shoulders sit ON the chest joint; hips sit ON the pelvis joint)
# -> 15 joints, root = joint 0 xy. 14 angles -> D = 2 + 14*2 = 30.
BONES = [
    ("spine",     0, 0.14),
    ("chest",     1, 0.14),
    ("neck",      2, 0.06),
    ("head",      3, 0.11),
    ("upperArmL", 2, 0.16),
    ("lowerArmL", 5, 0.15),
    ("upperArmR", 2, 0.16),
    ("lowerArmR", 7, 0.15),
    ("upperLegL", 0, 0.22),
    ("lowerLegL", 9, 0.20),
    ("footL",    10, 0.07),
    ("upperLegR", 0, 0.22),
    ("lowerLegR", 12, 0.20),
    ("footR",    13, 0.07),
]
N_BONES = len(BONES)  # 14
FEAT_DIM = 2 + N_BONES * 2  # 30

# rest pose: relative angles (radians, 0 = pointing up, + = clockwise)
# Natural grounded profile standing with slight knee ease (no locking/stilts)
REST_ANGLES = np.array([
    0.0,    # spine
    0.0,    # chest
    0.0,    # neck
    0.0,    # head
    0.10,   # upperArmL (hanging naturally at side)
   -0.15,   # lowerArmL
   -0.10,   # upperArmR
   -0.15,   # lowerArmR
    0.035,  # upperLegL (~2 deg ease)
   -0.070,  # lowerLegL (~-4 deg knee micro-flex)
    1.605,  # footL (flat on ground, parallel to floor)
    0.035,  # upperLegR
   -0.070,  # lowerLegR
    1.605,  # footR (flat on ground, parallel to floor)
], dtype=np.float32)


def decode(feat):
    """feat (...,30) -> root_xy (...,2), angles (...,14). Normalizes sin/cos."""
    feat = np.asarray(feat, dtype=np.float32)
    root = feat[..., :2]
    sc = feat[..., 2:].reshape(feat.shape[:-1] + (N_BONES, 2))
    norm = np.sqrt((sc ** 2).sum(-1, keepdims=True)) + 1e-8
    sc = sc / norm
    angles = np.arctan2(sc[..., 0], sc[..., 1])
    return root, angles


def encode(root_xy, angles):
    """root (...,2), angles (...,14) -> feat (...,30)."""
    root_xy = np.asarray(root_xy, dtype=np.float32)
    angles = np.asarray(angles, dtype=np.float32)
    sc = np.stack([np.sin(angles), np.cos(angles)], axis=-1)
    return np.concatenate([root_xy, sc.reshape(sc.shape[:-2] + (N_BONES * 2,))], axis=-1)


def forward_kinematics(root_xy, angles):
    """Relative angles -> joint positions. Returns (...,15,2) in world units (height~1.0)."""
    root_xy = np.asarray(root_xy, dtype=np.float32)
    angles = np.asarray(angles, dtype=np.float32)
    prefix = root_xy.shape[:-1]
    T = int(np.prod(prefix)) if prefix else 1
    r = root_xy.reshape(T, 2)
    a = angles.reshape(T, N_BONES)
    joints = np.zeros((T, 15, 2), dtype=np.float32)
    joints[:, 0] = r
    # absolute angle = sum of relative angles along chain
    abs_ang = np.zeros((T, N_BONES), dtype=np.float32)
    # parent bone index in chain (-1 = root / independent base)
    # torso: spine(0)<-root, chest(1)<-spine(0), neck(2)<-chest(1), head(3)<-neck(2)
    # arms: upperArmL(4)<-chest(1), lowerArmL(5)<-upperArmL(4), upperArmR(6)<-chest(1), lowerArmR(7)<-upperArmR(6)
    # legs: upperLegL(8)<-root, lowerLegL(9)<-upperLegL(8), footL(10)<-lowerLegL(9), upperLegR(11)<-root, etc.
    parents_bone = [-1, 0, 1, 2, 1, 4, 1, 6, -1, 8, 9, -1, 11, 12]
    # base direction along Y: torso points UP (+1), limbs point DOWN (-1)
    base_sign = np.array([1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1], dtype=np.float32)
    for i in range(N_BONES):
        p = parents_bone[i]
        if p == -1:
            abs_ang[:, i] = a[:, i]
        else:
            abs_ang[:, i] = abs_ang[:, p] + a[:, i]
        _, pj, ln = BONES[i]
        d = np.stack([np.sin(abs_ang[:, i]), base_sign[i] * np.cos(abs_ang[:, i])], axis=-1) * ln
        joints[:, i + 1] = joints[:, pj] + d
    return joints.reshape(prefix + (15, 2))


def _rest_ground_y() -> float:
    """World ground plane, DERIVED from the rest pose — never hardcoded.

    The ground is by definition the lowest joint of the rest pose, so if a leg
    bone length or a rest angle changes, the ground follows automatically and
    feet can never float or sink as a side effect of a proportion tweak.
    """
    rest = forward_kinematics(np.zeros(2, dtype=np.float32), REST_ANGLES)
    return float(rest[..., 1].min())


GROUND_Y = _rest_ground_y()  # World ground plane (lowest rest joint, ~-0.4198)


def enforce_ground_contact(feat, ground_y: float = GROUND_Y):
    """Author-time ground consistency: lift the root so no joint penetrates.

    Joint angles are preserved exactly (stance/IK pinning is untouched); only
    the root is translated in +y by the per-frame penetration depth. Frames
    already clear of the ground are returned unchanged, so this is the identity
    for valid motion. Accepts (T, 30) or (30,) and returns the same rank.
    """
    feat = np.asarray(feat, dtype=np.float32)
    single = feat.ndim == 1
    f2 = feat[None, :] if single else feat
    root, angles = decode(f2)
    joints = forward_kinematics(root, angles)
    lowest = joints[..., 1].min(axis=-1)  # (T,) lowest joint per frame
    lift = np.maximum(0.0, ground_y - lowest)
    if float(lift.max()) <= 1e-6:
        return feat
    root = root.copy()
    root[:, 1] += lift.astype(root.dtype)
    out = encode(root, angles).astype(np.float32)
    return out[0] if single else out
