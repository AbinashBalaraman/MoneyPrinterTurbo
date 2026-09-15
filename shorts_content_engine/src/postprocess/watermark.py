"""Watermark scrubbing and inpainting engine for AI-generated video clips."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class WatermarkProfile:
    """Defines spatial bounding box for watermark removal."""
    name: str
    x: int  # Absolute pixel or offset from left (supports negative for offset from right)
    y: int  # Absolute pixel or offset from top (supports negative for offset from bottom)
    w: int  # Width of watermark box
    h: int  # Height of watermark box
    band: int = 1  # Border band thickness for delogo interpolation

    @classmethod
    def veo_bottom_right(cls, video_w: int = 720, video_h: int = 1280) -> "WatermarkProfile":
        """Default preset for Google Veo / Flow vertical 9:16 watermark in bottom-right corner."""
        w = int(video_w * 0.28)  # ~200px on 720w, ~300px on 1080w
        h = int(video_h * 0.065) # ~80px on 1280h, ~125px on 1920h
        x = video_w - w - int(video_w * 0.03)  # 3% margin from right
        y = video_h - h - int(video_h * 0.03)  # 3% margin from bottom
        return cls(name="veo_bottom_right", x=max(0, x), y=max(0, y), w=w, h=h)

    @classmethod
    def gemini_bottom_right(cls, video_w: int = 720, video_h: int = 1280) -> "WatermarkProfile":
        """Preset for Gemini AI video corner badge."""
        w = int(video_w * 0.25)
        h = int(video_h * 0.055)
        x = video_w - w - 16
        y = video_h - h - 24
        return cls(name="gemini_bottom_right", x=max(0, x), y=max(0, y), w=w, h=h)

    @classmethod
    def custom(cls, x: int, y: int, w: int, h: int, name: str = "custom") -> "WatermarkProfile":
        """Custom bounding box coordinates."""
        return cls(name=name, x=max(0, x), y=max(0, y), w=max(1, w), h=max(1, h))


class WatermarkScrubber:
    """Scrubs visual AI watermarks from video files using spatial interpolation and alpha restoration."""

    def __init__(
        self,
        ffmpeg_cmd: str = "ffmpeg",
        ffprobe_cmd: str = "ffprobe",
    ) -> None:
        self.ffmpeg_cmd = ffmpeg_cmd
        self.ffprobe_cmd = ffprobe_cmd

    def is_ffmpeg_available(self) -> bool:
        """Checks if ffmpeg is accessible on PATH."""
        return shutil.which(self.ffmpeg_cmd) is not None

    def get_video_dimensions(self, video_path: str) -> tuple[int, int]:
        """Probes video file with ffprobe to determine pixel width and height."""
        if not os.path.exists(video_path):
            return 720, 1280

        cmd = [
            self.ffprobe_cmd,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0:s=x",
            video_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and "x" in res.stdout:
                parts = res.stdout.strip().split("x")
                return int(parts[0]), int(parts[1])
        except Exception as exc:
            logger.warning("Failed to probe video dimensions for %s: %s", video_path, exc)

        return 720, 1280

    def resolve_profile(
        self,
        profile_or_name: Union[WatermarkProfile, str],
        video_w: int,
        video_h: int,
    ) -> WatermarkProfile:
        """Resolves profile name or instance against actual video dimensions."""
        if isinstance(profile_or_name, WatermarkProfile):
            return profile_or_name

        name = str(profile_or_name).lower().strip()
        if name in ("veo", "veo_bottom_right", "google_veo", "default"):
            return WatermarkProfile.veo_bottom_right(video_w, video_h)
        elif name in ("gemini", "gemini_bottom_right"):
            return WatermarkProfile.gemini_bottom_right(video_w, video_h)
        else:
            return WatermarkProfile.veo_bottom_right(video_w, video_h)

    def scrub_video(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
        profile: Union[WatermarkProfile, str] = "veo_bottom_right",
        mode: str = "delogo",
        band: int = 1,
    ) -> bool:
        """Removes the watermark from input_path and writes cleaned video to output_path.
        
        Args:
            input_path: Path to source MP4 video.
            output_path: Path for cleaned output MP4.
            profile: WatermarkProfile instance or preset name ('veo_bottom_right', 'gemini_bottom_right').
            mode: Scrubbing filter mode ('delogo', 'boxblur').
            band: Interpolation border thickness for delogo filter.

        Returns:
            bool: True if scrubbing succeeded, False if fallback or error occurred.
        """
        in_str = str(input_path)
        out_str = str(output_path)

        if not os.path.exists(in_str):
            logger.error("Input video does not exist: %s", in_str)
            return False

        if not self.is_ffmpeg_available():
            logger.warning("FFmpeg not found on PATH. Copying source video without scrubbing.")
            os.makedirs(os.path.dirname(os.path.abspath(out_str)), exist_ok=True)
            shutil.copy2(in_str, out_str)
            return False

        os.makedirs(os.path.dirname(os.path.abspath(out_str)), exist_ok=True)
        video_w, video_h = self.get_video_dimensions(in_str)
        prof = self.resolve_profile(profile, video_w, video_h)

        # Boundary clamping to prevent FFmpeg filter crashes
        x = max(0, min(prof.x, video_w - 10))
        y = max(0, min(prof.y, video_h - 10))
        w = max(10, min(prof.w, video_w - x))
        h = max(10, min(prof.h, video_h - y))

        if mode == "boxblur":
            # Crop, blur, and overlay back
            vf = (
                f"[0:v]split[main][crop];"
                f"[crop]crop={w}:{h}:{x}:{y},boxblur=10:1[blurred];"
                f"[main][blurred]overlay={x}:{y}[outv]"
            )
        else:
            # Default: FFmpeg high-performance spatial interpolation delogo filter
            vf = f"delogo=x={x}:y={y}:w={w}:h={h}"

        cmd = [
            self.ffmpeg_cmd,
            "-y",
            "-i", in_str,
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "veryfast",
            "-c:a", "copy",
            out_str,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and os.path.exists(out_str) and os.path.getsize(out_str) > 0:
                logger.info("Successfully scrubbed watermark (%s) from %s -> %s", prof.name, in_str, out_str)
                return True
            else:
                logger.warning("FFmpeg delogo filter returned code %d. Stderr: %s", res.returncode, res.stderr[:300])
                # Safe fallback: copy original if filtering fails
                if not os.path.exists(out_str) or os.path.getsize(out_str) == 0:
                    shutil.copy2(in_str, out_str)
                return False
        except Exception as exc:
            logger.exception("Unexpected error during video watermark scrubbing: %s", exc)
            if not os.path.exists(out_str):
                shutil.copy2(in_str, out_str)
            return False
