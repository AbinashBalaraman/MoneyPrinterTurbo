"""Puppet Engine MCP Server (Model Context Protocol).

Provides a lightweight, headless MCP tool interface over stdio JSON-RPC
so any external LLM director can discover actions, sequence timelines,
and render stickman videos deterministically.
"""

import sys
import json
import traceback
from typing import Dict, Any, List, Optional

from .catalog import get_action_catalog, validate_action_params
from .parser import parse_prompt
from .catalog import ACTIONS_1P, ACTIONS_2P
from .puppet.choreography import build_motion_from_action, build_combat_pair
from .sequencer import PuppetSequencer, blend_feature_clips
from .renderer import render_to_video
from .stage.dsl import compile_stage_script, parse_scene_spec, compile_scene_puppets
from .stage.terminal_preview import TerminalStagePreview


TOOLS_REGISTRY = [
    {
        "name": "list_actions",
        "description": "Lists all available single-person (1P) and paired-combat (2P) stickman actions with their parameter schemas.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "parse_text_prompt",
        "description": "Converts a natural language prompt into structured puppet controls {action, speed, direction, amplitude, duration_seconds, seed}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Natural language action description (e.g. 'stickman run fast to the left for 3s')"}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "render_prompt_clip",
        "description": "Parses a natural language prompt, generates the motion, and renders an antialiased 512x512 24fps MP4 video.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text prompt describing stickman action"},
                "output_path": {"type": "string", "description": "Path to save the output MP4 file", "default": "output.mp4"},
                "seed": {"type": "integer", "description": "Random seed for motion diversity", "default": 0}
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "render_action",
        "description": "Renders a single or paired action directly by name with specific parameters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Action name from catalog (e.g. 'walk', 'punch', 'punch_block')"},
                "output_path": {"type": "string", "description": "Path to save the output MP4 file", "default": "output.mp4"},
                "duration_seconds": {"type": "number", "default": 5.0},
                "speed": {"type": "number", "default": 1.0},
                "amplitude": {"type": "number", "default": 1.0},
                "direction": {"type": "integer", "enum": [1, -1], "default": 1},
                "seed": {"type": "integer", "default": 0}
            },
            "required": ["action"]
        }
    },
    {
        "name": "sequence_timeline",
        "description": "Sequences multiple actions into a continuous video with smooth cosine-eased blending and continuous root handoff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of action prompts (e.g. ['walk for 2s', 'stop and wave', 'jump high'])"
                },
                "output_path": {"type": "string", "description": "Path to save the output MP4 file", "default": "output_sequence.mp4"},
                "overlap_frames": {"type": "integer", "description": "Frames of cosine blend between clips", "default": 8}
            },
            "required": ["prompts"]
        }
    },
    {
        "name": "preview_stage_ascii",
        "description": "Renders an ASCII symbolic storyboard preview of puppets and stage elements (perspective pillars, prison cage, speech bubbles, gavel, cracks) so an LLM can visualize the frame without an image viewer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene": {
                    "type": "object",
                    "description": "Scene specification dictionary with scenery, puppets, and props."
                },
                "frame_idx": {
                    "type": "integer",
                    "description": "Frame index to visualize (defaults to midpoint).",
                    "default": 0
                }
            },
            "required": ["scene"]
        }
    },
    {
        "name": "render_stage_script",
        "description": "Compiles a complete declarative Puppet Stage script into a 1280x720 HD H.264 video with custom perspective, scenery, props, and kinetic typography.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "script": {
                    "type": "object",
                    "description": "Stage script dictionary defining title, theme ('light' or 'dark'), and scenes."
                },
                "output_path": {
                    "type": "string",
                    "description": "Target MP4 file path.",
                    "default": "out/stage_performance.mp4"
                },
                "preview_ascii": {
                    "type": "boolean",
                    "description": "Whether to return ASCII terminal previews of each scene.",
                    "default": True
                }
            },
            "required": ["script"]
        }
    },
    {
        "name": "get_capabilities",
        "description": "Returns the full machine-readable world contract: allowed actions, objects (with capabilities), joints, themes, scenery types, camera modes, and the SceneScript JSON schema. Call this first to know what worlds can be expressed.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "validate_scene",
        "description": "Validates a SceneScript JSON without rendering. Returns the normalised plan plus warnings, or a fail-fast error listing every unrenderable field (unknown action/object/joint/character).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene": {"type": "object", "description": "SceneScript JSON (title, theme, characters, beats, objects, camera)."}
            },
            "required": ["scene"]
        }
    },
    {
        "name": "render_scene",
        "description": "The primary world tool: validates a SceneScript (characters, beats, objects, camera) and renders it to an MP4. Objects can be placed, held, thrown, picked up/dropped; camera can auto/follow/close/wide/pan. Set hd=false for 512x512 SD.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scene": {"type": "object", "description": "SceneScript JSON."},
                "output_path": {"type": "string", "default": "out/scene.mp4"},
                "hd": {"type": "boolean", "description": "Render 1280x720 HD (default true); false = 512x512 SD.", "default": True}
            },
            "required": ["scene"]
        }
    }
]


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a puppet engine tool and return JSON result."""
    if name == "list_actions":
        return get_action_catalog()

    elif name == "parse_text_prompt":
        prompt = args.get("prompt", "")
        return parse_prompt(prompt)

    elif name == "render_prompt_clip":
        prompt = args.get("prompt", "")
        output_path = args.get("output_path", "output.mp4")
        seed = args.get("seed", 0)

        parsed = parse_prompt(prompt, seed=seed)
        action = parsed["action"]

        if action in ACTIONS_2P:
            # Fail-fast: pure puppet combat, no sine fallback
            feat, vfx_events = build_combat_pair(
                action=action,
                duration_s=parsed["duration_seconds"],
                speed=parsed["speed"],
                amplitude=parsed["amplitude"],
                seed=seed,
                return_events=True
            )
            clip = {"feat": feat, "action": action, "n_person": 2, "duration_s": parsed["duration_seconds"], "seed": seed}
        else:
            # Fail-fast: pure puppet motion, no sine fallback
            feat, vfx_events = build_motion_from_action(
                action=action,
                duration_s=parsed["duration_seconds"],
                speed=parsed["speed"],
                amplitude=parsed["amplitude"],
                direction=parsed["direction"],
                seed=seed,
                return_events=True
            )
            clip = {"feat": feat, "action": action, "n_person": 1, "duration_s": parsed["duration_seconds"], "seed": seed}

        rendered_file = render_to_video(clip, output_path, vfx_events=vfx_events)
        return {
            "status": "success",
            "output_path": rendered_file,
            "action": action,
            "duration_seconds": parsed["duration_seconds"],
            "n_person": parsed["n_person"]
        }

    elif name == "render_action":
        action = args.get("action")
        output_path = args.get("output_path", "output.mp4")
        validated = validate_action_params(action, args)
        seed = validated.get("seed", 0)

        if action in ACTIONS_2P:
            feat, vfx_events = build_combat_pair(
                action=action,
                duration_s=validated.get("duration_seconds", 5.0),
                speed=validated.get("speed", 1.0),
                amplitude=validated.get("amplitude", 1.0),
                seed=seed,
                return_events=True
            )
            clip = {"feat": feat, "action": action, "n_person": 2, "duration_s": validated.get("duration_seconds", 5.0), "seed": seed}
        else:
            feat, vfx_events = build_motion_from_action(
                action=action,
                duration_s=validated.get("duration_seconds", 5.0),
                speed=validated.get("speed", 1.0),
                amplitude=validated.get("amplitude", 1.0),
                direction=validated.get("direction", 1),
                seed=seed,
                return_events=True
            )
            clip = {"feat": feat, "action": action, "n_person": 1, "duration_s": validated.get("duration_seconds", 5.0), "seed": seed}

        rendered_file = render_to_video(clip, output_path, vfx_events=vfx_events)
        return {
            "status": "success",
            "output_path": rendered_file,
            "action": action,
            "duration_seconds": validated.get("duration_seconds", 5.0)
        }

    elif name == "sequence_timeline":
        prompts = args.get("prompts", [])
        output_path = args.get("output_path", "output_sequence.mp4")
        overlap = args.get("overlap_frames", 8)

        seq = PuppetSequencer(overlap_frames=overlap)
        track = seq.get_or_create_actor("actor_0")
        for p in prompts:
            parsed = parse_prompt(p)
            track.add_step(
                action=parsed["action"],
                duration_seconds=parsed.get("duration_seconds", 3.0),
                speed=parsed.get("speed", 1.0),
                amplitude=parsed.get("amplitude", 1.0),
                direction=parsed.get("direction", 1),
                seed=parsed.get("seed", 0)
            )

        timeline = seq.build()
        rendered_file = render_to_video(timeline, output_path,
                                        vfx_events=timeline.get("vfx_events"))
        return {
            "status": "success",
            "output_path": rendered_file,
            "total_frames": timeline["T"],
            "duration_seconds": timeline["duration_seconds"]
        }

    elif name == "preview_stage_ascii":
        scene_data = args.get("scene", {})
        frame_idx = args.get("frame_idx", 0)
        scene = parse_scene_spec(scene_data)
        joints = compile_scene_puppets(scene)
        t_idx = min(len(joints) - 1, max(0, frame_idx if frame_idx > 0 else len(joints) // 2))
        terminal = TerminalStagePreview(cols=80, rows=24)
        ascii_text = terminal.render_ascii_frame(
            joints[t_idx],
            scenery=scene.scenery,
            props=scene.props,
            text_overlay=scene.text_overlay,
            frame_idx=t_idx
        )
        return {
            "status": "success",
            "frame_idx": t_idx,
            "total_scene_frames": len(joints),
            "ascii_preview": ascii_text
        }

    elif name == "render_stage_script":
        script_data = args.get("script", {})
        output_path = args.get("output_path", "out/stage_performance.mp4")
        preview_ascii = args.get("preview_ascii", True)
        result = compile_stage_script(script_data, output_path, preview_ascii=preview_ascii)
        return {
            "status": "success",
            "output_path": result["output_path"],
            "size_bytes": result["size_bytes"],
            "total_frames": result["total_frames"],
            "duration_seconds": result["duration_s"],
            "scenes_count": result["scenes_count"],
            "ascii_previews": result.get("ascii_previews", [])
        }

    elif name == "get_capabilities":
        from .contract import capabilities
        from .planner import llm_system_prompt
        caps = capabilities()
        caps["llm_system_prompt"] = llm_system_prompt()
        return caps

    elif name == "validate_scene":
        from .contract import validate_scene as _validate
        validated, report = _validate(args.get("scene", {}))
        return {"status": "success", "scene": validated, "warnings": report.get("warnings", [])}

    elif name == "render_scene":
        from .scene import compile_scene_dict
        scene_data = args.get("scene", {})
        output_path = args.get("output_path", "out/scene.mp4")
        hd = args.get("hd", True)
        timeline = compile_scene_dict(scene_data)
        if hd:
            from .stage_renderer import render_stage_video
            render_stage_video(
                timeline["feat"], output_path, theme_name=timeline.get("theme", "light"),
                scenery=timeline.get("scenery"), fix_contact=False,
                vfx=timeline.get("vfx_events"), prop_tracks=timeline.get("prop_tracks"),
                camera_track=timeline.get("camera_track"), impacts=timeline.get("impacts"))
        else:
            render_to_video(
                timeline["feat"], output_path, fix_contact=False,
                vfx_events=timeline.get("vfx_events"), prop_tracks=timeline.get("prop_tracks"),
                camera_track=timeline.get("camera_track"), impacts=timeline.get("impacts"))
        return {
            "status": "success",
            "output_path": output_path,
            "n_person": timeline["n_person"],
            "total_frames": timeline["T"],
            "duration_seconds": timeline["duration_seconds"],
            "impacts": len(timeline.get("impacts", [])),
            "title": timeline.get("title"),
        }

    else:
        raise ValueError(f"Unknown tool: {name}")


def run_stdio_server():
    """Run standard JSON-RPC 2.0 loop over stdin/stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "tools/list":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": TOOLS_REGISTRY}
                }
            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                tool_result = execute_tool(tool_name, tool_args)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(tool_result, indent=2)}]}
                }
            elif method == "initialize":
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "puppet-engine-mcp", "version": "1.0.0"}
                    }
                }
            else:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}
                }
        except Exception as e:
            err_msg = f"{type(e).__name__}: {str(e)}\n{traceback.format_exc()}"
            resp = {
                "jsonrpc": "2.0",
                "id": req.get("id") if 'req' in locals() and isinstance(req, dict) else None,
                "error": {"code": -32000, "message": err_msg}
            }

        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
