"""Interactive Terminal / ASCII Stage Player.

Allows developers and LLMs to watch stickman puppet animations directly
inside the console or terminal window as symbolic ASCII text frames at 24/12 fps.

Usage:
    python tools/play_terminal_ascii.py --prompt "stickman walk right for 3s"
    python tools/play_terminal_ascii.py --demo light
    python tools/play_terminal_ascii.py --demo dark
    python tools/play_terminal_ascii.py --action punch_block --duration 3.0
"""

import argparse
import json
import os
import sys
import time
import numpy as np

# Ensure root directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data_gen import gen_single, gen_pair, ACTIONS_1P, ACTIONS_2P
from src.parser import parse_prompt
from src.rig import decode, forward_kinematics
from src.stage.dsl import compile_scene_puppets, parse_stage_script
from src.stage.terminal_preview import TerminalStagePreview


def clear_console():
    """Fast console clear using ANSI escape sequences or OS fallback."""
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()


def play_frames(frames_text: list[str], fps: float = 12.0, loop: bool = False):
    """Plays an array of ASCII frame strings in the terminal at target FPS."""
    delay = 1.0 / max(1.0, fps)
    try:
        while True:
            for t, frame in enumerate(frames_text):
                clear_console()
                sys.stdout.write(frame + "\n")
                sys.stdout.flush()
                time.sleep(delay)
            if not loop:
                break
    except KeyboardInterrupt:
        pass


def build_demo_light() -> tuple[list[np.ndarray], list[dict], list[list[dict]], list[dict]]:
    """Builds frames and metadata for the Light Theme Demo in ASCII."""
    # 3 scenes: 3s dialog (72f), 3s colonnade (72f), 4s gavel & verdict (96f)
    preview = TerminalStagePreview(cols=80, rows=24)
    all_frames = []

    # Scene 1: Speech bubble dialog
    f1 = gen_single("idle", duration_s=3.0)["feat"]
    r1, a1 = decode(f1)
    a1[:, 4] = 1.3
    a1[:, 5] = -1.1
    a1[:, 6] = -1.3
    a1[:, 7] = 1.1
    j1 = forward_kinematics(r1, a1)[:, np.newaxis, :, :]
    
    props1 = [{"kind": "speech_bubble", "grid_c": 44, "grid_r": 9}]
    scenery1 = {"type": "plain"}
    for t in range(len(j1)):
        all_frames.append(preview.render_ascii_frame(j1[t], scenery1, props1, frame_idx=t))

    # Scene 2: 1-point perspective colonnade & baroque frame
    f2 = gen_single("walk", duration_s=3.0, speed=0.8)["feat"]
    r2, a2 = decode(f2)
    j2 = forward_kinematics(r2, a2)[:, np.newaxis, :, :]
    scenery2 = {"type": "perspective_hall", "colonnade": True, "baroque_frame": True}
    for t in range(len(j2)):
        all_frames.append(preview.render_ascii_frame(j2[t], scenery2, [], frame_idx=len(all_frames)))

    # Scene 3: Gavel smash, rubble & "NOT A VERDICT"
    f3 = gen_single("knockdown", duration_s=4.0)["feat"]
    r3, a3 = decode(f3)
    j3 = forward_kinematics(r3, a3)[:, np.newaxis, :, :]
    scenery3 = {"type": "perspective_hall", "shattered_pillars": True}
    text3 = {"text": "NOT A VERDICT"}
    for t in range(len(j3)):
        props3 = []
        if t >= 10:
            props3.append({"kind": "gavel", "grid_c": 40 + min(10, t - 10), "grid_r": 8 + min(6, t - 10)})
        all_frames.append(preview.render_ascii_frame(j3[t], scenery3, props3, text_overlay=text3 if t >= 25 else None, frame_idx=len(all_frames)))

    return all_frames


def build_demo_dark() -> list[str]:
    """Builds frames and metadata for the Dark Theme Demo in ASCII."""
    preview = TerminalStagePreview(cols=80, rows=24)
    all_frames = []

    # Scene 1: Spline web & thought bubble
    f1 = gen_single("wave", duration_s=3.0)["feat"]
    r1, a1 = decode(f1)
    j1 = forward_kinematics(r1, a1)[:, np.newaxis, :, :]
    scenery1 = {"type": "spline_web"}
    for t in range(len(j1)):
        all_frames.append(preview.render_ascii_frame(j1[t], scenery1, [], frame_idx=t))

    # Scene 2: 3-panel split screen & stamped envelope
    f2 = gen_pair("punch_block", duration_s=3.0)["feat"]
    r2a, a2a = decode(f2[:, :30])
    r2b, a2b = decode(f2[:, 30:])
    j2a = forward_kinematics(r2a, a2a)
    j2b = forward_kinematics(r2b, a2b)
    j2 = np.stack([j2a, j2b], axis=1)
    props2 = [{"kind": "envelope_x"}]
    scenery2 = {"type": "plain"}
    for t in range(len(j2)):
        all_frames.append(preview.render_ascii_frame(j2[t], scenery2, props2, frame_idx=len(all_frames)))

    # Scene 3: 3D perspective prison cage & distress
    f3 = gen_single("squat", duration_s=4.0)["feat"]
    r3, a3 = decode(f3)
    j3 = forward_kinematics(r3, a3)[:, np.newaxis, :, :]
    scenery3 = {"type": "plain", "prison_cage": True, "face_emotion": "distress"}
    for t in range(len(j3)):
        all_frames.append(preview.render_ascii_frame(j3[t], scenery3, [], frame_idx=len(all_frames)))

    return all_frames


def main():
    parser = argparse.ArgumentParser(description="Terminal ASCII Stickman Puppet Player")
    parser.add_argument("--prompt", type=str, help="Natural language prompt (e.g. 'stickman walk right for 3s')")
    parser.add_argument("--demo", choices=["light", "dark"], help="Play predefined goal video reproduction demo in ASCII")
    parser.add_argument("--action", type=str, help="Action name (e.g. walk, run, punch_block, celebrate)")
    parser.add_argument("--duration", type=float, default=3.0, help="Duration in seconds")
    parser.add_argument("--fps", type=float, default=12.0, help="Terminal playback framerate (default 12 for smooth rendering)")
    parser.add_argument("--loop", action="store_true", help="Loop animation indefinitely")
    parser.add_argument("--dump-frame", type=int, help="Print a single frame to stdout without playback")

    args = parser.parse_args()
    preview = TerminalStagePreview(cols=80, rows=24)
    frames_text = []

    if args.demo == "light":
        print("Generating Light Theme Demo ASCII frames...")
        frames_text = build_demo_light()
    elif args.demo == "dark":
        print("Generating Dark Theme Demo ASCII frames...")
        frames_text = build_demo_dark()
    elif args.prompt:
        parsed = parse_prompt(args.prompt)
        act = parsed["action"]
        dur = parsed["duration_seconds"]
        spd = parsed["speed"]
        amp = parsed["amplitude"]
        dir_ = parsed["direction"]
        n_p = parsed["n_person"]
        
        if n_p == 2:
            res = gen_pair(act, duration_s=dur, speed=spd, amplitude=amp)
            feat = res["feat"]
            ra, aa = decode(feat[:, :30])
            rb, ab = decode(feat[:, 30:])
            ja = forward_kinematics(ra, aa)
            jb = forward_kinematics(rb, ab)
            joints = np.stack([ja, jb], axis=1)
        else:
            res = gen_single(act, duration_s=dur, speed=spd, amplitude=amp, direction=dir_)
            feat = res["feat"]
            r, a = decode(feat)
            joints = forward_kinematics(r, a)[:, np.newaxis, :, :]

        for t in range(len(joints)):
            frames_text.append(preview.render_ascii_frame(joints[t], frame_idx=t))

    elif args.action:
        act = args.action
        dur = args.duration
        if act in ACTIONS_2P:
            res = gen_pair(act, duration_s=dur)
            feat = res["feat"]
            ra, aa = decode(feat[:, :30])
            rb, ab = decode(feat[:, 30:])
            ja = forward_kinematics(ra, aa)
            jb = forward_kinematics(rb, ab)
            joints = np.stack([ja, jb], axis=1)
        else:
            res = gen_single(act, duration_s=dur)
            r, a = decode(res["feat"])
            joints = forward_kinematics(r, a)[:, np.newaxis, :, :]

        for t in range(len(joints)):
            frames_text.append(preview.render_ascii_frame(joints[t], frame_idx=t))

    else:
        # Default fallback demo: walk
        res = gen_single("walk", duration_s=3.0)
        r, a = decode(res["feat"])
        joints = forward_kinematics(r, a)[:, np.newaxis, :, :]
        for t in range(len(joints)):
            frames_text.append(preview.render_ascii_frame(joints[t], frame_idx=t))

    if args.dump_frame is not None:
        idx = max(0, min(len(frames_text) - 1, args.dump_frame))
        print(frames_text[idx])
        return

    print(f"Loaded {len(frames_text)} frames. Starting playback at {args.fps} FPS...")
    time.sleep(1.0)
    play_frames(frames_text, fps=args.fps, loop=args.loop)


if __name__ == "__main__":
    main()
