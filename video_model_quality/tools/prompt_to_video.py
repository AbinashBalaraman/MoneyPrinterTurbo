"""User CLI: Text/Scene-to-Stickman-Video generator.

Usage:
    python tools/prompt_to_video.py "walk forward, then punch, then celebrate" -o out/x.mp4
    python tools/prompt_to_video.py "two stickmen punch and block for 3s" --sd
    python tools/prompt_to_video.py --scene out/scene.json -o out/x.mp4   # LLM/author plan

Division of labour (locked architecture):
  - An LLM (or human) owns the *world*. Emit SceneScript JSON and pass it with
    --scene; any planner backend can write that file. See src/planner.py.
  - Without --scene, a deterministic keyword planner compiles simple prompts.
The engine only ever *executes* a validated plan — it never invents a world.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.parser import parse_prompt
from src.catalog import ACTIONS_1P, ACTIONS_2P
from src.puppet.choreography import build_motion_from_action, build_combat_pair
from src.stage_renderer import render_stage_video
from src.renderer import render_to_video
from src.planner import plan_scene, DeterministicPlanner


def _render(timeline, out_path, args):
    """Render a compiled scene timeline to SD or HD, wiring props/camera/impacts."""
    feat = timeline["feat"]
    vfx_events = timeline.get("vfx_events", [])
    dur = timeline["duration_seconds"]
    prop_tracks = timeline.get("prop_tracks")
    cam = timeline.get("camera_track")
    impacts = timeline.get("impacts")
    scenery = timeline.get("scenery") or {"type": "plain", "auto_camera": True}
    theme = args.theme or timeline.get("theme", "light")

    if args.sd:
        print(f"[*] Rendering to 512x512 SD arena: {out_path}...")
        clip = {"feat": feat, "action": "scene",
                "n_person": timeline["n_person"], "duration_s": dur, "seed": args.seed}
        render_to_video(clip, str(out_path), fix_contact=False, vfx_events=vfx_events,
                        prop_tracks=prop_tracks, camera_track=cam, impacts=impacts)
    else:
        print(f"[*] Rendering to 1280x720 HD puppet stage: {out_path}...")
        render_stage_video(feat, str(out_path), theme_name=theme, scenery=scenery,
                           fix_contact=False, vfx=vfx_events, prop_tracks=prop_tracks,
                           camera_track=cam, impacts=impacts)


def main():
    parser = argparse.ArgumentParser(description="Text/Scene-to-Stickman-Video Generator")
    parser.add_argument("prompt", nargs="?", default="", type=str,
                        help="Text prompt describing the desired action(s)")
    parser.add_argument("-o", "--output", type=str, default="out/prompt_output.mp4",
                        help="Output MP4 file path")
    parser.add_argument("--scene", type=str, default=None,
                        help="Path to a SceneScript JSON file (LLM/author plan)")
    parser.add_argument("--seed", type=int, default=0, help="Seed for micro-variation")
    parser.add_argument("--theme", type=str, default=None, choices=["light", "dark"],
                        help="Visual theme (default: scene theme or light)")
    parser.add_argument("--sd", action="store_true",
                        help="Render 512x512 SD arena (default is 1280x720 HD stage)")
    parser.add_argument("--force", action="store_true",
                        help="Force rendering even if SceneDoctor detected hard defects.")
    parser.add_argument("--allow", type=str, default=None,
                        help="Comma-separated defect codes to excuse, e.g. "
                             "--allow foot_slide,jerk_spike. Codes: jerk_spike, "
                             "foot_slide, dead_hold, linear_easing, missing_anticipation.")
    parser.add_argument("--strict-timing", action="store_true",
                        help="Also block on timing debt (linear_easing, "
                             "missing_anticipation). Off by default: timing debt is "
                             "reported as advisory while Phase-2 timing work is in flight.")
    parser.add_argument("--review", action="store_true",
                        help="Pre-render text review: print a text digest of the scene "
                             "and STOP before rendering (no mp4).")
    parser.add_argument("--review-mode", type=str, default="skeleton",
                        choices=["skeleton", "half", "braille", "ascii"],
                        help="Text style for --review (default: skeleton stick figures).")
    parser.add_argument("--review-cols", type=int, default=80, help="Text width in columns.")
    parser.add_argument("--review-sample", type=int, default=10,
                        help="Key frames shown in the digest (token-bounded).")
    parser.add_argument("--review-full", action="store_true",
                        help="Also write the full per-frame animation to out/<name>_anim.txt.")
    args = parser.parse_args()

    if not args.prompt and not args.scene:
        parser.error("provide a prompt or --scene <file.json>")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _run_doctor_gate(timeline, scene_dict=None):
        """Run SceneDoctor on timeline. Block render if hard defects and not force."""
        from src.doctor import diagnose, format_report
        report = diagnose(timeline, scene=scene_dict, strict=True,
                          strict_timing=args.strict_timing, allow=args.allow)
        timing = report.get("timing") or []
        if not report["passed"]:
            print(format_report(report))
            if args.force:
                print("[!] WARNING: Hard defects detected, but --force was specified. Proceeding with render.")
                return True
            print("[ERROR] Render blocked by SceneDoctor due to hard defects.")
            print("        Fix them, or excuse a specific check with --allow <code>")
            print("        (or bypass everything with --force).")
            return False
        if timing:
            # Non-blocking, but never silent: timing debt is the Phase-2 queue.
            print(format_report(report))
            print(f"[!] {len(timing)} timing-debt item(s) reported (advisory). "
                  f"Use --strict-timing to block on these.")
        return True

    def _maybe_review(timeline, scene_dict=None):
        """Pre-render text review gate. Returns True if we stopped (no video)."""
        if not args.review:
            return False
        # Lazy import: keeps the render path free of the preview/PIL dependency.
        from src.preview import render_timeline_preview
        # Make the scene available so the SceneDoctor interaction check runs
        # (without it the doctor cannot know an interaction was declared).
        if scene_dict is not None:
            timeline.setdefault("scene_dict", scene_dict)
        r = render_timeline_preview(
            timeline, cols=args.review_cols,
            mode="half" if args.review_mode == "skeleton" else args.review_mode,
            sample=args.review_sample, out_dir=str(out_path.parent),
            name=out_path.stem, write_animation=args.review_full)
        digest = r["digest"]
        # Print safely on any console encoding (Windows cp1252 etc.).
        try:
            print(digest)
        except UnicodeEncodeError:
            print(digest.encode("ascii", "replace").decode("ascii"))
        if r.get("animation_path"):
            print(f"[+] Full text animation written: {r['animation_path']}")
        print("[REVIEW ONLY] No video rendered (remove --review to render).")
        return True

    # ---- Path A: an explicit world plan (LLM / author / MCP). ------------- #
    if args.scene:
        scene = json.loads(Path(args.scene).read_text(encoding="utf-8"))
        from src.scene import compile_scene_dict
        print(f"[*] Compiling scene script: {args.scene}")
        timeline = compile_scene_dict(scene)
        print(f"[+] Scene '{timeline.get('title')}': {timeline['n_person']} actor(s), "
              f"{timeline['T']} frames, {len(timeline.get('prop_tracks') or [])} prop-track frames")
        if _maybe_review(timeline, scene_dict=scene):
            return 0
        if not _run_doctor_gate(timeline, scene_dict=scene):
            return 1
        _render(timeline, out_path, args)
        print(f"[SUCCESS] Video rendered to: {out_path.resolve()}")
        print(f"          Size: {out_path.stat().st_size} bytes")
        return 0

    # ---- Path B: deterministic keyword planning. ------------------------- #
    print(f"[*] Parsing prompt: '{args.prompt}'...")
    # Single unambiguous action (incl. dedicated paired combat) -> optimized path.
    parsed = None
    try:
        parsed = parse_prompt(args.prompt, seed=args.seed)
    except ValueError:
        parsed = None

    if parsed is not None:
        action = parsed["action"]
        dur = parsed["duration_seconds"]
        print(f"[+] Detected Action: {action} ({parsed['n_person']}P)")
        if action in ACTIONS_2P:
            feat = build_combat_pair(action, duration_s=dur, speed=parsed["speed"],
                                     amplitude=parsed["amplitude"], seed=args.seed)
        else:
            feat = build_motion_from_action(action, duration_s=dur, speed=parsed["speed"],
                                            amplitude=parsed["amplitude"],
                                            direction=parsed["direction"], seed=args.seed)
        timeline = {"feat": feat, "n_person": parsed["n_person"], "duration_seconds": dur,
                    "vfx_events": [], "theme": args.theme or "light"}
        scene_dict = None
    else:
        # Ordered multi-action scene via the deterministic planner.
        scene = plan_scene(args.prompt, backend=DeterministicPlanner())
        from src.scene import compile_scene_dict
        timeline = compile_scene_dict(scene)
        print(f"[+] Scene plan: {len(scene.get('beats', []))} beats across "
              f"{timeline['n_person']} actor(s)")
        scene_dict = scene

    if _maybe_review(timeline):
        return 0
    if not _run_doctor_gate(timeline, scene_dict=scene_dict):
        return 1
    _render(timeline, out_path, args)
    print(f"[SUCCESS] Video rendered to: {out_path.resolve()}")
    print(f"          Size: {out_path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
