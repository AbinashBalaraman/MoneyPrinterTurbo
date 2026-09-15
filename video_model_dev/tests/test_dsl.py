"""Test suite for Puppet Stage DSL & Terminal Symbolic Preview."""

import os
import unittest

from src.stage.dsl import compile_stage_script, parse_stage_script
from src.stage.terminal_preview import TerminalStagePreview


class TestStageDSL(unittest.TestCase):
    def test_parse_stage_script(self):
        script_dict = {
            "title": "Unit Test Play",
            "theme": "light",
            "scenes": [
                {
                    "name": "Scene 1",
                    "duration_s": 1.0,
                    "scenery": {"type": "plain"},
                    "puppets": [{"actor_id": 0, "action": "idle", "arm_pose": "hold_object"}]
                }
            ]
        }
        parsed = parse_stage_script(script_dict)
        self.assertEqual(parsed.title, "Unit Test Play")
        self.assertEqual(len(parsed.scenes), 1)
        self.assertEqual(parsed.scenes[0].puppets[0].arm_pose, "hold_object")

    def test_compile_and_render_dsl(self):
        out_path = "out/test_dsl_output.mp4"
        script_dict = {
            "title": "Minimal Theatrical Performance",
            "theme": "light",
            "scenes": [
                {
                    "name": "Act 1: Speech",
                    "duration_s": 1.0,
                    "scenery": {"type": "plain"},
                    "puppets": [
                        {"actor_id": 0, "action": "idle", "arm_pose": "hold_object"},
                        {"actor_id": 1, "action": "walk", "offset_x": -1.0, "direction": 1}
                    ],
                    "props": [{"kind": "speech_bubble", "anchor_puppet": 0, "w": 100, "h": 60}]
                },
                {
                    "name": "Act 2: Colonnade Hall",
                    "duration_s": 1.0,
                    "scenery": {"type": "perspective_hall", "colonnade": True, "baroque_frame": True},
                    "puppets": [{"actor_id": 0, "action": "idle"}]
                }
            ]
        }
        res = compile_stage_script(script_dict, out_path, preview_ascii=True)
        self.assertTrue(os.path.exists(out_path))
        self.assertGreater(os.path.getsize(out_path), 5000)
        self.assertEqual(res["total_frames"], 48)
        self.assertEqual(len(res["ascii_previews"]), 2)
        # Check that ascii preview has content
        self.assertIn("PUPPET STAGE PREVIEW", res["ascii_previews"][0]["ascii"])
        self.assertIn("O", res["ascii_previews"][0]["ascii"])

    def test_terminal_player_builds(self):
        from tools.play_terminal_ascii import build_demo_light, build_demo_dark
        light_frames = build_demo_light()
        self.assertEqual(len(light_frames), 240)
        self.assertIn("PUPPET STAGE PREVIEW", light_frames[0])
        self.assertIn("NOT A VERDICT", light_frames[-1])

        dark_frames = build_demo_dark()
        self.assertEqual(len(dark_frames), 240)
        self.assertIn("PUPPET STAGE PREVIEW", dark_frames[0])
        self.assertIn("@", dark_frames[-1])  # Distressed prisoner head

    def test_camera_impulse_kick_and_settle(self):
        import numpy as np
        from src.stage_renderer import apply_camera_impulses
        base = np.zeros(10, dtype=np.float32)
        out = apply_camera_impulses(base.copy(), [{"start_frame": 4, "magnitude": 0.02}])
        self.assertAlmostEqual(float(out[4]), 0.02, places=6)
        self.assertAlmostEqual(float(out[5]), -0.01, places=6)
        self.assertAlmostEqual(float(out[3]), 0.0, places=6)
        # Out-of-range impulses are ignored; empty input is identity
        out2 = apply_camera_impulses(base.copy(), [{"start_frame": 99}])
        np.testing.assert_allclose(out2, base, atol=1e-9)


if __name__ == "__main__":
    unittest.main()

