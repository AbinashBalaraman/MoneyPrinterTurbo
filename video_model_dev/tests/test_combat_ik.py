"""Unit tests for target-driven dynamic combat (TASK-015)."""
import unittest

import numpy as np

from src.puppet.combat_ik import (capsule_matrix, capsule_contacts, HitTracker,
                                  rig_to_entity, balance_shift, classify_recoil,
                                  recoil_keyframes, solve_aimed_limb)
from src.puppet.director import Director
from src.puppet.pose import get_pose_angles
from src.rig import forward_kinematics


def _stand_joints(x=0.0):
    root = np.array([[x, 0.0]], dtype=np.float32)
    return forward_kinematics(root, get_pose_angles("stand_relaxed")[None, :])[0]


class TestCapsules(unittest.TestCase):
    def test_far_apart_no_hit(self):
        hit, dmin = capsule_matrix(_stand_joints(0.0), _stand_joints(5.0))
        self.assertFalse(bool(hit.any()))

    def test_overlap_hits_with_depth(self):
        hit, _ = capsule_matrix(_stand_joints(0.0), _stand_joints(0.1))
        self.assertTrue(bool(hit.any()))
        contacts = capsule_contacts(_stand_joints(0.0), _stand_joints(0.1))
        self.assertTrue(len(contacts) > 0)
        self.assertGreater(contacts[0]["depth"], 0.0)

    def test_tracker_single_hit_no_retrigger(self):
        from src.rig import forward_kinematics as _fk
        tr = HitTracker()
        ja = _fk(np.array([[0.0, 0.0]], dtype=np.float32),
                 get_pose_angles("punch_impact")[None, :])[0]
        hand0 = ja[8]
        events = []
        # Drive the defender onto the attacker's outstretched hand point,
        # then dwell 20 frames inside contact.
        for f in range(30):
            jb = _stand_joints(max(hand0[0] + 0.5 - f * 0.05, hand0[0]))
            events.extend(tr.update(f, ja, jb, armed={"hand_r": True}))
        self.assertEqual(len([e for e in events if e["striker"] == "hand_r"]), 1)


class TestRecoil(unittest.TestCase):
    def test_tiers(self):
        self.assertEqual(classify_recoil(0.3).tier, "lean")
        self.assertEqual(classify_recoil(0.6).tier, "stagger")
        self.assertEqual(classify_recoil(2.0).tier, "fall")

    def test_balance_shift_uses_entity(self):
        from src.entity import StickmanEntity
        root = np.array([0.3, 0.0])
        ang = get_pose_angles("stand_relaxed")
        ent = StickmanEntity(root_xy=(0.3, 0.0))
        for n, v in zip(["spine", "chest", "neck", "head"], ang[:4]):
            ent.angles[n] = float(v)
        expected = ent.balance_correction(["ankle_l", "ankle_r"])
        self.assertAlmostEqual(balance_shift(root, ang, ["both_feet"]), expected, places=9)
        self.assertLessEqual(balance_shift(root, ang, ["both_feet"]), 0.0)

    def test_recoil_keyframes_compile(self):
        from src.puppet.armature import ArmatureTimeline
        for p in (0.3, 0.6):
            plan = classify_recoil(p)
            tl = ArmatureTimeline()
            for kf in recoil_keyframes(0.0, plan):
                tl.add_keyframe(**kf)
            feat = tl.compile()
            self.assertFalse(np.isnan(feat).any())


class TestAimedStrike(unittest.TestCase):
    def test_reachable_residual_zero(self):
        root = np.array([0.0, 0.0])
        base = get_pose_angles("stand_relaxed")
        solved, residual, _ = solve_aimed_limb(root, base, np.array([0.25, 0.15]), "hand_r")
        self.assertAlmostEqual(residual, 0.0, places=6)
        j = forward_kinematics(root[None, :], solved[None, :])[0]
        self.assertLess(float(np.linalg.norm(j[8] - [0.25, 0.15])), 0.02)

    def test_unreachable_clamps_finite(self):
        root = np.array([0.0, 0.0])
        base = get_pose_angles("stand_relaxed")
        solved, residual, _ = solve_aimed_limb(root, base, np.array([5.0, 0.0]), "hand_r")
        self.assertGreater(residual, 1.0)
        self.assertTrue(np.all(np.isfinite(solved)))

    def test_dls_cross_check(self):
        from src.entity import solve_reach
        root = np.array([0.0, 0.0])
        base = get_pose_angles("stand_relaxed")
        target = np.array([0.25, 0.15])
        ent = rig_to_entity(root, base)
        pins = {"ankle_l": tuple(ent.fk()["ankle_l"]), "ankle_r": tuple(ent.fk()["ankle_r"])}
        err, _ = solve_reach(ent, tuple(target), end_joint="hand_r", pinned=pins)
        self.assertLess(err, 0.05)

    def test_director_strike_at(self):
        d = Director()
        d.locomote(speed=0.3, duration_s=1.0).strike_at(np.array([0.6, 0.1]))
        feat, events = d.compile(return_events=True)
        self.assertFalse(np.isnan(feat).any())
        self.assertTrue(any(e.get("kind") == "impact_burst" for e in events))


if __name__ == "__main__":
    unittest.main()
