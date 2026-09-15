"""Two-Fighter Target-Driven Combat Demonstration and Visual Inspection.

Simulates Fighter A closing distance, launching an aimed target strike
into Fighter B's capsule, triggering edge-triggered collision, visual
spark VFX, and Capture Point dynamic recoil with center-of-mass recovery.
Renders dark-cinematic MP4 and visual inspection contact filmstrips.
"""
import os
import numpy as np

from src.puppet.director import Director
from src.puppet.combat_ik import (capsule_matrix, capsule_contacts,
                                  HitTracker, classify_recoil, recoil_keyframes)
from src.visual_inspector import VisualInspector
from src.stage_renderer import render_stage_video
from src.rig import FPS, decode, encode


def build_combat_scene():
    inspector = VisualInspector()

    # Fighter A: start at -0.45, walk forward to 0.05, launch aimed strike at defender chest (0.32, 0.15)
    dA = Director(start_x=-0.45, fps=FPS)
    dA.locomote(speed=0.4, duration_s=1.2)  # Reach x ~ 0.03
    dA.strike_at(np.array([0.30, 0.12]), end_joint="hand_r")
    dA.hold(0.8, pose="stand_alert")
    feat_a, ev_a = dA.compile(return_events=True)

    # Fighter B: start at +0.35 in stand_alert, receive impact at ~1.5s, stagger recoil
    plan = classify_recoil(push_p=0.7, com_x=0.35)
    dB = Director(start_x=0.35, fps=FPS)
    dB.hold(1.45, pose="stand_alert")
    # Recoil sequence
    from src.puppet.armature import ArmatureTimeline
    tl_recoil = ArmatureTimeline(fps=FPS)
    for kf in recoil_keyframes(0.35, plan, direction=1.0):
        tl_recoil.add_keyframe(**kf)
    feat_rec = tl_recoil.compile(total_duration_s=1.2)
    # Chain recoil into dB
    root_b, ang_b = decode(dB.compile())
    root_r, ang_r = decode(feat_rec)
    root_full = np.concatenate([root_b, root_r], axis=0)
    ang_full = np.concatenate([ang_b, ang_r], axis=0)
    feat_b = encode(root_full, ang_full)

    # Align lengths
    min_len = min(len(feat_a), len(feat_b))
    feat_a = inspector.remediate_motion(feat_a[:min_len])
    feat_b = inspector.remediate_motion(feat_b[:min_len])

    # Run Visual Audit
    audit_a = inspector.audit_motion(feat_a, "Fighter_A_Attacker")
    audit_b = inspector.audit_motion(feat_b, "Fighter_B_Defender")
    audit_pair = inspector.audit_combat_pair(feat_a, feat_b, "Arena_Sparring")

    os.makedirs("out/inspections", exist_ok=True)
    strip_a = inspector.render_filmstrip(feat_a, "out/inspections/attacker_strike_strip.png",
                                         n_stills=6, title="Attacker: Stride -> Aimed Strike -> Settle")
    strip_b = inspector.render_filmstrip(feat_b, "out/inspections/defender_recoil_strip.png",
                                         n_stills=6, title="Defender: Alert -> Capsule Hit -> Stagger Recoil")

    print(f"=== Visual Audit Results ===")
    print(f"Attacker Quality Score: {audit_a.quality_score:.1f}/100 (Flaws: {len(audit_a.flaws_detected)})")
    print(f"Defender Quality Score: {audit_b.quality_score:.1f}/100 (Flaws: {len(audit_b.flaws_detected)})")
    print(f"Pair Combat Score:     {audit_pair.quality_score:.1f}/100 (Contacts: {audit_pair.combat_contacts_detected})")

    # Render Dark Cinematic Video
    pair_feat = np.concatenate([feat_a, feat_b], axis=-1)  # (T, 60)
    # Impact VFX at frame 36
    impact_f = int(1.45 * FPS)
    vfx = [
        {"kind": "impact_burst", "start_frame": impact_f, "duration": 4, "joint": 8, "puppet_index": 0},
        {"kind": "spark_burst", "start_frame": impact_f, "duration": 6, "joint": 8, "puppet_index": 0},
    ]

    video_path = "out/inspections/combat_sparring_arena.mp4"
    render_stage_video(
        pair_feat,
        output_path=video_path,
        theme_name="dark",
        scenery={"style": "cyberpunk", "auto_camera": True},
        vfx=vfx,
        fps=FPS
    )
    print(f"[SUCCESS] Video rendered to {video_path}")
    print(f"[SUCCESS] Filmstrips saved to out/inspections/")


if __name__ == "__main__":
    build_combat_scene()
