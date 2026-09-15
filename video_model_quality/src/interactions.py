"""Multi-actor interaction engine: reactions, staging, paired combat, and aimed limbs.

Transforms multi-actor scenes from independent 'soloists' into physically coupled,
synchronized choreography.
"""

from typing import Any, Dict, List, Optional, Set, Tuple
import numpy as np

from src.rig import FPS, GROUND_Y
from src.puppet.choreography import build_combat_pair
from src.puppet.combat_ik import solve_aimed_limb

INTERACTIONS: Tuple[str, ...] = (
    "strike", "block", "dodge", "grab", "knockdown", "assist", "talk"
)

# Maps (attacker_action, interaction) -> defender_reaction_action
REACTION_MAP: Dict[Tuple[str, str], str] = {
    ("punch", "strike"): "block",
    ("punch", "block"): "block",
    ("punch", "dodge"): "squat",
    ("punch", "knockdown"): "knockdown",
    ("punch", "grab"): "block",
    ("kick", "strike"): "squat",
    ("kick", "dodge"): "squat",
    ("kick", "block"): "block",
    ("kick", "knockdown"): "knockdown",
}

# Fallback reaction action by interaction enum alone
INTERACTION_DEFAULT_REACTION: Dict[str, str] = {
    "strike": "block",
    "block": "block",
    "dodge": "squat",
    "knockdown": "knockdown",
    "grab": "block",
    "assist": "celebrate",
    "talk": "wave",
}


def get_reaction_action(action: str, interaction: Optional[str] = None) -> str:
    """Determine defender's reaction action for a given attack and interaction."""
    act = (action or "punch").strip().lower()
    inter = (interaction or "strike").strip().lower()
    if (act, inter) in REACTION_MAP:
        return REACTION_MAP[(act, inter)]
    if inter in INTERACTION_DEFAULT_REACTION:
        return INTERACTION_DEFAULT_REACTION[inter]
    return "block"


def pair_action_for(
    attacker_action: str,
    defender_action: Optional[str] = None,
    interaction: Optional[str] = None
) -> str:
    """Select the combat pair choreography template name."""
    act = (attacker_action or "punch").strip().lower()
    inter = (interaction or "").strip().lower()
    def_act = (defender_action or "").strip().lower()

    if inter == "knockdown" or def_act == "knockdown" or act == "knockdown":
        return "knockdown_getup"
    if act == "kick" or inter == "dodge" or def_act in ("squat", "dodge"):
        return "kick_dodge"
    if inter == "exchange" or (act == "punch" and def_act == "punch"):
        return "exchange"
    return "punch_block"


def get_combat_pair_template(
    action: str,
    interaction: Optional[str] = None,
    defender_action: Optional[str] = None
) -> str:
    """Alias for pair_action_for."""
    return pair_action_for(action, defender_action, interaction)


def split_pair(clip_2p: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Split a (T, 60) pair motion into two (T, 30) single-person tracks."""
    return clip_2p[:, :30].copy(), clip_2p[:, 30:].copy()


def translate_to(clip: np.ndarray, target_x: float) -> np.ndarray:
    """Offset root x of clip so that its initial root x equals target_x."""
    out = np.copy(clip)
    delta = float(target_x) - float(out[0, 0])
    out[:, 0] += delta
    return out


def stage_pair_offset(clip_a: np.ndarray, clip_b: np.ndarray, mid_x: float) -> float:
    """Compute shift offset so that the midpoint of clip_a and clip_b starts at mid_x."""
    clip_mid = 0.5 * (float(clip_a[0, 0]) + float(clip_b[0, 0]))
    return float(mid_x - clip_mid)


def stage_for_interaction(
    attacker_x: float,
    defender_x: float,
    desired_gap: float = 0.90
) -> Tuple[float, float, int, int]:
    """Place attacker and defender within striking distance facing each other.

    Returns:
        (pos_a, pos_b, facing_a, facing_b)
    """
    if attacker_x <= defender_x:
        # Attacker on left facing right (+1), Defender on right facing left (-1)
        facing_a = 1
        facing_b = -1
        pos_b = float(defender_x)
        pos_a = float(defender_x - desired_gap)
    else:
        # Attacker on right facing left (-1), Defender on left facing right (+1)
        facing_a = -1
        facing_b = 1
        pos_b = float(defender_x)
        pos_a = float(defender_x + desired_gap)
    return pos_a, pos_b, facing_a, facing_b


def blend_overwrite(
    compiled_track: np.ndarray,
    clip: np.ndarray,
    start_frame: int,
    blend_frames: int = 8
) -> np.ndarray:
    """Smoothly splice a clip into compiled_track starting at start_frame.

    Uses cosine-eased crossfade over blend_frames at the boundaries.
    """
    T_track = len(compiled_track)
    T_clip = len(clip)
    end_frame = start_frame + T_clip

    if end_frame > T_track:
        pad_len = end_frame - T_track
        last_frame = np.tile(compiled_track[-1:], (pad_len, 1))
        out = np.concatenate([compiled_track, last_frame], axis=0)
    else:
        out = np.copy(compiled_track)

    if start_frame >= len(out):
        return out

    actual_end = min(end_frame, len(out))
    clip_len = actual_end - start_frame
    if clip_len <= 0:
        return out

    actual_clip = clip[:clip_len]
    bf = min(blend_frames, clip_len // 2, start_frame)
    if bf <= 0:
        out[start_frame:actual_end] = actual_clip
        return out

    # Start blend
    w_in = 0.5 * (1.0 - np.cos(np.pi * np.linspace(0.0, 1.0, bf, endpoint=True)))[:, None]
    out[start_frame:start_frame + bf, :2] = (
        (1.0 - w_in) * out[start_frame:start_frame + bf, :2] +
        w_in * actual_clip[:bf, :2]
    )
    sc_track = out[start_frame:start_frame + bf, 2:].reshape(bf, -1, 2)
    sc_clip = actual_clip[:bf, 2:].reshape(bf, -1, 2)
    w_in_3d = w_in[:, :, None]
    sc_blend = (1.0 - w_in_3d) * sc_track + w_in_3d * sc_clip
    norm = np.sqrt(np.sum(sc_blend ** 2, axis=-1, keepdims=True)) + 1e-8
    out[start_frame:start_frame + bf, 2:] = (sc_blend / norm).reshape(bf, -1)

    # Core
    out[start_frame + bf:actual_end - bf] = actual_clip[bf:clip_len - bf]

    # End blend
    if actual_end < len(out):
        tail_bf = min(blend_frames, len(out) - actual_end, clip_len // 2)
        if tail_bf > 0:
            w_out = 0.5 * (1.0 - np.cos(np.pi * np.linspace(1.0, 0.0, tail_bf, endpoint=True)))[:, None]
            out[actual_end - tail_bf:actual_end, :2] = (
                w_out * actual_clip[clip_len - tail_bf:, :2] +
                (1.0 - w_out) * out[actual_end - tail_bf:actual_end, :2]
            )
            sc_tail = out[actual_end - tail_bf:actual_end, 2:].reshape(tail_bf, -1, 2)
            sc_clip_tail = actual_clip[clip_len - tail_bf:, 2:].reshape(tail_bf, -1, 2)
            w_out_3d = w_out[:, :, None]
            sc_blend_tail = w_out_3d * sc_clip_tail + (1.0 - w_out_3d) * sc_tail
            norm_tail = np.sqrt(np.sum(sc_blend_tail ** 2, axis=-1, keepdims=True)) + 1e-8
            out[actual_end - tail_bf:actual_end, 2:] = (sc_blend_tail / norm_tail).reshape(tail_bf, -1)
    else:
        out[start_frame + bf:actual_end] = actual_clip[bf:]

    return out


def group_interactions(beats: List[Any]) -> Tuple[List[Dict[str, Any]], Set[int]]:
    """Group targeted beats into paired interaction specifications.

    Returns (groups, paired_beat_ids) where paired_beat_ids contains id(b) of beats
    that are part of an interaction group.
    """
    groups: List[Dict[str, Any]] = []
    paired_ids: Set[int] = set()

    for i, b in enumerate(beats):
        if id(b) in paired_ids:
            continue
        target = getattr(b, "target", None) if hasattr(b, "target") else (b.get("target") if isinstance(b, dict) else None)
        if not target:
            continue

        actor = getattr(b, "actor", "a") if hasattr(b, "actor") else b.get("actor", "a")
        action = getattr(b, "action", "punch") if hasattr(b, "action") else b.get("action", "punch")
        dur = float(getattr(b, "duration_s", 2.0) if hasattr(b, "duration_s") else b.get("duration_s", 2.0))
        inter = getattr(b, "interaction", "strike") if hasattr(b, "interaction") else b.get("interaction", "strike")

        paired_ids.add(id(b))

        # Look for defender's counter beat
        defender_action = None
        for j in range(i + 1, len(beats)):
            cand = beats[j]
            if id(cand) in paired_ids:
                continue
            c_actor = getattr(cand, "actor", None) if hasattr(cand, "actor") else cand.get("actor")
            c_target = getattr(cand, "target", None) if hasattr(cand, "target") else cand.get("target")
            if c_actor == target and (c_target == actor or c_target is None):
                defender_action = getattr(cand, "action", None) if hasattr(cand, "action") else cand.get("action")
                paired_ids.add(id(cand))
                break

        if defender_action is None:
            defender_action = get_reaction_action(action, inter)

        groups.append({
            "attacker": actor,
            "defender": target,
            "attacker_action": action,
            "defender_action": defender_action,
            "interaction": inter or "strike",
            "duration_s": dur,
        })

    return groups, paired_ids


def compile_interaction_pair(
    action: str,
    interaction: str = "strike",
    duration_s: float = 2.0,
    speed: float = 1.0,
    amplitude: float = 1.0,
    pos_a: float = -0.45,
    pos_b: float = 0.45,
    facing_a: int = 1,
    defender_action: Optional[str] = None,
    seed: int = 0
) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]]]:
    """Compile synchronized motion features for attacker and defender during an interaction.

    Returns:
        (feat_attacker, feat_defender, events)
        where feat_attacker and feat_defender are each (T, 30).
    """
    template = pair_action_for(action, defender_action, interaction)
    feat_60, events = build_combat_pair(
        template,
        duration_s=duration_s,
        speed=speed,
        amplitude=amplitude,
        seed=seed,
        return_events=True
    )

    feat_a, feat_b = split_pair(feat_60)

    if facing_a >= 0:
        feat_a[:, 0] += (pos_a - (-0.45))
        feat_b[:, 0] += (pos_b - (+0.45))
        out_a, out_b = feat_a, feat_b
        out_events = events
    else:
        feat_a[:, 0] = -feat_a[:, 0]
        feat_b[:, 0] = -feat_b[:, 0]
        feat_a[:, 0] += (pos_a - (+0.45))
        feat_b[:, 0] += (pos_b - (-0.45))
        out_a, out_b = feat_a, feat_b
        out_events = []
        for ev in events:
            nev = dict(ev)
            if "direction" in nev:
                nev["direction"] = -nev["direction"]
            out_events.append(nev)

    return out_a.astype(np.float32), out_b.astype(np.float32), out_events


def aim_strike_at_target(
    root_xy: np.ndarray,
    base_angles: np.ndarray,
    target_xy: np.ndarray,
    end_joint: str = "hand_r"
) -> Tuple[np.ndarray, float, float]:
    """Aim striking limb at a world-space target position using analytic IK.

    Returns (angles14, residual, lean_used).
    """
    return solve_aimed_limb(root_xy, base_angles, target_xy, end_joint=end_joint)


def resolve_interactions(
    beats: List[Any],
    actors: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    """Inspects beats, identifies targeted beats, and resolves interaction segments in chronological order."""
    resolved: List[Dict[str, Any]] = []
    consumed_indices = set()

    for i, b in enumerate(beats):
        if i in consumed_indices:
            continue
        target = getattr(b, "target", None) if hasattr(b, "target") else (b.get("target") if isinstance(b, dict) else None)
        actor = getattr(b, "actor", "a") if hasattr(b, "actor") else b.get("actor", "a")
        action = getattr(b, "action", "walk") if hasattr(b, "action") else b.get("action", "walk")
        dur = float(getattr(b, "duration_s", 2.0) if hasattr(b, "duration_s") else b.get("duration_s", 2.0))
        speed = float(getattr(b, "speed", 1.0) if hasattr(b, "speed") else b.get("speed", 1.0))
        amp = float(getattr(b, "amplitude", 1.0) if hasattr(b, "amplitude") else b.get("amplitude", 1.0))
        direction = int(getattr(b, "direction", 1) if hasattr(b, "direction") else b.get("direction", 1))

        if not target:
            resolved.append({
                "type": "solo",
                "actor": actor,
                "action": action,
                "duration_s": dur,
                "speed": speed,
                "amplitude": amp,
                "direction": direction,
            })
            continue

        # Targeted beat: find defender's counter beat if present
        defender_action = None
        inter = getattr(b, "interaction", "strike") if hasattr(b, "interaction") else b.get("interaction", "strike")
        for j in range(i + 1, len(beats)):
            if j in consumed_indices:
                continue
            cand = beats[j]
            c_actor = getattr(cand, "actor", None) if hasattr(cand, "actor") else cand.get("actor")
            c_target = getattr(cand, "target", None) if hasattr(cand, "target") else cand.get("target")
            c_action = getattr(cand, "action", None) if hasattr(cand, "action") else cand.get("action")
            if c_actor == target and (c_target == actor or c_target is None):
                if c_action in ("block", "dodge", "squat", "knockdown", "getup") or c_target is None:
                    defender_action = c_action
                    consumed_indices.add(j)
                    break
            break

        if defender_action is None:
            defender_action = get_reaction_action(action, inter)

        template = pair_action_for(action, defender_action, inter)
        if template == "punch_block":
            impact_t = 0.65 / max(0.1, speed)
        elif template == "kick_dodge":
            impact_t = 0.70 / max(0.1, speed)
        elif template == "knockdown_getup":
            impact_t = 0.55 / max(0.1, speed)
        elif template == "exchange":
            impact_t = 0.45 / max(0.1, speed)
        else:
            impact_t = 0.40 * dur

        resolved.append({
            "type": "interaction",
            "attacker": actor,
            "defender": target,
            "action": action,
            "interaction": inter or "strike",
            "defender_action": defender_action,
            "template": template,
            "duration_s": dur,
            "speed": speed,
            "amplitude": amp,
            "impact_time_s": impact_t,
            "impact_frame": int(round(impact_t * FPS)),
        })

    return resolved
