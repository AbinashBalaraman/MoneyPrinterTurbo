"""Generates 1280x720 HD reproduction videos matching the visual quality and details of goal_videos/.

Produces:
1. out/reproduction_light_demo.mp4 (Perspective hall, speech bubble, gavel smash, rubble, cracks, "NOT A VERDICT").
2. out/reproduction_dark_demo.mp4 (Spline web, 3-panel split screen with envelope X, 3D red cage with kneeling prisoner).
"""

import os
import numpy as np

from .puppet.choreography import build_motion_from_action
from .rig import FPS, decode, forward_kinematics, encode
from .sequencer import blend_feature_clips
from .stage_renderer import render_stage_video, StageRendererHD
from .stage.theme import get_theme


def generate_light_demo_video(output_path: str = "out/reproduction_light_demo.mp4") -> str:
    """Generates the 10-second 1280x720 reproduction of light-theme-demo.mp4."""
    print("Generating Light Theme 720p Reproduction Video...")
    T = 240  # 10.0s @ 24fps
    
    # 1. Base puppet motions
    # Stickman A: holds speech bubble, walks forward, then raises hands defensively
    clip_idle = build_motion_from_action("idle", duration_s=3.0, seed=1)
    clip_block = build_motion_from_action("block", duration_s=4.0, amplitude=1.3, seed=2)
    clip_celebrate = build_motion_from_action("celebrate", duration_s=3.0, seed=3)
    
    feat_a = np.concatenate([clip_idle, clip_block, clip_celebrate], axis=0)[:T]
    
    # Custom hand positioning: bend arms forward to hold the speech bubble in first 72 frames
    r_a, a_a = decode(feat_a)
    # Joint 4/5 upperArm, 6/7 lowerArm
    # Make arms hold object in front
    a_a[:72, 4] = 1.3   # upperArmL
    a_a[:72, 5] = -1.1  # lowerArmL
    a_a[:72, 6] = -1.3  # upperArmR
    a_a[:72, 7] = 1.1   # lowerArmR
    
    feat_a = encode(r_a, a_a)
    joints_a = forward_kinematics(r_a, a_a)  # (T, 15, 2)

    # Stickman B (companion reaching forward in scene 1)
    clip_walk = build_motion_from_action("walk", duration_s=3.5, speed=0.8, direction=1, seed=10)
    r_b, a_b = decode(clip_walk)
    r_b[:, 0] -= 1.1  # Offset to the left
    # Reach both arms forward
    a_b[:, 4] = 1.2
    a_b[:, 6] = -1.2
    joints_b = forward_kinematics(r_b, a_b)  # (T_b, 15, 2)
    # Pad to T
    if len(joints_b) < T:
        pad = np.tile(joints_b[-1:], (T - len(joints_b), 1, 1))
        joints_b = np.concatenate([joints_b, pad], axis=0)

    # Combined 2-actor joints: (T, 2, 15, 2)
    joints_all = np.stack([joints_a, joints_b], axis=1)

    stage = StageRendererHD(width=1280, height=720, theme_name="light")
    
    import subprocess
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1280x720", "-pix_fmt", "rgb24", "-r", "24",
        "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "20", output_path
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for t in range(T):
            # Dynamic scene direction across 10 seconds:
            # 0..72 (0-3s): Scene 1 - Speech bubble dialog
            if t < 72:
                scenery = {"type": "plain"}
                # Speech bubble anchored to puppet A's hands
                props = [{
                    "kind": "speech_bubble",
                    "anchor_puppet": 0,
                    "offset_x": 70,
                    "offset_y": -50,
                    "w": 160,
                    "h": 95,
                    "tail": "bottom_left"
                }]
                text_overlay = None
                current_joints = joints_all[t]

            # 72..144 (3-6s): Scene 2 - Perspective Colonnade & Baroque Frame
            elif t < 144:
                scenery = {
                    "type": "perspective_hall",
                    "colonnade": True,
                    "baroque_frame": True
                }
                props = []
                text_overlay = None
                # Only Stickman A in center looking into frame
                current_joints = joints_all[t:t+1, 0:1][0]

            # 144..240 (6-10s): Scene 3 - Giant Gavel Smash & Destruction
            else:
                scenery = {
                    "type": "perspective_hall",
                    "colonnade": False,
                    "shattered_pillars": True,
                    "ground_cracks": True
                }
                # Animate gavel swinging down
                dt_gavel = min(1.0, (t - 144) / 14.0)
                gavel_y = 120 + dt_gavel * 260
                gavel_angle = -15.0 + dt_gavel * 45.0
                
                props = [
                    {
                        "kind": "gavel",
                        "x": 640,
                        "y": gavel_y,
                        "angle": gavel_angle,
                        "scale": 1.2
                    }
                ]
                # Red fluid splash appears after impact (t > 165)
                if t > 165:
                    props.append({
                        "kind": "red_fluid_splash",
                        "x": 700,
                        "y": 420,
                        "scale": 1.1
                    })
                
                # Kinetic typography appears
                text_overlay = {
                    "text": "NOT A VERDICT",
                    "x": 260,
                    "y": 420,
                    "font_size": 42
                }
                current_joints = joints_all[t:t+1, 0:1][0]

            img = stage.render_stage_frame(
                current_joints,
                camera_x=0.0,
                scenery=scenery,
                props=props,
                text_overlay=text_overlay
            )
            proc.stdin.write(img.tobytes())
            if (t + 1) % 48 == 0 or t == T - 1:
                print(f"  [Light Demo] Frame {t+1}/{T} rendered ({((t+1)/T)*100:.0f}%)", flush=True)

        proc.stdin.close()
        stderr_output, _ = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {stderr_output.decode('utf-8', errors='ignore')}")
        print(f"Light demo video created: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    except Exception:
        proc.kill()
        raise


def generate_dark_demo_video(output_path: str = "out/reproduction_dark_demo.mp4") -> str:
    """Generates the 10-second 1280x720 reproduction of dark-theme-demo.mp4."""
    print("Generating Dark Theme 720p Reproduction Video...")
    T = 240
    
    # Puppet: white stickman kneeling inside cage or crawling
    clip_squat = build_motion_from_action("squat", duration_s=4.0, amplitude=1.2, seed=5)
    clip_block = build_motion_from_action("block", duration_s=3.0, seed=6)
    clip_idle = build_motion_from_action("idle", duration_s=3.0, seed=7)
    
    feat = np.concatenate([clip_squat, clip_block, clip_idle], axis=0)[:T]
    r, a = decode(feat)
    
    # Arms holding head in distress (hands up to temples)
    a[144:, 4] = 1.8   # upperArmL
    a[144:, 5] = -2.2  # lowerArmL
    a[144:, 6] = -1.8  # upperArmR
    a[144:, 7] = 2.2   # lowerArmR
    
    joints = forward_kinematics(r, a)  # (T, 15, 2)
    joints = joints[:, np.newaxis, :, :]  # (T, 1, 15, 2)

    stage = StageRendererHD(width=1280, height=720, theme_name="dark")
    
    import subprocess
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1280x720", "-pix_fmt", "rgb24", "-r", "24",
        "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "20", output_path
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        for t in range(T):
            # 0..72 (0-3s): Scene 1 - Cosmic Glowing Spline Web & Thought Bubble
            if t < 72:
                scenery = {
                    "type": "spline_web",
                    "seed": 42,
                    "thought_bubble": True,
                    "show_face": True,
                    "face_emotion": "distress"
                }
                props = []
                text_overlay = None

            # 72..144 (3-6s): Scene 2 - 3-Panel Split Screen (Crowd pointing, Envelope X)
            elif t < 144:
                scenery = {
                    "type": "split_screen_3",
                    "show_face": True,
                    "face_emotion": "angry"
                }
                props = [
                    {
                        "kind": "envelope_x",
                        "x": 640,
                        "y": 360,
                        "w": 260,
                        "h": 170
                    }
                ]
                text_overlay = None

            # 144..240 (6-10s): Scene 3 - 3D Red Prison Cage & Kneeling Prisoner
            else:
                scenery = {
                    "type": "plain",
                    "prison_cage": True,
                    "show_face": True,
                    "face_emotion": "distress"
                }
                props = []
                text_overlay = None

            img = stage.render_stage_frame(
                joints[t],
                camera_x=0.0,
                scenery=scenery,
                props=props,
                text_overlay=text_overlay
            )
            proc.stdin.write(img.tobytes())
            if (t + 1) % 48 == 0 or t == T - 1:
                print(f"  [Dark Demo] Frame {t+1}/{T} rendered ({((t+1)/T)*100:.0f}%)", flush=True)

        proc.stdin.close()
        stderr_output, _ = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed with code {proc.returncode}: {stderr_output.decode('utf-8', errors='ignore')}")
        print(f"Dark demo video created: {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    except Exception:
        proc.kill()
        raise


if __name__ == "__main__":
    p_light = generate_light_demo_video("out/reproduction_light_demo.mp4")
    p_dark = generate_dark_demo_video("out/reproduction_dark_demo.mp4")
    print("=" * 60)
    print("Both 1280x720 goal reproduction videos successfully generated:")
    print(f"1. {p_light} ({os.path.getsize(p_light)} bytes)")
    print(f"2. {p_dark} ({os.path.getsize(p_dark)} bytes)")
    print("=" * 60)
