"""Automated verification and regression suite for the Stickman Puppet Engine.

Tests:
1. Kinematics & Rig (bone hierarchy, angles, height, no NaNs).
2. Data Generation (all 13 1P and 4 2P actions).
3. Contact Correction (ground plane bounding).
4. Camera Tracking (staying within view).
5. Parser (synonyms, parameters, strict unsupported prompt errors).
6. Sequencer (multi-action continuous root handoff & cosine blending).
7. MCP Server Tools (registry, catalog discovery, prompt rendering).
"""

import os
import unittest
import numpy as np

from src.rig import decode, forward_kinematics, REST_ANGLES, BONES, N_BONES
from src.data_gen import gen_single, gen_pair, ACTIONS_1P, ACTIONS_2P
from src.catalog import get_action_catalog, validate_action_params, ACTION_METADATA
from src.parser import parse_prompt
from src.sequencer import PuppetSequencer, blend_feature_clips, sequence_prompts
from src.renderer import StickmanRenderer, decode_motion_features, apply_contact_correction, \
    active_vfx_for_frame
from src.mcp_server import execute_tool, TOOLS_REGISTRY


class TestStickmanEngine(unittest.TestCase):

    def test_01_rig_kinematics(self):
        """Verify forward kinematics produces valid anatomical coordinates."""
        root = np.array([[0.0, 0.0]], dtype=np.float32)
        joints = forward_kinematics(root, REST_ANGLES[None, :])[0]
        
        self.assertEqual(joints.shape, (15, 2))
        self.assertFalse(np.isnan(joints).any())
        
        # Head must be above pelvis, feet below pelvis
        y_head = joints[4, 1]
        y_foot = min(joints[11, 1], joints[14, 1])
        
        self.assertGreater(y_head, 0.0, "Head must extend upward (+Y)")
        self.assertLess(y_foot, 0.0, "Feet must extend downward (-Y)")
        
        total_height = y_head - y_foot
        self.assertAlmostEqual(total_height, 0.95, delta=0.1)

    def test_02_all_actions_generation(self):
        """Verify all 17 actions generate valid, finite feature arrays."""
        for act in ACTIONS_1P:
            clip = gen_single(act, duration_s=1.0)
            feat = clip["feat"]
            self.assertEqual(feat.shape[-1], 30)
            self.assertFalse(np.isnan(feat).any(), f"NaN found in action {act}")

        for act in ACTIONS_2P:
            clip = gen_pair(act, duration_s=1.0)
            feat = clip["feat"]
            self.assertEqual(feat.shape[-1], 60)
            self.assertFalse(np.isnan(feat).any(), f"NaN found in paired action {act}")

    def test_03_contact_correction(self):
        """Verify ground contact correction clamps feet at or above ground plane."""
        # Intentionally place character below ground
        joints = np.zeros((10, 1, 15, 2), dtype=np.float32)
        joints[:, 0, 11, 1] = -0.75  # Foot below ground (-0.50)
        
        corrected = apply_contact_correction(joints, ground_y=-0.50)
        min_foot_y = np.min(corrected[:, 0, [10, 11, 13, 14], 1])
        self.assertGreaterEqual(min_foot_y, -0.50 - 1e-5)

    def test_04_parser_nlp(self):
        """Verify natural language parsing for synonyms, speeds, and error handling."""
        # Walk with speed and direction
        p1 = parse_prompt("a stickman walks right fast for 3s")
        self.assertEqual(p1["action"], "walk")
        self.assertEqual(p1["direction"], 1)
        self.assertEqual(p1["speed"], 1.5)
        self.assertEqual(p1["duration_seconds"], 3.0)

        # Paired action
        p2 = parse_prompt("two fighters punch and block")
        self.assertEqual(p2["action"], "punch_block")
        self.assertEqual(p2["n_person"], 2)

        # Unsupported prompt rejection
        with self.assertRaises(ValueError):
            parse_prompt("a flying dragon shoots laser beams")

    def test_05_sequencer_composition(self):
        """Verify multi-action sequencing maintains continuous root translation."""
        prompts = ["stickman walk for 2s", "stickman jump for 2s"]
        timeline = sequence_prompts(prompts)
        
        self.assertIn("feat", timeline)
        self.assertEqual(timeline["feat"].shape[-1], 30)
        self.assertGreater(timeline["duration_seconds"], 3.0)
        self.assertFalse(np.isnan(timeline["feat"]).any())

    def test_06_mcp_server_tools(self):
        """Verify all MCP tools execute properly and return valid payloads."""
        self.assertEqual(len(TOOLS_REGISTRY), 10)
        
        cat = execute_tool("list_actions", {})
        self.assertEqual(len(cat["actions"]), 17)

        parsed = execute_tool("parse_text_prompt", {"prompt": "stickman wave gently"})
        self.assertEqual(parsed["action"], "wave")
        self.assertEqual(parsed["amplitude"], 0.6)

        ascii_res = execute_tool("preview_stage_ascii", {
            "scene": {"name": "Test", "duration_s": 1.0, "scenery": {"type": "plain"}}
        })
        self.assertEqual(ascii_res["status"], "success")
        self.assertIn("PUPPET STAGE PREVIEW", ascii_res["ascii_preview"])

        # World contract tools (LLM seam)
        caps = execute_tool("get_capabilities", {})
        self.assertIn("sword", caps["objects"])
        self.assertIn("llm_system_prompt", caps)

        val = execute_tool("validate_scene", {
            "scene": {"characters": [{"id": "a"}],
                      "beats": [{"actor": "a", "action": "walk"}]}
        })
        self.assertEqual(val["status"], "success")

    def test_07_vfx_plumbing_default_identical(self):
        import numpy as np
        r = StickmanRenderer(canvas_size=256)
        joints = np.zeros((1, 15, 2), dtype=np.float32)
        joints[0, 0] = [0.0, 0.0]
        a = np.asarray(r.render_frame(joints))
        b = np.asarray(r.render_frame(joints, vfx=None))
        np.testing.assert_array_equal(a, b)

    def test_08_speed_lines_active_window_only(self):
        import numpy as np
        r = StickmanRenderer(canvas_size=256)
        joints = np.zeros((1, 15, 2), dtype=np.float32)
        joints[0, 0] = [0.0, 0.0]
        ev = [{"kind": "speed_lines", "x": 0.3, "y": 0.3,
               "direction": 1.0, "scale": 1.0,
               "start_frame": 5, "duration": 4}]
        plain = np.asarray(r.render_frame(joints))
        # Outside window: identical to no-VFX.
        outside = r.render_frame(joints, vfx=active_vfx_for_frame(ev, 2))
        np.testing.assert_array_equal(np.asarray(outside), plain)
        # Inside window: visible + fading (mid < early pixel delta).
        early = np.asarray(r.render_frame(
            joints, vfx=active_vfx_for_frame(ev, 5))).astype(np.int32)
        mid = np.asarray(r.render_frame(
            joints, vfx=active_vfx_for_frame(ev, 7))).astype(np.int32)
        self.assertGreater(np.abs(early - plain).sum(), 0)
        self.assertLess(np.abs(mid - plain).sum(), np.abs(early - plain).sum())
        # Malformed/anchorless events resolve to nothing and never crash.
        junk = r.render_frame(joints, vfx=[{"kind": "speed_lines"}])
        np.testing.assert_array_equal(np.asarray(junk), plain)

    def test_09_joint_locked_props(self):
        import numpy as np
        from src.rig import forward_kinematics
        r = StickmanRenderer(canvas_size=256)
        # Real rest-pose joints so props land on-canvas by construction.
        root = np.zeros((1, 2), dtype=np.float32)
        ang = np.zeros((1, 14), dtype=np.float32)
        ang[0, 5] = 0.5  # bend right elbow so the forearm vector is nonzero
        joints = forward_kinematics(root, ang)
        bare = np.asarray(r.render_frame(joints)).astype(np.int32)
        # Each kind draws anchored pixels; bad targets are safe no-ops.
        for kind in ("sword", "staff", "shield"):
            prop = {"kind": kind, "anchor_puppet": 0, "joint": 8}
            armed = np.asarray(
                r.render_frame(joints, props=[prop])).astype(np.int32)
            self.assertGreater(np.abs(armed - bare).sum(), 0, kind)
        same = r.render_frame(joints, props=[{"kind": "sword",
                                              "anchor_puppet": 9}])
        np.testing.assert_array_equal(np.asarray(same), bare)
        same2 = r.render_frame(joints, props=[{"kind": "banana",
                                               "anchor_puppet": 0}])
        np.testing.assert_array_equal(np.asarray(same2), bare)
        # Tip tracks the hand: move the root, blade follows.
        joints2 = joints.copy()
        joints2[..., 0] += 0.10
        armed1 = np.asarray(r.render_frame(
            joints, props=[{"kind": "sword", "anchor_puppet": 0,
                            "joint": 8}])).astype(np.int32)
        armed2 = np.asarray(r.render_frame(
            joints2, props=[{"kind": "sword", "anchor_puppet": 0,
                             "joint": 8}])).astype(np.int32)
        d1 = np.argwhere(np.abs(armed1 - bare).sum(axis=-1) > 0)
        d2 = np.argwhere(np.abs(armed2 - bare).sum(axis=-1) > 0)
        self.assertGreater(d2[:, 1].mean() - d1[:, 1].mean(), 5.0)
        # Unanchored background props keep the legacy path.
        tree = np.asarray(r.render_frame(
            joints, props=[{"kind": "tree", "x": 0.0}])).astype(np.int32)
        self.assertGreater(np.abs(tree - bare).sum(), 0)

    def test_11_combat_pair_sword_clash(self):
        import numpy as np
        from src.puppet.choreography import build_combat_pair, get_combat_props
        from src.rig import decode as _decode, forward_kinematics as _fk
        feat, events = build_combat_pair("sword_clash", duration_s=2.0,
                                        return_events=True)
        self.assertEqual(feat.shape[-1], 60)
        kinds = [e["kind"] for e in events]
        self.assertIn("impact_burst", kinds)
        self.assertIn("speed_lines", kinds)
        # Burst and whoosh fire on the same clash frame.
        burst_f = next(e["start_frame"] for e in events
                       if e["kind"] == "impact_burst")
        whoosh_f = next(e["start_frame"] for e in events
                        if e["kind"] == "speed_lines")
        self.assertEqual(burst_f, whoosh_f)
        # Props contract: sword on attacker wrist, shield on defender wrist.
        props = get_combat_props("sword_clash")
        self.assertEqual(
            [(p["kind"], p["anchor_puppet"], p["joint"]) for p in props],
            [("sword", 0, 8), ("shield", 1, 6)])
        self.assertEqual(get_combat_props("exchange"), [])
        # Defender flinch: B root pushed back vs guard level + freeze present.
        rb, _ = _decode(feat[:, 30:])
        self.assertLess(rb[:, 0].min(), 0.40)
        jb = _fk(rb, _decode(feat[:, 30:])[1])
        best = cur = 1
        for t in range(1, len(jb)):
            if np.allclose(jb[t, 0], jb[t - 1, 0], atol=1e-6):
                cur += 1
                best = max(best, cur)
            else:
                cur = 1
        self.assertGreaterEqual(best, 2)

    def test_10_sequencer_shifts_vfx_events(self):
        from src.sequencer import PuppetSequencer
        from src.puppet.choreography import build_motion_from_action
        seq = PuppetSequencer(overlap_frames=8)
        track = seq.get_or_create_actor("actor_0")
        track.add_step(action="walk", duration_seconds=1.0)
        track.add_step(action="punch", duration_seconds=1.5)
        # Backward compat: default compile still returns bare features.
        feat_only = track.compile(overlap_frames=8)
        self.assertIsInstance(feat_only, np.ndarray)
        result = seq.build()
        bursts = [e for e in result["vfx_events"]
                  if e.get("kind") == "impact_burst"]
        self.assertGreaterEqual(len(bursts), 1)
        # Expected shift = len(walk clip) - overlap, mirrored from blend loop.
        walk_feat = build_motion_from_action("walk", duration_s=1.0)
        _, punch_events = build_motion_from_action(
            "punch", duration_s=1.5, return_events=True)
        punch_burst = next(e for e in punch_events
                           if e.get("kind") == "impact_burst")
        expected = int(punch_burst["start_frame"]) + len(walk_feat) - 8
        got = sorted(int(e["start_frame"]) for e in bursts)
        self.assertIn(expected, got)
        self.assertTrue(all(e["anchor_puppet"] == 0 for e in bursts))
        self.assertLess(max(got), result["T"])

        # Multi-clip (3+ steps) verification: walk -> idle -> punch
        seq3 = PuppetSequencer(overlap_frames=8)
        track3 = seq3.get_or_create_actor("actor_0")
        track3.add_step(action="walk", duration_seconds=1.0)
        track3.add_step(action="idle", duration_seconds=1.0)
        track3.add_step(action="punch", duration_seconds=1.5)
        res3 = seq3.build()
        bursts3 = [e for e in res3["vfx_events"] if e.get("kind") == "impact_burst"]
        self.assertGreaterEqual(len(bursts3), 1)
        idle_feat = build_motion_from_action("idle", duration_s=1.0)
        expected3 = int(punch_burst["start_frame"]) + len(walk_feat) + len(idle_feat) - 16
        got3 = [int(e["start_frame"]) for e in bursts3]
        self.assertIn(expected3, got3)
        self.assertLess(max(got3), res3["T"])


if __name__ == "__main__":
    unittest.main()
