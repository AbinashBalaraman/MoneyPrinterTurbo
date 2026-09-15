"""Pre-render text review: see a scene as terminal text BEFORE rendering mp4.

The engine compiles a SceneScript into a *timeline* (feat/joints/props/camera)
long before any video exists. This module turns that timeline into reviewable
text, so quality is judged on the actual motion rather than a finished export.

Techniques (from prior art: chafa, video2ascii, asciideia, llm-frames):
  - luminance -> character-ramp mapping
  - half-block (▀▄█) for 2x vertical resolution
  - braille (U+2800) for 4x vertical resolution (square dots)
  - aspect-ratio correction assuming a character cell ~2x taller than wide
  - a token-bounded *digest* (few sampled frames) plus a full playable dump

Nothing here touches the renderer's video path; it is read-only analysis.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

# Luminance -> ink density ramps. Index 0 = lightest ink, -1 = densest.
ASCII_RAMP = " .:-=+*#%@"

# Braille dot bit position for (col_in_cell, row_in_cell), 2 cols x 4 rows.
_BRAILLE_BITS = np.array([
    [0x01, 0x02, 0x04, 0x40],  # left column, rows 0..3
    [0x08, 0x10, 0x20, 0x80],  # right column, rows 0..3
], dtype=np.int32)


# --------------------------------------------------------------------------- #
# Image -> text
# --------------------------------------------------------------------------- #
def _to_ink_density(img: Image.Image) -> np.ndarray:
    """PIL image -> float density in [0,1]; 1 = dark ink, 0 = light background."""
    g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    return 1.0 - g


def _fit_cols(cols: int, w: int, h: int, char_aspect: float = 2.0) -> int:
    """Rows needed so the text grid preserves the image aspect on a terminal."""
    if w <= 0:
        return max(1, cols // 2)
    return max(1, int(round(cols * (h / w) / char_aspect)))


def _crop_to_content(img: Image.Image, pad: int = 8,
                     bg_tol: int = 12) -> Image.Image:
    """Trim near-uniform border so the subjects fill the text grid.

    Uses the corner pixel as the background reference; scans for the bounding box
    of pixels that differ from it. Falls back to the original image if the frame
    is effectively empty.
    """
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    bg = arr[0, 0]
    diff = np.abs(arr - bg).sum(axis=-1)
    mask = diff > bg_tol
    if not mask.any():
        return img
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    w, h = img.size
    x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
    x1 = min(w, x1 + pad + 1); y1 = min(h, y1 + pad + 1)
    if (x1 - x0) < 8 or (y1 - y0) < 8:
        return img
    return img.crop((x0, y0, x1, y1))


def image_to_text(img: Image.Image, cols: int = 80, mode: str = "half",
                  char_aspect: float = 2.0, auto_crop: bool = True,
                  crop_pad: int = 8) -> str:
    """Convert a rendered frame to text using the chosen resolution mode.

    mode: "ascii" (1 px/cell), "half" (2 px/cell vertical), "braille" (4x2 px/cell)
    auto_crop: trim uniform background margins so figures fill the grid (legible).
    """
    if cols < 4:
        cols = 4
    if auto_crop:
        img = _crop_to_content(img, pad=crop_pad)
    w, h = img.size
    rows = _fit_cols(cols, w, h, char_aspect)

    if mode == "braille":
        # 2 dots wide x 4 dots tall per character cell.
        dens = _to_ink_density(img.resize((cols * 2, rows * 4), Image.LANCZOS))
        dens = dens.reshape(rows, 4, cols, 2).transpose(0, 2, 1, 3)
        on = dens > 0.5  # (rows, cols, 4, 2)
        bits = np.zeros((rows, cols), dtype=np.int32)
        for ci in range(2):
            for ri in range(4):
                bits |= np.where(on[:, :, ri, ci], _BRAILLE_BITS[ci, ri], 0)
        chars = np.array([[chr(0x2800 + int(b)) for b in row] for row in bits])
        lines = ["".join(r).rstrip() for r in chars]
        return "\n".join(lines)

    if mode == "half":
        # 1 px wide x 2 px tall per cell; ▀ top, ▄ bottom, █ both.
        dens = _to_ink_density(img.resize((cols, rows * 2), Image.LANCZOS))
        top = dens[0::2] > 0.5
        bot = dens[1::2] > 0.5
        out = []
        for r in range(top.shape[0]):
            row = []
            for c in range(top.shape[1]):
                t, b = bool(top[r, c]), bool(bot[r, c])
                row.append("█" if (t and b) else "▀" if t else "▄" if b else " ")
            out.append("".join(row).rstrip())
        return "\n".join(out)

    # ascii: single sample per cell, ramp by density.
    dens = _to_ink_density(img.resize((cols, rows), Image.LANCZOS))
    idx = np.clip((dens * (len(ASCII_RAMP) - 1)).round().astype(int), 0, len(ASCII_RAMP) - 1)
    ramp = np.array(list(ASCII_RAMP))
    chars = ramp[idx]
    return "\n".join("".join(r).rstrip() for r in chars)


# --------------------------------------------------------------------------- #
# Frame rendering (low-res, from the real renderer so it matches the video)
# --------------------------------------------------------------------------- #
def _frame_image(joints_t: np.ndarray, camera_x: float, props, vfx, res: int) -> Image.Image:
    from .renderer import StickmanRenderer
    r = StickmanRenderer(canvas_size=res)
    return r.render_frame(joints_t, camera_x=camera_x, props=props, vfx=vfx)


# --------------------------------------------------------------------------- #
# Metrics — the checks that catch wrong output before rendering
# --------------------------------------------------------------------------- #
def interaction_stats(joints: np.ndarray,
                      windows: Optional[List[Dict[str, Any]]] = None
                      ) -> Dict[str, Any]:
    """Min inter-actor joint distance over time; flags 'two soloists' scripts.

    joints: (T, N, 15, 2). For N>=2, per frame computes the closest distance
    between ANY joint of actor 0 and ANY joint of actor 1. A real fight has the
    actors within striking range (< ~0.5 world units) for a good fraction of it.

    ``windows`` optionally lists declared exchanges ([{actors, frame, frames}])
    from the compiled timeline. When given, the verdict is judged on the BEST
    exchange rather than a global average, so a solo intro/outro or a long
    no-contact window cannot dilute a genuinely engaged fight.
    """
    T, N = joints.shape[0], joints.shape[1]
    if N < 2:
        return {"n_person": N, "min_dist": None, "contact_ratio": None,
                "interacting": None, "note": "single actor; no interaction possible"}
    d = []
    for t in range(T):
        a = joints[t, 0]  # (15,2)
        b = joints[t, 1]
        dist = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))  # (15,15)
        d.append(float(dist.min()))
    d = np.asarray(d)
    contact = d < 0.5
    ratio = float(contact.mean())
    mean_d = float(d.mean())

    # Per-declared-exchange ratios (window-aware), when available.
    win: List[Dict[str, Any]] = []
    for w in (windows or []):
        actors = w.get("actors") or []
        if len(actors) != 2:
            continue
        ai, bi = int(actors[0]), int(actors[1])
        if ai >= N or bi >= N or ai == bi:
            continue
        f0 = max(0, int(w.get("frame", 0)))
        n = int(w.get("frames", 0)) or max(1, T - f0)
        sub = joints[f0:f0 + n]
        if sub.shape[0] == 0:
            continue
        dd = np.sqrt(((sub[:, ai][:, None, :, :] - sub[:, bi][None, :, :, :]) ** 2)
                     ).sum(-1).min(axis=(1, 2))
        win.append({"interaction": w.get("interaction"), "frame": f0,
                    "contact_ratio": float((dd < 0.5).mean()),
                    "min_dist": float(dd.min())})
    judged = max((w["contact_ratio"] for w in win), default=ratio)
    min_d = min((w["min_dist"] for w in win), default=float(d.min()))

    # Sustained engagement, not an incidental crossing: a duel should show
    # frequent close-range frames. Weak/incidental contact is flagged.
    if judged > 0.20 and mean_d < 1.2:
        verdict = "engaged"
    elif judged > 0.05 or ratio > 0.05:
        verdict = "weak/incidental contact"
    else:
        verdict = "NO interaction (two solo actors)"
    out = {
        "n_person": N,
        "min_dist": min_d,
        "mean_min_dist": mean_d,
        "contact_frames": int(contact.sum()),
        "contact_ratio": ratio,
        "judged_contact_ratio": judged,
        "interacting": verdict == "engaged",
        "verdict": verdict,
        "note": ("actors fight/engage at close range" if verdict == "engaged"
                 else "actors stay apart -> looks like two solo actors, not a fight"),
    }
    if win:
        out["windows"] = win
    return out


def motion_stats(joints: np.ndarray, fps: int = 24) -> Dict[str, Any]:
    """Ground contact + root travel per actor (cheap, robust pre-render checks)."""
    from .rig import GROUND_Y
    T, N = joints.shape[0], joints.shape[1]
    out = {"T": T, "fps": fps, "duration_s": T / fps, "actors": []}
    for n in range(N):
        lowest = joints[:, n, :, 1].min(axis=-1)
        pen = float(max(0.0, GROUND_Y - lowest.min()))
        root_x = joints[:, n, 0, 0]
        out["actors"].append({
            "id": n,
            "min_foot_y": float(lowest.min()),
            "max_penetration": pen,
            "root_travel": float(np.abs(np.diff(root_x)).sum()),
            "root_range": [float(root_x.min()), float(root_x.max())],
        })
    return out


# --------------------------------------------------------------------------- #
# Full timeline preview + digest
# --------------------------------------------------------------------------- #
def _objects_at(timeline: Dict[str, Any], t: int) -> List[str]:
    props = (timeline.get("prop_tracks") or [])
    if t >= len(props):
        return []
    return [str(p.get("kind", "?")) for p in props[t]]


def _skeleton_text(joints_t: np.ndarray, chars: Dict[str, Any], cols: int,
                   rows: int, frame_idx: int, x_bounds: tuple) -> str:
    """Legible stick-figure text view via the stage skeleton renderer."""
    from .stage.terminal_preview import TerminalStagePreview
    labels = chars.get("labels") or None
    p = TerminalStagePreview(cols=cols, rows=rows)
    return p.render_ascii_frame(
        joints_t, scenery=chars.get("scenery"), props=chars.get("props"),
        frame_idx=frame_idx, actor_labels=labels, x_bounds=x_bounds)


def _render_frames(joints: np.ndarray, timeline: Dict[str, Any], res: int,
                   frames: List[int]):
    from .renderer import active_vfx_for_frame
    prop_tracks = timeline.get("prop_tracks")
    cam = (timeline.get("camera_track") or {}).get("camera_x")
    vfx = list(timeline.get("vfx_events") or []) + _impacts_vfx(timeline.get("impacts"))
    T = joints.shape[0]
    out = {}
    for t in frames:
        t = max(0, min(T - 1, t))
        props = prop_tracks[t] if prop_tracks is not None and t < len(prop_tracks) else None
        fv = active_vfx_for_frame(vfx, t) if vfx else None
        cx = float(cam[t]) if cam is not None and t < len(cam) else 0.0
        out[t] = _frame_image(joints[t], cx, props, fv, res)
    return out


def _impacts_vfx(impacts):
    if not impacts:
        return []
    out = []
    for i in impacts:
        try:
            out.append({"kind": i.get("kind", "impact_burst"),
                        "start_frame": int(i.get("frame", 0)),
                        "duration": int(i.get("duration", 6)),
                        "x": float(i.get("x", 0.0)), "y": float(i.get("y", -0.42))})
        except (TypeError, ValueError):
            continue
    return out


def render_timeline_preview(
    timeline: Dict[str, Any],
    cols: int = 80,
    mode: str = "half",
    sample: int = 12,
    out_dir: str = "out",
    name: str = "preview",
    write_animation: bool = True,
    fps: Optional[int] = None,
) -> Dict[str, Any]:
    """Produce a text digest + (optional) full playable animation for a timeline.

    Returns dict with: digest (str), animation_path, metrics (dict), frames_shown.
    The digest is token-bounded (``sample`` frames); the full animation is
    written to disk and NOT returned, so review cost stays small.
    """
    from .renderer import decode_motion_features, active_vfx_for_frame
    fps = fps or int(timeline.get("fps", 24))
    joints = decode_motion_features(timeline["feat"])
    T = joints.shape[0]

    inter = interaction_stats(
        joints, windows=timeline.get("interactions")) if joints.shape[1] >= 2 else {"n_person": joints.shape[1]}
    motion = motion_stats(joints, fps=fps)

    # Sample frames: always include first/last plus an even spread.
    sample = max(2, min(sample, T))
    frames = sorted(set(np.linspace(0, T - 1, sample).round().astype(int).tolist()))

    res = max(160, cols * 2)
    imgs = _render_frames(joints, timeline, res, frames)

    # ---- Digest -------------------------------------------------------- #
    lines: List[str] = []
    lines.append("=" * (cols + 12))
    lines.append(f"PRE-RENDER TEXT REVIEW  |  {timeline.get('title', 'untitled')}  |  "
                 f"{T} frames @ {fps}fps = {T/fps:.1f}s  |  mode={mode}")
    lines.append("=" * (cols + 12))
    lines.append("")

    # SceneDoctor Gate
    from .doctor import diagnose, format_report
    doc_report = diagnose(timeline, scene=timeline.get("scene_dict"), fps=fps)
    lines.append(format_report(doc_report))
    lines.append("-" * (cols + 12))
    lines.append("")

    # Metrics block
    inter_note = inter.get("note", "")
    verdict = inter.get("verdict", "n/a")
    lines.append(f"INTERACTION: verdict={verdict}  min joint dist={inter.get('min_dist')}  "
                 f"contact ratio={inter.get('contact_ratio')}")
    if inter.get("windows"):
        lines.append(f"  declared exchanges (window-aware, judged ratio "
                     f"{inter.get('judged_contact_ratio'):.3f}):")
        for w in inter["windows"]:
            lines.append(f"    {str(w['interaction']):<10} f={w['frame']:<4} "
                         f"ratio={w['contact_ratio']:.3f} min_dist={w['min_dist']:.3f} "
                         f"{'OK' if w['contact_ratio'] > 0.20 else 'WEAK' if w['contact_ratio'] > 0.05 else 'NO CONTACT'}")
    if inter.get("n_person", 1) >= 2 and not inter.get("interacting"):
        lines.append(f"  !! WARNING: {inter_note}")
    for a in motion["actors"]:
        lines.append(f"  actor {a['id']}: root range [{a['root_range'][0]:.2f}, "
                     f"{a['root_range'][1]:.2f}] travel={a['root_travel']:.2f} "
                     f"penetration={a['max_penetration']:.3f}")
    lines.append("")
    lines.append(f"KEY FRAMES ({len(frames)} of {T}):")
    labels = [f"A{n}" for n in range(joints.shape[1])]
    for t in frames:
        acts = []
        for n in range(joints.shape[1]):
            acts.append(f"A{n}@{joints[t, n, 0, 0]:+.2f}")
        objs = ",".join(_objects_at(timeline, t)) or "-"
        lines.append(f"  frame {t:4d}  t={t/fps:5.2f}s  {' '.join(acts)}  objs={objs}")
        # Adaptive horizontal framing around the actors so spacing is legible.
        xs = joints[t, :, :, 0]
        pad = max(0.35, 0.12 * (float(xs.max()) - float(xs.min())))
        xb = (float(xs.min()) - pad, float(xs.max()) + pad)
        lines.append(_skeleton_text(
            joints[t],
            {"scenery": {"type": "plain"}, "props": None, "labels": labels},
            cols=cols, rows=max(12, cols // 3), frame_idx=t, x_bounds=xb))
        lines.append("")
    digest = "\n".join(lines)

    # ---- Full animation (playable) ------------------------------------- #
    animation_path = None
    if write_animation:
        os.makedirs(out_dir, exist_ok=True)
        animation_path = os.path.join(out_dir, f"{name}_{mode}_{cols}.txt")
        with open(animation_path, "w", encoding="utf-8") as f:
            f.write(f"# {timeline.get('title', 'untitled')} | {T} frames @ {fps}fps | mode={mode}\n")
            for t in range(T):
                props = None
                if timeline.get("prop_tracks") is not None and t < len(timeline["prop_tracks"]):
                    props = timeline["prop_tracks"][t]
                vfx = list(timeline.get("vfx_events") or []) + _impacts_vfx(timeline.get("impacts"))
                fv = active_vfx_for_frame(vfx, t) if vfx else None
                cam = (timeline.get("camera_track") or {}).get("camera_x")
                cx = float(cam[t]) if cam is not None and t < len(cam) else 0.0
                img = _frame_image(joints[t], cx, props, fv, res)
                f.write(f"\f#FRAME {t} t={t/fps:.2f}s\n")
                f.write(image_to_text(img, cols=cols, mode=mode))
                f.write("\n")

    return {
        "digest": digest,
        "animation_path": animation_path,
        "metrics": {"interaction": inter, "motion": motion},
        "frames_shown": frames,
        "T": T,
    }
