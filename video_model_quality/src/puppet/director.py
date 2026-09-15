"""L3 Fluent Director API: chainable locomotion/gesture/pose direction.

Brain side (TASK-014). Base motion is built from L2 gait timelines on one
ArmatureTimeline; gesture/strike overlays are compiled separately and layered
with split-body crossfades, so legs always follow the base (stance safe).
Read-only consumer of choreography builders and Pi's Body entity.
"""
from typing import Dict, Any, List, Optional

import numpy as np

from src.puppet.armature import ArmatureTimeline
from src.puppet.controllers import (GaitCommand, LocomotionController,
                                    UPPER_BODY_BONES, layer_timelines)
from src.rig import FPS


class Director:
    """Fluent performance director.

    Example:
        d = Director()
        d.locomote(speed=0.4, duration_s=3.0).gesture("wave", at=0.5).strike("punch", at=2.0)
        feat, events = d.compile(return_events=True)
    """

    def __init__(self, start_x: float = 0.0, fps: int = FPS):
        self.fps = int(fps)
        self.start_x = float(start_x)
        self.current_x = float(start_x)
        self.current_t = 0.0
        self._gait = LocomotionController(fps=self.fps)
        self._segments: List[Dict[str, Any]] = []   # ordered base pieces
        self._overlays: List[Dict[str, Any]] = []   # gesture/strike overlays

    # -- base pieces (advance current_t / current_x) -------------------------
    def locomote(self, speed: float, duration_s: float, stride_length: float = 0.22,
                 cadence: int = 1, lean: float = 0.0) -> "Director":
        """Walks (or walkbacks, when speed < 0) for duration_s."""
        self._segments.append({"kind": "gait", "t": self.current_t,
                               "cmd": GaitCommand(speed=speed, duration_s=duration_s,
                                                  stride_length=stride_length,
                                                  cadence=cadence, lean=lean)})
        self.current_x += float(speed) * float(duration_s)
        self.current_t += float(duration_s)
        return self

    def hold(self, duration_s: float, pose: str = "stand_relaxed") -> "Director":
        """Holds a pose with breathing life."""
        self._segments.append({"kind": "hold", "t": self.current_t, "pose": pose,
                               "duration_s": float(duration_s), "x": self.current_x})
        self.current_t += float(duration_s)
        return self

    # -- overlays (do not advance the base clock) -----------------------------
    def gesture(self, action: str, at: Optional[float] = None,
                duration_s: float = 2.0, amplitude: float = 1.0) -> "Director":
        """Layers an upper-body action over the base starting at `at` seconds."""
        self._overlays.append({"action": action,
                               "t": self.current_t if at is None else float(at),
                               "duration_s": float(duration_s),
                               "amplitude": float(amplitude)})
        return self

    def strike(self, action: str, at: Optional[float] = None,
               duration_s: float = 1.5) -> "Director":
        """Gesture alias for strikes (punch/kick), kept explicit for readability."""
        return self.gesture(action, at=at, duration_s=duration_s)

    def strike_at(self, target_xy, end_joint: str = "hand_r",
                  at: Optional[float] = None) -> "Director":
        """Aimed strike at world-space target (analytic solver, exact lengths).

        Appends windup (0.12s) -> solved impact (snap, impact_burst event) ->
        recover hold. Only supported at the current end (at=None or ==current_t).
        """
        from src.puppet.combat_ik import solve_aimed_limb
        from src.rig import decode as _decode
        t0 = self.current_t if at is None else float(at)
        if abs(t0 - self.current_t) > 1e-9:
            raise ValueError("strike_at only supports the current end (at=None)")
        tl = self._base_timeline()
        feat = tl.compile(total_duration_s=max(t0, 0.1))
        root, ang = _decode(feat)
        frame = min(len(feat) - 1, int(round(t0 * self.fps)))
        r0, a0 = root[frame].copy(), ang[frame].copy()
        solved, residual, _ = solve_aimed_limb(r0, a0, np.asarray(target_xy, dtype=float),
                                               end_joint=end_joint)
        self._segments.append({"kind": "aimed", "t": t0, "windup": a0,
                               "impact": solved, "root": r0,
                               "joint": end_joint, "residual": float(residual)})
        self.current_t = t0 + 0.72
        return self

    def _base_timeline(self) -> ArmatureTimeline:
        """Builds the base timeline from segments recorded so far."""
        tl = ArmatureTimeline(fps=self.fps)
        x = self.start_x
        for seg in self._segments:
            if seg["kind"] == "gait":
                sub = self._gait.build_gait_timeline(x, seg["cmd"])
                self._append_shifted(tl, sub, seg["t"])
                x += float(seg["cmd"].speed) * float(seg["cmd"].duration_s)
            elif seg["kind"] == "aimed":
                tl.add_keyframe(t=seg["t"], pose=seg["windup"], root_x=float(seg["root"][0]),
                                root_y=float(seg["root"][1]), hold_duration_s=0.12,
                                easing="ease_in", moving_hold=False, stance_lock="both_feet")
                tl.add_keyframe(t=seg["t"] + 0.30, pose=seg["impact"],
                                root_x=float(seg["root"][0]), root_y=float(seg["root"][1]),
                                hold_duration_s=0.12, easing="snap_and_settle",
                                moving_hold=False, stance_lock="both_feet")
                tl.add_event(t=seg["t"] + 0.30, kind="impact_burst",
                             joint=seg["joint"], scale=1.0)
                tl.add_keyframe(t=seg["t"] + 0.42, pose="stand_relaxed",
                                root_x=float(seg["root"][0]),
                                hold_duration_s=0.30, easing="ease_out", stance_lock="both_feet")
            else:
                tl.add_keyframe(t=seg["t"], pose=seg["pose"], root_x=seg["x"],
                                hold_duration_s=seg["duration_s"])
        return tl

    # -- compile ---------------------------------------------------------------
    @staticmethod
    def _append_shifted(tl: ArmatureTimeline, sub: ArmatureTimeline, t0: float) -> None:
        for kf in sub.keyframes:
            tl.add_keyframe(t=t0 + kf.t, pose=kf.pose, root_x=kf.root_x, root_y=kf.root_y,
                            easing=kf.easing, hold_duration_s=kf.hold_duration_s,
                            stance_lock=kf.stance_lock, foot_roll_L=kf.foot_roll_L,
                            foot_roll_R=kf.foot_roll_R, moving_hold=kf.moving_hold,
                            cadence=kf.cadence)
        for ev in sub.events:
            tl.add_event(t=t0 + ev.t, kind=ev.kind, joint=ev.joint, x=ev.x, y=ev.y,
                         scale=ev.scale, duration_frames=ev.duration_frames, **ev.params)

    def compile(self, return_events: bool = False):
        """Compiles the performance to (T, 30) features, optionally with events."""
        from src.puppet.choreography import build_motion_from_action
        # Base timeline: rebuild segments with correct chained start_x.
        tl = self._base_timeline()
        x = self.start_x
        for seg in self._segments:
            if seg["kind"] == "gait":
                x += float(seg["cmd"].speed) * float(seg["cmd"].duration_s)
        events = tl.compile_events(puppet_index=0)
        # Overlay span determines nothing about length; base sets it.
        total_s = self.current_t
        for ov in self._overlays:
            total_s = max(total_s, ov["t"] + ov["duration_s"])
        feat = tl.compile(total_duration_s=max(total_s, 0.1))
        T = len(feat)
        for ov in self._overlays:
            built = build_motion_from_action(ov["action"], duration_s=ov["duration_s"],
                                             amplitude=ov["amplitude"],
                                             return_events=True)
            ofeat, oevents = built if isinstance(built, tuple) else (built, [])
            f0 = int(round(ov["t"] * self.fps))
            if f0 >= T:
                continue
            feat = layer_timelines(feat, ofeat, f0, bones=UPPER_BODY_BONES, fps=self.fps)
            for oe in oevents:
                shifted = dict(oe)
                shifted["start_frame"] = int(oe.get("start_frame", 0)) + f0
                events.append(shifted)
        if return_events:
            return feat, events
        return feat
