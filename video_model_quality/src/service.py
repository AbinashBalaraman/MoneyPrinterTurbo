"""StudioService: ONE code path from a prompt to a rendered clip.

The CLI (``tools/prompt_to_video.py``), the batch harness and the browser
studio all call into this module. It exists because that plan -> compile ->
diagnose -> render chain used to be duplicated inline in the CLI, which meant
the studio would have had to re-implement it (and drift from it).

Division of labour is unchanged and enforced here:
  - an LLM/human owns the *world* (SceneScript JSON),
  - the engine only *executes* a validated plan -- it never invents a world.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.catalog import ACTIONS_2P
from src.parser import parse_prompt
from src.planner import DeterministicPlanner, plan_scene
from src.puppet.choreography import build_combat_pair, build_motion_from_action
from src.renderer import render_to_video
from src.rig import FPS
from src.stage_renderer import render_stage_video

# A prompt that parses to a single unambiguous action takes the optimised
# single-action path; anything else becomes an ordered multi-beat scene.
MODE_ACTION = "action"
MODE_SCENE = "scene"


class PlanError(ValueError):
    """Raised when a prompt cannot be turned into a plan."""


def plan_prompt(prompt: str, seed: int = 0) -> Dict[str, Any]:
    """Turn a text prompt into a compiled timeline.

    Returns a dict with keys:
        timeline, scene_dict (None for single-action), mode, action, n_person,
        duration_seconds, T.
    """
    prompt = (prompt or "").strip()
    if not prompt:
        raise PlanError("empty prompt")

    parsed = None
    try:
        parsed = parse_prompt(prompt, seed=seed)
    except ValueError:
        parsed = None

    if parsed is not None:
        action = parsed["action"]
        dur = float(parsed["duration_seconds"])
        if action in ACTIONS_2P:
            feat = build_combat_pair(action, duration_s=dur, speed=parsed["speed"],
                                     amplitude=parsed["amplitude"], seed=seed)
        else:
            feat = build_motion_from_action(action, duration_s=dur, speed=parsed["speed"],
                                            amplitude=parsed["amplitude"],
                                            direction=parsed["direction"], seed=seed)
        timeline = {
            "feat": feat,
            "n_person": int(parsed["n_person"]),
            "duration_seconds": dur,
            "vfx_events": [],
            "theme": "light",
            "actions": [action],
        }
        return {
            "timeline": timeline,
            "scene_dict": None,
            "mode": MODE_ACTION,
            "action": action,
            "n_person": timeline["n_person"],
            "duration_seconds": dur,
            "T": int(feat.shape[0]),
        }

    # Ordered multi-action scene via the deterministic planner.
    try:
        scene = plan_scene(prompt, backend=DeterministicPlanner())
        from src.scene import compile_scene_dict
        timeline = compile_scene_dict(scene)
    except PlanError:
        raise
    except Exception as e:  # noqa: BLE001 -- surface as a plan failure, not a crash
        raise PlanError(f"could not plan prompt: {e}") from e
    timeline.setdefault("actions", [b.get("action") for b in scene.get("beats", [])
                                    if b.get("action")])
    return {
        "timeline": timeline,
        "scene_dict": scene,
        "mode": MODE_SCENE,
        "action": None,
        "n_person": int(timeline["n_person"]),
        "duration_seconds": float(timeline.get("duration_seconds", 0.0)),
        "T": int(timeline.get("T", 0)),
    }


def compile_scene_file(path: str | Path) -> Dict[str, Any]:
    """Compile an explicit LLM/author SceneScript JSON file."""
    import json

    from src.scene import compile_scene_dict

    scene = json.loads(Path(path).read_text(encoding="utf-8"))
    timeline = compile_scene_dict(scene)
    return {
        "timeline": timeline,
        "scene_dict": scene,
        "mode": MODE_SCENE,
        "action": None,
        "n_person": int(timeline["n_person"]),
        "duration_seconds": float(timeline.get("duration_seconds", 0.0)),
        "T": int(timeline.get("T", 0)),
    }


def diagnose_timeline(timeline: Dict[str, Any],
                      scene_dict: Optional[Dict[str, Any]] = None,
                      strict_timing: bool = False,
                      allow: Optional[str] = None) -> Dict[str, Any]:
    """Run SceneDoctor. Correctness defects block; timing debt is advisory."""
    from src.doctor import diagnose
    return diagnose(timeline, scene=scene_dict, strict=True,
                    strict_timing=strict_timing, allow=allow)


def render_timeline(timeline: Dict[str, Any], out_path: str | Path, *,
                    sd: bool = False, theme: Optional[str] = None,
                    seed: int = 0, progress_cb: Optional[Callable[[int, int], None]] = None) -> str:
    """Render a compiled timeline to MP4 (SD arena or HD stage)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    feat = timeline["feat"]
    vfx_events = timeline.get("vfx_events", [])
    prop_tracks = timeline.get("prop_tracks")
    cam = timeline.get("camera_track")
    impacts = timeline.get("impacts")
    scenery = timeline.get("scenery") or {"type": "plain", "auto_camera": True}
    theme_name = theme or timeline.get("theme", "light")

    if sd:
        clip = {"feat": feat, "action": "scene",
                "n_person": timeline["n_person"],
                "duration_s": timeline.get("duration_seconds", 0.0), "seed": seed}
        render_to_video(clip, str(out_path), fix_contact=False, vfx_events=vfx_events,
                        prop_tracks=prop_tracks, camera_track=cam, impacts=impacts,
                        progress_cb=progress_cb)
    else:
        render_stage_video(feat, str(out_path), theme_name=theme_name, scenery=scenery,
                           fix_contact=False, vfx=vfx_events, prop_tracks=prop_tracks,
                           camera_track=cam, impacts=impacts, progress_cb=progress_cb)
    return str(out_path)


def slowmo(src: str | Path, dst: str | Path, factor: float = 0.5) -> str:
    """Retime a clip to ``factor`` speed (0.5 = half speed) without re-rendering.

    Playback speed is a presentation concern, so we retime the encoded file with
    ffmpeg's ``setpts`` rather than re-running the renderer. The frame *content*
    is bit-identical -- which is the whole point of a slow-motion reviewer: you
    see the exact frames the engine produced, just stretched out.
    """
    if factor <= 0:
        raise ValueError("factor must be > 0")
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH; cannot retime clip")
    pts = 1.0 / factor
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(src),
           "-filter:v", f"setpts={pts:.6f}*PTS", "-an", str(dst)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg retime failed: {proc.stderr.strip()}")
    return str(dst)


def produce(prompt: str, out_dir: str | Path, *, sd: bool = False,
            theme: Optional[str] = None, seed: int = 0,
            strict_timing: bool = False, allow: Optional[str] = None,
            want_slowmo: bool = True, with_sound: bool = True,
            name: Optional[str] = None, max_frames: Optional[int] = None,
            progress_cb: Optional[Callable[[str, float], None]] = None) -> Dict[str, Any]:
    """Full pipeline for one prompt: plan -> compile -> diagnose -> render.

    Never raises for *content* problems (bad prompts, blocked scenes): those come
    back as a report with ``ok=False`` so a UI can show them. Only genuine bugs
    propagate.

    max_frames: refuse to render clips longer than this. Guards small hosts
    (a free container has ~0.1 CPU and 512 MB; a long HD clip will OOM it).
    progress_cb: optional ``(stage, fraction)`` callback for live UI progress.
    """

    def _say(stage: str, frac: float = 0.0) -> None:
        if progress_cb is not None:
            try:
                progress_cb(stage, float(frac))
            except Exception:  # noqa: BLE001 -- progress must never break a render
                pass

    from src.doctor import format_report

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = name or "clip"

    _say("planning", 0.0)
    try:
        planned = plan_prompt(prompt, seed=seed)
    except PlanError as e:
        return {"ok": False, "stage": "plan", "error": str(e),
                "prompt": prompt, "report": None, "report_text": ""}

    _say("diagnosing", 0.05)
    timeline = planned["timeline"]
    report = diagnose_timeline(timeline, planned["scene_dict"],
                               strict_timing=strict_timing, allow=allow)
    report_text = format_report(report)

    result: Dict[str, Any] = {
        "ok": bool(report["passed"]),
        "stage": "diagnose",
        "prompt": prompt,
        "mode": planned["mode"],
        "action": planned["action"],
        "n_person": planned["n_person"],
        "duration_seconds": planned["duration_seconds"],
        "T": planned["T"],
        "fps": FPS,
        "report": report,
        "report_text": report_text,
        "video": None,
        "slowmo_video": None,
        "scene_dict": planned["scene_dict"],
    }

    if not report["passed"]:
        result["error"] = "blocked by SceneDoctor (hard defects)"
        _say("blocked", 1.0)
        return result

    if max_frames is not None and planned["T"] > max_frames:
        result["ok"] = False
        result["stage"] = "guard"
        result["error"] = (f"clip too long for this host: {planned['T']} frames "
                           f"(limit {max_frames}). Shorten the duration.")
        _say("too long", 1.0)
        return result

    video = out_dir / f"{stem}.mp4"
    _say("rendering", 0.10)

    def _frame_cb(done: int, total: int) -> None:
        # Rendering owns 0.10 -> 0.80 of the bar; the rest is sound + retime.
        _say("rendering", 0.10 + 0.70 * (done / max(1, total)))

    render_timeline(timeline, video, sd=sd, theme=theme, seed=seed,
                    progress_cb=_frame_cb)
    result["video_silent"] = str(video)
    result["video"] = str(video)

    if with_sound:
        # Sound is derived from the same timeline that drove the picture, so it
        # cannot drift. A failure here degrades to a silent clip, never an error.
        try:
            from src.audio import add_sound
            _say("sound", 0.85)
            snd = add_sound(video, timeline, out_dir / f"{stem}_sound.mp4", seed=seed)
            result["video"] = snd["video"]
            result["wav"] = snd["wav"]
            result["audio_counts"] = snd["counts"]
        except Exception as e:  # noqa: BLE001
            result["audio_error"] = str(e)

    if want_slowmo:
        # Retimed from the finished (sounded) clip. Audio is dropped: a slow-mo
        # reviewer is a *timing* tool, and pitch-shifted impacts only distract.
        try:
            _say("retiming", 0.93)
            result["slowmo_video"] = slowmo(result["video"], out_dir / f"{stem}_slowmo.mp4", 0.5)
        except Exception as e:  # noqa: BLE001
            result["slowmo_error"] = str(e)

    _say("done", 1.0)
    return result


def batch(prompts: List[str], *, seed: int = 0, strict_timing: bool = False) -> List[Dict[str, Any]]:
    """Plan + compile + diagnose many prompts without rendering. Fast."""
    out: List[Dict[str, Any]] = []
    for p in prompts:
        try:
            planned = plan_prompt(p, seed=seed)
        except Exception as e:  # noqa: BLE001 -- one bad prompt must not stop the run
            out.append({"prompt": p, "ok": False, "error": str(e), "hard": [],
                        "timing": [], "hard_detail": [], "timing_detail": [],
                        "mode": None, "action": None, "n_person": 0, "T": 0,
                        "report": None})
            continue
        report = diagnose_timeline(planned["timeline"], planned["scene_dict"],
                                   strict_timing=strict_timing)
        out.append({
            "prompt": p,
            "ok": bool(report["passed"]),
            "mode": planned["mode"],
            "action": planned["action"],
            "n_person": planned["n_person"],
            "T": planned["T"],
            "hard": [h["code"] for h in report["hard"]],
            "timing": [t["code"] for t in report["timing"]],
            "hard_detail": report["hard"],
            "timing_detail": report["timing"],
            "report": report,
        })
    return out
