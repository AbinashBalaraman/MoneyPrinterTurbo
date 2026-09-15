"""Tests for src/audio.py: the soundtrack is derived from the motion."""
import numpy as np
import pytest

from src.audio import (SAMPLE_RATE, build_audio, detect_footsteps,
                       detect_impacts, detect_whooshes, split_actors, write_wav)
from src.service import plan_prompt


def _timeline(prompt, seed=0):
    pl = plan_prompt(prompt, seed=seed)
    tl = dict(pl["timeline"])
    tl["T"] = tl["feat"].shape[0]
    return tl


class TestEventDetection:
    def test_split_actors_handles_1p_and_2p(self):
        assert len(split_actors(np.zeros((10, 30), np.float32))) == 1
        assert len(split_actors(np.zeros((10, 60), np.float32))) == 2
        with pytest.raises(ValueError):
            split_actors(np.zeros((10, 31), np.float32))

    def test_walk_has_footsteps_and_no_whoosh(self):
        tl = _timeline("walk forward")
        steps = detect_footsteps(tl["feat"])
        assert len(steps) >= 4, "a walk must produce footfalls"
        # A walk is locomotion, not a strike: a speed-based whoosh gate used to
        # fire 27 times here. Whooshes must key off strike structure instead.
        assert detect_whooshes(tl, tl["feat"]) == []

    def test_idle_is_silent(self):
        tl = _timeline("idle")
        assert detect_footsteps(tl["feat"]) == []
        assert detect_whooshes(tl, tl["feat"]) == []

    def test_strike_action_produces_a_whoosh(self):
        tl = _timeline("punch")
        ws = detect_whooshes(tl, tl["feat"])
        assert len(ws) == 1
        assert ws[0]["kind"] == "whoosh"

    def test_combat_pair_detects_impacts(self):
        tl = _timeline("two stickmen fight for 3 seconds")
        assert len(detect_impacts(tl, tl["feat"])) >= 1

    def test_footstep_frames_are_in_range(self):
        tl = _timeline("walk forward")
        T = tl["feat"].shape[0]
        for e in detect_footsteps(tl["feat"]):
            assert 0 < e["frame"] < T
            assert 0.0 < e["strength"] <= 1.0


class TestAssembly:
    def test_length_matches_duration_and_peak_is_bounded(self):
        tl = _timeline("walk forward")
        a = build_audio(tl)
        assert abs(len(a["samples"]) / SAMPLE_RATE - a["duration_s"]) < 0.01
        assert np.abs(a["samples"]).max() <= 1.0
        assert np.isfinite(a["samples"]).all()

    def test_deterministic_for_a_seed(self):
        tl = _timeline("punch and block")
        a = build_audio(tl, seed=3)
        b = build_audio(tl, seed=3)
        np.testing.assert_array_equal(a["samples"], b["samples"])

    def test_music_can_be_disabled(self):
        tl = _timeline("idle")
        assert np.abs(build_audio(tl, with_music=False)["samples"]).max() == 0.0
        assert np.abs(build_audio(tl, with_music=True)["samples"]).max() > 0.0

    def test_write_wav_roundtrip(self, tmp_path):
        import wave
        tl = _timeline("walk forward")
        a = build_audio(tl)
        p = write_wav(a["samples"], tmp_path / "a.wav", a["sample_rate"])
        with wave.open(p, "rb") as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == SAMPLE_RATE
            assert w.getnframes() == len(a["samples"])
