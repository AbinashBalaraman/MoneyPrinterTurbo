"""Autonomous Scene Suite Generator & Visual Inspection Tool.

Renders standard action scenes into MP4 and exports key visual audit frames (PNG):
1. scene_walk_forward.mp4 (Locomotion: forward gait)
2. scene_walk_backward.mp4 (Locomotion: reverse walk with true rearward gait)
3. scene_combat_punch.mp4 (Combat: punch with hit-stop freeze)
4. scene_combat_kick.mp4 (Combat: kick with chamber, strike & hit-stop)
5. scene_jump.mp4 (Acrobatics: crouch, leap, apex flight, landing)
6. scene_combat_pair_exchange.mp4 (2P Martial Arts: multi-hit exchange)
7. scene_combat_pair_knockdown.mp4 (2P Martial Arts: heavy blow, recoil, collapse & getup)
8. scene_combat_pair_kick_dodge.mp4 (2P Martial Arts: high kick vs duck-under)
"""

import os
import sys
import numpy as np
from PIL import Image
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.puppet.choreography import build_motion_from_action, build_combat_pair
from src.renderer import (render_to_video, decode_motion_features, StickmanRenderer,
                          FPS, compute_smooth_camera_track, active_vfx_for_frame)


def _build(gen_fn):
    """Builds (feat, events), using return_events=True when the builder supports it."""
    try:
        feat, events = gen_fn(return_events=True)
        return feat, events or []
    except TypeError:
        return gen_fn(), []


def _run_and_leap(return_events=False):
    """Run-in to jump combo (used before a dedicated leap action exists)."""
    from src.puppet.choreography import PuppetChoreographer
    ch = PuppetChoreographer()
    ch.run(steps=3).jump()
    feat = ch.compile(total_duration_s=3.0)
    if return_events:
        return feat, ch.compile_events()
    return feat


def _narrative_martial_artist(return_events=False):
    """3-act narrative (walk -> punch -> celebrate); builder lives in render_narrative_sequence."""
    import importlib.util
    path = ROOT / "tools/render_narrative_sequence.py"
    spec = importlib.util.spec_from_file_location("render_narrative_sequence", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_narrative(return_events=return_events)


def _sword_duel_props():
    from src.puppet.choreography import get_combat_props
    return get_combat_props("sword_clash")


def export_key_frames(joints: np.ndarray, output_dir: str, prefix: str, frame_indices: list, props=None, vfx_events=None):
    os.makedirs(output_dir, exist_ok=True)
    renderer = StickmanRenderer(canvas_size=512)
    cam_track = compute_smooth_camera_track(joints, alpha=0.10)
    T = len(joints)
    for idx in frame_indices:
        if 0 <= idx < T:
            frame_vfx = active_vfx_for_frame(vfx_events, idx) if vfx_events else None
            img = renderer.render_frame(joints[idx], camera_x=cam_track[idx], props=props, vfx=frame_vfx)
            path = os.path.join(output_dir, f"{prefix}_frame_{idx:03d}.png")
            img.save(path)


def run_scene_suite():
    os.makedirs("out/scenes", exist_ok=True)
    os.makedirs("out/inspect_scenes", exist_ok=True)

    scenes = [
        ("walk_forward", lambda **kw: build_motion_from_action("walk", duration_s=3.0, **kw), [10, 25, 40, 55]),
        ("walk_backward", lambda **kw: build_motion_from_action("walkback", duration_s=3.0, **kw), [10, 25, 40, 55]),
        ("combat_punch", lambda **kw: build_motion_from_action("punch", duration_s=2.5, **kw), [12, 16, 17, 18, 24]),
        ("combat_kick", lambda **kw: build_motion_from_action("kick", duration_s=2.5, **kw), [12, 18, 19, 20, 26]),
        ("jump_acrobatic", lambda **kw: build_motion_from_action("jump", duration_s=2.5, **kw), [6, 8, 14, 22, 30, 32, 38]),
        ("combat_pair_exchange", lambda **kw: build_combat_pair("exchange", duration_s=3.0, **kw), [11, 22, 35, 48]),
        ("combat_pair_knockdown", lambda **kw: build_combat_pair("knockdown_getup", duration_s=3.5, **kw), [13, 20, 28, 45, 65]),
        ("combat_pair_punch_block", lambda **kw: build_combat_pair("punch_block", duration_s=3.0, **kw), [10, 16, 22, 30]),
        ("combat_pair_kick_dodge", lambda **kw: build_combat_pair("kick_dodge", duration_s=3.0, **kw), [10, 16, 20, 28]),
        ("expressive_celebrate", lambda **kw: build_motion_from_action("celebrate", duration_s=2.5, **kw), [8, 16, 24, 32]),
        ("expressive_wave", lambda **kw: build_motion_from_action("wave", duration_s=2.5, **kw), [8, 16, 24, 32]),
        ("expressive_distress", lambda **kw: build_motion_from_action("distress", duration_s=2.5, **kw), [8, 16, 24, 32]),
        ("run_and_leap", _run_and_leap, [8, 16, 24, 32]),
        ("narrative_martial_artist", _narrative_martial_artist, [51, 85, 89, 215, 300]),
        ("combat_pair_sword_duel", lambda **kw: build_combat_pair("sword_clash", duration_s=3.0, **kw), [10, 14, 20, 28], _sword_duel_props()),
        ("acrobatic_slide", lambda **kw: build_motion_from_action("slide", duration_s=2.5, **kw), [8, 14, 20, 28]),
    ]

    for entry in scenes:
        name, gen_fn, key_frames = entry[0], entry[1], entry[2]
        props = entry[3] if len(entry) > 3 else None
        print(f"Rendering scene: {name}...")
        feat, events = _build(gen_fn)
        mp4_path = f"out/scenes/{name}.mp4"
        render_to_video(feat, mp4_path, fps=FPS, canvas_size=512, fix_contact=False, auto_camera=True,
                        props=props, vfx_events=events or None)
        joints = decode_motion_features(feat)
        export_key_frames(joints, "out/inspect_scenes", name, key_frames, props=props, vfx_events=events or None)
        print(f"  -> {mp4_path} ({len(feat)} frames, {len(events)} events)")

    print("Scene suite rendering complete!")


if __name__ == "__main__":
    run_scene_suite()
