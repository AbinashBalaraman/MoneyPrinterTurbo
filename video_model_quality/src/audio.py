"""Event-driven sound, derived from the motion -- never authored by hand.

The clip already knows where every impact, footfall and fast limb is: the
choreographer emits ``vfx_events``, the rig knows when a foot is planted, and
the combat solver knows when two limbs touch. So the soundtrack is *computed*
from the same timeline that drives the picture, which means it can never drift
out of sync -- there is no second timeline to maintain.

Design notes:
  * Everything is synthesised with numpy, so there are no audio assets to ship
    and no licences to track. Output is a mono 44.1 kHz WAV.
  * Synthesis is deterministic: same timeline + same seed -> byte-identical WAV.
  * Muxing is a stream copy of the video, so adding sound never re-renders or
    re-compresses the picture.
"""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from src.renderer import decode_motion_features
from src.rig import BONES, FPS, GROUND_Y, decode

SAMPLE_RATE = 44100

# A foot is "planted" inside this band -- the same tolerance the visual
# inspector uses, so picture and sound agree on what counts as a footfall.
CONTACT_TOL = 0.008
# Angular speed (rad/s) at which a limb starts to whistle through the air.
WHOOSH_MIN_RAD_S = 9.0
# Catalog categories whose actions throw a limb (see ACTION_METADATA).
STRIKE_CATEGORIES = ("combat", "combat_pair")

_ARM_LEG = (4, 5, 6, 7, 8, 9, 11, 12)  # indices into BONES: arms + legs


def _strike_actions(actions: Optional[Sequence[str]]) -> List[str]:
    """Filter a timeline's actions down to the ones that throw a limb."""
    from src.catalog import ACTION_METADATA
    out: List[str] = []
    for a in actions or []:
        cat = str((ACTION_METADATA.get(a) or {}).get("category", ""))
        if cat in STRIKE_CATEGORIES:
            out.append(a)
    return out


# --------------------------------------------------------------------------- #
# Synthesis primitives
# --------------------------------------------------------------------------- #
def _onepole(x: np.ndarray, cutoff_hz: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """One-pole low-pass as an exponential-kernel convolution (vectorised)."""
    if cutoff_hz >= sr / 2.0:
        return x
    tau = 1.0 / (2.0 * np.pi * cutoff_hz)
    n = max(1, int(tau * sr * 4))
    k = np.exp(-np.arange(n) / (tau * sr))
    k /= k.sum()
    return np.convolve(x, k, mode="same")


def _band(x: np.ndarray, lo: float, hi: float, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Crude band-pass: low-passed minus more-low-passed."""
    return _onepole(x, hi, sr) - _onepole(x, lo, sr)


def _norm(s: np.ndarray, peak: float = 1.0) -> np.ndarray:
    m = float(np.abs(s).max())
    return s * (peak / m) if m > 1e-12 else s


def _footstep(rng: np.random.Generator, strength: float = 1.0) -> np.ndarray:
    """A scuff plus a low thump: heel-strike then body weight."""
    dur = 0.15
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    scuff_env = np.exp(-t / 0.028) * (1.0 - np.exp(-t / 0.0012))
    scuff = _onepole(rng.standard_normal(n), 480.0) * scuff_env
    # Pitch-dropping sine = weight settling.
    f = 98.0 - 45.0 * (t / dur)
    thump = np.sin(2.0 * np.pi * np.cumsum(f) / SAMPLE_RATE) * np.exp(-t / 0.042)
    return _norm(0.55 * scuff + 0.55 * thump, strength)


def _impact(rng: np.random.Generator, strength: float = 1.0) -> np.ndarray:
    """Heavier and longer than a footstep: a crack plus a body thud."""
    dur = 0.34
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    crack = _band(rng.standard_normal(n), 300.0, 5200.0) * np.exp(-t / 0.020)
    f = 150.0 - 95.0 * (t / dur)
    thud = np.sin(2.0 * np.pi * np.cumsum(f) / SAMPLE_RATE) * np.exp(-t / 0.075)
    return _norm(0.45 * crack + 0.75 * thud, strength)


def _whoosh(rng: np.random.Generator, strength: float = 1.0) -> np.ndarray:
    """Air through a fast-moving limb: a swelled band of noise."""
    dur = 0.24
    n = int(dur * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    env = np.sin(np.pi * t / dur) ** 2  # swell in, swell out
    body = _band(rng.standard_normal(n), 700.0, 4200.0)
    return _norm(body * env, 0.85 * strength)


def _music_bed(duration_s: float, rng: np.random.Generator) -> np.ndarray:
    """A quiet two-note drone with a soft heartbeat pulse.

    Deliberately sparse: a bed that competes with the impacts is worse than no
    bed at all.
    """
    n = int(duration_s * SAMPLE_RATE)
    t = np.arange(n) / SAMPLE_RATE
    drone = (np.sin(2.0 * np.pi * 55.0 * t) + 0.6 * np.sin(2.0 * np.pi * 82.5 * t)
             + 0.35 * np.sin(2.0 * np.pi * 110.0 * t))
    # Slow amplitude breathing so the drone is not a dead sine.
    drone *= 0.85 + 0.15 * np.sin(2.0 * np.pi * 0.09 * t)
    pulse = np.zeros(n)
    beat = 0.75  # seconds between pulses
    for k in range(int(duration_s / beat) + 1):
        s = int(k * beat * SAMPLE_RATE)
        seg = min(n - s, int(0.5 * SAMPLE_RATE))
        if seg <= 0:
            break
        tt = np.arange(seg) / SAMPLE_RATE
        pulse[s:s + seg] += np.sin(2.0 * np.pi * 62.0 * tt) * np.exp(-tt / 0.14)
    return 0.055 * _norm(drone) + 0.05 * _norm(pulse)


# --------------------------------------------------------------------------- #
# Event detection -- all derived from the motion
# --------------------------------------------------------------------------- #
def detect_footsteps(feat: np.ndarray, fps: int = FPS) -> List[Dict[str, Any]]:
    """Footfall onsets: the frame a foot lands after being airborne."""
    joints = decode_motion_features(feat)  # (T, N, 15, 2)
    T, N = joints.shape[0], joints.shape[1]
    events: List[Dict[str, Any]] = []
    for n in range(N):
        for foot_j, name in ((10, "footL"), (13, "footR")):
            label = name if N == 1 else f"p{n}_{name}"
            y = joints[:, n, foot_j, 1]
            planted = np.abs(y - GROUND_Y) < CONTACT_TOL
            for t in range(1, T):
                if planted[t] and not planted[t - 1]:
                    # Approach speed over the last few airborne frames sets weight.
                    back = max(0, t - 3)
                    v = float((y[back] - y[t]) * fps / max(1, t - back))
                    events.append({
                        "kind": "footstep", "frame": int(t), "foot": label,
                        "strength": float(np.clip(abs(v) / 2.2, 0.30, 1.0)),
                    })
    events.sort(key=lambda e: e["frame"])
    return events


def split_actors(feat: np.ndarray) -> List[np.ndarray]:
    """Split a (T, 30*N) feature block into N per-actor (T, 30) blocks."""
    feat = np.asarray(feat, dtype=np.float32)
    if feat.ndim != 2 or feat.shape[-1] % 30:
        raise ValueError(f"expected (T, 30*N) features, got {feat.shape}")
    return [feat[:, i * 30:(i + 1) * 30] for i in range(feat.shape[-1] // 30)]


def detect_whooshes(timeline: Dict[str, Any], feat: np.ndarray,
                    fps: int = FPS) -> List[Dict[str, Any]]:
    """Air-swishes on *strikes*.

    Deliberately NOT triggered on raw limb speed. Measured across all 13 single
    actions, every action's peak limb speed sits within ~1.0-1.7x its own p90 --
    a walk reaches 13.9 rad/s and a punch only 13.8. There is no
    fast-strike/slow-windup contrast to threshold on (that absence *is* the
    Phase-2 timing work). A speed gate therefore fires on a walk exactly as
    often as on a punch: an early version produced 27 whooshes for "walk".

    So whooshes key off strike *structure*, which is reliable:
      1. declared ``speed_lines`` VFX -- explicit author intent, and
      2. for clips whose action is a strike category, the limb's peak-speed
         frame (the strike itself).
    """
    events: List[Dict[str, Any]] = []

    # 1. Declared speed-line VFX.
    for ev in timeline.get("vfx_events") or []:
        if isinstance(ev, dict) and str(ev.get("kind", "")).lower() == "speed_lines":
            events.append({
                "kind": "whoosh", "frame": int(ev.get("start_frame", 0)),
                "bone": "declared", "speed": 0.0,
                "strength": float(np.clip(0.5 * float(ev.get("scale", 1.0)), 0.3, 1.0)),
            })

    # 2. Peak-speed frame, only for strike actions.
    if _strike_actions(timeline.get("actions")):
        for n, actor_feat in enumerate(split_actors(feat)):
            _root, ang = decode(actor_feat)
            ang = np.unwrap(np.asarray(ang, dtype=np.float64), axis=0)
            if len(ang) < 3:
                continue
            limb = (np.abs(np.diff(ang, axis=0)) * fps)[:, _ARM_LEG]
            peak = limb.max(axis=1)
            i = int(np.argmax(peak))
            if peak[i] >= WHOOSH_MIN_RAD_S:
                bone = _ARM_LEG[int(limb[i].argmax())]
                events.append({
                    "kind": "whoosh", "frame": int(i + 1), "actor": n,
                    "bone": BONES[bone][0], "speed": float(peak[i]),
                    "strength": float(np.clip(peak[i] / 18.0, 0.25, 1.0)),
                })

    events.sort(key=lambda e: e["frame"])
    return events


def detect_impacts(timeline: Dict[str, Any], feat: np.ndarray,
                   fps: int = FPS) -> List[Dict[str, Any]]:
    """Impact onsets from declared VFX *and* from actual limb contact.

    The single-action combat path declares no VFX events, so we also solve for
    limb-capsule contact onsets directly -- otherwise "punch and block" would be
    silent exactly where it should hit hardest.
    """
    events: List[Dict[str, Any]] = []

    for ev in timeline.get("vfx_events") or []:
        if not isinstance(ev, dict):
            continue
        kind = str(ev.get("kind", "")).lower()
        if any(k in kind for k in ("impact", "clash", "burst", "landing")):
            frame = int(ev.get("start_frame", 0))
            scale = float(ev.get("scale", 1.0))
            events.append({"kind": "impact", "frame": frame,
                           "strength": float(np.clip(0.6 * scale, 0.35, 1.0)),
                           "source": "vfx"})

    for imp in timeline.get("impacts") or []:
        if isinstance(imp, dict) and "frame" in imp:
            events.append({"kind": "impact", "frame": int(imp["frame"]),
                           "strength": float(np.clip(imp.get("strength", 0.8), 0.35, 1.0)),
                           "source": "impact"})

    n_person = int(timeline.get("n_person", 1))
    if n_person >= 2:
        try:
            from src.puppet.combat_ik import capsule_contacts
            joints = decode_motion_features(feat)
            T = joints.shape[0]
            was_touching = False
            for t in range(T):
                touching = bool(capsule_contacts(joints[t, 0], joints[t, 1]))
                if touching and not was_touching:
                    events.append({"kind": "impact", "frame": int(t),
                                   "strength": 0.85, "source": "contact"})
                was_touching = touching
        except Exception:
            pass  # contact audio is a bonus; never fail the render for it

    # De-duplicate onsets landing on the same frame.
    seen = set()
    unique: List[Dict[str, Any]] = []
    for e in sorted(events, key=lambda e: e["frame"]):
        if e["frame"] in seen:
            continue
        seen.add(e["frame"])
        unique.append(e)
    return unique


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def build_audio(timeline: Dict[str, Any], *, seed: int = 0,
                with_music: bool = True, gain: float = 1.0,
                fps: int = FPS) -> Dict[str, Any]:
    """Render the whole soundtrack for a timeline.

    Returns {"samples": (n,) float32 in [-1,1], "sample_rate", "events", "duration_s"}.
    """
    feat = timeline["feat"]
    T = int(timeline.get("T", feat.shape[0]))
    duration_s = float(timeline.get("duration_seconds") or (T / fps))
    rng = np.random.default_rng(seed)

    footsteps = detect_footsteps(feat, fps=fps)
    whooshes = detect_whooshes(timeline, feat, fps=fps)
    impacts = detect_impacts(timeline, feat, fps=fps)

    n = int(duration_s * SAMPLE_RATE)
    buf = np.zeros(n, dtype=np.float64)

    def place(sample: np.ndarray, frame: int, amp: float) -> None:
        s = int(round(frame / fps * SAMPLE_RATE))
        if s < 0 or s >= n:
            return
        seg = min(len(sample), n - s)
        buf[s:s + seg] += amp * sample[:seg]

    for e in footsteps:
        place(_footstep(rng, e["strength"]), e["frame"], 0.42)
    for e in whooshes:
        place(_whoosh(rng, e["strength"]), e["frame"], 0.30)
    for e in impacts:
        place(_impact(rng, e["strength"]), e["frame"], 0.75)

    if with_music:
        buf += _music_bed(duration_s, rng)

    # Soft-clip so a pile-up of simultaneous impacts saturates gracefully
    # instead of clipping into digital crunch.
    buf = np.tanh(buf * 1.15) * gain
    peak = float(np.abs(buf).max())
    if peak > 0.99:
        buf *= 0.99 / peak

    return {
        "samples": buf.astype(np.float32),
        "sample_rate": SAMPLE_RATE,
        "duration_s": duration_s,
        "events": {
            "footsteps": footsteps, "whooshes": whooshes, "impacts": impacts,
        },
        "counts": {"footsteps": len(footsteps), "whooshes": len(whooshes),
                   "impacts": len(impacts)},
    }


def write_wav(samples: np.ndarray, path: str | Path,
              sample_rate: int = SAMPLE_RATE) -> str:
    """Write mono float samples as 16-bit PCM WAV."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm.tobytes())
    return str(path)


def mux(video: str | Path, audio: str | Path, out: str | Path) -> str:
    """Attach audio to a video, copying the video stream (no re-encode)."""
    video, audio, out = Path(video), Path(audio), Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH; cannot mux audio")
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
           "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg mux failed: {proc.stderr.strip()}")
    return str(out)


def add_sound(video: str | Path, timeline: Dict[str, Any], out: str | Path,
              *, seed: int = 0, with_music: bool = True) -> Dict[str, Any]:
    """Soundtrack a finished clip. Returns {"video", "wav", "counts"}."""
    audio = build_audio(timeline, seed=seed, with_music=with_music)
    wav_path = Path(out).with_suffix(".wav")
    write_wav(audio["samples"], wav_path, audio["sample_rate"])
    mux(video, wav_path, out)
    return {"video": str(out), "wav": str(wav_path), "counts": audio["counts"]}
