"""Armature Timeline & Stop-Motion Keyframe Interpolator.

Transforms a sequence of discrete keyframe poses into a buttery-smooth 24fps
motion stream using custom easing curves, moving holds, and zero-drift stance pinning.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, Any, List, Optional, Union
import numpy as np

from src.puppet.easing import get_easing_function, moving_hold, hold_breath
from src.puppet.pose import POSES, get_pose_angles, get_pose_root_y
from src.rig import encode, forward_kinematics, FPS, N_BONES


JOINT_NAMES: Dict[str, int] = {
    "pelvis": 0, "root": 0, "abdomen": 1, "chest": 2, "neck": 3, "head": 4,
    "elbow_l": 5, "hand_l": 6, "wrist_l": 6, "elbow_r": 7, "hand_r": 8, "wrist_r": 8,
    "knee_l": 9, "ankle_l": 10, "toe_l": 11, "foot_l": 10,
    "knee_r": 12, "ankle_r": 13, "toe_r": 14, "foot_r": 13,
}


@dataclass
class TimelineEvent:
    """A timed VFX, impact, or trigger event on the armature timeline."""
    t: float                                    # Event timestamp in seconds
    kind: str                                   # "impact_burst", "dust_puff", "speed_lines", etc.
    joint: Optional[Union[int, str]] = None     # Joint index or name to anchor to
    x: Optional[float] = None                   # Explicit world X coordinate
    y: Optional[float] = None                   # Explicit world Y coordinate
    scale: float = 1.0                          # VFX visual scale factor
    duration_frames: int = 8                    # Duration of effect in frames
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Keyframe:
    """A discrete keyframe pose in the stop-motion armature timeline."""
    t: float                                    # Start timestamp in seconds
    pose: Union[str, np.ndarray]                # Pose name or (14,) angle array
    root_x: Optional[float] = None              # Root pelvis X (if None, maintains previous X)
    root_y: Optional[float] = None              # Root pelvis Y (if None, uses pose default)
    easing: str = "ease_in_out"                 # Easing curve name
    hold_duration_s: float = 0.0                # How long to hold this pose before moving to next
    stance_lock: Optional[str] = None           # "left_foot", "right_foot", "both_feet", or None
    foot_roll_L: float = 0.0                    # Prescribed left-foot roll overlay (rad, + = heel-up)
    foot_roll_R: float = 0.0                    # Prescribed right-foot roll overlay (rad)
    moving_hold: bool = True                    # Whether to apply subtle breathing life during holds
    cadence: Optional[int] = None               # 1 (on ones, 24fps) or 2 (on twos, 12fps)


def shortest_angle_diff(target: np.ndarray, source: np.ndarray) -> np.ndarray:
    """Computes the shortest angular difference on the circle: (target - source) in [-pi, pi]."""
    diff = (target - source + np.pi) % (2.0 * np.pi) - np.pi
    return diff


def limit_velocity_preserving_endpoints(angles: np.ndarray, max_step: float,
                                        margin: int = 5, passes: int = 8) -> np.ndarray:
    """Cap the per-frame angular step by SMOOTHING over-fast runs, not clipping.

    A causal one-pass clamp (``clip(step)``) is worse than the popping it tries
    to prevent: when a transition genuinely wants to move faster than the cap,
    the clamp makes the limb lag behind at a constant velocity and then stop
    dead when the segment ends. That is two artefacts for the price of one -- a
    linear ramp (constant speed reads as mechanical) followed by an abrupt halt
    (a jerk spike).

    Instead, every contiguous run of over-fast steps has its velocity profile
    diffused across a slightly wider window. The window's total displacement is
    conserved, so the pose is still reached exactly (endpoints preserved) -- the
    same move simply happens over more frames. Motion that is already within the
    cap is never touched, so genuine snap is preserved.

    ``angles`` is (T, N_BONES) in radians. Returns a new array.
    """
    a = np.array(angles, dtype=np.float64, copy=True)
    T = a.shape[0]
    if T < 3 or max_step <= 0.0:
        return a.astype(angles.dtype, copy=False)

    _HOLD_EPS = 1e-4  # below this a step is a hold, not motion

    for j in range(a.shape[1]):
        x = a[:, j]
        for _ in range(passes):
            v = np.diff(x)
            over = np.abs(v) > max_step
            if not over.any():
                break
            idx = np.nonzero(over)[0]
            runs, start, prev = [], idx[0], idx[0]
            for i in idx[1:]:
                if i == prev + 1:
                    prev = i
                else:
                    runs.append((start, prev))
                    start = prev = i
            runs.append((start, prev))

            for lo, hi in runs:
                # Expand into NEIGHBOURING MOTION only. A zero-velocity step is an
                # intentional hold (hit-stop, anticipation pause) -- a deliberate
                # animation device. Bleeding excess into it would dissolve the
                # freeze, so the window stops at any still frame.
                w0 = lo
                while w0 > 0 and abs(v[w0 - 1]) > _HOLD_EPS and (lo - w0) < margin:
                    w0 -= 1
                w1 = hi
                while w1 < len(v) - 1 and abs(v[w1 + 1]) > _HOLD_EPS and (w1 - hi) < margin:
                    w1 += 1
                seg = v[w0:w1 + 1]
                total = seg.sum()
                n = len(seg)
                # Sum-preserving diffusion: deviations from the uniform ramp
                # diffuse to zero mean, so the window total is conserved.
                r = seg - total / n
                for _ in range(3):
                    for i in range(n - 1):
                        m = 0.5 * (r[i] + r[i + 1])
                        r[i] = m
                        r[i + 1] = m
                v[w0:w1 + 1] = total / n + r
            x[1:] = x[0] + np.cumsum(v)
    return a.astype(angles.dtype, copy=False)


def solve_two_bone_ik(
    hip_xy: np.ndarray,
    target_ankle_xy: np.ndarray,
    l1: float = 0.22,
    l2: float = 0.20,
    bend_forward: bool = True
) -> tuple[float, float]:
    """Closed-form analytical Two-Bone Inverse Kinematics solver using Law of Cosines.

    Calculates exact relative angles (thigh, shin) for a 2-segment limb
    originating at hip_xy and terminating at target_ankle_xy.

    Args:
        hip_xy: (2,) array [x, y] of the root hip joint.
        target_ankle_xy: (2,) array [x, y] of target ankle position.
        l1: Length of thigh (bone 8/11). Default 0.25.
        l2: Length of shin (bone 9/12). Default 0.24.
        bend_forward: True if knee bends forward (standard human leg in side view).

    Returns:
        (angle_thigh, angle_shin) in radians.
    """
    dx = float(target_ankle_xy[0] - hip_xy[0])
    dy = float(target_ankle_xy[1] - hip_xy[1])
    d = float(np.hypot(dx, dy))

    # Clamp reach to avoid domain error in arccos
    max_reach = (l1 + l2) * 0.9999
    min_reach = abs(l1 - l2) + 0.001
    d_clamped = float(np.clip(d, min_reach, max_reach))

    # Target vector base angle psi relative to straight-down (0, -1)
    psi = float(np.arctan2(dx, -dy))

    # Law of Cosines for thigh angle alpha
    cos_alpha = (l1 * l1 + d_clamped * d_clamped - l2 * l2) / (2.0 * l1 * d_clamped)
    cos_alpha = float(np.clip(cos_alpha, -1.0, 1.0))
    alpha = float(np.arccos(cos_alpha))

    # Law of Cosines for knee angle gamma
    cos_gamma = (l1 * l1 + l2 * l2 - d_clamped * d_clamped) / (2.0 * l1 * l2)
    cos_gamma = float(np.clip(cos_gamma, -1.0, 1.0))
    gamma = float(np.arccos(cos_gamma))

    if bend_forward:
        thigh_angle = psi + alpha
        shin_angle = -(float(np.pi) - gamma)
    else:
        thigh_angle = psi - alpha
        shin_angle = float(np.pi) - gamma

    return thigh_angle, shin_angle


class ArmatureTimeline:
    """Compiles a choreography of keyframes into smooth, jitter-free 24fps puppet motion."""

    def __init__(self, fps: int = FPS, max_angular_vel: float = 0.60, cadence: int = 1):
        self.fps = fps
        self.max_angular_vel = float(max_angular_vel)
        self.cadence = int(cadence)
        self.keyframes: List[Keyframe] = []
        self.events: List[TimelineEvent] = []

    def add_keyframe(
        self,
        t: float,
        pose: Union[str, np.ndarray],
        root_x: Optional[float] = None,
        root_y: Optional[float] = None,
        easing: str = "ease_in_out",
        hold_duration_s: float = 0.0,
        stance_lock: Optional[str] = None,
        foot_roll_L: float = 0.0,
        foot_roll_R: float = 0.0,
        moving_hold: bool = True,
        cadence: Optional[int] = None
    ) -> "ArmatureTimeline":
        """Appends a keyframe to the timeline."""
        kf = Keyframe(
            t=float(t),
            pose=pose,
            root_x=root_x,
            root_y=root_y,
            easing=easing,
            hold_duration_s=float(hold_duration_s),
            stance_lock=stance_lock,
            foot_roll_L=float(foot_roll_L),
            foot_roll_R=float(foot_roll_R),
            moving_hold=moving_hold,
            cadence=cadence
        )
        self.keyframes.append(kf)
        self.keyframes.sort(key=lambda k: k.t)
        return self

    def add_event(
        self,
        t: float,
        kind: str,
        joint: Optional[Union[int, str]] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        scale: float = 1.0,
        duration_frames: int = 8,
        **params
    ) -> "ArmatureTimeline":
        """Appends a timed trigger event (impact burst, dust puff, speed line) to the timeline."""
        ev = TimelineEvent(
            t=float(t),
            kind=kind,
            joint=joint,
            x=x,
            y=y,
            scale=float(scale),
            duration_frames=int(duration_frames),
            params=params
        )
        self.events.append(ev)
        self.events.sort(key=lambda e: e.t)
        return self

    def compile_events(self, puppet_index: int = 0) -> List[Dict[str, Any]]:
        """Compiles timeline events into stage renderer VFX dictionaries."""
        compiled = []
        for ev in self.events:
            start_f = int(round(ev.t * self.fps))
            j_idx = None
            if isinstance(ev.joint, int):
                j_idx = ev.joint
            elif isinstance(ev.joint, str):
                j_idx = JOINT_NAMES.get(ev.joint.strip().lower(), None)

            d: Dict[str, Any] = {
                "kind": ev.kind,
                "start_frame": start_f,
                "duration": ev.duration_frames,
                "scale": ev.scale,
                **ev.params
            }
            if j_idx is not None:
                d["anchor_puppet"] = puppet_index
                d["anchor_joint"] = j_idx
            if ev.x is not None:
                d["x"] = ev.x
            if ev.y is not None:
                d["y"] = ev.y
            compiled.append(d)
        return compiled

    def compile(self, total_duration_s: Optional[float] = None) -> np.ndarray:
        """Compiles keyframes into a continuous feature array of shape (T, 30).
        
        Guarantees:
        1. Zero micro-vibrations: No continuous mathematical sine waves.
        2. Clean easing: Acceleration and deceleration follow animation timing principles.
        3. Stance stability: Planted feet remain pinned during stance holds.
        """
        if not self.keyframes:
            # Fallback: standing relaxed for 2.0s
            self.add_keyframe(t=0.0, pose="stand_relaxed")

        # Resolve total sequence length
        last_kf = self.keyframes[-1]
        min_duration = last_kf.t + last_kf.hold_duration_s
        dur_s = max(min_duration, float(total_duration_s or min_duration or 1.0))
        T = int(round(dur_s * self.fps))

        # Output buffers
        out_root = np.zeros((T, 2), dtype=np.float32)
        out_angles = np.zeros((T, N_BONES), dtype=np.float32)
        # Which keyframe governs each frame's stance (-1 = none). Recorded during
        # interpolation so stance pinning can be re-applied after the rate limiter.
        frame_seg = np.full(T, -1, dtype=np.int32)

        # Pre-process keyframes into concrete numeric arrays
        processed = []
        curr_x = 0.0
        for kf in self.keyframes:
            if isinstance(kf.pose, str):
                ang = get_pose_angles(kf.pose)
                def_ry = get_pose_root_y(kf.pose)
                # Case-insensitive POSES lookup (keys contain capitals like stride_contact_L)
                p_obj = next((v for k, v in POSES.items() if k.lower() == kf.pose.strip().lower()), None)
                st_lock = kf.stance_lock or (p_obj.stance_anchor if p_obj else None)
            else:
                ang = np.asarray(kf.pose, dtype=np.float32)
                def_ry = 0.0
                st_lock = kf.stance_lock

            rx = curr_x if kf.root_x is None else float(kf.root_x)
            ry = def_ry if kf.root_y is None else float(kf.root_y)
            curr_x = rx

            # Compute FK joint locations of initial pose to capture exact stance foot world coordinates
            init_j = forward_kinematics(np.array([[rx, ry]], dtype=np.float32), ang[None, :])[0]

            processed.append({
                "t_start": kf.t,
                "t_end_hold": kf.t + kf.hold_duration_s,
                "angles": ang,
                "root_xy": np.array([rx, ry], dtype=np.float32),
                "easing": get_easing_function(kf.easing),
                "stance_lock": st_lock,
                "foot_roll_L": float(kf.foot_roll_L),
                "foot_roll_R": float(kf.foot_roll_R),
                "anchor_ankle_L": init_j[10].copy(),
                "anchor_ankle_R": init_j[13].copy(),
                "moving_hold": kf.moving_hold,
                "cadence": int(kf.cadence if kf.cadence is not None else self.cadence)
            })

        # Generate each frame t = 0..T-1
        for frame_idx in range(T):
            t_sec = frame_idx / float(self.fps)
            # Find active interval
            if t_sec <= processed[0]["t_start"]:
                # Before or at first keyframe
                frame_seg[frame_idx] = 0
                out_root[frame_idx] = processed[0]["root_xy"]
                out_angles[frame_idx] = processed[0]["angles"]
                continue

            if t_sec >= processed[-1]["t_end_hold"]:
                # Past last keyframe (moving hold on final pose)
                final = processed[-1]
                frame_seg[frame_idx] = len(processed) - 1
                hold_t = t_sec - final["t_end_hold"]
                ang = final["angles"].copy()
                r_xy = final["root_xy"].copy()
                if final["moving_hold"]:
                    # Continuous low-amplitude breathing keeps long holds alive
                    breath = hold_breath(hold_t)
                    ang[0] += breath          # Spine subtle expansion
                    ang[1] += breath * 0.5    # Chest
                    ang[2] += breath * 0.25   # Neck counters
                    r_xy[1] += breath * 0.02  # Root micro-sway
                out_root[frame_idx] = r_xy
                out_angles[frame_idx] = ang
                
                # Apply stance lock if active on final pose
                st = final["stance_lock"]
                if st in ("left_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], final["anchor_ankle_L"])
                    out_angles[frame_idx, 8] = th
                    out_angles[frame_idx, 9] = sh
                    out_angles[frame_idx, 10] = 1.605 - (th + sh) + final["foot_roll_L"]

                if st in ("right_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], final["anchor_ankle_R"])
                    out_angles[frame_idx, 11] = th
                    out_angles[frame_idx, 12] = sh
                    out_angles[frame_idx, 13] = 1.605 - (th + sh) + final["foot_roll_R"]
                continue

            # Locate which keyframe segment we are in
            k_idx = 0
            for i in range(len(processed)):
                if processed[i]["t_start"] <= t_sec:
                    k_idx = i
                else:
                    break

            curr_k = processed[k_idx]

            # Check if we are in the moving hold span of curr_k
            if t_sec < curr_k["t_end_hold"]:
                # Inside hold
                frame_seg[frame_idx] = k_idx
                span = max(1e-4, curr_k["t_end_hold"] - curr_k["t_start"])
                u = (t_sec - curr_k["t_start"]) / span
                ang = curr_k["angles"].copy()
                r_xy = curr_k["root_xy"].copy()
                if curr_k["moving_hold"]:
                    breath = hold_breath(t_sec - curr_k["t_start"])
                    ang[0] += breath
                    ang[1] += breath * 0.5
                    ang[2] += breath * 0.25
                    r_xy[1] += breath * 0.02
                out_root[frame_idx] = r_xy
                out_angles[frame_idx] = ang

                # Apply stance pinning
                st = curr_k["stance_lock"]
                if st in ("left_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_L"])
                    out_angles[frame_idx, 8] = th
                    out_angles[frame_idx, 9] = sh
                    out_angles[frame_idx, 10] = 1.605 - (th + sh) + curr_k["foot_roll_L"]

                if st in ("right_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_R"])
                    out_angles[frame_idx, 11] = th
                    out_angles[frame_idx, 12] = sh
                    out_angles[frame_idx, 13] = 1.605 - (th + sh) + curr_k["foot_roll_R"]
                continue

            # We are transitioning between curr_k and next_k
            next_k = processed[k_idx + 1]
            frame_seg[frame_idx] = k_idx + 1
            t_trans_start = curr_k["t_end_hold"]
            t_trans_end = next_k["t_start"]
            trans_duration = max(1e-4, t_trans_end - t_trans_start)

            norm_t = np.clip((t_sec - t_trans_start) / trans_duration, 0.0, 1.0)
            eased_t = next_k["easing"](norm_t)

            # 1. Angular interpolation (shortest circular distance)
            diff = shortest_angle_diff(next_k["angles"], curr_k["angles"])
            interp_angles = curr_k["angles"] + diff * eased_t

            # 2. Root translation interpolation
            interp_root = curr_k["root_xy"] + (next_k["root_xy"] - curr_k["root_xy"]) * eased_t

            # A zero-difference segment (e.g. ch.hold()/wait appends a same-pose
            # keyframe at the tail) is a hold in disguise: keep it alive with
            # breathing so long static stretches don't read as dead freeze.
            if (float(np.max(np.abs(diff))) < 1e-6
                    and float(np.max(np.abs(next_k["root_xy"] - curr_k["root_xy"]))) < 1e-6
                    and (next_k["t_start"] - t_trans_start) > 0.35):
                breath = hold_breath(t_sec - t_trans_start)
                interp_angles[0] += breath
                interp_angles[1] += breath * 0.5
                interp_angles[2] += breath * 0.25
                interp_root[1] += breath * 0.02

            out_root[frame_idx] = interp_root
            out_angles[frame_idx] = interp_angles

            # Stance pinning during transition:
            # Foot-roll overlays interpolate with the same easing so roll is continuous.
            roll_L = curr_k["foot_roll_L"] + (next_k["foot_roll_L"] - curr_k["foot_roll_L"]) * eased_t
            roll_R = curr_k["foot_roll_R"] + (next_k["foot_roll_R"] - curr_k["foot_roll_R"]) * eased_t
            # If both keyframes share a stance lock, hold it across the whole transition.
            # If transitioning between different stance feet, hold curr_k anchor while eased_t < 0.5
            if curr_k["stance_lock"] == next_k["stance_lock"] and curr_k["stance_lock"] is not None:
                st = curr_k["stance_lock"]
                if st in ("left_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_L"])
                    out_angles[frame_idx, 8] = th
                    out_angles[frame_idx, 9] = sh
                    out_angles[frame_idx, 10] = 1.605 - (th + sh) + roll_L

                if st in ("right_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_R"])
                    out_angles[frame_idx, 11] = th
                    out_angles[frame_idx, 12] = sh
                    out_angles[frame_idx, 13] = 1.605 - (th + sh) + roll_R
            elif eased_t < 0.5 and curr_k["stance_lock"] is not None:
                st = curr_k["stance_lock"]
                if st in ("left_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_L"])
                    out_angles[frame_idx, 8] = th
                    out_angles[frame_idx, 9] = sh
                    out_angles[frame_idx, 10] = 1.605 - (th + sh) + roll_L

                if st in ("right_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], curr_k["anchor_ankle_R"])
                    out_angles[frame_idx, 11] = th
                    out_angles[frame_idx, 12] = sh
                    out_angles[frame_idx, 13] = 1.605 - (th + sh) + roll_R
            elif eased_t >= 0.5 and next_k["stance_lock"] is not None:
                st = next_k["stance_lock"]
                if st in ("left_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], next_k["anchor_ankle_L"])
                    out_angles[frame_idx, 8] = th
                    out_angles[frame_idx, 9] = sh
                    out_angles[frame_idx, 10] = 1.605 - (th + sh) + roll_L

                if st in ("right_foot", "both_feet"):
                    th, sh = solve_two_bone_ik(out_root[frame_idx], next_k["anchor_ankle_R"])
                    out_angles[frame_idx, 11] = th
                    out_angles[frame_idx, 12] = sh
                    out_angles[frame_idx, 13] = 1.605 - (th + sh) + roll_R

        # 1. Safety net: cap angular velocity across frame boundaries.
        # Uses excess-spreading (endpoint-preserving), NOT a causal clip: a clip
        # would lag behind a fast transition and then stop dead, which is itself
        # the pop we are trying to remove. See limit_velocity_preserving_endpoints.
        # NOTE: deliberately runs AFTER stance pinning and is NOT re-pinned. Re-
        # solving IK here would re-apply each keyframe's own anchor and put the
        # discontinuity straight back (that was the getup leg-snap).
        if self.max_angular_vel > 0.0:
            out_angles = limit_velocity_preserving_endpoints(out_angles, self.max_angular_vel)

        # 2. Adaptive Cadence Stepping (e.g. hold on twos for cadence == 2)
        frame_cadence = np.ones(T, dtype=np.int32) * self.cadence
        for i, k in enumerate(processed):
            start_f = int(round(k["t_start"] * self.fps))
            end_f = int(round(k["t_end_hold"] * self.fps)) if i == len(processed) - 1 else int(round(processed[i + 1]["t_start"] * self.fps))
            start_f = max(0, min(T, start_f))
            end_f = max(0, min(T, end_f))
            if start_f < end_f:
                frame_cadence[start_f:end_f] = k["cadence"]

        for frame_idx in range(1, T):
            c = frame_cadence[frame_idx]
            if c > 1 and (frame_idx % c) != 0:
                out_root[frame_idx] = out_root[frame_idx - 1]
                out_angles[frame_idx] = out_angles[frame_idx - 1]

        # Encode to (T, 30) feature representation
        feat = encode(out_root, out_angles)
        return feat


def interpolate_keyframes(keyframes: List[Keyframe], total_duration_s: Optional[float] = None) -> np.ndarray:
    """Convenience helper to compile a list of Keyframes into motion features."""
    timeline = ArmatureTimeline()
    for k in keyframes:
        timeline.keyframes.append(k)
    return timeline.compile(total_duration_s=total_duration_s)
