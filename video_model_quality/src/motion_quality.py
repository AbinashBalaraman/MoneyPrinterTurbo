"""Motion quality analysers: the timing defects a threshold cannot see.

These are the two checks the SceneDoctor could not previously make:

1. **Linear easing segments** -- "nothing in real life moves at constant speed".
   A run of frames where a joint's velocity is constant (and non-trivial) reads
   as mechanical. It is usually the fingerprint of a rate limiter saturating, or
   of a transition that was never given an easing curve.

2. **Anticipation before a strike** -- the wind-up. The striking limb must move
   *against* the strike direction before it snaps forward; without it a punch
   reads as teleporting. We judge it at the frames where an impact is already
   declared, so no new authoring is required.

Both operate on continuous (unwrapped) joint angles, in radians, at a known fps.
Pure numpy, deterministic, no side effects.
"""
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from src.rig import BONES, FPS

# Defaults, calibrated against the 13 single-person actions (see docs).
DEFAULT_MIN_FRAMES = 4        # a run shorter than this is not a "segment"
DEFAULT_VEL_TOL = 0.5         # rad/s -- below this the joint is holding, not moving
DEFAULT_ACCEL_TOL = 8.0       # rad/s^2 -- "constant velocity" band
DEFAULT_LOOKBACK_S = 0.5      # how far back a wind-up may start
DEFAULT_MIN_ANTICIPATION = 0.25  # wind-up speed as a fraction of strike speed


def unwrap_angles(angles: np.ndarray) -> np.ndarray:
    """Continuous angles: arctan2 wraps at +/-pi and would fake huge derivatives."""
    return np.unwrap(np.asarray(angles, dtype=np.float64), axis=0)


def linear_easing_segments(angles_cont: np.ndarray, fps: int = FPS,
                           min_frames: int = DEFAULT_MIN_FRAMES,
                           vel_tol: float = DEFAULT_VEL_TOL,
                           accel_tol: float = DEFAULT_ACCEL_TOL) -> List[Dict[str, Any]]:
    """Find runs of constant non-zero velocity (mechanically-timed motion).

    Returns one entry per offending run: bone, frame range, mean speed.
    """
    a = unwrap_angles(angles_cont)
    if len(a) < min_frames + 2:
        return []
    vel = np.diff(a, axis=0) * fps          # (T-1, N)
    accel = np.diff(vel, axis=0) * fps      # (T-2, N)

    found: List[Dict[str, Any]] = []
    for j in range(a.shape[1]):
        moving = np.abs(vel[1:, j]) > vel_tol
        straight = np.abs(accel[:, j]) < accel_tol
        mask = moving & straight
        start: Optional[int] = None
        for i, flag in enumerate(mask):
            if flag and start is None:
                start = i
            elif not flag and start is not None:
                run = i - start
                if run >= min_frames:
                    found.append({
                        "code": "linear_easing",
                        "bone": BONES[j][0],
                        "bone_index": j,
                        "start_frame": int(start + 1),
                        "frames": int(run),
                        "mean_speed_rad_s": float(np.abs(vel[start + 1:i + 1, j]).mean()),
                    })
                start = None
        if start is not None:
            run = len(mask) - start
            if run >= min_frames:
                found.append({
                    "code": "linear_easing",
                    "bone": BONES[j][0],
                    "bone_index": j,
                    "start_frame": int(start + 1),
                    "frames": int(run),
                    "mean_speed_rad_s": float(np.abs(vel[start + 1:, j]).mean()),
                })
    return found


def strike_anticipation(angles_cont: np.ndarray, impact_frames: Sequence[int],
                        fps: int = FPS,
                        lookback_s: float = DEFAULT_LOOKBACK_S,
                        min_ratio: float = DEFAULT_MIN_ANTICIPATION) -> List[Dict[str, Any]]:
    """Check that each declared impact is preceded by a wind-up.

    For every impact frame we take the fastest-moving bone at that moment (the
    striking limb) and look back for motion in the *opposite* direction. If the
    best reversal is weaker than ``min_ratio`` of the strike speed, the strike
    has no anticipation -- it just teleports into the hit.

    Returns one entry per strike that lacks a wind-up.
    """
    a = unwrap_angles(angles_cont)
    if len(a) < 3:
        return []
    vel = np.diff(a, axis=0) * fps
    lookback = max(1, int(lookback_s * fps))

    found: List[Dict[str, Any]] = []
    for f in sorted({int(x) for x in impact_frames if 0 <= int(x) < len(vel)}):
        lo = max(0, f - lookback)
        window = vel[lo:f]
        if window.shape[0] == 0:
            continue
        # Striking limb = the bone with the largest peak speed anywhere in the
        # lookback window. Sampling only the few frames at the impact picks up
        # whatever is fastest *then* (often a bracing leg), not the limb that
        # actually threw the strike.
        bone = int(np.argmax(np.abs(window).max(axis=0)))
        peak = float(np.abs(window[:, bone]).max())
        if peak < 1e-6:
            continue
        signed = window[:, bone]
        peak_sign = float(np.sign(vel[f - 1, bone])) or 1.0
        opposite = signed[np.sign(signed) == -peak_sign]
        antic = float(np.abs(opposite).max()) if opposite.size else 0.0
        ratio = antic / peak
        if ratio < min_ratio:
            found.append({
                "code": "missing_anticipation",
                "impact_frame": int(f),
                "bone": BONES[bone][0],
                "bone_index": bone,
                "anticipation_ratio": float(ratio),
                "strike_speed_rad_s": peak,
            })
    return found


def impact_frames_from_events(events: Optional[Sequence[Dict[str, Any]]]) -> List[int]:
    """Frame indices of impact/whoosh events, for anticipation checking."""
    out: List[int] = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind", "")).lower()
        if "impact" in kind or "burst" in kind or "clash" in kind:
            try:
                out.append(int(ev.get("start_frame", 0)))
            except (TypeError, ValueError):
                continue
    return out
