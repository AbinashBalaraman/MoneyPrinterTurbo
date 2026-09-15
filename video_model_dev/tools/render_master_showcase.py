"""Master Showcase Video Generator — Smooth Stop-Motion Puppet Platform.

Demonstrates:
1. 2.5D Vector Puppet with depth shading and anti-tearing joint caps.
2. Adaptive stop-motion cadence: walks/holds on twos (12fps), strikes/jumps on ones (24fps).
3. Zero-drift stance pinning via analytical Two-Bone IK (< 1e-7 drift).
4. Modular joint-locked weapons & props (sword, shield) rotating with character limbs.
5. Procedural vector VFX (impact spark bursts, ground landing dust puffs, speed lines).
6. Synchronized 2-person martial arts combat choreography (kick dodge, punch block clash, knockdown & getup).
"""

import os
import numpy as np

from src.puppet.armature import ArmatureTimeline, Keyframe
from src.puppet.choreography import _mirror_pose_angles, build_combat_pair
from src.stage_renderer import render_stage_video
from src.renderer import FPS


def generate_master_showcase(output_path: str = "out/puppet_platform_master_showcase.mp4") -> str:
    print("Compiling Master Showcase choreography...")

    # -------------------------------------------------------------
    # ROUND 1: Stance & Advance (2.5s / 60 frames)
    # -------------------------------------------------------------
    # Both fighters enter and advance on TWOS (cadence=2)
    tl_a1 = ArmatureTimeline(fps=FPS, cadence=2)
    tl_a1.add_keyframe(t=0.0, pose="stand_relaxed", root_x=-0.55, hold_duration_s=0.6, stance_lock="both_feet", moving_hold=True, cadence=2)
    tl_a1.add_keyframe(t=0.9, pose="stride_contact_L", root_x=-0.46, stance_lock="left_foot", cadence=2)
    tl_a1.add_keyframe(t=1.4, pose="stride_pass_L", root_x=-0.38, cadence=2)
    tl_a1.add_keyframe(t=1.9, pose="stride_contact_R", root_x=-0.30, stance_lock="right_foot", cadence=2)
    tl_a1.add_keyframe(t=2.3, pose="stand_relaxed", root_x=-0.30, hold_duration_s=0.2, stance_lock="both_feet", cadence=2)

    tl_b1 = ArmatureTimeline(fps=FPS, cadence=2)
    tl_b1.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=0.55, hold_duration_s=0.8, stance_lock="both_feet", moving_hold=True, cadence=2)
    tl_b1.add_keyframe(t=1.3, pose=_mirror_pose_angles("stride_contact_L"), root_x=0.48, stance_lock="right_foot", cadence=2)
    tl_b1.add_keyframe(t=1.8, pose=_mirror_pose_angles("guard_high"), root_x=0.42, hold_duration_s=0.7, stance_lock="both_feet", cadence=2)

    fa1 = tl_a1.compile(total_duration_s=2.5)
    fb1 = tl_b1.compile(total_duration_s=2.5)
    round1 = np.concatenate([fa1, fb1], axis=-1)

    # -------------------------------------------------------------
    # ROUND 2: Snappy Sword Strike & Shield Block Clash (2.5s)
    # -------------------------------------------------------------
    round2 = build_combat_pair("punch_block", duration_s=2.5, speed=1.0)

    # -------------------------------------------------------------
    # ROUND 3: High Acrobatic Kick & Duck Dodge (2.5s)
    # -------------------------------------------------------------
    round3 = build_combat_pair("kick_dodge", duration_s=2.5, speed=1.0)

    # -------------------------------------------------------------
    # ROUND 4: Heavy Knockdown & Prone Recovery (3.2s)
    # -------------------------------------------------------------
    round4 = build_combat_pair("knockdown_getup", duration_s=3.2, speed=1.0)

    # -------------------------------------------------------------
    # ROUND 5: Victory Cheer & Respect Stance (2.0s)
    # -------------------------------------------------------------
    tl_a5 = ArmatureTimeline(fps=FPS, cadence=1)
    tl_a5.add_keyframe(t=0.0, pose="stand_relaxed", root_x=-0.35, hold_duration_s=0.2)
    tl_a5.add_keyframe(t=0.5, pose="celebrate_cheer", root_x=-0.35, hold_duration_s=1.5, easing="snap_and_settle")

    tl_b5 = ArmatureTimeline(fps=FPS, cadence=2)
    tl_b5.add_keyframe(t=0.0, pose=_mirror_pose_angles("stand_relaxed"), root_x=0.45, hold_duration_s=2.0, moving_hold=True, cadence=2)

    fa5 = tl_a5.compile(total_duration_s=2.0)
    fb5 = tl_b5.compile(total_duration_s=2.0)
    round5 = np.concatenate([fa5, fb5], axis=-1)

    # Concatenate all 5 rounds
    feat_master = np.concatenate([round1, round2, round3, round4, round5], axis=0)
    T_total = len(feat_master)
    print(f"Total Master Showcase frames: {T_total} ({T_total / FPS:.2f}s at {FPS} FPS)")

    # -------------------------------------------------------------
    # Props & Procedural Vector VFX Keyframing
    # -------------------------------------------------------------
    len_r1 = len(round1)
    len_r2 = len(round2)
    len_r3 = len(round3)
    len_r4 = len(round4)

    props = [
        # Person 0 (Fighter 1) holds sword
        {"kind": "sword", "anchor_puppet": 0, "joint": 8, "scale": 1.05},
        # Person 1 (Fighter 2) holds defensive buckler shield
        {"kind": "shield", "anchor_puppet": 1, "joint": 6, "scale": 1.1}
    ]

    vfx = [
        # Round 2: Punch & Block Clash (frame ~16 in round 2)
        {"kind": "speed_lines", "frame": len_r1 + 13, "anchor_puppet": 0, "anchor_joint": 0, "direction": 1, "scale": 1.2},
        {"kind": "impact_burst", "frame": len_r1 + 15, "anchor_puppet": 0, "anchor_joint": 8, "scale": 1.4, "color": (255, 230, 60)},
        {"kind": "impact_burst", "frame": len_r1 + 16, "anchor_puppet": 0, "anchor_joint": 8, "scale": 0.9, "color": (255, 255, 200)},

        # Round 3: High Kick & Dodge
        {"kind": "speed_lines", "frame": len_r1 + len_r2 + 15, "anchor_puppet": 0, "anchor_joint": 10, "direction": 1, "scale": 1.3},
        {"kind": "dust_puff", "frame": len_r1 + len_r2 + 27, "anchor_puppet": 0, "anchor_joint": 10, "scale": 1.2},
        {"kind": "dust_puff", "frame": len_r1 + len_r2 + 28, "anchor_puppet": 0, "anchor_joint": 10, "scale": 1.5},

        # Round 4: Heavy Knockdown Impact & Floor Dust
        {"kind": "impact_burst", "frame": len_r1 + len_r2 + len_r3 + 14, "anchor_puppet": 0, "anchor_joint": 8, "scale": 1.6, "color": (255, 70, 30)},
        {"kind": "dust_puff", "frame": len_r1 + len_r2 + len_r3 + 28, "anchor_puppet": 1, "anchor_joint": 0, "scale": 1.8},
        {"kind": "dust_puff", "frame": len_r1 + len_r2 + len_r3 + 29, "anchor_puppet": 1, "anchor_joint": 0, "scale": 1.4}
    ]

    scenery = {
        "type": "plain",
        "show_face": True,
        "face_emotion": "neutral",
        "auto_camera": False
    }

    text_overlay = {
        "text": "SMOOTH STOP-MOTION PUPPET PLATFORM",
        "x": 640,
        "y": 90,
        "font_size": 28
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    out = render_stage_video(
        feat_or_joints=feat_master,
        output_path=output_path,
        theme_name="dark",
        scenery=scenery,
        props=props,
        text_overlay=text_overlay,
        vfx=vfx,
        fps=FPS,
        width=1280,
        height=720
    )
    print(f"Master Showcase rendered successfully to: {out}")
    return out


if __name__ == "__main__":
    generate_master_showcase()
