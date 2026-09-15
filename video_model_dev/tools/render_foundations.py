"""Render script for the 3 core stickman foundation primitives:
1. Foundation 1: Standing (proportions, rest pose, grounded feet, subtle breathing)
2. Foundation 2: Squatting (torso balance, deep knee flexion, glued feet)
3. Foundation 3: One Step (weight transfer, knee lift, heel strike, settle)
"""

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

from src.puppet.choreography import (
    create_standing_sequence,
    create_squat_sequence,
    create_single_step_sequence,
)
from src.renderer import render_to_video, decode_motion_features, StickmanRenderer


def main():
    print("[*] Generating Foundation Primitive Deliverables...")
    renderer = StickmanRenderer(canvas_size=512)

    # -------------------------------------------------------------
    # 1. Foundation Primitive 1: Standing
    # -------------------------------------------------------------
    print("[1/3] Generating Foundation 1: Standing...")
    tl_stand = create_standing_sequence(start_x=0.0, duration_s=2.0)
    feat_stand = tl_stand.compile(total_duration_s=2.0)
    
    # Save video
    out_stand_mp4 = "out/foundation_1_standing.mp4"
    render_to_video(feat_stand, out_stand_mp4, fps=24, canvas_size=512, fix_contact=False, auto_camera=False)
    print(f"  [+] Saved {out_stand_mp4}")

    # Save still PNG frame
    joints_stand = decode_motion_features(feat_stand)
    img_stand = renderer.render_frame(joints_stand[0], camera_x=0.0)
    out_stand_png = "out/foundation_1_standing.png"
    img_stand.save(out_stand_png)
    print(f"  [+] Saved {out_stand_png}")

    # -------------------------------------------------------------
    # 2. Foundation Primitive 2: Squatting
    # -------------------------------------------------------------
    print("[2/3] Generating Foundation 2: Squatting...")
    tl_squat = create_squat_sequence(start_x=0.0, duration_s=2.5)
    feat_squat = tl_squat.compile(total_duration_s=2.5)
    
    out_squat_mp4 = "out/foundation_2_squat.mp4"
    render_to_video(feat_squat, out_squat_mp4, fps=24, canvas_size=512, fix_contact=False, auto_camera=False)
    print(f"  [+] Saved {out_squat_mp4}")

    # Save deep squat still PNG
    joints_squat = decode_motion_features(feat_squat)
    # Find frame with lowest pelvis
    squat_frame_idx = int(np.argmin(joints_squat[:, 0, 0, 1]))
    img_squat = renderer.render_frame(joints_squat[squat_frame_idx], camera_x=0.0)
    out_squat_png = "out/foundation_2_squat.png"
    img_squat.save(out_squat_png)
    print(f"  [+] Saved {out_squat_png}")

    # -------------------------------------------------------------
    # 3. Foundation Primitive 3: One Step
    # -------------------------------------------------------------
    print("[3/3] Generating Foundation 3: One Step...")
    tl_step = create_single_step_sequence(start_x=-0.15, step_foot="left", stride=0.32, duration_s=2.2)
    feat_step = tl_step.compile(total_duration_s=2.2)

    out_step_mp4 = "out/foundation_3_one_step.mp4"
    render_to_video(feat_step, out_step_mp4, fps=24, canvas_size=512, fix_contact=False, auto_camera=False)
    print(f"  [+] Saved {out_step_mp4}")

    # Save passing still PNG and heel strike still PNG
    joints_step = decode_motion_features(feat_step)
    # Frame at ~0.7s (passing) and ~1.1s (heel strike)
    pass_f = int(0.7 * 24)
    strike_f = int(1.1 * 24)
    img_pass = renderer.render_frame(joints_step[pass_f], camera_x=0.0)
    img_pass.save("out/foundation_3_step_pass.png")
    img_strike = renderer.render_frame(joints_step[strike_f], camera_x=0.0)
    img_strike.save("out/foundation_3_step_strike.png")
    print("  [+] Saved step keyframe images")

    print("[SUCCESS] All 3 foundation primitives rendered successfully!")


if __name__ == "__main__":
    main()
