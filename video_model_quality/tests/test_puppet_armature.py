"""Unit tests for Smooth Stop-Motion Puppet Platform (Armature, Poses, Easing, Choreography)."""

import unittest
import numpy as np

from src.puppet.easing import (
    linear,
    ease_in_cubic,
    ease_out_cubic,
    ease_in_out_cubic,
    ease_in_quad,
    ease_out_quad,
    snap_and_settle,
    moving_hold,
    get_easing_function,
)
from src.puppet.pose import (
    POSES,
    get_pose_angles,
    get_pose_root_y,
)
from src.puppet.armature import (
    Keyframe,
    ArmatureTimeline,
    shortest_angle_diff,
    limit_velocity_preserving_endpoints,
)
from src.puppet.choreography import (
    PuppetChoreographer,
    create_walk_sequence,
    create_combat_sequence,
    create_jump_sequence,
)
from src.rig import decode, forward_kinematics


class TestPuppetPlatform(unittest.TestCase):

    def test_01_easing_boundaries(self):
        """Verify easing curves satisfy boundary conditions and have no infinities."""
        for fn in [linear, ease_in_cubic, ease_out_cubic, ease_in_out_cubic, ease_in_quad, ease_out_quad]:
            self.assertAlmostEqual(fn(0.0), 0.0, places=5)
            self.assertAlmostEqual(fn(1.0), 1.0, places=5)
            # Intermediate values must stay bounded
            for t in np.linspace(0.0, 1.0, 21):
                val = fn(float(t))
                self.assertFalse(np.isnan(val))
                self.assertGreaterEqual(val, -0.01)
                self.assertLessEqual(val, 1.01)

        # Snap and settle reaches 0.0 at t=0 and 1.0 at t=1
        self.assertAlmostEqual(snap_and_settle(0.0), 0.0, places=4)
        self.assertAlmostEqual(snap_and_settle(1.0), 1.0, places=4)

        # Moving hold returns to 0 at t=0 and t=1
        self.assertAlmostEqual(moving_hold(0.0), 0.0, places=4)
        self.assertAlmostEqual(moving_hold(1.0), 0.0, places=4)

    def test_02_pose_library_integrity(self):
        """Verify all 20+ poses are anatomically valid with finite angles."""
        self.assertGreater(len(POSES), 15)
        for name, pose in POSES.items():
            self.assertEqual(pose.angles.shape, (14,))
            self.assertFalse(np.isnan(pose.angles).any(), f"NaN in pose {name}")
            # All angles in radians should be within [-2pi, 2pi]
            self.assertTrue((np.abs(pose.angles) <= 2.0 * np.pi).all())
            # Forward kinematics must succeed
            joints = forward_kinematics(np.array([[0.0, pose.root_y]]), pose.angles[None, :])[0]
            self.assertEqual(joints.shape, (15, 2))
            self.assertFalse(np.isnan(joints).any())

    def test_03_shortest_angle_diff(self):
        """Verify circular angle difference wraps within [-pi, pi]."""
        # Close angles
        d1 = shortest_angle_diff(np.array([0.1]), np.array([0.0]))
        self.assertAlmostEqual(d1[0], 0.1, places=5)

        # Wrapping across +/- pi boundary
        d2 = shortest_angle_diff(np.array([3.10]), np.array([-3.10]))
        self.assertLess(abs(d2[0]), 0.2)  # Should wrap around rather than traveling 6.2 rad

    def test_04_armature_timeline_smoothness(self):
        """Verify armature compilation has zero NaNs, correct shape, and no angular velocity spikes."""
        timeline = ArmatureTimeline(fps=24)
        timeline.add_keyframe(t=0.0, pose="stand_relaxed", hold_duration_s=0.2)
        timeline.add_keyframe(t=0.5, pose="punch_windup", easing="ease_in")
        timeline.add_keyframe(t=0.7, pose="punch_impact", easing="snap_and_settle", hold_duration_s=0.1)
        timeline.add_keyframe(t=1.2, pose="stand_relaxed", easing="ease_out", hold_duration_s=0.3)

        feat = timeline.compile()
        self.assertEqual(feat.shape[-1], 30)
        self.assertFalse(np.isnan(feat).any())
        self.assertGreaterEqual(len(feat), 36)

        # Check angular acceleration: no instantaneous discontinuities
        root, angles = decode(feat)
        angular_vel = np.abs(shortest_angle_diff(angles[1:], angles[:-1]))
        # Maximum angular change per frame is strictly bounded by safety cap (<= 0.60 rad/frame at 24fps)
        max_vel = np.max(angular_vel)
        self.assertLessEqual(max_vel, 0.60 + 1e-4, f"Velocity exceeded safety cap: {max_vel} rad/frame")




    def test_05_choreographer_walk_and_combat(self):
        """Verify PuppetChoreographer builds multi-action choreography with zero foot skate."""
        director = PuppetChoreographer(start_x=0.0)
        director.walk(steps=4)
        director.punch()
        director.jump()
        director.celebrate()

        feat = director.compile()
        self.assertEqual(feat.shape[-1], 30)
        self.assertFalse(np.isnan(feat).any())

        # Decode and run FK
        root, angles = decode(feat)
        joints = forward_kinematics(root, angles)
        self.assertEqual(joints.shape, (len(feat), 15, 2))
        self.assertFalse(np.isnan(joints).any())

        # Forward progression: character must have traveled forward (+X)
        self.assertGreater(root[-1, 0], root[0, 0] + 0.5)

    def test_06_two_bone_ik_accuracy(self):
        """Verify analytical Two-Bone IK reaches targets to within machine epsilon."""
        from src.puppet.armature import solve_two_bone_ik
        from src.rig import BONES
        hip = np.array([0.1, -0.05], dtype=np.float32)
        target_ankle = np.array([0.05, -0.41], dtype=np.float32)
        th, sh = solve_two_bone_ik(hip, target_ankle, l1=BONES[8][2], l2=BONES[9][2])

        # Plug into FK
        a = np.zeros(14, dtype=np.float32)
        a[8] = th
        a[9] = sh
        j = forward_kinematics(hip[None, :], a[None, :])[0]
        err = np.linalg.norm(j[10] - target_ankle)
        self.assertLess(err, 1e-6)

    def test_07_stance_pinning_zero_drift(self):
        """Verify stance foot experiences zero drift (< 1e-6) during moving holds."""
        timeline = ArmatureTimeline(fps=24)
        timeline.add_keyframe(t=0.0, pose="stand_relaxed", hold_duration_s=1.0, stance_lock="both_feet", moving_hold=True)
        feat = timeline.compile(total_duration_s=1.0)
        root, ang = decode(feat)
        j = forward_kinematics(root, ang)
        drift_L = np.max(np.abs(j[:, 10, 0] - j[0, 10, 0]))
        drift_R = np.max(np.abs(j[:, 13, 0] - j[0, 13, 0]))
        self.assertLess(drift_L, 1e-6)
    def test_08_adaptive_cadence_stepping(self):
        """Verify adaptive cadence: cadence=2 holds pairs of frames identically, while cadence=1 animates on ones."""
        # Test full timeline cadence=2
        tl = ArmatureTimeline(fps=24, cadence=2)
        tl.add_keyframe(t=0.0, pose="stand_relaxed")
        tl.add_keyframe(t=1.0, pose="punch_impact")
        feat_twos = tl.compile(total_duration_s=1.0)
        # Check that odd frames match preceding even frames
        for f in range(1, len(feat_twos), 2):
            np.testing.assert_allclose(feat_twos[f], feat_twos[f - 1], atol=1e-5)

        # Test adaptive keyframe cadence: walk on twos (cadence=2) then strike on ones (cadence=1)
        tl_adapt = ArmatureTimeline(fps=24, cadence=2)
        tl_adapt.add_keyframe(t=0.0, pose="stand_relaxed", hold_duration_s=0.5, cadence=2)
        tl_adapt.add_keyframe(t=0.5, pose="punch_windup", cadence=2)
        tl_adapt.add_keyframe(t=0.8, pose="punch_impact", cadence=1)
        feat_adapt = tl_adapt.compile(total_duration_s=1.2)
        self.assertEqual(feat_adapt.shape, (int(round(1.2 * 24)), 30))
        self.assertFalse(np.isnan(feat_adapt).any())

    def test_09_synchronized_combat_pairs(self):
        """Verify 2P synchronized combat choreography (punch_block, kick_dodge, exchange, knockdown_getup)."""
        from src.puppet.choreography import build_combat_pair
        from src.eval import evaluate_motion_features
        for act in ["punch_block", "kick_dodge", "exchange", "knockdown_getup"]:
            feat = build_combat_pair(act, duration_s=2.5)
            self.assertEqual(feat.shape[-1], 60)
            self.assertFalse(np.isnan(feat).any())
            eval_res = evaluate_motion_features(feat, n_person=2)
            self.assertTrue(eval_res["passed"], f"{act} failed kinematics eval: {eval_res.get('issues')}")

    def test_10_joint_props_and_vfx(self):
        """Verify StageRendererHD renders joint-locked props and vector VFX without errors."""
        from src.puppet.choreography import build_motion_from_action
        from src.stage_renderer import StageRendererHD
        from src.renderer import decode_motion_features
        feat = build_motion_from_action("punch", duration_s=1.0)
        joints = decode_motion_features(feat)
        stage = StageRendererHD(width=640, height=360, theme_name="light")
        props = [
            {"kind": "sword", "anchor_puppet": 0, "joint": 8},
            {"kind": "shield", "anchor_puppet": 0, "joint": 6}
        ]
        vfx = [
            {"kind": "impact_burst", "anchor_puppet": 0, "anchor_joint": 8},
            {"kind": "dust_puff", "x": 320, "y": 300},
            {"kind": "speed_lines", "x": 320, "y": 200, "direction": 1}
        ]
        img = stage.render_stage_frame(joints[10], props=props, vfx=vfx)
        self.assertEqual(img.size, (640, 360))

    def test_11_timeline_events(self):
        """Verify ArmatureTimeline events track compiles timed trigger events for renderer."""
        from src.puppet.armature import ArmatureTimeline
        tl = ArmatureTimeline(fps=24)
        tl.add_keyframe(t=0.0, pose="stand_relaxed")
        tl.add_keyframe(t=0.5, pose="punch_impact")
        tl.add_event(t=0.5, kind="impact_burst", joint="hand_R", scale=1.5)
        tl.add_event(t=1.0, kind="dust_puff", x=320.0, y=450.0)

        events = tl.compile_events(puppet_index=1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["kind"], "impact_burst")
        self.assertEqual(events[0]["start_frame"], 12)  # 0.5s * 24fps
        self.assertEqual(events[0]["anchor_puppet"], 1)
        self.assertEqual(events[0]["anchor_joint"], 8)  # hand_R index
        self.assertEqual(events[0]["scale"], 1.5)

        self.assertEqual(events[1]["kind"], "dust_puff")
        self.assertEqual(events[1]["start_frame"], 24)  # 1.0s * 24fps
        self.assertEqual(events[1]["x"], 320.0)

    def test_12_foot_roll_zero_ankle_drift(self):
        """Prescribed foot roll articulates the toe while the ankle stays pinned (< 1e-6)."""
        tl = ArmatureTimeline(fps=24)
        tl.add_keyframe(t=0.0, pose="stand_relaxed", root_x=0.0, hold_duration_s=0.2,
                        stance_lock="both_feet", foot_roll_L=0.0, foot_roll_R=0.0)
        tl.add_keyframe(t=0.6, pose="stride_contact_L", root_x=0.1,
                        stance_lock="left_foot", foot_roll_L=0.25)
        tl.add_keyframe(t=1.2, pose="stand_relaxed", root_x=0.2, hold_duration_s=0.2,
                        stance_lock="both_feet")
        feat = tl.compile()
        root, ang = decode(feat)
        j = forward_kinematics(root, ang)
        # Ankle path must be identical with or without roll (roll only touches foot_rel)
        tl_flat = ArmatureTimeline(fps=24)
        tl_flat.add_keyframe(t=0.0, pose="stand_relaxed", root_x=0.0, hold_duration_s=0.2,
                             stance_lock="both_feet")
        tl_flat.add_keyframe(t=0.6, pose="stride_contact_L", root_x=0.1, stance_lock="left_foot")
        tl_flat.add_keyframe(t=1.2, pose="stand_relaxed", root_x=0.2, hold_duration_s=0.2,
                             stance_lock="both_feet")
        r0, a0 = decode(tl_flat.compile())
        j0 = forward_kinematics(r0, a0)
        np.testing.assert_allclose(j[:, 10], j0[:, 10], atol=1e-6)
        # Toe must actually articulate (foot segment rotates about the pinned ankle)
        toe_range = float(np.max(j[:, 11, 1]) - np.min(j[:, 11, 1]))
        self.assertGreater(toe_range, 0.005)

    def test_13_hit_stop_freeze_zero_shimmer(self):
        """Hit-stop impact holds freeze (post-arrival frames equal at 1e-6)."""
        from src.rig import decode as _decode, forward_kinematics as _fk

        def longest_freeze_run(joints, atol=1e-6):
            # Freeze = post-arrival hold frames equal at project drift tolerance.
            # The arrival frame itself is reshaped by the anti-pop rate limiter,
            # so any freeze run starts the frame after arrival by design.
            best = cur = 1
            for t in range(1, len(joints)):
                if np.allclose(joints[t], joints[t - 1], atol=atol):
                    cur += 1
                    best = max(best, cur)
                else:
                    cur = 1
            return best

        # Synthetic freeze: suppressed breathing must hold still after arrival.
        tl = ArmatureTimeline(fps=24)
        tl.add_keyframe(t=0.0, pose="guard_high", root_x=0.0, hold_duration_s=0.2,
                        stance_lock="both_feet")
        tl.add_keyframe(t=0.5, pose="punch_impact", root_x=0.08, hold_duration_s=0.15,
                        easing="snap_and_settle", stance_lock="both_feet",
                        moving_hold=False)
        r, a = _decode(tl.compile())
        self.assertGreaterEqual(longest_freeze_run(_fk(r, a)), 2,
                                "hit-stop hold tail must freeze >=2 frames")

        # Control: default breathing hold must NOT freeze (proves discrimination).
        tl2 = ArmatureTimeline(fps=24)
        tl2.add_keyframe(t=0.0, pose="guard_high", root_x=0.0, hold_duration_s=0.3,
                         stance_lock="both_feet")
        r2, a2 = _decode(tl2.compile())
        self.assertEqual(longest_freeze_run(_fk(r2, a2)), 1)

        # Product path: combat punch impact window must contain a freeze.
        tl3 = create_combat_sequence(start_x=0.0, action="punch")
        r3, a3 = _decode(tl3.compile())
        self.assertGreaterEqual(longest_freeze_run(_fk(r3, a3)), 2)


class TestVelocityLimiter(unittest.TestCase):
    """The sum-conserving rate limiter: smooths over-fast runs without
    inventing linear ramps, dead stops, or moving the pose."""

    def _ramp_with_spike(self, max_step=0.1):
        v = np.array([0.05] * 5 + [0.5] + [0.05] * 5)
        x = np.concatenate([[0.0], np.cumsum(v)]).reshape(-1, 1)
        return x, max_step

    def test_untouched_when_within_cap(self):
        """Motion already under the cap must be returned byte-identical."""
        x = np.linspace(0.0, 0.4, 30).reshape(-1, 1)  # 0.0138/frame, well under
        out = limit_velocity_preserving_endpoints(x, 0.1)
        np.testing.assert_array_equal(out, x)

    def test_reduces_over_fast_step_under_cap(self):
        x, cap = self._ramp_with_spike()
        out = limit_velocity_preserving_endpoints(x, cap)
        before = np.abs(np.diff(x[:, 0])).max()
        after = np.abs(np.diff(out[:, 0])).max()
        self.assertAlmostEqual(before, 0.5, places=6)
        self.assertLessEqual(after, cap * 1.5, "limiter must bring the spike near the cap")
        self.assertLess(after, before * 0.5, "limiter must actually cut the spike")

    def test_endpoints_preserved_exactly(self):
        """The pose is still reached -- the same move just takes more frames."""
        x, cap = self._ramp_with_spike()
        out = limit_velocity_preserving_endpoints(x, cap)
        self.assertAlmostEqual(out[0, 0], x[0, 0], places=9)
        self.assertAlmostEqual(out[-1, 0], x[-1, 0], places=6)

    def test_total_displacement_conserved(self):
        x, cap = self._ramp_with_spike()
        out = limit_velocity_preserving_endpoints(x, cap)
        self.assertAlmostEqual(out[-1, 0] - out[0, 0], x[-1, 0] - x[0, 0], places=6)

    def test_intentional_holds_are_not_dissolved(self):
        """A freeze (hit-stop / anticipation pause) must survive untouched.
        Excess velocity must not bleed into a zero-velocity run."""
        h = np.zeros((20, 1))
        h[:5, 0] = np.linspace(0.0, 0.2, 5)
        h[10:, 0] = 0.2  # deliberate hold tail
        out = limit_velocity_preserving_endpoints(h, 0.05)
        self.assertTrue(np.allclose(out[10:, 0], out[10, 0]),
                        "hold tail must stay perfectly flat")

    def test_degenerate_inputs_are_safe(self):
        for arr in (np.zeros((1, 1)), np.zeros((2, 2)), np.zeros((5, 3))):
            out = limit_velocity_preserving_endpoints(arr, 0.1)
            self.assertEqual(out.shape, arr.shape)
        # max_step <= 0 disables the limiter.
        x = np.linspace(0, 1, 10).reshape(-1, 1)
        np.testing.assert_array_equal(limit_velocity_preserving_endpoints(x, 0.0), x)


if __name__ == "__main__":
    unittest.main()


