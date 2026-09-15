"""Puppet Stage Choreography DSL & Platform Engine.

Provides a clean, declarative specification format for multi-scene puppet theatre.
Compiles high-level scene scripts into:
1. Full 1280x720 HD H.264 videos composited via StageRendererHD.
2. Symbolic terminal/ASCII frame storyboards for LLM directors to visualize and plan.
"""

from dataclasses import dataclass, field
import os
from typing import Any, Dict, List, Optional
import numpy as np

from src.rig import decode, encode, forward_kinematics, FPS
from src.video_encode import open_ffmpeg_writer, close_ffmpeg_writer
from src.sequencer import blend_feature_clips
from src.stage_renderer import StageRendererHD, render_stage_video
from src.stage.terminal_preview import TerminalStagePreview


@dataclass
class PuppetSpec:
    """Specification of an individual puppet actor on stage."""
    actor_id: int
    action: str = "idle"
    duration_s: float = 3.0
    speed: float = 1.0
    amplitude: float = 1.0
    direction: int = 1
    seed: int = 0
    offset_x: float = 0.0
    offset_y: float = 0.0
    arm_pose: Optional[str] = None  # e.g., "hold_object", "hands_on_head", "reach_forward"


@dataclass
class SceneSpec:
    """Specification of a single stage scene."""
    name: str
    duration_s: float
    scenery: Dict[str, Any] = field(default_factory=dict)
    puppets: List[PuppetSpec] = field(default_factory=list)
    props: List[Dict[str, Any]] = field(default_factory=list)
    text_overlay: Optional[Dict[str, Any]] = None


@dataclass
class StageScript:
    """Complete multi-scene theatrical script."""
    title: str
    theme: str = "light"
    width: int = 1280
    height: int = 720
    fps: int = 24
    scenes: List[SceneSpec] = field(default_factory=list)


def parse_puppet_spec(data: Dict[str, Any]) -> PuppetSpec:
    return PuppetSpec(
        actor_id=data.get("actor_id", 0),
        action=data.get("action", "idle"),
        duration_s=float(data.get("duration_s", 3.0)),
        speed=float(data.get("speed", 1.0)),
        amplitude=float(data.get("amplitude", 1.0)),
        direction=int(data.get("direction", 1)),
        seed=int(data.get("seed", 0)),
        offset_x=float(data.get("offset_x", 0.0)),
        offset_y=float(data.get("offset_y", 0.0)),
        arm_pose=data.get("arm_pose")
    )


def parse_scene_spec(data: Dict[str, Any]) -> SceneSpec:
    puppets = [parse_puppet_spec(p) for p in data.get("puppets", [])]
    return SceneSpec(
        name=data.get("name", "Untitled Scene"),
        duration_s=float(data.get("duration_s", 3.0)),
        scenery=data.get("scenery", {}),
        puppets=puppets,
        props=data.get("props", []),
        text_overlay=data.get("text_overlay")
    )


def parse_stage_script(data: Dict[str, Any]) -> StageScript:
    scenes = [parse_scene_spec(s) for s in data.get("scenes", [])]
    return StageScript(
        title=data.get("title", "Puppet Stage Performance"),
        theme=data.get("theme", "light"),
        width=int(data.get("width", 1280)),
        height=int(data.get("height", 720)),
        fps=int(data.get("fps", 24)),
        scenes=scenes
    )


def compile_scene_puppets(scene: SceneSpec, fps: int = 24) -> np.ndarray:
    """Compiles puppet motions for a single scene.
    
    Returns joints array of shape (T_scene, N_puppets, 15, 2).
    """
    T = int(scene.duration_s * fps)
    from src.puppet.choreography import build_motion_from_action

    if not scene.puppets:
        # Default single idle puppet at center with gentle life
        feat = build_motion_from_action("idle", duration_s=scene.duration_s)[:T]
        r, a = decode(feat)
        j = forward_kinematics(r, a)
        return j[:, np.newaxis, :, :]

    actor_joints = []
    for p in scene.puppets:
        feat = build_motion_from_action(
            p.action,
            duration_s=scene.duration_s,
            speed=p.speed,
            amplitude=p.amplitude,
            direction=p.direction,
            seed=p.seed,
            start_x=p.offset_x
        )[:T]

        r, a = decode(feat)

        # Apply spatial offset Y (X is already handled by start_x in build_motion_from_action)
        r[:, 1] += p.offset_y

        # Apply high-level arm poses
        if p.arm_pose == "hold_object":
            # Joint 4/5 upperArmL/lowerArmL, 6/7 upperArmR/lowerArmR
            a[:, 4] = 1.3
            a[:, 5] = -1.1
            a[:, 6] = -1.3
            a[:, 7] = 1.1
        elif p.arm_pose == "hands_on_head":
            a[:, 4] = 1.8
            a[:, 5] = -2.2
            a[:, 6] = -1.8
            a[:, 7] = 2.2
        elif p.arm_pose == "reach_forward":
            a[:, 4] = 1.2
            a[:, 6] = -1.2

        j = forward_kinematics(r, a)
        actor_joints.append(j)

    # Combine actors: (T, N, 15, 2)
    return np.stack(actor_joints, axis=1)


def compile_stage_script(
    script_data: Dict[str, Any],
    output_path: str,
    preview_ascii: bool = False
) -> Dict[str, Any]:
    """Compiles a complete declarative StageScript into an HD MP4 video.
    
    Optionally returns ASCII terminal storyboards for each scene.
    """
    script = parse_stage_script(script_data)
    stage = StageRendererHD(width=script.width, height=script.height, theme_name=script.theme)
    terminal = TerminalStagePreview(cols=80, rows=24)

    proc = open_ffmpeg_writer(
        output_path,
        width=script.width,
        height=script.height,
        fps=script.fps,
    )

    ascii_previews = []
    total_frames = 0

    try:
        for s_idx, scene in enumerate(script.scenes):
            scene_joints = compile_scene_puppets(scene, fps=script.fps)
            T_scene = len(scene_joints)
            total_frames += T_scene

            # Generate ASCII snapshot of midpoint of the scene
            mid_frame = T_scene // 2
            ascii_text = terminal.render_ascii_frame(
                scene_joints[mid_frame],
                scenery=scene.scenery,
                props=scene.props,
                text_overlay=scene.text_overlay,
                frame_idx=total_frames - T_scene + mid_frame
            )
            ascii_previews.append({
                "scene_name": scene.name,
                "midpoint_frame": total_frames - T_scene + mid_frame,
                "ascii": ascii_text
            })

            # Stream frames into ffmpeg
            for t in range(T_scene):
                frame_props = []
                for p in scene.props:
                    p_copy = dict(p)
                    # Gavel animation support
                    if p_copy.get("kind") == "gavel" and "start_frame" in p_copy:
                        sf = p_copy["start_frame"]
                        if t >= sf:
                            dt = min(1.0, (t - sf) / 12.0)
                            p_copy["y"] = p_copy.get("start_y", 120) + dt * (p_copy.get("target_y", 380) - p_copy.get("start_y", 120))
                            p_copy["angle"] = p_copy.get("start_angle", -15.0) + dt * (p_copy.get("target_angle", 30.0) - p_copy.get("start_angle", -15.0))
                            frame_props.append(p_copy)
                    else:
                        frame_props.append(p_copy)

                img = stage.render_stage_frame(
                    scene_joints[t],
                    camera_x=0.0,
                    scenery=scene.scenery,
                    props=frame_props,
                    text_overlay=scene.text_overlay
                )
                proc.stdin.write(img.tobytes())

        close_ffmpeg_writer(proc)

    except Exception:
        proc.kill()
        raise

    return {
        "output_path": output_path,
        "size_bytes": os.path.getsize(output_path),
        "total_frames": total_frames,
        "duration_s": total_frames / script.fps,
        "scenes_count": len(script.scenes),
        "ascii_previews": ascii_previews
    }
