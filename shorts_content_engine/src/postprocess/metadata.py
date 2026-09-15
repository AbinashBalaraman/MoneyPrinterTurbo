"""Metadata and provenance scrubbing for media containers."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


class MetadataScrubber:
    """Removes EXIF, C2PA, IPTC, and container provenance metadata from video and audio files."""

    def __init__(self, ffmpeg_cmd: str = "ffmpeg") -> None:
        self.ffmpeg_cmd = ffmpeg_cmd

    def is_ffmpeg_available(self) -> bool:
        """Checks if ffmpeg is accessible on PATH."""
        return shutil.which(self.ffmpeg_cmd) is not None

    def strip_metadata(
        self,
        input_path: Union[str, Path],
        output_path: Union[str, Path],
    ) -> bool:
        """Strips all container metadata tags, creation provenance, and chapter markers.
        
        Uses stream-copy mode (-c copy) so execution completes in milliseconds without re-encoding.
        """
        in_str = str(input_path)
        out_str = str(output_path)

        if not os.path.exists(in_str):
            logger.error("Input file does not exist: %s", in_str)
            return False

        if not self.is_ffmpeg_available():
            logger.warning("FFmpeg not found. Copying file directly.")
            os.makedirs(os.path.dirname(os.path.abspath(out_str)), exist_ok=True)
            shutil.copy2(in_str, out_str)
            return False

        os.makedirs(os.path.dirname(os.path.abspath(out_str)), exist_ok=True)

        cmd = [
            self.ffmpeg_cmd,
            "-y",
            "-i", in_str,
            "-map_metadata", "-1",
            "-map_chapters", "-1",
            "-fflags", "+bitexact",
            "-flags:v", "+bitexact",
            "-flags:a", "+bitexact",
            "-c", "copy",
            out_str,
        ]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and os.path.exists(out_str) and os.path.getsize(out_str) > 0:
                logger.info("Successfully stripped metadata from %s -> %s", in_str, out_str)
                return True
            else:
                logger.warning("FFmpeg metadata strip exited with %d: %s", res.returncode, res.stderr[:300])
                if not os.path.exists(out_str) or os.path.getsize(out_str) == 0:
                    shutil.copy2(in_str, out_str)
                return False
        except Exception as exc:
            logger.exception("Error stripping metadata from %s: %s", in_str, exc)
            if not os.path.exists(out_str):
                shutil.copy2(in_str, out_str)
            return False
