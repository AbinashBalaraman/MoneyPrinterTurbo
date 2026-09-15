"""High-Level Puppet Choreography & Director Engine.

Provides fluent, expressive stop-motion choreography templates for locomotion,
combat, acrobatics, and character performance.
"""

from typing import Dict, Any, List, Optional, Union
import numpy as np

from src.puppet.armature import ArmatureTimeline, Keyframe
from src.puppet.pose import get_pose_angles
from src.rig import FPS, enforce_ground_contact


def create_standing_sequence(
    start_x: float = 0.0,
    duration_s: float = 2.0
) -> ArmatureTimeline:
    """Builds a pure natural standing sequence with subtle breathing life."""
    timeline = ArmatureTimeline()
    timeline.add_keyframe(
        t=0.0,
        pose="stand_relaxed",
        root_x=start_x,
        root_y=0.0,
        hold_duration_s=duration_s,
        stance_lock="both_feet",
        moving_hold=True,
        easing="ease_in_out"
    )
    return timeline


def create_squat_sequence(
    start_x: float = 0.0,
    duration_s: float = 2.5
) -> ArmatureTimeline:
    """Builds a controlled, physically grounded squat sequence."""
    timeline = ArmatureTimeline()
    curr_t = 0.0

    # 1. Standing preparation hold
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=start_x,
        root_y=0.0,
        hold_duration_s=0.35,
        stance_lock="both_feet",
        easing="ease_in_out"
    )
    curr_t += 0.35

    # 2. Descend into balanced squat
    curr_t += 0.65
    timeline.add_keyframe(
        t=curr_t,
        pose="squat_deep",
        root_x=start_x,
        root_y=-0.15,
        hold_duration_s=0.50,
        stance_lock="both_feet",
        moving_hold=True,
        easing="ease_in_out"
    )
    curr_t += 0.50

    # 3. Rise back up to standing
    curr_t += 0.60
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=start_x,
        root_y=0.0,
        hold_duration_s=0.40,
        stance_lock="both_feet",
        moving_hold=True,
        easing="ease_out"
    )

    return timeline


def create_single_step_sequence(
    start_x: float = 0.0,
    step_foot: str = "left",
    stride: float = 0.32,
    duration_s: float = 2.0
) -> ArmatureTimeline:
    """Builds a single, biomechanically pure step from standing rest to standing rest."""
    timeline = ArmatureTimeline()
    curr_t = 0.0
    curr_x = float(start_x)
    is_left = (step_foot.lower() == "left")

    # 1. Initial stable standing stance
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=curr_x,
        root_y=0.0,
        hold_duration_s=0.15,
        stance_lock="both_feet",
        easing="ease_in"
    )
    curr_t += 0.15

    # 2. Swing foot lifts & passes (weight on opposite plant foot)
    curr_x += stride * 0.45
    curr_t += 0.35
    pass_pose = "stride_pass_L" if is_left else "stride_pass_R"
    plant_lock = "right_foot" if is_left else "left_foot"
    timeline.add_keyframe(
        t=curr_t,
        pose=pass_pose,
        root_x=curr_x,
        root_y=0.01,
        easing="ease_in_out",
        stance_lock=plant_lock
    )

    # 3. Heel strike contact forward (3.5% pelvic absorption dip)
    curr_x += stride * 0.45
    curr_t += 0.35
    contact_pose = "stride_contact_L" if is_left else "stride_contact_R"
    strike_lock = "left_foot" if is_left else "right_foot"
    timeline.add_keyframe(
        t=curr_t,
        pose=contact_pose,
        root_x=curr_x,
        root_y=-0.035,
        easing="ease_in_out",
        stance_lock=strike_lock,
        foot_roll_L=0.25 if is_left else 0.0,
        foot_roll_R=0.0 if is_left else 0.25
    )

    # 4. Trailing foot steps forward alongside leading foot, snap-and-settle to balanced standing
    curr_x += stride * 0.10
    curr_t += 0.35
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=curr_x,
        root_y=0.0,
        hold_duration_s=0.20,
        stance_lock="both_feet",
        moving_hold=True,
        easing="snap_and_settle"
    )

    return timeline


def create_walk_sequence(
    steps: int = 4,
    step_duration: float = 0.45,
    start_x: float = 0.0,
    stride_length: float = 0.22,
    direction: int = 1,
    flight: float = 0.0,
    arm_scale: float = 1.0,
    start_hold: float = 0.20,
    end_hold: float = 0.50,
) -> ArmatureTimeline:
    """Builds a classic stop-motion walk cycle with proper anticipation, passing, and settle."""
    timeline = ArmatureTimeline()
    curr_t = 0.0
    curr_x = start_x
    dir_sign = 1.0 if direction >= 0 else -1.0

    def _pose(name: str):
        if arm_scale == 1.0:
            return name
        from src.puppet.pose import get_pose_root_y as _ry
        ang = get_pose_angles(name).copy()
        ang[[4, 5, 6, 7]] *= float(arm_scale)
        return ang

    def _root_y(name: str, extra: float = 0.0):
        if arm_scale == 1.0 and extra == 0.0:
            return None
        from src.puppet.pose import get_pose_root_y as _ry
        return float(_ry(name) + extra)

    # 1. Initial relaxed standing pose with a brief moving hold
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=curr_x,
        hold_duration_s=start_hold,
        easing="ease_in"
    )
    curr_t += start_hold

    # 2. Alternating steps (L contact -> L pass -> R contact -> R pass)
    # Backward locomotion (dir_sign < 0) uses dedicated walkback keyframes:
    # same facing, toe-first rear reach, 0.75x stride, reverse (toe-down) foot roll.
    is_back = dir_sign < 0.0
    step_stride = stride_length * (0.75 if is_back else 1.0)
    roll_strike = 0.20 if is_back else 0.0
    half_dur = step_duration / 2.0
    for s in range(steps):
        if s % 2 == 0:
            # Left leg leads (backward: left toe strikes behind, facing kept)
            contact_pose = "walkback_contact_L" if is_back else "stride_contact_L"
            pass_pose = "walkback_pass_L" if is_back else "stride_pass_L"
            curr_x += dir_sign * (step_stride * 0.5)
            curr_t += half_dur
            timeline.add_keyframe(
                t=curr_t,
                pose=_pose(contact_pose),
                root_x=curr_x,
                root_y=_root_y(contact_pose),
                easing="ease_in_out",
                stance_lock="left_foot",
                foot_roll_L=roll_strike,
            )

            curr_x += dir_sign * (step_stride * 0.5)
            curr_t += half_dur
            timeline.add_keyframe(
                t=curr_t,
                pose=_pose(pass_pose),
                root_x=curr_x,
                root_y=_root_y(pass_pose, flight),
                easing="ease_in_out",
                stance_lock=None if flight > 0 else "left_foot"
            )
        else:
            # Right leg leads (backward: right toe strikes behind, facing kept)
            contact_pose = "walkback_contact_R" if is_back else "stride_contact_R"
            pass_pose = "walkback_pass_R" if is_back else "stride_pass_R"
            curr_x += dir_sign * (step_stride * 0.5)
            curr_t += half_dur
            timeline.add_keyframe(
                t=curr_t,
                pose=_pose(contact_pose),
                root_x=curr_x,
                root_y=_root_y(contact_pose),
                easing="ease_in_out",
                stance_lock="right_foot",
                foot_roll_R=roll_strike,
            )

            curr_x += dir_sign * (step_stride * 0.5)
            curr_t += half_dur
            timeline.add_keyframe(
                t=curr_t,
                pose=_pose(pass_pose),
                root_x=curr_x,
                root_y=_root_y(pass_pose, flight),
                easing="ease_in_out",
                stance_lock=None if flight > 0 else "right_foot"
            )

    # 3. Settle back into relaxed stance
    curr_t += 0.30
    timeline.add_keyframe(
        t=curr_t,
        pose="stand_relaxed",
        root_x=curr_x,
        hold_duration_s=end_hold,
        easing="ease_out",
        stance_lock="both_feet"
    )

    return timeline


def create_combat_sequence(
    start_x: float = 0.0,
    action: str = "punch"
) -> ArmatureTimeline:
    """Builds a dynamic combat sequence: stance -> windup -> snap strike -> settle."""
    timeline = ArmatureTimeline()
    curr_t = 0.0

    # 1. Guard Stance
    timeline.add_keyframe(t=curr_t, pose="guard_high", root_x=start_x, hold_duration_s=0.25, easing="ease_in")
    curr_t += 0.25

    if action == "kick":
        # Anticipation & Chamber
        curr_t += 0.25
        timeline.add_keyframe(t=curr_t, pose="kick_chamber", root_x=start_x, easing="ease_in_out", stance_lock="right_foot")

        # Snappy Strike
        curr_t += 0.18
        timeline.add_keyframe(t=curr_t, pose="kick_extend", root_x=start_x + 0.05, hold_duration_s=0.12, easing="snap_and_settle", moving_hold=False)
        timeline.add_event(t=curr_t, kind="impact_burst", joint="foot_L", scale=1.1)
        curr_t += 0.12

        # Return to guard
        curr_t += 0.30
        timeline.add_keyframe(t=curr_t, pose="guard_high", root_x=start_x, hold_duration_s=0.40, easing="ease_out")

    else:
        # Punch Anticipation Windup
        curr_t += 0.25
        timeline.add_keyframe(t=curr_t, pose="punch_windup", root_x=start_x - 0.04, easing="ease_in")

        # Crisp Snap & Settle Strike
        curr_t += 0.16
        timeline.add_keyframe(t=curr_t, pose="punch_impact", root_x=start_x + 0.08, hold_duration_s=0.10, easing="snap_and_settle", moving_hold=False)
        timeline.add_event(t=curr_t, kind="impact_burst", joint="hand_R", scale=1.0)
        curr_t += 0.10

        # Recover to Guard
        curr_t += 0.30
        timeline.add_keyframe(t=curr_t, pose="guard_high", root_x=start_x, hold_duration_s=0.40, easing="ease_out")

    return timeline


def create_jump_sequence(
    start_x: float = 0.0,
    distance_x: float = 0.35,
    apex_height: float = 0.38
) -> ArmatureTimeline:
    """Builds an acrobatic jump: crouch anticipation -> explosive leap -> apex flight -> absorption."""
    timeline = ArmatureTimeline()
    curr_t = 0.0

    # 1. Stance
    timeline.add_keyframe(t=curr_t, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.08, easing="ease_in")
    curr_t += 0.08

    # 2. Deep Crouch Anticipation (loading springs)
    curr_t += 0.25
    timeline.add_keyframe(t=curr_t, pose="crouch_anticipate", root_x=start_x, hold_duration_s=0.15, easing="ease_in_out")
    curr_t += 0.15
    # Takeoff dust kicked up as the leap drives off the planted feet
    timeline.add_event(t=0.33, kind="dust_puff", joint="foot_L", scale=1.1)

    # 3. Explosive Takeoff
    curr_t += 0.12
    timeline.add_keyframe(t=curr_t, pose="jump_takeoff", root_x=start_x + distance_x * 0.2, easing="ease_out")

    # 4. Flight Apex (corrected tuck: thighs forward, shins folded back, arms spread)
    curr_t += 0.28
    _apex = get_pose_angles("jump_apex").copy()
    _apex[8] = 0.80
    _apex[9] = -1.20
    _apex[11] = 0.60
    _apex[12] = -1.00
    timeline.add_keyframe(t=curr_t, pose=_apex, root_x=start_x + distance_x * 0.5, root_y=apex_height, easing="ease_out")

    # 5. Touchdown Contact (toes meet ground, legs extended in stagger, no overshoot)
    curr_t += 0.26
    _contact = get_pose_angles("jump_takeoff").copy()
    _contact[0] = 0.18
    _contact[1] = 0.10
    _contact[4] = 0.35
    _contact[5] = -0.15
    _contact[6] = -0.35
    _contact[7] = 0.15
    _contact[8] = 0.32
    _contact[9] = -0.15
    _contact[11] = -0.20
    _contact[12] = -0.12
    timeline.add_keyframe(t=curr_t, pose=_contact, root_x=start_x + distance_x * 0.8, root_y=0.02, hold_duration_s=0.04, easing="ease_in")
    curr_t += 0.04

    # 6. Squash / Absorption (deep staggered knee bend, hips drop, arms counterbalance)
    curr_t += 0.16
    _absorb = get_pose_angles("jump_land_absorb").copy()
    _absorb[0] = 0.30
    _absorb[1] = 0.18
    _absorb[4] = 0.55
    _absorb[5] = -0.30
    _absorb[6] = -0.55
    _absorb[7] = 0.30
    _absorb[8] = 0.65
    _absorb[9] = -1.25
    _absorb[11] = 0.50
    _absorb[12] = -1.05
    timeline.add_keyframe(t=curr_t, pose=_absorb, root_x=start_x + distance_x, root_y=-0.18, hold_duration_s=0.25, easing="ease_out")
    timeline.add_event(t=curr_t, kind="dust_puff", x=start_x + distance_x, scale=1.1)
    curr_t += 0.25

    # 7. Recovery (half-rise, keeps forward stagger so side read never snaps frontal)
    curr_t += 0.25
    _rec = get_pose_angles("stand_relaxed").copy()
    _rec[0] = 0.14
    _rec[1] = 0.08
    _rec[4] = 0.30
    _rec[6] = -0.30
    _rec[8] = 0.30
    _rec[9] = -0.50
    _rec[11] = 0.20
    _rec[12] = -0.40
    timeline.add_keyframe(t=curr_t, pose=_rec, root_x=start_x + distance_x, root_y=-0.06, hold_duration_s=0.10, easing="ease_out")
    curr_t += 0.10

    # 8. Rise to staggered standing (slight lead foot + lean keeps profile view)
    curr_t += 0.30
    _stand = get_pose_angles("stand_relaxed").copy()
    _stand[0] = 0.05
    _stand[8] = 0.12
    _stand[9] = -0.08
    _stand[11] = -0.10
    _stand[12] = -0.06
    timeline.add_keyframe(t=curr_t, pose=_stand, root_x=start_x + distance_x, hold_duration_s=0.35, easing="ease_out")

    return timeline


def create_slide_sequence(
    start_x: float = 0.0,
    distance_x: float = 0.60,
    duration_s: float = 2.0
) -> ArmatureTimeline:
    """Builds an acrobatic powerslide: sprint-in -> low ground glide -> recover.

    The glide keeps stance unlocked so both feet skim forward with the root;
    dust puffs fire at drop-in and mid-glide (ground level y=-0.40).
    """
    timeline = ArmatureTimeline()
    curr_t = 0.0

    # 1. Ready stance
    timeline.add_keyframe(t=curr_t, pose="stand_relaxed", root_x=start_x,
                          hold_duration_s=0.15, easing="ease_in")
    curr_t += 0.15

    # 2. Sprint-in strides (two quick contacts driving +X)
    curr_t += 0.20
    timeline.add_keyframe(t=curr_t, pose="stride_contact_L", root_x=start_x + 0.15,
                          easing="ease_in_out", stance_lock="left_foot")
    curr_t += 0.20
    timeline.add_keyframe(t=curr_t, pose="stride_contact_R", root_x=start_x + 0.30,
                          easing="ease_in_out", stance_lock="right_foot")

    # 3. Drop into low slide (legs thrown forward, torso leaned back, no pin -> glide)
    curr_t += 0.18
    _sl = get_pose_angles("stand_relaxed").copy()
    _sl[0] = -0.30
    _sl[1] = -0.20
    _sl[2] = 0.10
    _sl[3] = 0.12
    _sl[4] = -0.70
    _sl[5] = -0.30
    _sl[6] = -0.50
    _sl[7] = 0.20
    _sl[8] = 0.95
    _sl[9] = -0.25
    _sl[10] = 1.45
    _sl[11] = 0.75
    _sl[12] = -0.20
    _sl[13] = 1.45
    timeline.add_keyframe(t=curr_t, pose=_sl, root_x=start_x + 0.38, root_y=-0.20,
                          easing="ease_out")
    timeline.add_event(t=curr_t, kind="dust_puff", joint="foot_L", scale=1.2)
    timeline.add_event(t=curr_t, kind="dust_puff", x=start_x + 0.45, y=-0.40, scale=1.0)

    # 4. Glide through to full distance, skimming low
    curr_t += 0.45
    timeline.add_keyframe(t=curr_t, pose=_sl, root_x=start_x + distance_x, root_y=-0.20,
                          hold_duration_s=0.10, easing="ease_in_out")

    # 5. Recover to standing
    curr_t += 0.35
    timeline.add_keyframe(t=curr_t, pose="stand_relaxed", root_x=start_x + distance_x,
                          hold_duration_s=max(0.2, duration_s - curr_t), easing="ease_out")

    return timeline


def create_expressive_sequence(
    start_x: float = 0.0,
    gesture: str = "wave"
) -> ArmatureTimeline:
    """Builds character theatrical performance: wave, celebration, or distress."""
    timeline = ArmatureTimeline()
    curr_t = 0.0

    timeline.add_keyframe(t=curr_t, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.20, easing="ease_in")
    curr_t += 0.20

    if gesture == "celebrate":
        curr_t += 0.35
        timeline.add_keyframe(t=curr_t, pose="celebrate_cheer", root_x=start_x, hold_duration_s=1.2, easing="snap_and_settle")
        curr_t += 1.2
    elif gesture == "distress":
        curr_t += 0.40
        timeline.add_keyframe(t=curr_t, pose="distress_head_clasp", root_x=start_x, hold_duration_s=1.5, easing="ease_in_out")
        curr_t += 1.5
    else:  # wave
        curr_t += 0.35
        timeline.add_keyframe(t=curr_t, pose="wave_tilt", root_x=start_x, hold_duration_s=1.2, easing="ease_in_out")
        curr_t += 1.2

    curr_t += 0.35
    timeline.add_keyframe(t=curr_t, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.5, easing="ease_out")
    return timeline


class PuppetChoreographer:
    """Fluent director API for choreographing multi-action stop-motion puppet sequences."""

    def __init__(self, start_x: float = 0.0, fps: int = FPS, init_pose: Optional[str] = None):
        self.fps = fps
        self.current_x = float(start_x)
        self.timeline = ArmatureTimeline(fps=fps)
        self.current_t = 0.0
        if init_pose is not None:
            self.timeline.add_keyframe(t=0.0, pose=init_pose, root_x=self.current_x, hold_duration_s=0.2)
            self.current_t = 0.2

    def wait(self, duration_s: float = 1.0) -> "PuppetChoreographer":
        """Holds current pose with subtle organic breathing life."""
        # Find last pose
        last_pose = self.timeline.keyframes[-1].pose if self.timeline.keyframes else "stand_relaxed"
        self.current_t += float(duration_s)
        self.timeline.add_keyframe(
            t=self.current_t,
            pose=last_pose,
            root_x=self.current_x,
            hold_duration_s=0.0,
            moving_hold=True
        )
        return self

    hold = wait

    def _append_sub_timeline(self, sub: ArmatureTimeline) -> None:
        """Appends keyframes and events from a sub-timeline."""
        for kf in sub.keyframes:
            self.timeline.add_keyframe(
                t=self.current_t + kf.t,
                pose=kf.pose,
                root_x=kf.root_x,
                root_y=kf.root_y,
                easing=kf.easing,
                hold_duration_s=kf.hold_duration_s,
                stance_lock=kf.stance_lock,
                foot_roll_L=kf.foot_roll_L,
                foot_roll_R=kf.foot_roll_R,
                moving_hold=kf.moving_hold,
                cadence=kf.cadence
            )
        for ev in sub.events:
            self.timeline.add_event(
                t=self.current_t + ev.t,
                kind=ev.kind,
                joint=ev.joint,
                x=ev.x,
                y=ev.y,
                scale=ev.scale,
                duration_frames=ev.duration_frames,
                **ev.params
            )
        self.current_x = sub.keyframes[-1].root_x or self.current_x
        self.current_t += sub.keyframes[-1].t + sub.keyframes[-1].hold_duration_s

    def squat(self, duration_s: float = 2.5) -> "PuppetChoreographer":
        """Appends a controlled, grounded squat to the director timeline."""
        sub = create_squat_sequence(start_x=self.current_x, duration_s=duration_s)
        self._append_sub_timeline(sub)
        return self

    def single_step(self, step_foot: str = "left", stride: float = 0.32, duration_s: float = 2.0) -> "PuppetChoreographer":
        """Appends a single clean biomechanical step from standing to standing."""
        sub = create_single_step_sequence(start_x=self.current_x, step_foot=step_foot, stride=stride, duration_s=duration_s)
        self._append_sub_timeline(sub)
        return self

    def walk(self, steps: int = 4, step_duration: float = 0.45, stride_length: float = 0.22, direction: int = 1, flight: float = 0.0, arm_scale: float = 1.0, end_hold: float = 0.50) -> "PuppetChoreographer":
        """Appends a walk sequence to the director timeline."""
        sub = create_walk_sequence(steps=steps, step_duration=step_duration, start_x=self.current_x, stride_length=stride_length, direction=direction, flight=flight, arm_scale=arm_scale, end_hold=end_hold)
        self._append_sub_timeline(sub)
        return self

    def run(self, steps: int = 4, step_duration: float = 0.26, stride_length: float = 0.34, direction: int = 1) -> "PuppetChoreographer":
        """Appends a sprint/run sequence with dynamic lean, wider stride, and fast cadence."""
        sub = create_walk_sequence(steps=steps, step_duration=step_duration, start_x=self.current_x, stride_length=stride_length, direction=direction)
        self._append_sub_timeline(sub)
        return self

    def punch(self) -> "PuppetChoreographer":
        """Appends a punch strike with snap-and-settle and automatic impact burst VFX."""
        sub = create_combat_sequence(start_x=self.current_x, action="punch")
        self._append_sub_timeline(sub)
        return self

    def kick(self) -> "PuppetChoreographer":
        """Appends a kick strike with snap-and-settle and automatic impact burst VFX."""
        sub = create_combat_sequence(start_x=self.current_x, action="kick")
        self._append_sub_timeline(sub)
        return self

    def jump(self, distance_x: float = 0.35, height: float = 0.38) -> "PuppetChoreographer":
        """Appends an acrobatic jump with takeoff and landing dust puff VFX."""
        sub = create_jump_sequence(start_x=self.current_x, distance_x=distance_x, apex_height=height)
        self._append_sub_timeline(sub)
        return self

    def slide(self, distance_x: float = 0.60, duration_s: float = 2.0) -> "PuppetChoreographer":
        """Appends an acrobatic powerslide: sprint-in, low ground glide, recover."""
        sub = create_slide_sequence(start_x=self.current_x, distance_x=distance_x, duration_s=duration_s)
        self._append_sub_timeline(sub)
        return self

    def wave(self) -> "PuppetChoreographer":
        """Appends a hand-wave gesture."""
        sub = create_expressive_sequence(start_x=self.current_x, gesture="wave")
        self._append_sub_timeline(sub)
        return self

    def celebrate(self) -> "PuppetChoreographer":
        """Appends a celebration cheer."""
        sub = create_expressive_sequence(start_x=self.current_x, gesture="celebrate")
        self._append_sub_timeline(sub)
        return self

    def vfx(
        self,
        kind: str,
        joint: Optional[Union[int, str]] = None,
        x: Optional[float] = None,
        y: Optional[float] = None,
        scale: float = 1.0,
        duration_frames: int = 8,
        **params
    ) -> "PuppetChoreographer":
        """Appends a timed visual effect event at the current director timestamp."""
        self.timeline.add_event(
            t=self.current_t,
            kind=kind,
            joint=joint,
            x=x,
            y=y,
            scale=scale,
            duration_frames=duration_frames,
            **params
        )
        return self

    def compile_events(self, puppet_index: int = 0) -> List[Dict[str, Any]]:
        """Returns compiled render-ready VFX event dictionaries for stage renderer."""
        return self.timeline.compile_events(puppet_index=puppet_index)

    def compile(self, total_duration_s: Optional[float] = None) -> np.ndarray:
        """Compiles complete choreography into (T, 30) motion features."""
        from src.rig import enforce_ground_contact
        return enforce_ground_contact(self.timeline.compile(total_duration_s=total_duration_s))


def build_motion_from_action(
    action: str,
    duration_s: float = 3.0,
    speed: float = 1.0,
    amplitude: float = 1.0,
    direction: int = 1,
    seed: int = 0,
    start_x: float = 0.0,
    return_events: bool = False
):
    """Compiles any action name into smooth stop-motion puppet motion features (T, 30).

    Replaces legacy continuous sine waves with pose-to-pose keyframing,
    smooth easing, zero-drift stance pinning, and moving holds.
    """
    ch = PuppetChoreographer(start_x=start_x)
    act = action.strip().lower()
    dir_val = 1 if direction >= 0 else -1

    # Deterministic per-seed micro-variation: scales speed/amplitude by a small
    # seed-derived factor. Contact-safe (IK re-pins stance; ground pass runs
    # after), so it adds diversity without breaking biomechanics.
    if seed:
        jitter = 1.0 + 0.06 * (((seed * 2654435761) % 1000) / 1000.0 - 0.5)
        speed = float(speed) * jitter
        amplitude = float(amplitude) * (2.0 - jitter)

    if act in ("walk", "stroll", "march"):
        step_dur = max(0.25, 0.45 / speed)
        n_steps = max(2, int(duration_s / step_dur))
        ch.walk(steps=n_steps, step_duration=step_dur, stride_length=0.22 * amplitude, direction=dir_val, end_hold=0.20)
    elif act in ("walkback", "retreat", "backpedal"):
        step_dur = max(0.25, 0.45 / speed)
        n_steps = max(2, int(duration_s / step_dur))
        ch.walk(steps=n_steps, step_duration=step_dur, stride_length=0.22 * amplitude, direction=-dir_val, end_hold=0.20)
    elif act in ("run", "sprint", "dash"):
        step_dur = max(0.18, 0.30 / speed)
        n_steps = max(2, int(duration_s / step_dur))
        ch.walk(steps=n_steps, step_duration=step_dur, stride_length=0.34 * amplitude, direction=dir_val, flight=0.06 * amplitude, arm_scale=1.6, end_hold=0.15)
    elif act in ("punch", "strike", "hit", "jab"):
        ch.punch()
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("kick", "high_kick"):
        ch.kick()
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("jump", "leap", "hop"):
        ch.jump(distance_x=0.35 * amplitude * dir_val, height=0.38 * amplitude)
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("slide", "powerslide", "slide_tackle"):
        ch.slide(distance_x=0.60 * amplitude * dir_val)
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("wave", "greeting"):
        ch.wave()
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("celebrate", "cheer", "victory"):
        ch.celebrate()
        rem = max(0.2, duration_s - ch.current_t)
        ch.hold(rem)
    elif act in ("squat", "crouch", "duck"):
        ch.timeline.add_keyframe(t=0.0, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.2, easing="ease_in")
        ch.timeline.add_keyframe(t=0.2, pose="crouch_anticipate", root_x=start_x, hold_duration_s=max(0.2, duration_s - 0.8), easing="ease_in_out")
        ch.timeline.add_keyframe(t=max(0.4, duration_s - 0.4), pose="stand_relaxed", root_x=start_x, hold_duration_s=0.4, easing="ease_out")
    elif act in ("block", "guard", "defend"):
        ch.timeline.add_keyframe(t=0.0, pose="guard_high", root_x=start_x, hold_duration_s=max(0.5, duration_s - 0.4), easing="ease_in_out")
        ch.timeline.add_keyframe(t=max(0.5, duration_s - 0.3), pose="stand_relaxed", root_x=start_x, hold_duration_s=0.3, easing="ease_out")
    elif act in ("knockdown", "fall", "collapse"):
        ch.timeline.add_keyframe(t=0.0, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.1)
        ch.timeline.add_keyframe(t=0.25, pose="hit_recoil", root_x=start_x - 0.12 * dir_val, easing="ease_in")
        ch.timeline.add_keyframe(t=0.55, pose="knockdown_fall", root_x=start_x - 0.25 * dir_val, easing="ease_in")
        ch.timeline.add_keyframe(t=0.85, pose="ground_prone", root_x=start_x - 0.35 * dir_val, hold_duration_s=max(0.5, duration_s - 1.0), easing="snap_and_settle")
    elif act in ("getup", "rise", "stand_up"):
        ch.timeline.add_keyframe(t=0.0, pose="ground_prone", root_x=start_x, hold_duration_s=0.15)
        # Steady organic rise to crouch over 0.55s
        ch.timeline.add_keyframe(t=0.70, pose="crouch_anticipate", root_x=start_x, hold_duration_s=0.20, easing="ease_in_out")
        # Rise from crouch to full standing
        t_stand = min(1.35, max(1.10, duration_s - 0.35))
        ch.timeline.add_keyframe(t=t_stand, pose="stand_relaxed", root_x=start_x, hold_duration_s=max(0.2, duration_s - t_stand), easing="ease_out")
    elif act in ("distress", "panic"):
        ch.timeline.add_keyframe(t=0.0, pose="stand_relaxed", root_x=start_x, hold_duration_s=0.1)
        ch.timeline.add_keyframe(t=0.4, pose="distress_head_clasp", root_x=start_x, hold_duration_s=max(0.5, duration_s - 0.5), easing="ease_in_out")
    elif act in ("idle", "stand", "standing", "rest"):
        # Idle: stand with subtle breathing life.
        ch.timeline.add_keyframe(t=0.0, pose="stand_relaxed", root_x=start_x, hold_duration_s=duration_s, moving_hold=True)
    else:
        # Fail loudly. PROJECT.md contract: an unsupported action must never be
        # silently mapped to a plausible-looking pose ("never silent wrong mapping").
        from src.catalog import ACTIONS_1P, ACTIONS_2P  # lazy: avoids import cycle
        raise ValueError(
            f"Unknown action {action!r}. Supported actions: "
            f"{sorted(ACTIONS_1P) + sorted(ACTIONS_2P)}"
        )

    feat = ch.compile(total_duration_s=duration_s)
    if return_events:
        return feat, ch.timeline.compile_events(puppet_index=0)
    return feat


def _mirror_pose_angles(pose_name: str) -> np.ndarray:
    """Returns pose joint angles negated so character faces left (-X)."""
    return -get_pose_angles(pose_name)


def get_combat_props(action: str):
    """Joint-anchored prop specs for weapon combat pairs (renderer draw contract).

    Returns a list of prop dicts with anchor_puppet/joint keys, or [] when the
    action fields no weapons. Suite callers should still guard with a fallback.
    """
    act = (action or "").strip().lower()
    if act in ("sword_clash", "weapon_duel"):
        return [
            {"kind": "sword", "anchor_puppet": 0, "joint": 8},
            {"kind": "shield", "anchor_puppet": 1, "joint": 6},
        ]
    return []


def build_combat_pair(
    action: str,
    duration_s: float = 3.0,
    speed: float = 1.0,
    amplitude: float = 1.0,
    seed: int = 0,
    return_events: bool = False
):
    """Compiles synchronized 2-person martial arts stop-motion combat features (T, 60).

    Person A (Attacker) is on the left at x = -0.45 facing right (+X).
    Person B (Defender) is on the right at x = +0.45 facing left (-X).
    Keyframe timestamps and spatial distances are synchronized so strikes physically
    connect with blocks, dodges, and knockdowns without clipping or missing.
    """
    act = action.strip().lower()
    dur = float(duration_s)
    
    tl_a = ArmatureTimeline(fps=FPS, max_angular_vel=0.60)
    tl_b = ArmatureTimeline(fps=FPS, max_angular_vel=0.60)

    pos_a = -0.45
    pos_b = +0.45

    if act in ("punch_block", "strike_block"):
        # Person A (Attacker): winds up and launches straight punch
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=0.2)
        tl_a.add_keyframe(t=0.40 / speed, pose="strike_anticipate", root_x=pos_a + 0.12 * amplitude, easing="ease_in")
        tl_a.add_keyframe(t=0.65 / speed, pose="punch_impact", root_x=pos_a + 0.22 * amplitude, hold_duration_s=0.12, easing="snap_and_settle", moving_hold=False)
        tl_a.add_event(t=0.65 / speed, kind="impact_burst", joint="hand_r", scale=1.0)
        t_rec = min(1.30 / speed, dur - 0.5)
        tl_a.add_keyframe(t=t_rec, pose="stand_relaxed", root_x=pos_a, hold_duration_s=max(0.3, dur - t_rec), easing="ease_out")

        # Person B (Defender): raises high guard to intercept punch at impact
        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=0.25)
        tl_b.add_keyframe(t=0.55 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05 * amplitude, hold_duration_s=0.20, easing="ease_in_out")
        # Block flinch: B absorbs the blocked punch on guard (pushback + hit-stop).
        tl_b.add_keyframe(t=0.77 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05 * amplitude - 0.06 * amplitude, hold_duration_s=0.08, easing="ease_in", moving_hold=False)
        t_b_rec = min(1.35 / speed, dur - 0.4)
        tl_b.add_keyframe(t=t_b_rec, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=max(0.3, dur - t_b_rec), easing="ease_out")

    elif act in ("kick_dodge", "kick_crouch"):
        # Person A (Attacker): chambers and fires high kick
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=0.2)
        tl_a.add_keyframe(t=0.40 / speed, pose="kick_anticipate", root_x=pos_a + 0.10 * amplitude, easing="ease_in")
        tl_a.add_keyframe(t=0.70 / speed, pose="kick_impact", root_x=pos_a + 0.20 * amplitude, hold_duration_s=0.20, easing="snap_and_settle")
        tl_a.add_event(t=0.65 / speed, kind="speed_lines", joint="foot_l", direction=1.0, scale=1.2)
        t_rec = min(1.35 / speed, dur - 0.5)
        tl_a.add_keyframe(t=t_rec, pose="stand_relaxed", root_x=pos_a, hold_duration_s=max(0.3, dur - t_rec), easing="ease_out")

        # Person B (Defender): ducks low under the high kick
        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=0.30)
        tl_b.add_keyframe(t=0.60 / speed, pose=_mirror_pose_angles("crouch_anticipate"), root_x=pos_b, hold_duration_s=0.35, easing="ease_in_out")
        t_b_rec = min(1.40 / speed, dur - 0.4)
        tl_b.add_keyframe(t=t_b_rec, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=max(0.3, dur - t_b_rec), easing="ease_out")

    elif act in ("exchange", "sparring"):
        # Multi-hit exchange: A attacks, B blocks; B counters, A ducks; A kicks, B parries
        # Hit 1: A strikes, B blocks
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=0.15)
        tl_a.add_keyframe(t=0.45 / speed, pose="punch_impact", root_x=pos_a + 0.18 * amplitude, hold_duration_s=0.12, easing="snap_and_settle")
        tl_a.add_event(t=0.45 / speed, kind="impact_burst", joint="hand_r", scale=1.0)
        tl_a.add_keyframe(t=0.90 / speed, pose="guard_high", root_x=pos_a + 0.05, hold_duration_s=0.10, easing="ease_in_out")
        # Block flinch: A absorbs B's counter on guard (pushback + hit-stop freeze).
        tl_a.add_keyframe(t=1.02 / speed, pose="guard_high", root_x=pos_a + 0.05 + 0.06 * amplitude, hold_duration_s=0.08, easing="ease_in", moving_hold=False)
        tl_a.add_keyframe(t=1.45 / speed, pose="kick_impact", root_x=pos_a + 0.15 * amplitude, hold_duration_s=0.15, easing="snap_and_settle")
        tl_a.add_event(t=1.45 / speed, kind="impact_burst", joint="foot_r", scale=1.1)
        t_rec = min(2.10 / speed, dur - 0.4)
        tl_a.add_keyframe(t=t_rec, pose="stand_relaxed", root_x=pos_a, hold_duration_s=max(0.3, dur - t_rec), easing="ease_out")

        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=0.2)
        tl_b.add_keyframe(t=0.45 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05, hold_duration_s=0.10, easing="ease_in_out")
        # Block flinch: B absorbs A's strike on guard (pushback + hit-stop freeze).
        tl_b.add_keyframe(t=0.57 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05 - 0.06 * amplitude, hold_duration_s=0.08, easing="ease_in", moving_hold=False)
        tl_b.add_keyframe(t=0.90 / speed, pose=_mirror_pose_angles("punch_impact"), root_x=pos_b - 0.18 * amplitude, hold_duration_s=0.12, easing="snap_and_settle")
        tl_b.add_event(t=0.90 / speed, kind="impact_burst", joint="hand_r", scale=1.0)
        tl_b.add_keyframe(t=1.45 / speed, pose=_mirror_pose_angles("crouch_anticipate"), root_x=pos_b, hold_duration_s=0.25, easing="ease_in_out")
        t_b_rec = min(2.15 / speed, dur - 0.4)
        tl_b.add_keyframe(t=t_b_rec, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=max(0.3, dur - t_b_rec), easing="ease_out")

    elif act in ("knockdown_getup", "knockout"):
        # Person A (Attacker): Heavy blow that knocks B down, then celebrates
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=0.2)
        tl_a.add_keyframe(t=0.55 / speed, pose="punch_impact", root_x=pos_a + 0.25 * amplitude, hold_duration_s=0.20, easing="snap_and_settle")
        tl_a.add_keyframe(t=1.00 / speed, pose="stand_relaxed", root_x=pos_a + 0.10, hold_duration_s=0.3, easing="ease_out")
        t_cel = min(1.60 / speed, dur - 0.5)
        tl_a.add_keyframe(t=t_cel, pose="celebrate_cheer", root_x=pos_a + 0.10, hold_duration_s=max(0.4, dur - t_cel), easing="ease_out")

        # Person B (Defender): Recoils from impact, collapses flat, holds prone, then rises
        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=0.25)
        tl_b.add_keyframe(t=0.55 / speed, pose=_mirror_pose_angles("hit_recoil"), root_x=pos_b + 0.10 * amplitude, hold_duration_s=0.10, easing="ease_in", moving_hold=False)
        tl_b.add_event(t=0.55 / speed, kind="impact_burst", joint="hand_r", scale=1.2)
        tl_b.add_keyframe(t=0.85 / speed, pose=_mirror_pose_angles("knockdown_fall"), root_x=pos_b + 0.22 * amplitude, easing="ease_in")
        tl_b.add_keyframe(t=1.15 / speed, pose=_mirror_pose_angles("ground_prone"), root_x=pos_b + 0.32 * amplitude, hold_duration_s=0.50, easing="snap_and_settle")
        tl_b.add_keyframe(t=1.85 / speed, pose=_mirror_pose_angles("crouch_anticipate"), root_x=pos_b + 0.32 * amplitude, hold_duration_s=0.25, easing="ease_in_out")
        t_b_rec = min(2.50 / speed, dur - 0.4)
        tl_b.add_keyframe(t=t_b_rec, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b + 0.32 * amplitude, hold_duration_s=max(0.3, dur - t_b_rec), easing="ease_out")

    elif act in ("sword_clash", "weapon_duel"):
        # Weapon duel: A slashes with sword, B catches it on shield guard.
        # Person A (Attacker): windup into forward sword slash.
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=0.2)
        tl_a.add_keyframe(t=0.35 / speed, pose="strike_anticipate", root_x=pos_a + 0.12 * amplitude, easing="ease_in")
        tl_a.add_keyframe(t=0.60 / speed, pose="punch_impact", root_x=pos_a + 0.22 * amplitude, hold_duration_s=0.12, easing="snap_and_settle", moving_hold=False)
        tl_a.add_event(t=0.60 / speed, kind="speed_lines", joint="hand_r", direction=1.0, scale=1.2)
        tl_a.add_event(t=0.60 / speed, kind="impact_burst", joint="hand_r", scale=1.2)
        t_rec = min(1.30 / speed, dur - 0.5)
        tl_a.add_keyframe(t=t_rec, pose="stand_relaxed", root_x=pos_a, hold_duration_s=max(0.3, dur - t_rec), easing="ease_out")

        # Person B (Defender): shield guard up, absorbs clash with flinch + freeze.
        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=0.25)
        tl_b.add_keyframe(t=0.55 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05 * amplitude, hold_duration_s=0.20, easing="ease_in_out")
        tl_b.add_keyframe(t=0.60 / speed, pose=_mirror_pose_angles("guard_high"), root_x=pos_b - 0.05 * amplitude - 0.08, hold_duration_s=0.08, easing="ease_in", moving_hold=False)
        # Recover to a live stance so the defender does not freeze for the rest of the clip.
        t_b_rec = min(1.35 / speed, dur - 0.4)
        tl_b.add_keyframe(t=t_b_rec, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=max(0.3, dur - t_b_rec), easing="ease_out")

    else:
        # Default 2P: two stickmen facing each other in idle stance with subtle breathing
        tl_a.add_keyframe(t=0.0, pose="stand_relaxed", root_x=pos_a, hold_duration_s=dur, moving_hold=True)
        tl_b.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=pos_b, hold_duration_s=dur, moving_hold=True)

    feat_a = enforce_ground_contact(tl_a.compile(total_duration_s=dur))  # (T, 30)
    feat_b = enforce_ground_contact(tl_b.compile(total_duration_s=dur))  # (T, 30)

    # Harmonize length
    T_min = min(len(feat_a), len(feat_b))
    feat_2p = np.concatenate([feat_a[:T_min], feat_b[:T_min]], axis=-1)  # (T, 60)
    feat_2p = feat_2p.astype(np.float32)
    if return_events:
        events = tl_a.compile_events(puppet_index=0) + tl_b.compile_events(puppet_index=1)
        return feat_2p, events
    return feat_2p


