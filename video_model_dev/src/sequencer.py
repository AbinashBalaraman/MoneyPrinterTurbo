"""Compositional timeline sequencer with continuous pose, velocity, and root handoff.

Enables chaining arbitrary actions (e.g., Walk -> Wave -> Jump -> Idle)
with cosine-eased angle blending and continuous root translation.
"""

import numpy as np
from typing import List, Dict, Any, Optional, Union

from .rig import FPS, decode, encode, N_BONES, FEAT_DIM
from .puppet.choreography import build_motion_from_action
from .parser import parse_prompt
from .catalog import validate_action_params


def blend_feature_clips(feat_a: np.ndarray, feat_b: np.ndarray, overlap_frames: int = 8) -> np.ndarray:
    """Seamlessly blend two single-person motion feature clips (T1, 30) and (T2, 30).
    
    Carries over root position from the end of clip A to clip B and applies
    cosine-eased S-curve interpolation over normalized sin/cos bone angles.
    """
    T1 = len(feat_a)
    T2 = len(feat_b)
    
    if overlap_frames <= 0 or T1 < overlap_frames or T2 < overlap_frames:
        # Hard cut without overlap, but with root position offset handoff
        root_a_end = feat_a[-1, :2]
        root_b_start = feat_b[0, :2]
        offset = root_a_end - root_b_start
        feat_b_offset = np.copy(feat_b)
        feat_b_offset[:, :2] += offset
        return np.concatenate([feat_a, feat_b_offset], axis=0)

    # Decode roots and sin/cos
    root_a = feat_a[:, :2]
    sc_a = feat_a[:, 2:].reshape(T1, N_BONES, 2)
    
    root_b = np.copy(feat_b[:, :2])
    sc_b = np.copy(feat_b[:, 2:].reshape(T2, N_BONES, 2))
    
    # 1. Root handoff: offset clip B so its start matches clip A's position at the start of overlap
    overlap_start_a = T1 - overlap_frames
    root_offset = root_a[overlap_start_a] - root_b[0]
    root_b += root_offset

    # Non-overlapping prefix of A
    prefix_root = root_a[:overlap_start_a]
    prefix_sc = sc_a[:overlap_start_a]
    
    # Non-overlapping suffix of B
    suffix_root = root_b[overlap_frames:]
    suffix_sc = sc_b[overlap_frames:]
    
    # Blended transition window
    # Smooth S-curve weights via cosine easing: 0 -> 1
    t = np.linspace(0.0, 1.0, overlap_frames, endpoint=True)[:, None]
    weights = 0.5 * (1.0 - np.cos(np.pi * t))  # (overlap_frames, 1)
    
    window_a_root = root_a[overlap_start_a:]
    window_b_root = root_b[:overlap_frames]
    blend_root = (1.0 - weights) * window_a_root + weights * window_b_root
    
    # Interpolate sin/cos pairs and re-normalize onto unit circle
    weights_sc = weights[:, :, None]  # (overlap_frames, 1, 1)
    window_a_sc = sc_a[overlap_start_a:]
    window_b_sc = sc_b[:overlap_frames]
    blend_sc = (1.0 - weights_sc) * window_a_sc + weights_sc * window_b_sc
    norm = np.sqrt(np.sum(blend_sc ** 2, axis=-1, keepdims=True)) + 1e-8
    blend_sc = blend_sc / norm

    # Reconstruct full blended motion
    out_root = np.concatenate([prefix_root, blend_root, suffix_root], axis=0)
    out_sc = np.concatenate([prefix_sc, blend_sc, suffix_sc], axis=0)
    
    out_feat = np.concatenate([out_root, out_sc.reshape(-1, N_BONES * 2)], axis=-1)
    return out_feat.astype(np.float32)


class ActorTrack:
    """Manages an ordered sequence of action clips for a single stickman."""

    def __init__(self, actor_id: str = "actor_0", initial_x: float = 0.0):
        self.actor_id = actor_id
        self.initial_x = initial_x
        self.steps: List[Dict[str, Any]] = []

    def add_step(self, action: str, duration_seconds: float = 3.0,
                 speed: float = 1.0, amplitude: float = 1.0,
                 direction: int = 1, seed: int = 0) -> "ActorTrack":
        """Add an action step to this actor's timeline."""
        validated = validate_action_params(action, {
            "duration_seconds": duration_seconds,
            "speed": speed,
            "amplitude": amplitude,
            "direction": direction,
            "seed": seed
        })
        self.steps.append({"action": action, **validated})
        return self

    def compile(self, overlap_frames: int = 8, return_events: bool = False):
        """Stitch all steps into a continuous motion feature array (T, 30). Fail-fast: pure puppet, no sine fallback.

        With return_events=True, returns (feat, events) where each clip's events
        carry start_frame shifted by the cumulative timeline offset (mirroring
        the blend loop: offset += len(prev) - overlap_frames, hard-cut aware).
        """
        if not self.steps:
            # Return 1 second of default idle via puppet engine
            feat = build_motion_from_action("idle", duration_s=1.0, start_x=self.initial_x)
            if return_events:
                return feat, []
            return feat

        clips: List[np.ndarray] = []
        clip_events: List[List[Dict[str, Any]]] = []
        for step in self.steps:
            # Fail-fast: let puppet errors surface instead of silently falling back to sine
            feat, events = build_motion_from_action(
                action=step["action"],
                duration_s=step.get("duration_seconds", 3.0),
                speed=step.get("speed", 1.0),
                amplitude=step.get("amplitude", 1.0),
                direction=step.get("direction", 1),
                seed=step.get("seed", 0),
                return_events=True
            )
            clips.append(feat)
            clip_events.append(events)

        current = clips[0]
        current[:, 0] += self.initial_x

        # Shift each clip's events by its start offset in the stitched timeline.
        shifted: List[Dict[str, Any]] = []
        offset = 0
        for ev in clip_events[0]:
            shifted.append({**ev, "start_frame": int(ev.get("start_frame", 0)) + offset})
        for i, next_clip in enumerate(clips[1:]):
            t1, t2 = len(current), len(next_clip)
            hard_cut = overlap_frames <= 0 or t1 < overlap_frames or t2 < overlap_frames
            offset = t1 if hard_cut else t1 - overlap_frames
            for ev in clip_events[i + 1]:
                shifted.append({**ev, "start_frame": int(ev.get("start_frame", 0)) + offset})
            current = blend_feature_clips(current, next_clip, overlap_frames=overlap_frames)

        if return_events:
            return current, shifted
        return current


class PuppetSequencer:
    """Compositional timeline builder for single and multi-person scenes."""

    def __init__(self, overlap_frames: int = 8):
        self.overlap_frames = overlap_frames
        self.tracks: Dict[str, ActorTrack] = {}

    def get_or_create_actor(self, actor_id: str = "actor_0", initial_x: float = 0.0) -> ActorTrack:
        if actor_id not in self.tracks:
            self.tracks[actor_id] = ActorTrack(actor_id=actor_id, initial_x=initial_x)
        return self.tracks[actor_id]

    def sequence(self, actor_id: str, steps: List[Dict[str, Any]]) -> "PuppetSequencer":
        track = self.get_or_create_actor(actor_id)
        for s in steps:
            track.add_step(**s)
        return self

    def build(self) -> Dict[str, Any]:
        """Compile all actor tracks and synchronize timeline duration."""
        if not self.tracks:
            raise ValueError("Cannot build empty timeline. Add steps first.")

        compiled_tracks = []
        track_events: List[List[Dict[str, Any]]] = []
        for track in self.tracks.values():
            feat, events = track.compile(overlap_frames=self.overlap_frames,
                                         return_events=True)
            compiled_tracks.append(feat)
            track_events.append(events)
        
        # Synchronize lengths to the maximum track length
        max_T = max(len(t) for t in compiled_tracks)
        padded_tracks = []
        for t in compiled_tracks:
            if len(t) < max_T:
                # Pad with last pose repeated
                pad_len = max_T - len(t)
                last_frame = np.tile(t[-1:], (pad_len, 1))
                t_padded = np.concatenate([t, last_frame], axis=0)
            else:
                t_padded = t
            padded_tracks.append(t_padded)

        # Concatenate across actors: (T, 30 * N)
        full_feat = np.concatenate(padded_tracks, axis=-1)
        n_person = len(padded_tracks)

        # Gather VFX events stamped with their actor index. Padded tail frames
        # repeat the last pose, so events need no shifting for padding.
        vfx_events: List[Dict[str, Any]] = []
        for actor_idx, events in enumerate(track_events):
            for ev in events:
                vfx_events.append({**ev, "anchor_puppet": actor_idx})

        return {
            "feat": full_feat,
            "n_person": n_person,
            "T": max_T,
            "duration_seconds": max_T / FPS,
            "fps": FPS,
            "vfx_events": vfx_events
        }


def sequence_prompts(prompt_list: List[str], actor_id: str = "actor_0",
                     initial_x: float = 0.0, overlap_frames: int = 8) -> Dict[str, Any]:
    """Convenience helper to sequence a chain of natural text prompts into a video motion."""
    seq = PuppetSequencer(overlap_frames=overlap_frames)
    track = seq.get_or_create_actor(actor_id, initial_x=initial_x)
    for p in prompt_list:
        parsed = parse_prompt(p)
        track.add_step(
            action=parsed["action"],
            duration_seconds=parsed.get("duration_seconds", 3.0),
            speed=parsed.get("speed", 1.0),
            amplitude=parsed.get("amplitude", 1.0),
            direction=parsed.get("direction", 1),
            seed=parsed.get("seed", 0)
        )
    return seq.build()
