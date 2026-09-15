"""L2 Parametric Controllers: phase-oscillator locomotion, posture overlay, split-body layering.

Brain side of the platform split (Body lives with Pi: rig entity, DLS IK,
biomechanical limits, CoM balance). Controllers reuse L0/L1 machinery
(ArmatureTimeline, pose library, analytical IK pinning, foot-roll overlays)
and compose through plain feature arrays, so no existing module is modified.
"""
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

import numpy as np

from src.puppet.armature import ArmatureTimeline
from src.rig import FPS, decode, encode

# Bones driven by upper-body gesture overlays (neck/head/arms).
# Spine+chest (0, 1) stay with the base to preserve balance; legs (8..13) stay
# with locomotion so stance pinning is never disturbed.
UPPER_BODY_BONES = (2, 3, 4, 5, 6, 7)

# Gait keyframe cycle per leading foot: contact (strike) then pass (swing-through).
_FWD_CYCLE = (
    ("stride_contact_L", "left_foot", "L"),
    ("stride_pass_L", "left_foot", "L"),
    ("stride_contact_R", "right_foot", "R"),
    ("stride_pass_R", "right_foot", "R"),
)
_BACK_CYCLE = (
    ("walkback_contact_L", "left_foot", "L"),
    ("walkback_pass_L", "left_foot", "L"),
    ("walkback_contact_R", "right_foot", "R"),
    ("walkback_pass_R", "right_foot", "R"),
)


@dataclass
class GaitCommand:
    """Parametric locomotion order: signed speed selects gait direction.

    Positive speed walks forward (+X) on stride_* poses; negative speed walks
    backward (-X) on walkback_* poses, so reverse locomotion can never moonwalk.
    Near-zero speed degrades to a standing hold.
    """
    speed: float = 0.3          # world units/s, signed
    duration_s: float = 2.0
    stride_length: float = 0.22  # per-step travel at full weight
    cadence: int = 1
    lean: float = 0.0           # torso lean overlay (rad, + = forward)
    foot_roll: float = 0.25     # strike roll overlay (rad)


class LocomotionController:
    """Phase-oscillator gait engine compiling signed-speed locomotion timelines."""

    def __init__(self, fps: int = FPS):
        self.fps = int(fps)

    def build_gait_timeline(self, start_x: float, cmd: GaitCommand) -> ArmatureTimeline:
        """Compiles a gait timeline honouring speed*duration travel exactly."""
        tl = ArmatureTimeline(fps=self.fps)
        total_dist = float(cmd.speed) * float(cmd.duration_s)
        if abs(total_dist) < 1e-6 or abs(cmd.speed) < 1e-6:
            tl.add_keyframe(t=0.0, pose="stand_relaxed", root_x=float(start_x),
                            hold_duration_s=float(cmd.duration_s))
            return tl

        forward = cmd.speed > 0
        cycle = _FWD_CYCLE if forward else _BACK_CYCLE
        rate = float(np.clip(abs(cmd.speed) / max(1e-6, cmd.stride_length), 0.5, 4.0))
        n_steps = max(1, int(round(abs(total_dist) / max(1e-6, cmd.stride_length))))
        step_dur = float(cmd.duration_s) / n_steps
        direction = 1.0 if forward else -1.0

        # Per-step weights: soften first/last steps (accel/decel ramps),
        # renormalized so total travel stays exactly speed*duration.
        weights = np.ones(n_steps, dtype=np.float64)
        if n_steps > 1:
            weights[0] = weights[-1] = 0.6
        weights *= abs(total_dist) / (weights.sum() * max(1e-6, cmd.stride_length))

        tl.add_keyframe(t=0.0, pose="stand_relaxed", root_x=float(start_x),
                        hold_duration_s=0.15, easing="ease_in")
        t = 0.15
        x = float(start_x)
        for s in range(n_steps):
            leg_is_left = (s % 2 == 0)
            stride = float(cmd.stride_length) * float(weights[s])
            half = step_dur / 2.0
            contact, _, side = cycle[0] if leg_is_left else cycle[2]
            passer, _, _ = cycle[1] if leg_is_left else cycle[3]
            lock = "left_foot" if leg_is_left else "right_foot"
            roll_kw = {"foot_roll_L": cmd.foot_roll} if side == "L" else {"foot_roll_R": cmd.foot_roll}
            x += direction * stride * 0.5
            t += half
            tl.add_keyframe(t=t, pose=contact, root_x=x, root_y=0.0,
                            easing="ease_in_out", stance_lock=lock,
                            cadence=cmd.cadence, **roll_kw)
            x += direction * stride * 0.5
            t += half
            tl.add_keyframe(t=t, pose=passer, root_x=x, root_y=0.0,
                            easing="ease_in_out", stance_lock=lock,
                            cadence=cmd.cadence)
        tl.add_keyframe(t=t, pose="stand_relaxed", root_x=x,
                        hold_duration_s=max(0.1, float(cmd.duration_s) - t),
                        easing="ease_out")
        return tl

    def build_gait_features(self, start_x: float, cmd: GaitCommand) -> np.ndarray:
        """Compiles gait features (T, 30) with the posture-lean post pass applied."""
        feat = self.build_gait_timeline(start_x, cmd).compile(total_duration_s=cmd.duration_s)
        if cmd.lean:
            root, ang = decode(feat)
            ang = ang.copy()
            ang[:, 0] += float(cmd.lean)
            ang[:, 1] += float(cmd.lean) * 0.6
            feat = encode(root, ang)
        return feat


def layer_timelines(base_feat: np.ndarray, over_feat: np.ndarray, f0: int,
                    bones: tuple = UPPER_BODY_BONES,
                    fade_s: float = 0.15, fps: int = FPS) -> np.ndarray:
    """Blends an overlay span into a base feature stream with cosine crossfades.

    over_feat (M, 30) starts at base frame f0. Legs/pelvis always come from base
    (stance pinning untouched); only the masked bones crossfade in across
    [f0-fade, f0] and out across [f1, f1+fade].
    """
    base = np.asarray(base_feat, dtype=np.float32).copy()
    over = np.asarray(over_feat, dtype=np.float32)
    T = len(base)
    f0 = int(max(0, min(T, f0)))
    f1 = int(min(T, f0 + len(over)))
    if f1 <= f0:
        return base
    fade = max(1, int(round(fade_s * fps)))
    w = np.zeros(T, dtype=np.float32)
    w[f0:f1] = 1.0
    pre0, pre1 = max(0, f0 - fade), f0
    if pre1 > pre0:
        w[pre0:pre1] = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, pre1 - pre0))
    post0, post1 = f1, min(T, f1 + fade)
    if post1 > post0:
        w[post0:post1] = 0.5 + 0.5 * np.cos(np.linspace(0.0, np.pi, post1 - post0))
    rb, ab = decode(base)
    _, ao = decode(over[:f1 - f0])
    ab = ab.copy()
    span = slice(f0, f1)
    ab[span][:, list(bones)] = ((1.0 - w[span, None]) * ab[span][:, list(bones)]
                                + w[span, None] * ao[:, list(bones)])
    pre = slice(pre0, pre1)
    if pre1 > pre0:
        first = np.repeat(ao[0:1, list(bones)], pre1 - pre0, axis=0)
        ab[pre][:, list(bones)] = ((1.0 - w[pre, None]) * ab[pre][:, list(bones)]
                                   + w[pre, None] * first)
    post = slice(post0, post1)
    if post1 > post0:
        last = np.repeat(ao[-1:, list(bones)], post1 - post0, axis=0)
        ab[post][:, list(bones)] = ((1.0 - w[post, None]) * ab[post][:, list(bones)]
                                    + w[post, None] * last)
    return encode(rb, ab)
