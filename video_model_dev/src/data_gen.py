"""Procedural motion generator: single + paired (fight) clips, 5s @24fps.
Numpy only. Each clip returns dict(feat (T,30*n_person), family_id, label).
"""
import numpy as np
from .rig import REST_ANGLES, encode, FPS, forward_kinematics

ACTIONS_1P = ["idle", "walk", "run", "walkback", "jump", "punch",
              "kick", "block", "wave", "squat", "knockdown", "getup", "celebrate"]
# paired templates for 2-person
ACTIONS_2P = ["punch_block", "kick_dodge", "exchange", "knockdown_getup"]

BONE_IDX = {n: i for i, (n, _, _) in enumerate(
    [("spine", 0, 0), ("chest", 0, 0), ("neck", 0, 0), ("head", 0, 0),
     ("upperArmL", 0, 0), ("lowerArmL", 0, 0), ("upperArmR", 0, 0), ("lowerArmR", 0, 0),
     ("upperLegL", 0, 0), ("lowerLegL", 0, 0), ("footL", 0, 0),
     ("upperLegR", 0, 0), ("lowerLegR", 0, 0), ("footR", 0, 0)])}


def _base(T, seed):
    rng = np.random.default_rng(seed)
    root = np.zeros((T, 2), np.float32)
    ang = np.tile(REST_ANGLES[None, :], (T, 1)).astype(np.float32)
    return rng, root, ang


def _time(T):
    return np.arange(T, dtype=np.float32) / FPS


def gen_single(action, duration_s=5.0, speed=1.0, amplitude=1.0, direction=1, seed=0):
    T = int(duration_s * FPS)
    rng, root, ang = _base(T, seed)
    t = _time(T)
    f = 2 * np.pi * speed
    A = amplitude
    i = BONE_IDX
    if action == "idle":
        ang[:, i["chest"]] += 0.03 * A * np.sin(f * 0.5 * t)
        ang[:, i["upperArmL"]] += 0.05 * A * np.sin(f * 0.5 * t)
        ang[:, i["upperArmR"]] -= 0.05 * A * np.sin(f * 0.5 * t)
    elif action in ("walk", "run", "walkback"):
        base = "walk" if action == "walkback" else action
        freq = 1.6 if base == "walk" else 2.6
        stride = (0.55 if base == "walk" else 0.8) * A
        mirror = (action == "walkback" or direction == -1)
        phase = f * freq * t  # always build forward, mirror feat below if needed
        sw = np.sin(phase) * stride
        ang[:, i["upperLegL"]] += sw
        ang[:, i["upperLegR"]] -= sw
        ang[:, i["lowerLegL"]] += np.maximum(0, -np.sin(phase)) * 0.9 * A
        ang[:, i["lowerLegR"]] += np.maximum(0, np.sin(phase)) * 0.9 * A
        ang[:, i["upperArmL"]] -= sw * 0.7
        ang[:, i["upperArmR"]] += sw * 0.7
        ang[:, i["lowerArmL"]] -= 0.3 * A
        ang[:, i["lowerArmR"]] -= 0.3 * A
        # Add diversity noise BEFORE anchor so the anchor accounts for it.
        ang += rng.normal(0, 0.01, ang.shape).astype(np.float32)
        # Generation-time foot anchor: derive root from stance foot so the
        # planted foot stays fixed in world X (kills foot skate by construction).
        # Stance foot = left foot while sin(phase) >= 0 (lowerLegL is straight/planted),
        # else right foot while sin(phase) < 0 (lowerLegR is straight/planted).
        zeros = np.zeros((T, 2), dtype=np.float32)
        rel = forward_kinematics(zeros, ang)
        fl_x = rel[:, 11, 0].astype(np.float64)
        fr_x = rel[:, 14, 0].astype(np.float64)
        stance_left = np.sin(phase) >= 0
        root_x = np.zeros((T,), dtype=np.float64)
        for tt in range(1, T):
            cur = fl_x[tt] if stance_left[tt] else fr_x[tt]
            prev = fl_x[tt - 1] if stance_left[tt] else fr_x[tt - 1]
            root_x[tt] = root_x[tt - 1] - (cur - prev)
        root[:, 0] = root_x.astype(np.float32)
        root[:, 1] = (0.02 * np.abs(np.sin(phase))).astype(np.float32)
        feat = encode(root, ang)
        if mirror:
            # Mirror feat (not ang): angle a -> -a means sin negates, cos stays.
            # Root y unchanged. This mirrors noise too, preserving the pin.
            feat = feat.copy()
            feat[:, 0] = -feat[:, 0]
            feat[:, 2::2] = -feat[:, 2::2]
        return {"feat": feat, "family_id": f"1p-{action}",
                "label": action, "n_person": 1, "T": T}
    elif action == "jump":
        # one jump centered
        c = T // 2
        w = int(FPS * 0.5)
        env = np.exp(-0.5 * ((np.arange(T) - c) / (w / 2)) ** 2)
        root[:, 1] = 0.45 * A * env
        ang[:, i["upperLegL"]] -= 0.9 * A * env
        ang[:, i["upperLegR"]] -= 0.9 * A * env
        ang[:, i["lowerLegL"]] += 1.2 * A * env
        ang[:, i["lowerLegR"]] += 1.2 * A * env
        ang[:, i["upperArmL"]] += 1.0 * A * env
        ang[:, i["upperArmR"]] -= 1.0 * A * env
    elif action in ("punch", "kick", "block", "wave", "squat", "celebrate"):
        n_hit = 2 if action in ("punch", "kick") else 1
        for k in range(n_hit):
            c = int(T * (0.3 + 0.4 * k / max(1, n_hit - 1) if n_hit > 1 else 0.5))
            w = int(FPS * 0.4)
            env = np.exp(-0.5 * ((np.arange(T) - c) / (w / 2)) ** 2)
            if action == "punch":
                ang[:, i["upperArmR"]] += (1.6 * A) * env * direction
                ang[:, i["lowerArmR"]] += 0.2 * env
                ang[:, i["chest"]] += 0.25 * A * env * direction
            elif action == "kick":
                ang[:, i["upperLegR"]] += 1.2 * A * env * direction
                ang[:, i["lowerLegR"]] -= 0.4 * env
                ang[:, i["upperArmL"]] -= 0.6 * A * env
            elif action == "block":
                ang[:, i["upperArmL"]] += 1.2 * A * env
                ang[:, i["upperArmR"]] -= 1.2 * A * env
                ang[:, i["lowerArmL"]] += 0.8 * env
                ang[:, i["lowerArmR"]] += 0.8 * env
                ang[:, i["squat" if False else "chest"]] += 0.1 * env
            elif action == "wave":
                ang[:, i["upperArmR"]] -= (1.8 + 0.4 * np.sin(2 * np.pi * 3 * t)) * A * env
            elif action == "squat":
                ang[:, i["upperLegL"]] -= 0.9 * A * env
                ang[:, i["upperLegR"]] += 0.0 * env - 0.0
                ang[:, i["upperLegR"]] -= 0.9 * A * env
                ang[:, i["lowerLegL"]] += 1.1 * A * env
                ang[:, i["lowerLegR"]] += 1.1 * A * env
                root[:, 1] = -0.18 * A * env
            elif action == "celebrate":
                ang[:, i["upperArmL"]] += (1.5 + 0.3 * np.sin(2 * np.pi * 2 * t)) * A * env
                ang[:, i["upperArmR"]] -= (1.5 + 0.3 * np.sin(2 * np.pi * 2 * t)) * A * env
                root[:, 1] = 0.08 * A * np.abs(np.sin(2 * np.pi * 2 * t)) * env
    elif action == "knockdown":
        k = np.linspace(0, 1, T).astype(np.float32)
        root[:, 1] = -0.45 * k
        root[:, 0] = -0.3 * direction * k
        ang[:, i["chest"]] += 1.2 * k
        ang[:, i["upperLegL"]] -= 1.0 * k
        ang[:, i["upperLegR"]] -= 1.0 * k
    elif action == "getup":
        k = np.linspace(0, 1, T).astype(np.float32)
        root[:, 1] = -0.45 * (1 - k)
        ang[:, i["chest"]] += 1.2 * (1 - k)
        ang[:, i["upperLegL"]] -= 1.0 * (1 - k)
        ang[:, i["upperLegR"]] -= 1.0 * (1 - k)
    else:
        raise ValueError(action)
    # small noise for diversity (not new knowledge, just jitter)
    ang += rng.normal(0, 0.01, ang.shape).astype(np.float32)
    feat = encode(root, ang)
    return {"feat": feat, "family_id": f"1p-{action}",
            "label": action, "n_person": 1, "T": T}


def gen_pair(action, duration_s=5.0, seed=0):
    """Two-person templates: person B mirrors A with reaction delay."""
    T = int(duration_s * FPS)
    a = gen_single("punch" if "punch" in action else "kick" if "kick" in action else "walk",
                   duration_s, speed=1.0, amplitude=1.0, direction=1, seed=seed)
    b_act = "block" if action == "punch_block" else "squat" if action == "kick_dodge" else "block"
    b = gen_single(b_act, duration_s, speed=1.0, amplitude=1.0, direction=-1, seed=seed + 999)
    fa = a["feat"].reshape(T, -1)
    fb = b["feat"].reshape(T, -1)
    # offset B to the right, delay reaction by ~8 frames
    d = 8
    fb = np.concatenate([np.tile(fb[:1], (d, 1)), fb[:T - d]], axis=0)
    fb[:, 0] += 0.9  # world offset so they face each other
    if action == "knockdown_getup":
        a = gen_single("kick", duration_s, seed=seed)
        b = gen_single("knockdown", duration_s, seed=seed + 999)
        fa, fb = a["feat"], b["feat"]
        fb[:, 0] += 0.9
    feat = np.concatenate([fa, fb], axis=-1)  # (T,60)
    return {"feat": feat.astype(np.float32), "family_id": f"2p-{action}",
            "label": action, "n_person": 2, "T": T}
