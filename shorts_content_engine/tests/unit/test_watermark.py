"""Unit tests for watermark scrubbing and metadata sanitization."""

import os
import subprocess
import tempfile
import pytest

from src.postprocess.watermark import WatermarkProfile, WatermarkScrubber
from src.postprocess.metadata import MetadataScrubber


def create_synthetic_mp4(path: str, duration: int = 1, width: int = 720, height: int = 1280) -> bool:
    """Helper to generate a real synthetic video clip with a synthetic watermark box for testing."""
    # Draw a white watermark rectangle in the bottom right corner
    vf = f"color=c=black:s={width}x{height}:d={duration},drawbox=x={width-220}:y={height-90}:w=200:h=70:color=white@0.8:t=fill"
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        path,
    ]
    res = subprocess.run(cmd, capture_output=True, check=False)
    return res.returncode == 0 and os.path.exists(path) and os.path.getsize(path) > 0


class TestWatermarkProfiles:
    """Validates spatial profiles for different AI video generation formats."""

    def test_veo_profile_720p(self):
        prof = WatermarkProfile.veo_bottom_right(720, 1280)
        assert prof.name == "veo_bottom_right"
        assert prof.w == int(720 * 0.28)
        assert prof.h == int(1280 * 0.065)
        assert prof.x > 0 and prof.x + prof.w <= 720
        assert prof.y > 0 and prof.y + prof.h <= 1280

    def test_veo_profile_1080p(self):
        prof = WatermarkProfile.veo_bottom_right(1080, 1920)
        assert prof.w == int(1080 * 0.28)
        assert prof.h == int(1920 * 0.065)
        assert prof.x + prof.w <= 1080
        assert prof.y + prof.h <= 1920

    def test_gemini_profile(self):
        prof = WatermarkProfile.gemini_bottom_right(720, 1280)
        assert prof.name == "gemini_bottom_right"
        assert prof.x + prof.w <= 720
        assert prof.y + prof.h <= 1280

    def test_custom_profile(self):
        prof = WatermarkProfile.custom(x=50, y=100, w=150, h=60, name="custom_logo")
        assert prof.name == "custom_logo"
        assert prof.x == 50
        assert prof.y == 100
        assert prof.w == 150
        assert prof.h == 60


class TestWatermarkScrubber:
    """Validates scrubber functionality, dimension probing, and FFmpeg filter execution."""

    def test_resolve_profile_string(self):
        scrubber = WatermarkScrubber()
        prof_veo = scrubber.resolve_profile("veo_bottom_right", 720, 1280)
        assert prof_veo.name == "veo_bottom_right"
        prof_gemini = scrubber.resolve_profile("gemini", 720, 1280)
        assert prof_gemini.name == "gemini_bottom_right"

    def test_scrub_nonexistent_file(self, tmp_path):
        scrubber = WatermarkScrubber()
        out_file = str(tmp_path / "out.mp4")
        ok = scrubber.scrub_video("non_existent_file.mp4", out_file)
        assert ok is False

    def test_scrub_synthetic_video_delogo(self, tmp_path):
        scrubber = WatermarkScrubber()
        if not scrubber.is_ffmpeg_available():
            pytest.skip("FFmpeg is not available in environment")

        in_file = str(tmp_path / "watermarked.mp4")
        out_file = str(tmp_path / "scrubbed.mp4")

        created = create_synthetic_mp4(in_file, duration=1, width=720, height=1280)
        if not created:
            pytest.skip("Failed to generate synthetic test mp4 via lavfi")

        ok = scrubber.scrub_video(in_file, out_file, profile="veo_bottom_right", mode="delogo")
        assert ok is True
        assert os.path.exists(out_file)
        assert os.path.getsize(out_file) > 0

    def test_scrub_synthetic_video_boxblur(self, tmp_path):
        scrubber = WatermarkScrubber()
        if not scrubber.is_ffmpeg_available():
            pytest.skip("FFmpeg is not available in environment")

        in_file = str(tmp_path / "watermarked_blur.mp4")
        out_file = str(tmp_path / "scrubbed_blur.mp4")

        created = create_synthetic_mp4(in_file, duration=1, width=720, height=1280)
        if not created:
            pytest.skip("Failed to generate synthetic test mp4 via lavfi")

        ok = scrubber.scrub_video(in_file, out_file, profile="gemini_bottom_right", mode="boxblur")
        assert ok is True
        assert os.path.exists(out_file)
        assert os.path.getsize(out_file) > 0


class TestMetadataScrubber:
    """Validates container provenance and metadata tag stripping."""

    def test_strip_metadata_nonexistent(self, tmp_path):
        meta = MetadataScrubber()
        out_file = str(tmp_path / "clean_meta.mp4")
        ok = meta.strip_metadata("no_such_file.mp4", out_file)
        assert ok is False

    def test_strip_metadata_synthetic(self, tmp_path):
        meta = MetadataScrubber()
        if not meta.is_ffmpeg_available():
            pytest.skip("FFmpeg is not available in environment")

        in_file = str(tmp_path / "raw_meta.mp4")
        out_file = str(tmp_path / "sanitized_meta.mp4")

        created = create_synthetic_mp4(in_file, duration=1)
        if not created:
            pytest.skip("Failed to generate synthetic test mp4")

        ok = meta.strip_metadata(in_file, out_file)
        assert ok is True
        assert os.path.exists(out_file)
        assert os.path.getsize(out_file) > 0
