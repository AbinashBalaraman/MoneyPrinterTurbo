"""Unit tests for L2 controllers and L3 Director (Brain side, TASK-014)."""
import unittest

import numpy as np

from src.puppet.controllers import (GaitCommand, LocomotionController,
                                    UPPER_BODY_BONES, layer_timelines)
from src.puppet.director import Director
from src.rig import decode, forward_kinematics


class TestControllers(unittest.TestCase):
    def test_gait_forward_travel(self):
        ctl = LocomotionController()
        cmd = GaitCommand(speed=0.4, duration_s=3.0)
        feat = ctl.build_gait_features(0.0, cmd)
        root, _ = decode(feat)
        travel = float(root[-1, 0] - root[0, 0])
        self.assertAlmostEqual(travel, 0.4 * 3.0, delta=0.15)
        self.assertFalse(np.isnan(feat).any())

    def test_gait_backward_travel(self):
        ctl = LocomotionController()
        cmd = GaitCommand(speed=-0.3, duration_s=2.0)
        feat = ctl.build_gait_features(0.0, cmd)
        root, _ = decode(feat)
        travel = float(root[-1, 0] - root[0, 0])
        self.assertLess(travel, -0.3)
        self.assertFalse(np.isnan(feat).any())

    def test_gait_zero_speed_stands(self):
        ctl = LocomotionController()
        feat = ctl.build_gait_features(1.0, GaitCommand(speed=0.0, duration_s=1.0))
        root, _ = decode(feat)
        np.testing.assert_allclose(root[:, 0], 1.0, atol=1e-6)

    def test_lean_touches_spine_only(self):
        ctl = LocomotionController()
        base = ctl.build_gait_features(0.0, GaitCommand(speed=0.3, duration_s=1.0, lean=0.0))
        leaned = ctl.build_gait_features(0.0, GaitCommand(speed=0.3, duration_s=1.0, lean=0.2))
        _, ab = decode(base)
        _, al = decode(leaned)
        self.assertGreater(float(np.abs(al[:, 0] - ab[:, 0]).max()), 0.05)
        np.testing.assert_allclose(al[:, 8:], ab[:, 8:], atol=1e-6)

    def test_layer_keeps_legs_moves_arms(self):
        from src.puppet.choreography import build_motion_from_action
        base = build_motion_from_action("walk", duration_s=2.0)
        over = build_motion_from_action("wave", duration_s=2.0)
        fused = layer_timelines(base, over, f0=6)
        _, ab = decode(base)
        _, af = decode(fused)
        np.testing.assert_allclose(af[:, 8:], ab[:, 8:], atol=1e-5)
        self.assertGreater(float(np.abs(af[12:, 4] - ab[12:, 4]).max()), 1e-3)
        self.assertFalse(np.isnan(fused).any())


class TestDirector(unittest.TestCase):
    def test_locomote_gesture_chain(self):
        d = Director()
        d.locomote(speed=0.4, duration_s=2.0).gesture("wave", at=0.5).strike("punch", at=1.5)
        feat, events = d.compile(return_events=True)
        self.assertEqual(feat.shape[-1], 30)
        self.assertFalse(np.isnan(feat).any())
        root, _ = decode(feat)
        self.assertGreater(float(root[-1, 0] - root[0, 0]), 0.4)
        kinds = [e.get("kind") for e in events]
        self.assertTrue(any(k == "impact_burst" for k in kinds))

    def test_backward_director(self):
        d = Director()
        d.locomote(speed=-0.3, duration_s=2.0)
        feat = d.compile()
        root, _ = decode(feat)
        self.assertLess(float(root[-1, 0] - root[0, 0]), -0.3)


if __name__ == "__main__":
    unittest.main()
