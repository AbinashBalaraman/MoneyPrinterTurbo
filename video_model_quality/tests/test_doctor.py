"""Tests for src/doctor.py: SceneDoctor defect gate."""
import numpy as np
import pytest

from src.doctor import diagnose, format_report
from src.scene import SceneScript, Beat, Character, compile_scene


class TestSceneDoctor:
    def test_clean_timeline_passes(self):
        script = SceneScript(
            title="Clean Scene",
            characters=[Character("a", 0.0)],
            beats=[Beat(action="walk", duration_s=1.5)]
        )
        timeline = compile_scene(script)
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is True
        assert len(report["hard"]) == 0
        text = format_report(report)
        assert "PASSED" in text

    def test_numeric_instability_hard_defect(self):
        script = SceneScript(characters=[Character("a", 0.0)], beats=[Beat(action="idle", duration_s=1.0)])
        timeline = compile_scene(script)
        timeline["feat"][10, 0] = np.nan
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is False
        codes = [h["code"] for h in report["hard"]]
        assert "numeric_instability" in codes

    def test_ground_penetration_hard_defect(self):
        script = SceneScript(characters=[Character("a", 0.0)], beats=[Beat(action="idle", duration_s=1.0)])
        timeline = compile_scene(script)
        # Drop root Y far below ground
        timeline["feat"][:, 1] = -0.60
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is False
        codes = [h["code"] for h in report["hard"]]
        assert "ground_penetration" in codes

    def test_targeted_interaction_absent_hard_defect(self):
        # Create a fake timeline with 2 actors far apart (e.g. at -5.0 and +5.0)
        script = SceneScript(
            characters=[Character("a", -5.0), Character("b", 5.0)],
            beats=[
                Beat(actor="a", action="punch", target="b", interaction="strike", duration_s=2.0)
            ]
        )
        # Manually compile solo beats without interaction coupling to simulate defect
        from src.puppet.choreography import build_motion_from_action
        f_a = build_motion_from_action("punch", duration_s=2.0)
        f_b = build_motion_from_action("idle", duration_s=2.0)
        f_a[:, 0] -= 5.0
        f_b[:, 0] += 5.0
        feat = np.concatenate([f_a, f_b], axis=-1)
        fake_tl = {"feat": feat, "T": len(feat), "n_person": 2, "duration_seconds": 2.0}
        report = diagnose(fake_tl, script.to_dict())
        assert report["passed"] is False
        codes = [h["code"] for h in report["hard"]]
        assert "targeted_interaction_absent" in codes

    def test_object_never_lives_hard_defect(self):
        script = SceneScript(
            characters=[Character("a", 0.0)],
            beats=[Beat(action="walk", duration_s=1.0)],
            objects=[{"id": "sword_ghost", "kind": "sword"}]
        )
        timeline = compile_scene(script)
        # Empty the prop tracks
        timeline["prop_tracks"] = [[] for _ in range(timeline["T"])]
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is False
        codes = [h["code"] for h in report["hard"]]
        assert "object_never_lives" in codes

    def test_actor_off_frame_hard_defect(self):
        script = SceneScript(characters=[Character("a", 0.0)], beats=[Beat(action="idle", duration_s=2.0)])
        timeline = compile_scene(script)
        # Teleport actor to x = 10.0 (way outside camera viewport)
        timeline["feat"][:, 0] = 10.0
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is False
        codes = [h["code"] for h in report["hard"]]
        assert "actor_off_frame" in codes

    def test_camera_jump_warn_defect(self):
        script = SceneScript(characters=[Character("a", 0.0)], beats=[Beat(action="idle", duration_s=1.0)])
        timeline = compile_scene(script)
        cam = np.zeros(timeline["T"], dtype=np.float32)
        cam[15:] = 2.0  # sudden jump
        timeline["camera_track"] = {"camera_x": cam, "zoom": 1.0, "mode": "auto"}
        report = diagnose(timeline, script.to_dict())
        warn_codes = [w["code"] for w in report["warn"]]
        assert "camera_jump" in warn_codes

    def test_window_aware_interaction_passes(self):
        # Two sequential exchanges that both engage -> pass, no hard defect.
        script = SceneScript(
            characters=[Character("a", -0.45), Character("b", 0.45)],
            beats=[
                Beat(actor="a", action="punch", target="b", interaction="strike", duration_s=2.0),
                Beat(actor="a", action="kick", target="b", interaction="dodge", duration_s=2.0),
            ],
        )
        timeline = compile_scene(script)
        report = diagnose(timeline, script.to_dict())
        assert report["passed"] is True
        assert "targeted_interaction_absent" not in [h["code"] for h in report["hard"]]

    def test_targeted_absent_window_still_hard(self):
        # One declared window, actors never close -> HARD block.
        fa = np.zeros((60, 30), dtype=np.float32)
        fb = np.zeros((60, 30), dtype=np.float32)
        fa[:, 0], fb[:, 0] = -5.0, 5.0
        fake = {
            "feat": np.concatenate([fa, fb], axis=-1), "T": 60, "n_person": 2,
            "interactions": [{"kind": "interaction", "interaction": "strike",
                              "actors": [0, 1], "frame": 0, "frames": 60}],
        }
        scene = {"beats": [{"actor": "a", "action": "punch", "target": "b",
                            "interaction": "strike"}]}
        report = diagnose(fake, scene=scene)
        assert report["passed"] is False
        assert "targeted_interaction_absent" in [h["code"] for h in report["hard"]]

    def test_partial_interaction_window_warns(self):
        # First window engages, second never connects -> warn, not block.
        fa = np.zeros((120, 30), dtype=np.float32)
        fb = np.zeros((120, 30), dtype=np.float32)
        fa[:60, 0], fb[:60, 0] = 0.0, 0.4   # engaged
        fa[60:, 0], fb[60:, 0] = -5.0, 5.0  # stranded
        fake = {
            "feat": np.concatenate([fa, fb], axis=-1), "T": 120, "n_person": 2,
            "interactions": [
                {"interaction": "strike", "actors": [0, 1], "frame": 0, "frames": 60},
                {"interaction": "knockdown", "actors": [0, 1], "frame": 60, "frames": 60},
            ],
        }
        scene = {"beats": [{"actor": "a", "action": "punch", "target": "b",
                            "interaction": "strike"}]}
        report = diagnose(fake, scene=scene)
        codes = [w["code"] for w in report["warn"]]
        assert "interaction_window_no_contact" in codes


class TestSeverityTiers:
    """Correctness blocks the product; timing debt is advisory until Phase 2."""

    def _linear_timeline(self):
        """A timeline with a guaranteed constant-velocity run: the head bone is
        swept at a perfectly constant rate from a grounded rest pose, so nothing
        else (contact, penetration, jerk) can trip and mask the timing signal."""
        from src.rig import encode, REST_ANGLES
        T = 60
        sweep = np.linspace(0.0, 2.0, T, dtype=np.float32)  # ~0.8 rad/s, steady
        frames = []
        for t in range(T):
            ang = REST_ANGLES.copy()
            ang[3] = REST_ANGLES[3] + sweep[t]  # head
            frames.append(encode(np.zeros(2, dtype=np.float32), ang))
        return {"feat": np.stack(frames), "T": T, "n_person": 1}

    def test_timing_debt_is_advisory_by_default(self):
        rep = diagnose(self._linear_timeline())
        assert "linear_easing" in [t["code"] for t in rep["timing"]]
        assert "linear_easing" not in [h["code"] for h in rep["hard"]]
        # Advisory debt must not block the product.
        assert rep["passed"] is True

    def test_strict_timing_promotes_to_hard(self):
        rep = diagnose(self._linear_timeline(), strict_timing=True)
        assert "linear_easing" in [h["code"] for h in rep["hard"]]
        assert rep["passed"] is False

    def test_allow_excuses_timing_even_under_strict_timing(self):
        rep = diagnose(self._linear_timeline(), strict_timing=True,
                       allow="linear_easing")
        assert rep["passed"] is True
        assert rep["timing"] == []

    def test_allow_demotes_defects_to_warn(self):
        """`allow` is uniform: an excused code never blocks, whichever tier."""
        from src.doctor import CORRECTNESS_CODES, TIMING_CODES
        assert "jerk_spike" in CORRECTNESS_CODES
        assert "linear_easing" in TIMING_CODES
        # A timing code, excused even under strict_timing -> warn, not hard.
        rep = diagnose(self._linear_timeline(), strict_timing=True,
                       allow="linear_easing")
        assert rep["passed"] is True
        assert "linear_easing" in [w["code"] for w in rep["warn"]]
        assert rep["timing"] == []

    def test_format_report_shows_timing_section(self):
        text = format_report(diagnose(self._linear_timeline()))
        assert "TIMING DEBT" in text
        assert "PASSED" in text

    def test_duel_scene_blocks_on_correctness_not_timing(self):
        """The real 07_final_duel scene must block on correctness defects only;
        its timing debt must land in the advisory tier, not in hard."""
        import json
        from pathlib import Path
        p = Path("out/scenes/07_final_duel.json")
        if not p.exists():
            pytest.skip("07_final_duel.json not present")
        sc = SceneScript.from_dict(json.loads(p.read_text(encoding="utf-8")))
        rep = diagnose(compile_scene(sc), sc.to_dict())
        hard_codes = {h["code"] for h in rep["hard"]}
        timing_codes = {t["code"] for t in rep["timing"]}
        assert hard_codes <= {"jerk_spike", "foot_slide", "dead_hold"}
        assert "linear_easing" in timing_codes or "missing_anticipation" in timing_codes
        assert not (hard_codes & {"linear_easing", "missing_anticipation"})
