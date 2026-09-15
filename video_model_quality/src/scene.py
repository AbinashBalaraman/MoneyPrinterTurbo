"""SceneScript: declarative multi-actor scene plan + deterministic compiler.

This is the control layer above the puppet platform. A *plan* (data, not code)
describes characters and an ordered list of beats; the compiler turns it into
per-actor motion feature streams + VFX events using the existing sequencer.

Design follows the state of the art (animdsl, Stick-Gen ScriptSchema,
blender-llm-animator): a planner emits declarative data, a deterministic
compiler executes it. No planner ever emits joint angles or raw motion.

    text ---> parse_script() ---> SceneScript ---> compile_scene() ---> timeline

`parse_script` is the deterministic (no-LLM) front-end: it extracts an ordered
list of actions from free text. It never silently drops a clause.

`SceneScript.from_scene_dict` adapts a **validated** contract scene dict (the
LLM/author interface) into this dataclass, so the same compiler serves both the
keyword path and a real planner.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .sequencer import PuppetSequencer, ActorTrack
from .puppet.choreography import build_motion_from_action

FPS = 24

# 2-person pair actions expand into synchronized per-actor 1P beats so any
# a script mixing pair and solo beats can be compiled on the actor model.
PAIR_EXPANSION: Dict[str, List[Tuple[str, str]]] = {
    # action -> [(actor_key, 1P action), ...]
    "punch_block":   [("a", "punch"), ("b", "block")],
    "kick_dodge":    [("a", "kick"),  ("b", "squat")],
    "exchange":      [("a", "punch"), ("b", "block")],
    "knockdown_getup": [("a", "punch"), ("b", "knockdown")],
}

PAIR_ACTIONS = tuple(PAIR_EXPANSION.keys())

# Default staging for a 2-actor scene (world units).
ACTOR_A_X = -0.45  # faces +X
ACTOR_B_X = +0.45  # faces -X


@dataclass
class Beat:
    action: str
    duration_s: float = 2.0
    direction: int = 1
    speed: float = 1.0
    amplitude: float = 1.0
    actor: str = "a"
    at_s: Optional[float] = None          # optional start time on the actor's track
    target: Optional[str] = None          # actor this beat interacts with
    interaction: Optional[str] = None     # strike/block/dodge/grab/knockdown/...
    expression: Optional[str] = None      # 16-decal facial expression


@dataclass
class Character:
    id: str = "a"
    start_x: float = 0.0
    facing: int = 1
    color: Optional[Any] = None
    role: Optional[str] = None
    expression: Optional[str] = None      # 16-decal facial expression


@dataclass
class SceneScript:
    title: str = "untitled"
    fps: int = FPS
    theme: str = "light"
    scenery: Dict[str, Any] = field(default_factory=dict)
    camera: Dict[str, Any] = field(default_factory=dict)
    characters: List[Character] = field(default_factory=list)
    beats: List[Beat] = field(default_factory=list)
    objects: List[Dict[str, Any]] = field(default_factory=list)
    shots: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "title": self.title,
            "fps": self.fps,
            "theme": self.theme,
            "scenery": dict(self.scenery),
            "camera": dict(self.camera),
            "characters": [
                {"id": c.id, "start_x": c.start_x, "facing": c.facing, "color": c.color, "role": c.role, "expression": c.expression}
                for c in self.characters
            ],
            "beats": [vars(b) for b in self.beats],
            "objects": [dict(o) for o in self.objects],
        }
        if self.shots is not None:
            d["shots"] = [dict(s) for s in self.shots]
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SceneScript":
        return cls(
            title=d.get("title", "untitled"),
            fps=int(d.get("fps", FPS)),
            theme=d.get("theme", "light"),
            scenery=dict(d.get("scenery") or {}),
            camera=dict(d.get("camera") or {}),
            characters=[Character(**{k: v for k, v in c.items()
                                     if k in ("id", "start_x", "facing", "color", "role", "expression")})
                        for c in d.get("characters", [])],
            beats=[Beat(**{k: v for k, v in b.items()
                           if k in ("action", "duration_s", "direction", "speed",
                                    "amplitude", "actor", "at_s", "target",
                                    "interaction", "expression")})
                    for b in d.get("beats", [])],
            objects=[dict(o) for o in d.get("objects", [])],
            shots=[dict(s) for s in d["shots"]] if d.get("shots") is not None else None,
        )


def _compile_pair_clip(group: Dict[str, Any], n_frames: int,
                       amplitude: float = 1.0) -> Optional[np.ndarray]:
    """Compile one synchronized interaction group into a (n_frames, 60) clip.

    Returns None if the pair action is not renderable (caller falls back to
    per-actor compilation so we never drop motion).
    """
    from .puppet.choreography import build_combat_pair
    from .interactions import pair_action_for

    action = pair_action_for(group["attacker_action"], group["defender_action"],
                             group.get("interaction"))
    try:
        clip = build_combat_pair(action, duration_s=max(0.4, n_frames / FPS),
                                 amplitude=amplitude)
    except Exception:
        return None
    T = clip.shape[0]
    if T >= n_frames:
        return clip[:n_frames]
    pad = np.tile(clip[-1:], (n_frames - T, 1))
    return np.concatenate([clip, pad], axis=0)


def _compile_interaction_scene(
    script: SceneScript,
    actor_ids: List[str],
    start_x: Dict[str, float],
    overlap_frames: int = 8
) -> Dict[str, Any]:
    """Compile multi-actor interaction scene sequentially preserving continuous root handoffs."""
    from .interactions import resolve_interactions, compile_interaction_pair
    from .sequencer import blend_feature_clips
    from .rig import enforce_ground_contact

    segments = resolve_interactions(script.beats)
    actor_clips: Dict[str, List[np.ndarray]] = {aid: [] for aid in actor_ids}
    # Per-clip: should the blend preserve the clip's absolute root position?
    # Paired/interaction clips are staged in world space and must NOT be
    # re-anchored, or the two fighters drift apart again.
    actor_handoff: Dict[str, List[bool]] = {aid: [] for aid in actor_ids}
    current_x: Dict[str, float] = {aid: float(start_x.get(aid, 0.0)) for aid in actor_ids}
    vfx_events: List[Dict[str, Any]] = []
    interactions_list: List[Dict[str, Any]] = []
    total_frames = 0

    for seg in segments:
        dur = seg["duration_s"]
        speed = seg.get("speed", 1.0)
        amp = seg.get("amplitude", 1.0)

        if seg["type"] == "interaction":
            atk = seg["attacker"]
            defn = seg["defender"]
            action = seg["action"]
            inter = seg["interaction"]
            def_action = seg.get("defender_action")

            if current_x[atk] <= current_x[defn]:
                pos_b = current_x[defn]
                pos_a = pos_b - 0.90
                facing_a = 1
            else:
                pos_b = current_x[defn]
                pos_a = pos_b + 0.90
                facing_a = -1

            feat_atk, feat_defn, evs = compile_interaction_pair(
                action=action,
                interaction=inter,
                duration_s=dur,
                speed=speed,
                amplitude=amp,
                pos_a=pos_a,
                pos_b=pos_b,
                facing_a=facing_a,
                defender_action=def_action
            )
            seg_len = len(feat_atk)

            for ev in evs:
                ev_shifted = dict(ev)
                ev_shifted["start_frame"] = int(ev.get("start_frame", 0)) + total_frames
                vfx_events.append(ev_shifted)

            interactions_list.append({
                "kind": "interaction",
                "interaction": inter,
                "actors": [actor_ids.index(atk), actor_ids.index(defn)],
                "frame": total_frames,
                "frames": seg_len,
                "clip_index": len(actor_clips[atk]),
            })

            actor_clips[atk].append(feat_atk)
            actor_clips[defn].append(feat_defn)
            actor_handoff[atk].append(False)
            actor_handoff[defn].append(False)
            current_x[atk] = float(feat_atk[-1, 0])
            current_x[defn] = float(feat_defn[-1, 0])

            for other_id in actor_ids:
                if other_id not in (atk, defn):
                    feat_idle = build_motion_from_action("idle", duration_s=dur, start_x=current_x[other_id])
                    if len(feat_idle) < seg_len:
                        pad = np.tile(feat_idle[-1:], (seg_len - len(feat_idle), 1))
                        feat_idle = np.concatenate([feat_idle, pad], axis=0)
                    else:
                        feat_idle = feat_idle[:seg_len]
                    actor_clips[other_id].append(feat_idle)
                    actor_handoff[other_id].append(True)

            total_frames += seg_len

        else:
            actor = seg["actor"]
            action = seg["action"]
            feat_solo, evs = build_motion_from_action(
                action, duration_s=dur, speed=speed, amplitude=amp,
                direction=seg.get("direction", 1), start_x=current_x[actor],
                return_events=True
            )
            seg_len = len(feat_solo)
            for ev in evs:
                ev_shifted = dict(ev)
                ev_shifted["start_frame"] = int(ev.get("start_frame", 0)) + total_frames
                vfx_events.append(ev_shifted)

            actor_clips[actor].append(feat_solo)
            actor_handoff[actor].append(True)
            current_x[actor] = float(feat_solo[-1, 0])

            for other_id in actor_ids:
                if other_id != actor:
                    feat_idle = build_motion_from_action("idle", duration_s=dur, start_x=current_x[other_id])
                    if len(feat_idle) < seg_len:
                        pad = np.tile(feat_idle[-1:], (seg_len - len(feat_idle), 1))
                        feat_idle = np.concatenate([feat_idle, pad], axis=0)
                    else:
                        feat_idle = feat_idle[:seg_len]
                    actor_clips[other_id].append(feat_idle)
                    actor_handoff[other_id].append(True)

            total_frames += seg_len

    compiled_tracks = []
    for aid in actor_ids:
        clips = actor_clips[aid]
        if not clips:
            feat_idle = build_motion_from_action("idle", duration_s=1.0, start_x=start_x.get(aid, 0.0))
            compiled_tracks.append(enforce_ground_contact(feat_idle))
            continue
        # Record the real (post-blend) start frame of each clip so doctor/preview
        # windows line up with the final stitched timeline.
        actual_offsets = [0]
        cur = clips[0]
        for i, next_clip in enumerate(clips[1:], start=1):
            ov = min(overlap_frames, max(1, len(cur)//4), max(1, len(next_clip)//4))
            actual_offsets.append(len(cur) - ov)
            cur = blend_feature_clips(cur, next_clip, overlap_frames=ov,
                                      handoff=actor_handoff[aid][i])
        for iv in interactions_list:
            if aid in (actor_ids[iv["actors"][0]],):
                ci = iv.get("clip_index")
                if ci is not None and ci < len(actual_offsets):
                    iv["frame"] = actual_offsets[ci]
        compiled_tracks.append(enforce_ground_contact(cur))

    max_T = max(len(t) for t in compiled_tracks)
    padded = []
    for t in compiled_tracks:
        if len(t) < max_T:
            pad = np.tile(t[-1:], (max_T - len(t), 1))
            t = np.concatenate([t, pad], axis=0)
        padded.append(t)

    full_feat = np.concatenate(padded, axis=-1)
    return {
        "feat": full_feat,
        "n_person": len(padded),
        "T": max_T,
        "duration_seconds": max_T / FPS,
        "fps": FPS,
        "vfx_events": vfx_events,
        "interactions": interactions_list,
    }


def compile_scene(script: SceneScript, overlap_frames: int = 8,
                  resolve_props: bool = True) -> Dict[str, Any]:
    """Deterministically compile a SceneScript into motion + events."""
    if script.shots:
        shot_timelines = []
        for s in script.shots:
            s_dict = dict(s)
            shot_dict = {
                **script.to_dict(),
                **s_dict,
            }
            shot_dict["shots"] = None  # prevent recursion
            shot_script = SceneScript.from_dict(shot_dict)
            shot_tl = compile_scene(shot_script, overlap_frames=overlap_frames, resolve_props=False)
            shot_timelines.append(shot_tl)

        feats = [tl["feat"] for tl in shot_timelines]
        full_feat = np.concatenate(feats, axis=0)
        max_T = len(full_feat)
        merged_events = []
        frame_offset = 0
        for tl in shot_timelines:
            for ev in tl.get("vfx_events", []):
                merged_events.append({**ev, "start_frame": ev.get("start_frame", 0) + frame_offset})
            frame_offset += tl["T"]

        result = {
            "feat": full_feat,
            "n_person": shot_timelines[0]["n_person"],
            "T": max_T,
            "duration_seconds": max_T / FPS,
            "fps": FPS,
            "vfx_events": merged_events,
            "title": script.title,
            "theme": script.theme,
            "scenery": dict(script.scenery),
            "camera": dict(script.camera),
            "characters": shot_timelines[0]["characters"],
            "actor_colors": [{c.id: getattr(c, "color", None) for c in script.characters}.get(aid) for aid in shot_timelines[0]["characters"]],
        }
        merged_expr = []
        for tl in shot_timelines:
            if "actor_expression_tracks" in tl:
                merged_expr.extend(tl["actor_expression_tracks"])
        if merged_expr:
            result["actor_expression_tracks"] = merged_expr
        if resolve_props:
            from .renderer import decode_motion_features
            from .objects import evaluate_objects
            from .camera import compute_camera

            joints = decode_motion_features(result["feat"])
            prop_tracks, impacts = evaluate_objects(
                script.objects, joints, fps=script.fps, T=result["T"], actor_ids=result["characters"])
            result["prop_tracks"] = prop_tracks
            result["impacts"] = impacts
            cam_spec = dict(script.camera) if script.camera else {}
            cam_spec.setdefault("actors", result["characters"])
            result["camera_track"] = compute_camera(joints, cam_spec, fps=script.fps)
        return result

    if not script.beats:
        raise ValueError("SceneScript has no beats; nothing to compile.")

    # Stable actor ordering: declared characters first, then any referenced.
    actor_ids: List[str] = [c.id for c in script.characters]
    for b in script.beats:
        if b.actor not in actor_ids:
            actor_ids.append(b.actor)
        if getattr(b, "target", None) and b.target not in actor_ids:
            actor_ids.append(b.target)
    start_x = {c.id: c.start_x for c in script.characters}

    has_interactions = any(getattr(b, "target", None) is not None for b in script.beats)

    if has_interactions:
        result = _compile_interaction_scene(script, actor_ids, start_x, overlap_frames=overlap_frames)
    else:
        seq = PuppetSequencer(overlap_frames=overlap_frames)
        for aid in actor_ids:
            seq.get_or_create_actor(aid, initial_x=start_x.get(aid, 0.0))
        for b in script.beats:
            seq.get_or_create_actor(b.actor, initial_x=start_x.get(b.actor, 0.0)).add_step(
                action=b.action,
                duration_seconds=b.duration_s,
                speed=b.speed,
                amplitude=b.amplitude,
                direction=b.direction,
                seed=0,
            )
        result = seq.build()

    result["title"] = script.title
    result["theme"] = script.theme
    result["scenery"] = dict(script.scenery)
    result["camera"] = dict(script.camera)
    result["characters"] = actor_ids
    result["actor_expression_tracks"] = _build_expression_tracks(script, actor_ids, result["T"], fps=script.fps)
    color_map = {c.id: getattr(c, "color", None) for c in script.characters}
    result["actor_colors"] = [color_map.get(aid) for aid in actor_ids]

    if resolve_props:
        from .renderer import decode_motion_features
        from .objects import evaluate_objects
        from .camera import compute_camera

        joints = decode_motion_features(result["feat"])
        prop_tracks, impacts = evaluate_objects(
            script.objects, joints, fps=script.fps, T=result["T"], actor_ids=actor_ids)
        result["prop_tracks"] = prop_tracks
        result["impacts"] = impacts
        cam_spec = dict(script.camera) if script.camera else {}
        cam_spec.setdefault("actors", actor_ids)
        result["camera_track"] = compute_camera(joints, cam_spec, fps=script.fps)
    return result


def _build_expression_tracks(script: SceneScript, actor_ids: List[str], T: int, fps: int = FPS) -> List[List[str]]:
    """Builds (T, N) per-frame expression strings for all actors."""
    from .contract import resolve_expression
    char_map = {c.id: resolve_expression(getattr(c, "expression", None)) or "neutral" for c in script.characters}
    actor_changes: Dict[str, List[Tuple[int, str]]] = {aid: [] for aid in actor_ids}

    actor_t: Dict[str, float] = {aid: 0.0 for aid in actor_ids}
    for b in script.beats:
        aid = b.actor
        at = b.at_s if b.at_s is not None else actor_t.get(aid, 0.0)
        start_f = int(round(at * fps))
        raw_expr = getattr(b, "expression", None)
        expr = resolve_expression(raw_expr) if raw_expr else None
        if expr:
            actor_changes[aid].append((start_f, expr))
        actor_t[aid] = at + b.duration_s

    tracks: List[List[str]] = []
    for t in range(T):
        frame_exprs = []
        for aid in actor_ids:
            active = char_map.get(aid, "neutral")
            for cf, cexpr in actor_changes.get(aid, []):
                if t >= cf:
                    active = cexpr
            frame_exprs.append(active)
        tracks.append(frame_exprs)
    return tracks


def compile_scene_dict(scene: Dict[str, Any], overlap_frames: int = 8) -> Dict[str, Any]:
    """Validate a contract scene dict, then compile it. Fail-fast on bad worlds."""
    from .contract import validate_scene
    validated, _ = validate_scene(scene)
    return compile_scene(SceneScript.from_dict(validated), overlap_frames=overlap_frames)


# ------------------------------------------------------------------ text -> plan
def _duration_after(text: str, term: str, pos: int, default: float) -> float:
    """Find a duration (e.g. '3s', '2 seconds') near a matched term."""
    import re
    window = text[pos + len(term): pos + len(term) + 24]
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b", window)
    if m:
        try:
            v = float(m.group(1))
            if 0.5 <= v <= 30.0:
                return v
        except ValueError:
            pass
    return default


def parse_script(prompt: str, default_duration: float = 2.0,
                 seed: int = 0) -> SceneScript:
    """Deterministic free-text -> SceneScript. Preserves clause order.

    Never silently collapses a multi-action script to one action: every matched
    clause becomes a beat. Raises ValueError only when *no* action is found.
    """
    from .parser import match_actions, parse_prompt
    text = (prompt or "").strip().lower()
    if not text:
        raise ValueError("Empty prompt.")

    hits = match_actions(text)

    if not hits:
        # Delegate to parse_prompt for its precise error message.
        parse_prompt(prompt, seed=seed)
        raise ValueError(f"Unsupported prompt: could not match an action in '{prompt}'.")

    has_pair = any(a in PAIR_ACTIONS for _, a, _ in hits)
    script = SceneScript(title=prompt[:60] or "scene")

    # Multi-actor cue: explicit pair phrase, or wording implying two figures.
    import re as _re
    two_actor_cue = bool(_re.search(
        r"\b(two|both|each other|versus|vs)\b", text)) or (" one " in f" {text} " and " other " in f" {text} ")

    if has_pair or (two_actor_cue and len(hits) >= 2):
        script.characters = [Character("a", ACTOR_A_X), Character("b", ACTOR_B_X)]
    else:
        script.characters = [Character("a", 0.0)]

    # Global modifiers (direction/speed/amplitude) apply to every beat for now.
    try:
        mods = parse_prompt(prompt, default_duration=default_duration, seed=seed)
    except ValueError:
        mods = {}
    direction = int(mods.get("direction", 1))
    speed = float(mods.get("speed", 1.0))
    amplitude = float(mods.get("amplitude", 1.0))

    for pos, action, term in hits:
        dur = _duration_after(text, term, pos, default_duration)
        # Collapse consecutive duplicate actions ("celebrates victory" matches
        # both "celebrate" and "victory"): merge the duration into the last beat.
        if script.beats and script.beats[-1].action == action and action not in PAIR_ACTIONS:
            script.beats[-1].duration_s = max(script.beats[-1].duration_s, dur)
            continue
        if action in PAIR_ACTIONS:
            for actor_key, one_p in PAIR_EXPANSION[action]:
                script.beats.append(Beat(action=one_p, duration_s=dur, actor=actor_key,
                                         direction=direction, speed=speed, amplitude=amplitude))
        else:
            # In a 2-actor scene, a solo beat defaults to the primary actor "a".
            script.beats.append(Beat(action=action, duration_s=dur, actor="a",
                                     direction=direction, speed=speed, amplitude=amplitude))
    return script
