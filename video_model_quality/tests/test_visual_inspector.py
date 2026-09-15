"""Unit tests for VisualInspector and automated defect remediation."""
import os
import unittest
import numpy as np

from src.visual_inspector import VisualInspector, GROUND_Y
from src.puppet.director import Director
from src.puppet.combat_ik import solve_aimed_limb
from src.puppet.pose import get_pose_angles
from src.rig import encode, decode


class TestVisualInspector(unittest.TestCase):
    def setUp(self):
        self.inspector = VisualInspector()

    def test_clean_locomotion_passes_audit(self):
        d = Director(fps=24)
        d.locomote(speed=0.3, duration_s=1.0)
        feat = d.compile()
        report = self.inspector.audit_motion(feat, name="clean_walk")
        self.assertEqual(report.bone_length_violations, 0)
        self.assertEqual(report.max_bone_error, 0.0)
        self.assertEqual(report.ground_penetrations, 0)
        self.assertGreaterEqual(report.quality_score, 85.0)

    def test_floor_penetration_detected_and_remediated(self):
        d = Director(fps=24)
        d.locomote(speed=0.2, duration_s=0.5)
        feat = d.compile()
        root, ang = decode(feat)
        # Inject artificial penetration
        root[5:10, 1] -= 0.05
        bad_feat = encode(root, ang)

        rep_bad = self.inspector.audit_motion(bad_feat, name="penetrating_clip")
        self.assertGreater(rep_bad.ground_penetrations, 0)
        self.assertGreater(rep_bad.max_penetration_depth, 0.04)

        # Remediate
        fixed_feat = self.inspector.remediate_motion(bad_feat, fix_ground_penetration=True)
        rep_fixed = self.inspector.audit_motion(fixed_feat, name="fixed_clip")
        self.assertEqual(rep_fixed.ground_penetrations, 0)

    def test_dead_hold_detected_and_remediated(self):
        # 1.5s completely frozen hold
        base = get_pose_angles("stand_relaxed")
        feat = encode(np.zeros((36, 2)), np.tile(base, (36, 1)))
        rep = self.inspector.audit_motion(feat, name="frozen_clip")
        self.assertGreater(rep.dead_hold_frames, 30)

        # Remediate breathing
        fixed = self.inspector.remediate_motion(feat, kill_dead_holds=True)
        rep_fixed = self.inspector.audit_motion(fixed, name="breathing_clip")
        self.assertEqual(rep_fixed.dead_hold_frames, 0)

    def test_filmstrip_generation(self):
        d = Director(fps=24)
        d.locomote(speed=0.3, duration_s=0.5).gesture("wave", duration_s=0.5)
        feat = d.compile()
        out_path = "out/inspections/test_filmstrip.png"
        res = self.inspector.render_filmstrip(feat, out_path, n_stills=4, title="Walk and Wave")
        self.assertTrue(os.path.exists(res))
        self.assertGreater(os.path.getsize(res), 5000)


if __name__ == "__main__":
    unittest.main()
