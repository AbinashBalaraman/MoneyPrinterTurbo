"""Tests for src/service.py: the single prompt -> clip code path.

The CLI, the batch harness and the studio all go through this module, so its
contract is what keeps them from drifting apart.
"""
import shutil

import pytest

from src.service import (MODE_ACTION, MODE_SCENE, PlanError, batch,
                         diagnose_timeline, plan_prompt, produce, slowmo)

HAS_FFMPEG = shutil.which("ffmpeg") is not None


class TestPlanning:
    def test_single_action_takes_the_action_path(self):
        p = plan_prompt("punch")
        assert p["mode"] == MODE_ACTION
        assert p["action"] == "punch"
        assert p["n_person"] == 1
        assert p["T"] > 0

    def test_paired_action_is_two_person(self):
        p = plan_prompt("punch and block")
        assert p["n_person"] == 2
        assert p["timeline"]["feat"].shape[1] == 60

    def test_multi_beat_prompt_takes_the_scene_path(self):
        p = plan_prompt("walk forward, then punch, then celebrate")
        assert p["mode"] == MODE_SCENE
        # The action list rides on the timeline so downstream consumers (audio)
        # do not need to re-parse the prompt.
        assert p["timeline"]["actions"][:2] == ["walk", "punch"]

    def test_empty_prompt_is_a_plan_error(self):
        for bad in ("", "   ", None):
            with pytest.raises(PlanError):
                plan_prompt(bad or "")


class TestDiagnose:
    def test_report_has_all_three_tiers(self):
        p = plan_prompt("walk forward")
        rep = diagnose_timeline(p["timeline"], p["scene_dict"])
        for key in ("passed", "hard", "timing", "warn"):
            assert key in rep

    def test_timing_debt_does_not_block_by_default(self):
        p = plan_prompt("punch and block")
        assert diagnose_timeline(p["timeline"], p["scene_dict"])["passed"] is True


class TestGuards:
    def test_max_frames_refuses_before_rendering(self, tmp_path):
        r = produce("walk forward", tmp_path, name="g", max_frames=10,
                    with_sound=False, want_slowmo=False)
        assert r["ok"] is False
        assert r["stage"] == "guard"
        assert "too long" in r["error"]
        assert r["video"] is None

    def test_blocked_scene_returns_a_report_not_an_exception(self, tmp_path):
        prompt = "two stickmen exchange punches, then one gets knocked down and gets back up"
        r = produce(prompt, tmp_path, name="b", with_sound=False, want_slowmo=False)
        assert r["ok"] is False
        assert r["error"]
        assert r["report"]["hard"], "a blocked scene must explain itself"
        assert r["video"] is None

    def test_allow_override_renders(self, tmp_path):
        prompt = "two stickmen exchange punches, then one gets knocked down and gets back up"
        p = plan_prompt(prompt)
        codes = ",".join(sorted({h["code"] for h in
                                 diagnose_timeline(p["timeline"], p["scene_dict"])["hard"]}))
        assert codes, "expected this scene to have hard defects to excuse"
        r = produce(prompt, tmp_path, name="a", allow=codes, sd=True,
                    with_sound=False, want_slowmo=False)
        assert r["ok"] is True
        assert r["video"]


class TestBatch:
    def test_batch_returns_one_row_per_prompt(self):
        rows = batch(["idle", "walk forward", "punch"])
        assert len(rows) == 3
        assert all("hard" in r and "timing" in r for r in rows)

    def test_batch_survives_a_bad_prompt(self):
        rows = batch(["walk forward", ""])
        assert len(rows) == 2
        assert rows[1]["ok"] is False


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg required for retiming")
class TestSlowmo:
    def test_slowmo_doubles_duration(self, tmp_path):
        import json
        import subprocess
        r = produce("walk forward", tmp_path, name="s", sd=True,
                    with_sound=False, want_slowmo=False)
        assert r["ok"]
        out = slowmo(r["video"], tmp_path / "s_slow.mp4", 0.5)
        def dur(path):
            o = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                "format=duration", "-of", "json", str(path)],
                               capture_output=True, text=True)
            return float(json.loads(o.stdout)["format"]["duration"])
        assert dur(out) > dur(r["video"]) * 1.8
