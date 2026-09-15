"""Narrative 3-Act Martial Arts Story: walk forward -> punch strike -> victory celebrate.

Usage:
    python tools/render_narrative_sequence.py
Renders out/narrative_martial_artist.mp4 (512x512) + audit stills
out/inspect_scenes/narrative_martial_artist_frame_*.png covering the walk,
stride->windup seam, punch apex, settle->cheer seam, and cheer hold.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sequencer import sequence_prompts
from src.renderer import render_to_video, decode_motion_features
from src.stage_renderer import render_stage_video  # noqa: F401 (kept for HD upgrade path)

PROMPTS = [
    "stickman walk forward steadily for 3 seconds",
    "stickman punch fiercely",
    "stickman celebrate victory",
]


def build_narrative(return_events=False):
    """Compiles the 3-act narrative; optionally returns (feat, events)."""
    res = sequence_prompts(PROMPTS)
    feat = res["feat"]
    if not return_events:
        return feat
    apex = int(np.argmax(decode_motion_features(feat)[:, 0, 8, 0]))
    events = [{"kind": "impact_burst", "anchor_puppet": 0, "anchor_joint": 8,
               "start_frame": apex, "duration": 8, "scale": 1.2}]
    return feat, events


def seam_report(feat):
    """Per-frame max joint speeds; returns top spikes (frame, speed) for blend audit."""
    joints = decode_motion_features(feat)
    speeds = np.max(np.linalg.norm(np.diff(joints[:, 0], axis=0), axis=-1), axis=-1)
    order = np.argsort(speeds)[::-1][:5]
    return [(int(i + 1), round(float(speeds[i]), 4)) for i in order]


def main():
    feat, events = build_narrative(return_events=True)
    apex = events[0]["start_frame"]
    T = len(feat)
    print(f"[*] Narrative: {PROMPTS}")
    print(f"[*] T={T} frames ({T / 24:.2f}s), punch apex frame={apex}")
    print(f"[*] Top joint-speed spikes (frame, speed): {seam_report(feat)}")

    out = ROOT / "out/narrative_martial_artist.mp4"
    render_to_video(feat, str(out), fps=24, canvas_size=512, fix_contact=False,
                    auto_camera=True, vfx_events=events)
    print(f"[+] {out} ({out.stat().st_size} bytes)")

    still_frames = sorted({T // 6, apex - 4, apex, apex + 6, T - 6})
    for f in still_frames:
        still = ROOT / f"out/inspect_scenes/narrative_martial_artist_frame_{f:03d}.png"
        still.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(f / 24),
                        "-i", str(out), "-vframes", "1", str(still)], check=True)
        print(f"[+] {still}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
