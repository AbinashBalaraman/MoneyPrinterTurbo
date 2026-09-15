"""Gate G1: a held-out paragraph/script renders to a playable mp4.

Exercises the full pipeline: parse_script -> compile_scene -> render_to_video.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.scene import parse_script, compile_scene
from src.renderer import render_to_video


def main():
    prompt = ("a stickman walks forward slowly, then punches hard, "
              "then celebrates victory")
    out = ROOT / "out" / "gate_e2e.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    script = parse_script(prompt, seed=3)
    timeline = compile_scene(script)
    print(f"[+] beats: {[b.action for b in script.beats]}"
          f" {len({b.actor for b in script.beats})} actor(s)")
    clip = {"feat": timeline["feat"], "action": "scene",
            "n_person": timeline["n_person"],
            "duration_s": timeline["duration_seconds"], "seed": 3}
    render_to_video(clip, str(out), fix_contact=False,
                    vfx_events=timeline.get("vfx_events", []))
    size = out.stat().st_size
    print(f"rendered: {out.relative_to(ROOT)} ({size} bytes)")
    if size < 1000:
        print("G1 FAILED: output suspiciously small")
        sys.exit(1)
    print("G1: rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())