"""Tests for the pre-render text review system (src/preview.py)."""
import numpy as np
import pytest

from src.preview import (
    interaction_stats, motion_stats, image_to_text, ASCII_RAMP,
)


def _pair_joints(T=60, sep=0.3):
    """Two actors `sep` apart horizontally, both standing."""
    j = np.zeros((T, 2, 15, 2))
    j[:, 0, :, 1] = np.linspace(0.0, 0.45, T)[:, None]          # A vertical
    j[:, 1, :, 1] = np.linspace(0.0, 0.45, T)[:, None]
    j[:, 0, :, 0] = 0.0
    j[:, 1, :, 0] = sep
    return j


class TestInteractionStats:
    def test_single_actor_no_interaction(self):
        j = _pair_joints()[:, :1]
        s = interaction_stats(j)
        assert s["n_person"] == 1 and s["min_dist"] is None

    def test_close_actors_are_engaged(self):
        # Overlapping positions every frame -> sustained contact.
        s = interaction_stats(_pair_joints(sep=0.05))
        assert s["interacting"] is True
        assert s["verdict"] == "engaged"

    def test_far_actors_flagged_no_interaction(self):
        s = interaction_stats(_pair_joints(sep=2.5))
        assert s["interacting"] is False
        assert s["contact_ratio"] < 0.05
        assert "solo" in s["verdict"]

    def test_incidental_crossing_is_weak(self):
        # Actors far apart except a brief pass through the middle.
        j = _pair_joints(sep=2.6)
        j[25:32, 1, :, 0] = 0.0  # brief overlap
        s = interaction_stats(j)
        assert s["interacting"] is False
        assert s["verdict"] in ("weak/incidental contact", "NO interaction (two solo actors)")


class TestMotionStats:
    def test_reports_travel_and_penetration(self):
        j = _pair_joints(T=24)
        j[:, 1, :, 0] += np.linspace(0, 2.0, 24)[:, None]  # B travels
        s = motion_stats(j, fps=24)
        assert s["T"] == 24 and abs(s["duration_s"] - 1.0) < 1e-6
        assert s["actors"][1]["root_travel"] > 1.0
        assert s["actors"][0]["root_travel"] < 1e-6
        assert s["actors"][0]["max_penetration"] >= 0.0


class TestImageToText:
    def _img(self, w=40, h=20, box=None):
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (w, h), (255, 255, 255))
        d = ImageDraw.Draw(im)
        if box:
            d.rectangle(box, fill=(0, 0, 0))
        return im

    def test_half_block_uses_block_glyphs(self):
        txt = image_to_text(self._img(box=[10, 5, 30, 15]), cols=40, mode="half",
                            auto_crop=False)
        assert any(ch in txt for ch in "█▀▄")

    def test_braille_uses_braille_codepoints(self):
        txt = image_to_text(self._img(box=[10, 5, 30, 15]), cols=40, mode="braille",
                            auto_crop=False)
        assert any(0x2800 <= ord(c) <= 0x28FF for c in txt)

    def test_ascii_ramp_only(self):
        txt = image_to_text(self._img(box=[10, 5, 30, 15]), cols=40, mode="ascii",
                            auto_crop=False)
        assert set(txt.replace("\n", "")).issubset(set(ASCII_RAMP))

    def test_auto_crop_removes_empty_margin(self):
        # A small box in a big frame should crop to roughly the box.
        txt = image_to_text(self._img(w=200, h=100, box=[90, 40, 110, 60]),
                            cols=30, mode="half", auto_crop=True)
        lines = [l for l in txt.split("\n") if l.strip()]
        assert len(lines) <= 12  # tightly cropped, not the full 100px height


class TestDigest:
    def test_digest_contains_metrics_and_frames(self):
        from src.preview import render_timeline_preview
        # Minimal timeline built directly (feat (T,60) = 2 actors).
        from src.puppet.choreography import build_motion_from_action
        a = build_motion_from_action("walk", duration_s=1.0, start_x=-0.4)
        b = build_motion_from_action("walk", duration_s=1.0, start_x=0.4)
        T = min(len(a), len(b))
        feat = np.concatenate([a[:T], b[:T]], axis=-1).astype(np.float32)
        tl = {"feat": feat, "T": T, "fps": 24, "title": "t", "n_person": 2}
        r = render_timeline_preview(tl, cols=40, sample=3, write_animation=False)
        assert "PRE-RENDER TEXT REVIEW" in r["digest"]
        assert "INTERACTION" in r["digest"]
        assert len(r["frames_shown"]) == 3
