"""Render the Smooth Stop-Motion Puppet Showcase Video (1280x720 HD @ 24fps).

Demonstrates:
1. Zero character vibration / zero shaking.
2. Natural pose-to-pose animation timing (anticipation, snappy attack, moving holds).
3. Smooth ease-in / ease-out transitions.
4. Rock-solid stance foot pinning with zero skating.
"""

import os
import sys
import subprocess

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from src.puppet.choreography import PuppetChoreographer
from src.rig import decode, forward_kinematics, FPS
from src.stage_renderer import StageRendererHD


def render_showcase(output_path: str = "out/smooth_stop_motion_showcase.mp4"):
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # 1. Build rich stop-motion choreography
    print("Building smooth stop-motion choreography timeline...")
    director = PuppetChoreographer(start_x=-0.8, fps=24)

    # Act 1: Relaxed stance with subtle breathing moving hold (1.0s)
    director.wait(duration_s=0.8)

    # Act 2: Confident walk forward (4 steps, ~2.0s)
    director.walk(steps=4, step_duration=0.48, stride_length=0.24, direction=1)

    # Act 3: Brief pause before action (0.4s)
    director.wait(duration_s=0.4)

    # Act 4: Snappy punch combination with snap-and-settle (1.2s)
    director.punch()

    # Act 5: Dynamic high kick strike (1.3s)
    director.kick()

    # Act 6: Explosive jump across stage (1.8s)
    director.jump(distance_x=0.40, height=0.42)

    # Act 7: Triumphant celebration cheer & hold (1.8s)
    director.celebrate()
    director.wait(duration_s=0.8)

    # Compile motion features
    feat = director.compile()
    T = len(feat)
    duration_s = T / 24.0
    print(f"Compiled {T} frames ({duration_s:.2f}s of motion). Decoding FK...")

    # Decode and forward kinematics
    root, angles = decode(feat)
    joints = forward_kinematics(root, angles)  # (T, 15, 2)
    # StageRendererHD expects (T, N_actors, 15, 2)
    scene_joints = joints[:, np.newaxis, :, :]

    # 2. Setup Stage Renderer (1280x720 HD, Light theme paper aesthetic)
    stage = StageRendererHD(width=1280, height=720, theme_name="light")

    # 3. Stream frames into ffmpeg
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1280x720",
        "-pix_fmt", "rgb24",
        "-r", "24",
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "18",
        output_path
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    print(f"Rendering {T} frames to {output_path} via ffmpeg pipe...")
    scenery = {"type": "plain"}
    for t in range(T):
        # Subtle camera follow smoothly centering actor
        cam_x = float(root[t, 0] * 0.4)
        img = stage.render_stage_frame(
            scene_joints[t],
            camera_x=cam_x,
            scenery=scenery,
            props=[]
        )
        proc.stdin.write(img.tobytes())

    proc.stdin.close()
    stderr_out, _ = proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {stderr_out.decode('utf-8', errors='ignore')}")

    size = os.path.getsize(output_path)
    print(f"Showcase generated successfully!")
    print(f"File: {output_path} | Size: {size:,} bytes | Frames: {T} ({duration_s:.2f}s @ 24fps)")
    return output_path


if __name__ == "__main__":
    render_showcase()
