"""Unit tests for the Platform Entity (TASK-013): limits, FK, DLS IK, balance."""

import unittest
import numpy as np

from src.entity import (
    NAMES, INDEX, LIMITS, MASS, ANCHORS,
    StickmanEntity, solve_reach,
)


class TestPlatformEntity(unittest.TestCase):
    def test_01_joint_count_and_hierarchy(self):
        self.assertEqual(len(NAMES), 17)
        for key in ("sword_hand", "shield_hand", "hat", "cape"):
            self.assertIn(ANCHORS[key], NAMES)
        self.assertAlmostEqual(sum(MASS.values()), 1.0, places=6)

    def test_02_fk_preserves_bone_lengths(self):
        import math
        from src.entity import _JOINTS
        e = StickmanEntity()
        e.angles["elbow_r"] = 0.7
        e.angles["knee_l"] = 0.9
        e.angles["spine"] = 0.2
        p = e.fk()
        pmap = {j[0]: (j[1], j[2]) for j in _JOINTS}
        for name in NAMES:
            parent, length = pmap[name]
            if parent is None or length == 0:
                continue
            d = float(np.linalg.norm(p[name] - p[parent]))
            self.assertAlmostEqual(d, length, places=9)

    def test_03_limits_clamp_hinges(self):
        e = StickmanEntity()
        e.angles["knee_l"] = -1.0   # backward bend forbidden
        e.angles["elbow_l"] = 5.0   # past 145 deg
        worst = e.clamp_limits()
        self.assertGreater(worst, 0.0)
        self.assertAlmostEqual(e.angles["knee_l"], 0.0)
        self.assertAlmostEqual(e.angles["elbow_l"], np.radians(145))

    def test_04_rest_com_centered_and_grounded(self):
        e = StickmanEntity()
        com = e.com()
        self.assertAlmostEqual(com[0], 0.0, places=9)
        self.assertEqual(e.foot_contacts(), {"ankle_l": True, "ankle_r": True})

    def test_05_dls_reach_converges_pins_hold(self):
        e = StickmanEntity()
        ank = {f: e.fk()[f].copy() for f in ("ankle_l", "ankle_r")}
        err, it = solve_reach(e, (0.25, -0.1), end_joint="hand_r", pinned=ank)
        self.assertLess(err, 1e-3)
        self.assertLessEqual(it, 50)
        np.testing.assert_allclose(e.fk()["hand_r"], (0.25, -0.1), atol=1e-3)
        for f in ank:
            np.testing.assert_allclose(e.fk()[f], ank[f], atol=1e-6)

    def test_06_balance_correction_sign(self):
        e = StickmanEntity()
        e.angles["spine"] = 0.35
        e.angles["chest"] = 0.35  # forced +x lean pushes CoM past support
        e.clamp_limits()
        corr = e.balance_correction(["ankle_l", "ankle_r"], margin=0.0)
        self.assertLess(corr, 0.0)  # root must shift -x to recenter
        e2 = StickmanEntity()
        self.assertAlmostEqual(e2.balance_correction(["ankle_l", "ankle_r"]), 0.0,
                               places=9)  # rest pose already balanced

    def test_07_solver_deterministic(self):
        def run():
            e = StickmanEntity()
            ank = {f: e.fk()[f].copy() for f in ("ankle_l", "ankle_r")}
            solve_reach(e, (0.25, -0.1), end_joint="hand_r", pinned=ank)
            return e.joint_array()
        np.testing.assert_array_equal(run(), run())


if __name__ == "__main__":
    unittest.main()
