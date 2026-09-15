"""1-Minute Cinematic: 'The Way of the Stick' (60s, 1440f, 1280x720 HD).

A lone warrior's journey: arrival, travel, trials (leap/slide), twin kata,
fall, rise, triumph, farewell. Solo acts + one synchronized kata duo
(side-by-side forms: the 2D sagittal rig faces +X, so no mirrored duels).

Usage:
    python tools/render_cinematic.py
Output: out/cinematic_way_of_the_stick.mp4 + per-act stills out/cinematic_stills/.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.stage.dsl import compile_stage_script

TITLE = "THE WAY OF THE STICK"
SUB = "a stickman cinematic in ten acts"

# (name, duration, scenery, puppets, text, audit still global frame or None for midpoint)
ACTS = [
    ("Prologue - Empty Arena", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "idle", "offset_x": -0.6}],
     {"text": TITLE, "x": 340, "y": 120, "font_size": 44}, None),
    ("The Wanderer Enters", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "walk", "offset_x": -1.8, "speed": 0.55, "amplitude": 0.85}],
     None, None),
    ("Trial of Air", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "jump", "offset_x": -0.9, "amplitude": 1.1}],
     {"text": "trial of air", "x": 480, "y": 70, "font_size": 36}, 309),
    ("Trial of Earth", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "slide", "offset_x": -1.2, "amplitude": 1.0}],
     {"text": "trial of earth", "x": 460, "y": 120, "font_size": 36}, 450),
    ("Forms", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "punch", "offset_x": -0.3}],
     {"text": "forms", "x": 560, "y": 120, "font_size": 36}, 591),
    ("Twin Kata", 8.0, {"type": "perspective_hall", "colonnade": True},
     [{"actor_id": 0, "action": "punch", "offset_x": -0.9},
      {"actor_id": 1, "action": "punch", "offset_x": 0.3}],
     {"text": "twin kata", "x": 520, "y": 110, "font_size": 36}, None),
    ("Trial by Fall", 7.0, {"type": "plain"},
     [{"actor_id": 0, "action": "knockdown", "offset_x": -0.2}],
     {"text": "fall", "x": 600, "y": 120, "font_size": 36}, None),
    ("Rise", 6.0, {"type": "plain"},
     [{"actor_id": 0, "action": "getup", "offset_x": -0.5}],
     {"text": "rise", "x": 590, "y": 120, "font_size": 36}, None),
    ("Triumph", 5.0, {"type": "perspective_hall", "colonnade": True, "baroque_frame": True},
     [{"actor_id": 0, "action": "celebrate", "offset_x": -0.2}],
     {"text": "triumph", "x": 540, "y": 110, "font_size": 40}, None),
    ("Farewell", 4.0, {"type": "plain"},
     [{"actor_id": 0, "action": "wave", "offset_x": -0.2}],
     {"text": "FIN", "x": 600, "y": 120, "font_size": 44}, None),
]

SCRIPT = {
    "title": "The Way of the Stick",
    "theme": "light",
    "width": 1280,
    "height": 720,
    "fps": 24,
    "scenes": [
        {"name": name, "duration_s": dur, "scenery": scenery, "puppets": puppets,
         **({"text_overlay": text} if text else {})}
        for name, dur, scenery, puppets, text, _ in ACTS
    ],
}

TOTAL = sum(d for _, d, _, _, _, _ in ACTS)
assert abs(TOTAL - 60.0) < 1e-6, f"script must total 60s, got {TOTAL}"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills-only", action="store_true",
                    help="Skip render; extract stills from existing mp4.")
    args = ap.parse_args()
    out = ROOT / "out/cinematic_way_of_the_stick.mp4"
    if not args.stills_only:
        print(f"[*] Compiling {len(ACTS)} acts, {TOTAL:.0f}s @24fps (1440 frames, 1280x720)...")
        res = compile_stage_script(SCRIPT, str(out), preview_ascii=True)
        print(f"[+] {out} ({res['size_bytes']} bytes, {res['total_frames']} frames, {res['duration_s']:.1f}s)")
    elif not out.exists():
        print(f"[!] {out} missing; run without --stills-only first.")
        return 1
    still_dir = ROOT / "out/cinematic_stills"
    still_dir.mkdir(parents=True, exist_ok=True)
    cursor = 0
    for (name, dur, _, _, _, still_override) in ACTS:
        mid = still_override if still_override is not None else cursor + int(dur * 24) // 2
        still = still_dir / f"{name.split(' - ')[0].lower().replace(' ', '_')}_{mid:04d}.png"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(mid / 24),
                        "-i", str(out), "-vframes", "1", str(still)], check=True)
        print(f"[+] {still}")
        cursor += int(dur * 24)
    return 0


if __name__ == "__main__":
    sys.exit(main())
