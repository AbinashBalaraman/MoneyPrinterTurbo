"""The Great Heist — Cartoon Animation Studio Proof Scene.

Demonstrates all Phase 1-4 capabilities:
1. Declarative SceneScript JSON compiled via compile_scene().
2. 16-Decal Facial Expression Engine (focused -> shocked -> dead, suspicious -> effort -> wink).
3. Joint-socketed katana (hand_r) and world-anchored props (office desk and cyber laptop).
4. Synchronized multi-actor combat interaction (infiltrator strikes hacker into knockdown).
5. Procedural 8-point geometric anime starburst VFX and camera impulse hit-shake.
6. SceneDoctor defect gate audit (pre-render validation ensuring 0 hard defects).
7. High-definition 720p H.264 video rendering via stage_renderer.
"""

import os
import sys

# Ensure repo root is on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import numpy as np

from src.contract import validate_scene
from src.scene import SceneScript, compile_scene
from src.doctor import diagnose, format_report
from src.stage_renderer import render_stage_video
from src.renderer import FPS


def build_heist_scene() -> dict:
    """Builds the SceneScript JSON dictionary for The Great Heist."""
    scene = {
        "title": "The Great Heist: Cyber Infiltration",
        "fps": 24,
        "theme": "dark",
        "scenery": {
            "type": "plain",
            "show_face": True,
            "auto_camera": True,
        },
        "camera": {
            "mode": "auto",
            "zoom": 1.1,
            "follow": True,
        },
        "characters": [
            {
                "id": "hacker",
                "start_x": -0.30,
                "facing": 1,
                "role": "hacker",
                "expression": "focused",
            },
            {
                "id": "infiltrator",
                "start_x": 0.85,
                "facing": -1,
                "role": "infiltrator",
                "expression": "suspicious",
            },
        ],
        "objects": [
            {
                "id": "office_desk",
                "kind": "desk",
                "at": [-0.30, -0.42],
            },
            {
                "id": "cyber_laptop",
                "kind": "laptop",
                "at": [-0.30, -0.27],
            },
            {
                "id": "katana",
                "kind": "sword",
                "attach": {
                    "actor": "infiltrator",
                    "joint": "hand_r",
                    "from_frame": 0,
                    "to_frame": -1,
                },
            },
        ],
        "beats": [
            # Beat 1: Hacker typing intently at workstation (2.0s)
            {
                "actor": "hacker",
                "action": "squat",
                "duration_s": 2.0,
                "direction": 1,
                "speed": 0.8,
                "expression": "focused",
            },
            # Beat 2: Infiltrator sneaks in from shadows with drawn katana (2.0s)
            {
                "actor": "infiltrator",
                "action": "walk",
                "duration_s": 2.0,
                "direction": -1,
                "speed": 0.9,
                "expression": "suspicious",
            },
            # Beat 3: Synchronized Strike & Knockdown!
            # Infiltrator strikes hacker; hacker reacts with shocked expression & knockdown (2.5s)
            {
                "actor": "infiltrator",
                "action": "punch",
                "target": "hacker",
                "interaction": "knockdown",
                "duration_s": 2.5,
                "speed": 1.1,
                "expression": "effort",
            },
            # Beat 4: Infiltrator poses victoriously with katana, hacker is KO'd on floor (2.0s)
            {
                "actor": "infiltrator",
                "action": "celebrate",
                "duration_s": 2.0,
                "speed": 1.0,
                "expression": "wink",
            },
        ],
    }
    return scene


def run_heist_pipeline(output_mp4: str = "out/the_great_heist.mp4"):
    print("=" * 65)
    print("  STAGE 1: Validating SceneScript Contract...")
    print("=" * 65)
    raw_scene = build_heist_scene()
    validated_scene, val_rep = validate_scene(raw_scene)
    print(f"Contract Validation: OK (Warnings: {len(val_rep['warnings'])})")
    for w in val_rep["warnings"]:
        print(f"  [WARN] {w}")

    print("\n" + "=" * 65)
    print("  STAGE 2: Compiling SceneScript to Deterministic Timeline...")
    print("=" * 65)
    script = SceneScript.from_dict(validated_scene)
    timeline = compile_scene(script)
    print(f"Compilation finished:")
    print(f"  Total frames: {timeline['T']} ({timeline['duration_seconds']:.2f}s @ {timeline['fps']} FPS)")
    print(f"  Actors: {timeline['characters']}")
    print(f"  VFX Events: {len(timeline.get('vfx_events', []))}")
    print(f"  Interactions: {len(timeline.get('interactions', []))}")

    # Set hacker expression to shocked/dead during and after the knockdown
    if "actor_expression_tracks" in timeline:
        expr_tracks = timeline["actor_expression_tracks"]
        kd_frame = int(2.0 * FPS) # start of beat 3
        for t in range(kd_frame, len(expr_tracks)):
            if t < kd_frame + int(0.7 * FPS):
                expr_tracks[t][0] = "shocked"
            elif t < kd_frame + int(1.4 * FPS):
                expr_tracks[t][0] = "despair"
            else:
                expr_tracks[t][0] = "dead"

    print("\n" + "=" * 65)
    print("  STAGE 3: SceneDoctor Quality & Defect Gate Audit...")
    print("=" * 65)
    doctor_rep = diagnose(timeline, scene=validated_scene, strict=True, allow=["dead_hold", "foot_slide"])
    report_text = format_report(doctor_rep)
    print(report_text)

    if not doctor_rep["passed"]:
        print("\n[ERROR] SceneDoctor detected HARD defects! Aborting render.")
        sys.exit(1)
    print("\n[PASS] SceneDoctor gate passed! All pre-render checks green.")

    print("\n" + "=" * 65)
    print("  STAGE 4: Rendering High-Definition 720p Video...")
    print("=" * 65)
    os.makedirs(os.path.dirname(output_mp4), exist_ok=True)

    text_overlay = {
        "text": "THE GREAT HEIST",
        "x": 640,
        "y": 80,
        "font_size": 32,
    }

    vfx = list(timeline.get("vfx_events", []))
    # Add starburst impact at the strike frame
    strike_frame = int(3.5 * FPS)
    vfx.append({
        "kind": "starburst",
        "frame": strike_frame,
        "x": -0.15,
        "y": -0.15,
        "scale": 1.4,
        "cam_impulse": 0.035,
    })

    out = render_stage_video(
        feat_or_joints=timeline,
        output_path=output_mp4,
        theme_name=timeline.get("theme", "dark"),
        scenery=timeline.get("scenery"),
        prop_tracks=timeline.get("prop_tracks"),
        camera_track=timeline.get("camera_track"),
        vfx=vfx,
        text_overlay=text_overlay,
        fps=timeline.get("fps", FPS),
        width=1280,
        height=720,
    )
    print(f"\n[DONE] 'The Great Heist' rendered successfully to:\n  {os.path.abspath(out)}")
    return out


if __name__ == "__main__":
    run_heist_pipeline()
