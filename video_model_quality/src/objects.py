"""Deterministic object runtime (Task 2).

Evaluates validated object specs (contract.validate_scene output) against
world-space joints into per-frame renderer props + impact events.

Object-space physics uses +y UP with ground derived from the rig rest pose
(`rig.GROUND_Y`). Pure numpy, no RNG, fully deterministic. One malformed object
never breaks the batch: it is skipped.
"""

import numpy as np

from .rig import GROUND_Y
_CHEST_JOINT = 2
_HIT_X_DIST = 0.12
_REST_SPEED = 0.05
_RESTITUTION = 0.45
_VX_DAMP = 0.7


_JOINT_NAME_MAP = {
    "root": 0, "pelvis": 0, "abdomen": 1, "chest": 2, "neck": 3, "head": 4,
    "elbow_l": 5, "elbowl": 5, "hand_l": 6, "handl": 6,
    "elbow_r": 7, "elbowr": 7, "hand_r": 8, "handr": 8,
    "knee_l": 9, "kneel": 9, "ankle_l": 10, "anklel": 10, "foot_l": 11, "footl": 11,
    "knee_r": 12, "kneer": 12, "ankle_r": 13, "ankler": 13, "foot_r": 14, "footr": 14,
}


def _as_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _actor_index(actor_id, n_actors, actor_ids=None):
    """Actor id string -> track index. Defensive mapping, clamped."""
    if n_actors <= 0:
        return 0
    if actor_ids is not None and actor_id in actor_ids:
        return actor_ids.index(actor_id)
    try:
        if isinstance(actor_id, bool):
            return 0
        if isinstance(actor_id, int):
            idx = actor_id
        else:
            s = str(actor_id).strip().lower()
            if s.lstrip("-").isdigit():
                idx = int(s)
            elif len(s) == 1 and "a" <= s <= "z":
                idx = ord(s) - ord("a")
            else:
                digits = "".join(ch for ch in s if ch.isdigit())
                idx = int(digits) if digits else 0
        return max(0, min(n_actors - 1, idx))
    except (TypeError, ValueError):
        return 0


def _joint_index(joint, default=8):
    if isinstance(joint, str):
        cleaned = joint.strip().lower()
        if cleaned in _JOINT_NAME_MAP:
            return _JOINT_NAME_MAP[cleaned]
    try:
        j = int(joint)
        return j if 0 <= j < 15 else default
    except (TypeError, ValueError):
        return default


def evaluate_objects(objects, joints, fps=24, T=None, actor_ids=None):
    """Evaluates object specs to per-frame renderer props + impacts.

    objects: validated list from contract.validate_scene (out['objects']).
    joints:  np.ndarray (T, N, 15, 2) world-space joints.
    returns: (prop_tracks, impacts)
      prop_tracks[t] = list of prop dicts visible at frame t.
      impacts entries: {"frame", "x", "y", "kind": "impact_burst"|"dust_puff"}.
    """
    fps = _as_float(fps, 24.0)
    if fps <= 0:
        fps = 24.0
    dt = 1.0 / fps

    try:
        joints = np.asarray(joints, dtype=np.float64)
    except (TypeError, ValueError):
        joints = np.zeros((0, 0, 15, 2))
    if joints.ndim != 4 or joints.shape[2] != 15 or joints.shape[1] == 0:
        n_t = _as_int(T, 0)
        n_t = max(0, n_t)
        return [[] for _ in range(n_t)], []
    n_frames = joints.shape[0]
    n_actors = joints.shape[1]
    if T is None:
        T = n_frames
    T = max(0, _as_int(T, n_frames))
    T = min(T, n_frames)

    if not isinstance(objects, (list, tuple)):
        return [[] for _ in range(T)], []

    prop_tracks = [[] for _ in range(T)]
    impacts = []

    for spec in objects:
        try:
            _eval_one(spec, joints, T, n_actors, dt, prop_tracks, impacts, actor_ids=actor_ids)
        except Exception:
            continue  # never raise on a single bad object

    return prop_tracks, impacts


def _eval_one(spec, joints, T, n_actors, dt, prop_tracks, impacts, actor_ids=None):
    if not isinstance(spec, dict):
        return
    kind = spec.get("kind", spec.get("type"))
    if not isinstance(kind, str) or not kind:
        return
    scale = _as_float(spec.get("scale", 1.0), 1.0)
    if scale < 0.1:
        scale = 0.1

    at = spec.get("at")
    if isinstance(at, (list, tuple)) and len(at) == 2:
        home = [_as_float(at[0], 0.0), _as_float(at[1], GROUND_Y)]
    else:
        home = [0.0, GROUND_Y]

    spawn = max(0, _as_int(spec.get("spawn_frame", 0), 0))
    despawn = spec.get("despawn_frame", None)
    if despawn is not None:
        despawn = _as_int(despawn, T)
    else:
        despawn = T
    if despawn <= spawn:
        return

    attach = spec.get("attach") if isinstance(spec.get("attach"), dict) else None
    throw = spec.get("throw") if isinstance(spec.get("throw"), dict) else None
    pickup = spec.get("pickup") if isinstance(spec.get("pickup"), dict) else None
    drop = spec.get("drop") if isinstance(spec.get("drop"), dict) else None
    bounce = bool(spec.get("bounce", False))

    throw_frame = _as_int(throw.get("frame", 0), 0) if throw else None
    vx = _as_float(throw.get("vx", 0.8), 0.8) if throw else 0.0
    vy = _as_float(throw.get("vy", 0.9), 0.9) if throw else 0.0
    grav = _as_float(throw.get("gravity", 1.8), 1.8) if throw else 0.0
    if grav < 0:
        grav = 0.0

    drop_frame = _as_int(drop.get("frame", T + 1), T + 1) if drop else T + 1

    # Ballistic state (lazily launched at throw_frame).
    flying = False
    resting = False
    px, py, cvx, cvy = home[0], home[1], 0.0, 0.0
    was_in_hit_range = False
    collided_with_actor = False
    ground_bounces = 0
    drop_pos = None

    for t in range(spawn, min(despawn, T)):
        # ---- throwing takes over from throw_frame on ------------------- #
        if throw is not None and t >= throw_frame and not resting:
            if not flying:
                flying = True
                # Launch from current holder, else from `at`.
                launched = False
                holder = _holder_at(spec, attach, pickup, t, n_actors, actor_ids=actor_ids)
                if holder is not None:
                    aidx, jidx = holder
                    if 0 <= aidx < n_actors:
                        px = float(joints[t, aidx, jidx, 0])
                        py = float(joints[t, aidx, jidx, 1])
                        launched = True
                if not launched:
                    px, py = home[0], home[1]
                cvx, cvy = vx, vy
                was_in_hit_range = _in_hit_range(px, joints, t, n_actors)
            # Step flight.
            px = px + cvx * dt
            py = py + cvy * dt
            cvy = cvy - grav * dt
            if bounce and py < GROUND_Y and cvy < 0:
                py = GROUND_Y
                cvy = -cvy * _RESTITUTION
                cvx = cvx * _VX_DAMP
                ground_bounces += 1
                impacts.append({"frame": t, "x": px, "y": py, "kind": "impact_burst"})
                impacts.append({"frame": t, "x": px, "y": py, "kind": "dust_puff"})
            if bounce:
                # Settle when slow, low, or after a bounded number of bounces.
                speed = abs(cvx) + abs(cvy)
                if (speed < _REST_SPEED and py <= GROUND_Y + 1e-6) or ground_bounces >= 6:
                    resting = True
                    py = GROUND_Y
                    cvy = 0.0
                    cvx = 0.0
            # Mid-air actor collision (once per object; no energy pumping).
            in_range = _in_hit_range(px, joints, t, n_actors)
            if in_range and not was_in_hit_range and not collided_with_actor:
                collided_with_actor = True
                impacts.append({"frame": t, "x": px, "y": py, "kind": "impact_burst"})
                if bounce and not resting:
                    # Small single rebound, never a repeated energy source.
                    cvy = max(abs(cvy), 0.3) * _RESTITUTION
                    cvx = -cvx * _VX_DAMP
                    ground_bounces += 1
            was_in_hit_range = in_range
            prop_tracks[t].append({"kind": kind, "x": px, "y": py, "scale": scale})
            continue

        # ---- drop: freeze at release point ------------------------------ #
        if drop is not None and t >= drop_frame:
            if drop_pos is None:
                holder = _holder_at(spec, attach, pickup, t - 1, n_actors, actor_ids=actor_ids)
                if holder is not None and 0 <= holder[0] < n_actors:
                    drop_pos = [float(joints[t - 1, holder[0], holder[1], 0]),
                                float(joints[t - 1, holder[0], holder[1], 1])]
                else:
                    drop_pos = list(home)
            prop_tracks[t].append({"kind": kind, "x": drop_pos[0],
                                   "y": drop_pos[1], "scale": scale})
            continue

        # ---- held (attach window or post-pickup): joint-locked ----------- #
        holder = _holder_at(spec, attach, pickup, t, n_actors, actor_ids=actor_ids)
        if holder is not None:
            aidx, jidx = holder
            if 0 <= aidx < n_actors:
                prop_tracks[t].append({"kind": kind, "anchor_puppet": aidx,
                                       "joint": jidx, "scale": scale})
                continue

        # ---- otherwise: static at home ---------------------------------- #
        if _has_placement(spec, attach, pickup):
            prop_tracks[t].append({"kind": kind, "x": home[0],
                                   "y": home[1], "scale": scale})
        # (no `at` and not held: nowhere to be -> absent)


def _holder_at(spec, attach, pickup, t, n_actors, actor_ids=None):
    """Returns (actor_idx, joint_idx) holding the object at frame t, else None."""
    drop = spec.get("drop") if isinstance(spec.get("drop"), dict) else None
    if drop is not None and t >= _as_int(drop.get("frame", 10 ** 9), 10 ** 9):
        return None
    if pickup is not None:
        if t >= _as_int(pickup.get("frame", 0), 0):
            return (_actor_index(pickup.get("actor", 0), n_actors, actor_ids=actor_ids),
                    _joint_index(pickup.get("joint", 8)))
        return None  # pre-pickup: on the ground, not held
    if attach is not None:
        frm = _as_int(attach.get("from_frame", 0), 0)
        to = _as_int(attach.get("to_frame", -1), -1)
        if t >= frm and (to < 0 or t < to):
            return (_actor_index(attach.get("actor", 0), n_actors, actor_ids=actor_ids),
                    _joint_index(attach.get("joint", 8)))
    return None


def _has_placement(spec, attach, pickup):
    """Static home placement exists when the spec carries an `at` anchor."""
    del attach, pickup
    at = spec.get("at")
    return isinstance(at, (list, tuple)) and len(at) == 2


def _in_hit_range(px, joints, t, n_actors):
    try:
        for a in range(n_actors):
            cx = float(joints[t, a, _CHEST_JOINT, 0])
            if abs(px - cx) <= _HIT_X_DIST:
                return True
    except (IndexError, TypeError, ValueError):
        pass
    return False
