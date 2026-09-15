"""Multi-scene suite runner and generalization verification tool.

Runs all scene definitions under out/scenes/ through the full pipeline:
validate -> compile -> doctor -> review -> optional render.
Produces the 'proof it generalises' deliverable table.
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Any, Dict, List

# Ensure project root is in sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.contract import validate_scene
from src.scene import compile_scene_dict
from src.doctor import diagnose, format_report
from src.preview import render_timeline_preview, interaction_stats
from src.renderer import decode_motion_features
from src.stage_renderer import render_stage_video


def run_scene_suite(
    scenes_dir: str = "out/scenes",
    render_count: int = 3,
    output_dir: str = "out/scenes"
) -> List[Dict[str, Any]]:
    """Runs all scene JSONs through the engine and returns results."""
    scenes_path = Path(scenes_dir)
    json_files = sorted([f for f in scenes_path.glob("*.json")])

    if not json_files:
        print(f"No scene JSON files found in {scenes_dir}")
        return []

    results = []
    print(f"Running Multi-Scene Suite on {len(json_files)} scenes...\n")

    rendered_so_far = 0

    for idx, jf in enumerate(json_files):
        scene_name = jf.stem
        print(f"[{idx+1}/{len(json_files)}] Testing scene: {jf.name}")
        with open(jf, "r", encoding="utf-8") as f:
            raw_scene = json.load(f)

        # 1. Validate
        try:
            validated, val_warnings = validate_scene(raw_scene)
            val_ok = True
            val_err = ""
        except Exception as e:
            val_ok = False
            val_err = str(e)
            validated = raw_scene
            val_warnings = []

        if not val_ok:
            print(f"  [VALIDATE FAILED] {val_err}")
            results.append({
                "name": scene_name,
                "file": jf.name,
                "title": raw_scene.get("title", scene_name),
                "valid": False,
                "compiled": False,
                "passed": False,
                "hard_defects": [f"validation_error: {val_err}"],
                "warnings": val_warnings,
                "frames": 0,
                "actors": len(raw_scene.get("characters", [])),
                "rendered_mp4": None,
            })
            continue

        # 2. Compile
        try:
            timeline = compile_scene_dict(validated)
            comp_ok = True
            comp_err = ""
        except Exception as e:
            comp_ok = False
            comp_err = str(e)
            timeline = {}

        if not comp_ok:
            print(f"  [COMPILE FAILED] {comp_err}")
            results.append({
                "name": scene_name,
                "file": jf.name,
                "title": validated.get("title", scene_name),
                "valid": True,
                "compiled": False,
                "passed": False,
                "hard_defects": [f"compile_error: {comp_err}"],
                "warnings": val_warnings,
                "frames": 0,
                "actors": len(validated.get("characters", [])),
                "rendered_mp4": None,
            })
            continue

        # 3. Doctor Gate
        diagnosis = diagnose(timeline, scene=validated)
        doctor_status = "PASSED" if diagnosis["passed"] else "BLOCKED"
        hard_codes = [h["code"] for h in diagnosis["hard"]]
        warn_codes = [w["code"] for w in diagnosis["warn"]]

        T = int(timeline.get("T", 0))
        n_person = int(timeline.get("n_person", 1))

        # 4. Optional Render to MP4
        rendered_file = None
        should_render = (rendered_so_far < render_count) and diagnosis["passed"]

        if should_render:
            out_mp4 = Path(output_dir) / f"{scene_name}.mp4"
            print(f"  Rendering MP4 ({T} frames, {n_person} actors) -> {out_mp4}...")
            try:
                render_stage_video(
                    feat_or_joints=timeline["feat"],
                    output_path=str(out_mp4),
                    theme_name=timeline.get("theme", "light"),
                    scenery=timeline.get("scenery"),
                    prop_tracks=timeline.get("prop_tracks"),
                    vfx=timeline.get("vfx_events"),
                    fps=timeline.get("fps", 24),
                    fix_contact=False,
                    camera_track=timeline.get("camera_track"),
                    impacts=timeline.get("impacts")
                )
                rendered_file = str(out_mp4.relative_to(Path.cwd()) if out_mp4.is_relative_to(Path.cwd()) else out_mp4)
                rendered_so_far += 1
                print(f"  [RENDER COMPLETE] -> {rendered_file}")
            except Exception as e:
                print(f"  [RENDER FAILED] {e}")

        res = {
            "name": scene_name,
            "file": jf.name,
            "title": validated.get("title", scene_name),
            "valid": True,
            "compiled": True,
            "passed": diagnosis["passed"],
            "doctor_status": doctor_status,
            "hard_defects": hard_codes,
            "warnings": warn_codes,
            "frames": T,
            "duration_s": round(T / max(1, timeline.get("fps", 24)), 2),
            "actors": n_person,
            "rendered_mp4": rendered_file,
        }
        results.append(res)
        status_sym = "[OK]" if diagnosis["passed"] else "[FAIL]"
        print(f"  {status_sym} Doctor: {doctor_status} | Hard: {hard_codes or 'None'} | Warn: {warn_codes or 'None'}\n")

    return results


def print_and_save_summary(results: List[Dict[str, Any]], save_path: str = "docs/scene_suite_results.md"):
    """Format results into a markdown table and save."""
    lines = [
        "# Multi-Scene Suite Verification Table",
        "",
        "| Scene File | Title | Actors | Frames | Duration | SceneDoctor | Hard Defects | Warnings | Rendered MP4 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in results:
        title = r["title"][:28]
        actors = r["actors"]
        frames = r["frames"]
        dur = f"{r.get('duration_s', 0)}s"
        doc = "**PASSED**" if r["passed"] else "<span style='color:red'>BLOCKED</span>"
        hard = ", ".join(r["hard_defects"]) if r["hard_defects"] else "None"
        warns = ", ".join(r["warnings"]) if r["warnings"] else "None"
        mp4 = f"`{r['rendered_mp4']}`" if r.get("rendered_mp4") else "—"
        lines.append(f"| `{r['file']}` | {title} | {actors} | {frames} | {dur} | {doc} | {hard} | {warns} | {mp4} |")

    table_text = "\n".join(lines)
    print("\n" + "=" * 80)
    print(table_text)
    print("=" * 80 + "\n")

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "w", encoding="utf-8") as f:
        f.write(table_text + "\n")
    print(f"Results written to {save_path}")


if __name__ == "__main__":
    count = 4
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
        except ValueError:
            count = 4
    results = run_scene_suite(render_count=count)
    print_and_save_summary(results)
