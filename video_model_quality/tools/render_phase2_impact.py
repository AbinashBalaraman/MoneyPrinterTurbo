"""Phase-2 impact inspection scenes: punch/kick with hit-stop, impact VFX, cam impulse.

Usage:
    python tools/render_phase2_impact.py
Renders out/phase2_punch.mp4, out/phase2_kick.mp4 (512x512) + impact stills
out/phase2_*_impact.png for visual inspection loop.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.puppet.choreography import build_motion_from_action
from src.stage_renderer import render_stage_video

SCENES = [
    ("punch", {"kind": "impact_burst", "anchor_puppet": 0, "anchor_joint": 8}),
    ("kick", {"kind": "impact_burst", "anchor_puppet": 0, "anchor_joint": 10}),
]
# Measured apex: max wrist/ankle extension at frame 15 (build_motion_from_action, 2.0s)
IMPACT_FRAME = 15

for action, vfx_anchor in SCENES:
    feat = build_motion_from_action(action, duration_s=2.0)
    # Impact apex ≈ frame 15; VFX + auto cam impulse there
    vfx = [dict(vfx_anchor, start_frame=IMPACT_FRAME, duration=8, scale=1.2)]
    out = ROOT / f"out/phase2_{action}.mp4"
    render_stage_video(feat, str(out), theme_name="light", width=512, height=512,
                       fix_contact=False, vfx=vfx,
                       cam_impulse=[{"start_frame": IMPACT_FRAME, "magnitude": 0.02}])
    print(f"[+] {out} ({out.stat().st_size} bytes)")
    still = ROOT / f"out/phase2_{action}_impact.png"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(IMPACT_FRAME / 24),
                    "-i", str(out), "-vframes", "1", str(still)], check=True)
    print(f"[+] {still}")
