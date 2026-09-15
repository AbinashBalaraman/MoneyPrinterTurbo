"""User CLI tool: Text-to-Stickman-Video generator.

Usage:
    python tools/prompt_to_video.py "two stickmen punch and block for 3s" -o out/my_combat.mp4
    python tools/prompt_to_video.py "stickman walk forward fast" --theme dark
    python tools/prompt_to_video.py "celebrate win"
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.parser import parse_prompt
from src.catalog import ACTIONS_1P, ACTIONS_2P
from src.puppet.choreography import build_motion_from_action, build_combat_pair
from src.stage_renderer import render_stage_video
from src.renderer import render_to_video


def main():
    parser = argparse.ArgumentParser(description="Text-to-Stickman-Video Generator")
    parser.add_argument("prompt", type=str, help="Text prompt describing the desired action")
    parser.add_argument("-o", "--output", type=str, default="out/prompt_output.mp4", help="Output MP4 file path")
    parser.add_argument("--seed", type=int, default=0, help="Random seed for micro-variation")
    parser.add_argument("--theme", type=str, default="light", choices=["light", "dark"], help="Visual theme")
    parser.add_argument("--sd", action="store_true", help="Render in 512x512 SD arena canvas (default is 1280x720 HD stage)")
    args = parser.parse_args()

    print(f"[*] Parsing prompt: '{args.prompt}'...")
    parsed = parse_prompt(args.prompt, seed=args.seed)
    print(f"[+] Detected Action: {parsed['action']} ({parsed['n_person']}P)")
    print(f"    - Duration:  {parsed['duration_seconds']:.2f}s")
    print(f"    - Direction: {parsed['direction']}")
    print(f"    - Speed:     {parsed['speed']}x")
    print(f"    - Amplitude: {parsed['amplitude']}x")

    action = parsed["action"]
    dur = parsed["duration_seconds"]
    speed = parsed["speed"]
    amp = parsed["amplitude"]
    direction = parsed["direction"]

    if action in ACTIONS_2P:
        feat = build_combat_pair(action, duration_s=dur, speed=speed, amplitude=amp, seed=args.seed)
    else:
        feat = build_motion_from_action(action, duration_s=dur, speed=speed, amplitude=amp, direction=direction, seed=args.seed)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.sd:
        print(f"[*] Rendering to 512x512 SD arena: {out_path}...")
        clip = {"feat": feat, "action": action, "n_person": parsed["n_person"], "duration_s": dur, "seed": args.seed}
        render_to_video(clip, str(out_path), fix_contact=False)
    else:
        print(f"[*] Rendering to 1280x720 HD puppet stage: {out_path}...")
        render_stage_video(feat, str(out_path), theme_name=args.theme, fix_contact=False)

    print(f"[SUCCESS] Video rendered to: {out_path.resolve()}")
    print(f"          Size: {out_path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
