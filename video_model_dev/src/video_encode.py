"""Shared FFmpeg video encoding utilities for deterministic stickman rendering."""
import os
import subprocess
from typing import Optional


def open_ffmpeg_writer(
    output_path: str,
    width: int,
    height: int,
    fps: int = 24,
    crf: int = 20,
    preset: str = "fast"
) -> subprocess.Popen:
    """Spawns an ffmpeg subprocess configured for raw RGB24 input to H.264 MP4 output."""
    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", preset,
        "-crf", str(crf),
        output_path
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


def close_ffmpeg_writer(proc: subprocess.Popen) -> None:
    """Flushes stdin, waits for termination, and checks return code."""
    try:
        proc.stdin.close()
        stderr_bytes = proc.stderr.read()
        proc.wait()
        if proc.returncode != 0:
            err_msg = stderr_bytes.decode("utf-8", errors="ignore") if stderr_bytes else f"code {proc.returncode}"
            raise RuntimeError(f"FFmpeg encoding failed with return code {proc.returncode}: {err_msg}")
    except Exception:
        proc.kill()
        raise
