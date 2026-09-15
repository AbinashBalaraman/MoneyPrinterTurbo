"""SceneDoctor: Pre-render defect gate for SceneScripts and compiled timelines.

Every scene compile runs through SceneDoctor before video export.
- HARD defects BLOCK rendering (raise error or exit non-zero).
- WARN defects are presented in text reviews and logs but do not block.

Defects are graded into three explicit tiers:

* ``hard``   -- correctness defects. They BLOCK. Includes numeric/decode
                failures, ground penetration, absent targeted interactions, and
                the motion-correctness codes (jerk spikes, foot slide, dead
                holds). Excuse individual codes with ``allow`` to render
                deliberately.
* ``timing`` -- *timing debt*: constant-velocity (linear-easing) runs and
                strikes with no anticipation. These are the Phase-2 work queue.
                They are surfaced and ranked but do NOT block by default, so the
                product stays testable while the fix is in flight. Pass
                ``strict_timing=True`` to promote them to blocking.
* ``warn``   -- informational (occlusion, staging notes).

The severity split is deliberate: correctness blocks the product, timing debt
is reported and worked down. Flipping ``strict_timing`` on is the single switch
that ends Phase 2.
"""

from typing import Any, Dict, Iterable, List, Optional
import numpy as np

from src.rig import GROUND_Y, FPS, decode
from src.renderer import compute_smooth_camera_track, decode_motion_features
from src.preview import interaction_stats
from src.visual_inspector import VisualInspector
from src.motion_quality import (linear_easing_segments, strike_anticipation,
                                impact_frames_from_events, unwrap_angles)

# Motion-correctness defect codes: strict mode promotes these to hard defects.
# (ground_penetration is always hard and is emitted unconditionally below.)
CORRECTNESS_CODES = ("jerk_spike", "foot_slide", "dead_hold")

# Timing-debt codes: the Phase-2 work queue. Advisory unless strict_timing=True.
TIMING_CODES = ("linear_easing", "missing_anticipation")

# All promotable quality codes -- used by the --allow CLI help text.
QUALITY_CODES = CORRECTNESS_CODES + TIMING_CODES

# Thresholds, kept here so they are tunable in one place.
MAX_JERK_SPIKES = 10
MAX_FOOT_SLIDE_EVENTS = 5
MAX_DEAD_HOLD_S = 0.35


def diagnose(
    timeline: Dict[str, Any],
    scene: Optional[Dict[str, Any]] = None,
    fps: int = FPS,
    half_viewport_width: float = 1.35,
    strict: bool = True,
    strict_timing: bool = False,
    allow: Optional[Iterable[str]] = None
) -> Dict[str, Any]:
    """Diagnose a compiled scene timeline for hard, timing and warning defects.

    Args:
        strict:        promote *correctness* codes to hard defects (default True).
        strict_timing: also promote *timing-debt* codes to hard defects
                       (default False; flip on to close Phase 2).
        allow:         iterable of defect codes to excuse even when strict
                       (e.g. ``{"foot_slide"}``), or a comma-separated string.

    Returns:
        {
            "passed": bool (True if len(hard) == 0),
            "hard":   List[Dict[str, Any]],   # blocking
            "timing": List[Dict[str, Any]],   # advisory timing debt
            "warn":   List[Dict[str, Any]],   # informational
            "metrics": Dict[str, Any],
        }
    """
    if isinstance(allow, str):
        allow = {c.strip() for c in allow.split(",") if c.strip()}
    allowed = set(allow or ())

    hard: List[Dict[str, Any]] = []
    timing: List[Dict[str, Any]] = []
    warn: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}

    def emit(code: str, payload: Dict[str, Any]) -> None:
        """Route a defect by tier.

        ``allow`` is uniform: an excused code never blocks -- it is demoted to
        an informational warning. Otherwise correctness codes block under
        ``strict``, and timing codes block only under ``strict_timing``.
        """
        if code in allowed:
            warn.append(payload)
        elif code in TIMING_CODES:
            (hard if strict_timing else timing).append(payload)
        elif strict:
            hard.append(payload)
        else:
            warn.append(payload)

    feat = timeline.get("feat")
    if feat is None:
        hard.append({"code": "missing_feat", "message": "Timeline has no motion features 'feat'"})
        return {"passed": False, "hard": hard, "timing": timing,
                "warn": warn, "metrics": metrics}

    feat = np.asarray(feat, dtype=np.float32)
    T = int(timeline.get("T", len(feat)))
    n_person = int(timeline.get("n_person", feat.shape[1] // 30 if feat.ndim == 2 else 1))

    # 1. Numeric Instability (HARD)
    if not np.isfinite(feat).all():
        hard.append({
            "code": "numeric_instability",
            "message": "NaN or Inf detected in motion features 'feat'"
        })

    cam_track = timeline.get("camera_track") or {}
    cam_x = cam_track.get("camera_x")
    has_explicit_cam = cam_x is not None
    if has_explicit_cam:
        cam_x = np.asarray(cam_x, dtype=np.float32)
        if not np.isfinite(cam_x).all():
            hard.append({
                "code": "numeric_instability",
                "message": "NaN or Inf detected in camera track 'camera_x'"
            })

    zoom = float(cam_track.get("zoom", 1.0))
    metrics["zoom"] = zoom
    metrics["T"] = T
    metrics["n_person"] = n_person

    # Decode joints: (T, N, 15, 2)
    try:
        joints = decode_motion_features(feat)
    except Exception as e:
        hard.append({"code": "decode_failure", "message": f"Could not decode joints: {e}"})
        return {"passed": False, "hard": hard, "warn": warn, "metrics": metrics}

    if not np.isfinite(joints).all():
        hard.append({
            "code": "numeric_instability",
            "message": "NaN or Inf detected in decoded joint positions"
        })

    # The renderer pans to follow the actors unless an explicit camera track is
    # supplied (or scenery opts out with auto_camera=False). The gate MUST judge
    # the same camera the renderer will use: judging a frozen viewport rejects
    # clips that render perfectly well (a walking actor simply walks out of it).
    # Computed here, not earlier, because it needs decoded joints.
    if not has_explicit_cam:
        scenery = timeline.get("scenery") or {}
        if scenery.get("auto_camera", True):
            cam_x = compute_smooth_camera_track(joints, alpha=0.10)
        else:
            cam_x = np.zeros(T, dtype=np.float32)
    metrics["camera_follows"] = bool(not has_explicit_cam
                                     and (timeline.get("scenery") or {}).get("auto_camera", True))

    # 2. Ground Penetration (HARD)
    # Calibrated GROUND_Y = -0.42. Allow 0.025m tolerance for micro-squash.
    lowest_y = float(joints[..., 1].min())
    metrics["lowest_joint_y"] = lowest_y
    if lowest_y < (GROUND_Y - 0.025):
        depth = float(GROUND_Y - lowest_y)
        hard.append({
            "code": "ground_penetration",
            "depth": depth,
            "lowest_y": lowest_y,
            "message": f"Joint penetrated ground plane by {depth:.4f}m (lowest_y={lowest_y:.4f}, ground={GROUND_Y})"
        })

    # 3. Targeted Interaction (HARD when absent; window-aware) ---------------
    # A scene may contain several sequential interactions; a single global
    # contact ratio dilutes them (an engaged dodge can be buried by a long
    # knockdown window). Judge each declared exchange instead, and only block
    # when NO declared exchange meaningfully engages. This keeps the doctor's
    # verdict aligned with the review's interaction_stats tiers.
    declared_targets = False
    if scene:
        beats = scene.get("beats") or []
        for b in beats:
            if isinstance(b, dict) and b.get("target"):
                declared_targets = True
                break
            elif hasattr(b, "target") and getattr(b, "target", None):
                declared_targets = True
                break

    istats = interaction_stats(joints)
    metrics["interaction"] = istats

    win_ratios: List[float] = []
    windows: List[Dict[str, Any]] = []
    for iv in (timeline.get("interactions") or []):
        actors = iv.get("actors") or []
        if len(actors) != 2:
            continue
        ai, bi = int(actors[0]), int(actors[1])
        if ai >= n_person or bi >= n_person or ai == bi:
            continue
        f0 = max(0, int(iv.get("frame", 0)))
        n = int(iv.get("frames", 0)) or max(1, T - f0)
        sub = joints[f0:f0 + n]
        if sub.shape[0] == 0:
            continue
        d = np.sqrt(((sub[:, ai][:, None, :, :] - sub[:, bi][None, :, :, :]) ** 2)
                    ).sum(-1).min(axis=(1, 2))
        ratio = float((d < 0.5).mean())
        win_ratios.append(ratio)
        windows.append({"interaction": iv.get("interaction"), "frame": f0,
                        "frames": int(sub.shape[0]), "contact_ratio": ratio,
                        "min_dist": float(d.min())})
    if windows:
        metrics["interaction_windows"] = windows

    if declared_targets and n_person >= 2:
        if win_ratios:
            metric_ratio = max(win_ratios)
        else:
            metric_ratio = istats.get("contact_ratio")
        if metric_ratio is not None and metric_ratio < 0.05:
            hard.append({
                "code": "targeted_interaction_absent",
                "contact_ratio": metric_ratio,
                "message": (f"Targeted interaction declared, but no declared exchange "
                            f"engages (best contact_ratio={metric_ratio:.3f} < 0.05)")
            })
        elif metric_ratio is not None and metric_ratio < 0.20:
            warn.append({
                "code": "weak_interaction",
                "contact_ratio": metric_ratio,
                "message": (f"Declared interaction is only weakly engaged "
                            f"(best contact_ratio={metric_ratio:.3f} < 0.20)")
            })
        # Surface any individual exchange that never connects, even when the
        # scene as a whole engages (e.g. a knockdown that never lands).
        if len(windows) > 1 and metric_ratio is not None and metric_ratio >= 0.05:
            for w in windows:
                if w["contact_ratio"] < 0.05:
                    warn.append({
                        "code": "interaction_window_no_contact",
                        "interaction": w["interaction"],
                        "frame": w["frame"],
                        "message": (f"Declared '{w['interaction']}' at frame {w['frame']} "
                                    f"shows no close-range contact "
                                    f"(ratio={w['contact_ratio']:.3f}, "
                                    f"min_dist={w['min_dist']:.3f})")
                    })

    # 4. Object Never Lives (HARD)
    declared_objects = []
    if scene:
        declared_objects = scene.get("objects") or []
    elif "objects" in timeline:
        declared_objects = timeline.get("objects") or []

    prop_tracks = timeline.get("prop_tracks")
    metrics["declared_objects_count"] = len(declared_objects)
    if declared_objects and prop_tracks is not None:
        for obj in declared_objects:
            oid = str(obj.get("id")) if isinstance(obj, dict) else str(getattr(obj, "id", ""))
            okind = str(obj.get("kind", obj.get("type", ""))) if isinstance(obj, dict) else str(getattr(obj, "kind", ""))
            if not oid and not okind:
                continue
            lived = False
            for fprops in prop_tracks:
                if any(str(p.get("id", "")) == oid or (not p.get("id") and p.get("kind") == okind) for p in fprops):
                    lived = True
                    break
            if not lived:
                hard.append({
                    "code": "object_never_lives",
                    "object_id": oid or okind,
                    "message": f"Declared object '{oid or okind}' never appears in any frame of prop_tracks"
                })

    # 5. Actor Off Frame (HARD)
    # Viewport half-width scales inversely with zoom
    eff_half_w = half_viewport_width / max(0.2, zoom)
    metrics["viewport_half_width"] = eff_half_w
    for n in range(n_person):
        root_x = joints[:, n, 0, 0]
        off_mask = (root_x < (cam_x - eff_half_w)) | (root_x > (cam_x + eff_half_w))
        off_count = int(off_mask.sum())
        # If actor is off-screen for > 24 frames (1 full second)
        if off_count > 24:
            hard.append({
                "code": "actor_off_frame",
                "actor": n,
                "off_frames": off_count,
                "message": f"Actor {n} is outside camera viewport for {off_count} frames ({off_count/fps:.2f}s)"
            })

    # ---- WARNING CHECKS (Do not block export) ------------------------------ #

    # 6. Camera Jump (WARN)
    if len(cam_x) > 1:
        cam_deltas = np.abs(np.diff(cam_x))
        max_delta = float(cam_deltas.max())
        metrics["max_camera_step"] = max_delta
        if max_delta > 0.40:
            warn.append({
                "code": "camera_jump",
                "max_delta": max_delta,
                "message": f"Sudden camera jump detected: max frame-to-frame delta {max_delta:.3f} > 0.40"
            })

    # 7. Empty Frame (WARN)
    for t in range(T):
        any_in_frame = False
        cx = cam_x[t] if t < len(cam_x) else 0.0
        for n in range(n_person):
            rx = joints[t, n, 0, 0]
            if (cx - eff_half_w) <= rx <= (cx + eff_half_w):
                any_in_frame = True
                break
        if not any_in_frame:
            warn.append({
                "code": "empty_frame",
                "frame": t,
                "message": f"No actors visible in camera viewport at frame {t}"
            })
            break

    # 8. Motion quality via VisualInspector + motion_quality (promoted in strict)
    insp = VisualInspector(ground_y=GROUND_Y, fps=fps)
    impact_frames = impact_frames_from_events(timeline.get("vfx_events"))
    for n in range(n_person):
        actor_feat = feat[:, n * 30:(n + 1) * 30]
        rep = insp.audit_motion(actor_feat, name=f"actor_{n}")
        if rep.jerk_spikes > MAX_JERK_SPIKES:
            emit("jerk_spike", {
                "code": "jerk_spike",
                "actor": n,
                "spikes": rep.jerk_spikes,
                "message": (f"Actor {n} has {rep.jerk_spikes} angular jerk spikes "
                            f"(max accel {rep.max_angular_accel:.1f})")
            })
        if rep.foot_sliding_events > MAX_FOOT_SLIDE_EVENTS:
            emit("foot_slide", {
                "code": "foot_slide",
                "actor": n,
                "events": rep.foot_sliding_events,
                "message": f"Actor {n} has {rep.foot_sliding_events} foot sliding events"
            })
        if rep.dead_hold_frames > int(MAX_DEAD_HOLD_S * fps):
            emit("dead_hold", {
                "code": "dead_hold",
                "actor": n,
                "frames": rep.dead_hold_frames,
                "message": (f"Actor {n} freezes for {rep.dead_hold_frames} frames "
                            f"({rep.dead_hold_frames / fps:.2f}s) with no micro-sway")
            })

        # 8b. Timing: constant-velocity runs read as mechanical.
        _root, _ang = decode(actor_feat)
        ang_cont = unwrap_angles(_ang)
        segs = linear_easing_segments(ang_cont, fps=fps)
        if segs:
            worst = max(segs, key=lambda s: s["frames"])
            emit("linear_easing", {
                "code": "linear_easing",
                "actor": n,
                "segments": len(segs),
                "message": (f"Actor {n} has {len(segs)} constant-velocity segment(s); "
                            f"worst {worst['bone']} for {worst['frames']} frames at "
                            f"frame {worst['start_frame']} "
                            f"({worst['mean_speed_rad_s']:.1f} rad/s)")
            })

        # 8c. Timing: a strike with no wind-up reads as a teleport.
        if impact_frames:
            missing = strike_anticipation(ang_cont, impact_frames, fps=fps)
            for m in missing:
                emit("missing_anticipation", {
                    "code": "missing_anticipation",
                    "actor": n,
                    "frame": m["impact_frame"],
                    "message": (f"Actor {n} strike at frame {m['impact_frame']} has no "
                                f"anticipation ({m['bone']}, ratio "
                                f"{m['anticipation_ratio']:.2f} < 0.25)")
                })

    # 9. Scenery Column Occlusion (WARN)
    scenery = timeline.get("scenery") or {}
    stype = scenery.get("type", "plain")
    if stype == "perspective_hall":
        # Columns in perspective hall are positioned at x = +/-1.2
        col_xs = [-1.2, 1.2]
        for n in range(n_person):
            rx = joints[:, n, 0, 0]
            occluded = np.zeros(T, dtype=bool)
            for col_x in col_xs:
                occluded |= (np.abs(rx - col_x) < 0.10)
            occ_count = int(occluded.sum())
            if occ_count > 24:
                warn.append({
                    "code": "occlusion",
                    "actor": n,
                    "frames": occ_count,
                    "message": f"Actor {n} is occluded behind scenery columns for {occ_count} frames"
                })

    passed = (len(hard) == 0)
    return {
        "passed": passed,
        "hard": hard,
        "timing": timing,
        "warn": warn,
        "metrics": metrics,
    }


def format_report(report: Dict[str, Any]) -> str:
    """Format doctor diagnosis into a readable text summary."""
    lines = []
    status = "PASSED" if report["passed"] else "BLOCKED (Hard Defects Detected)"
    lines.append(f"=== SCENEDOCTOR REPORT: {status} ===")
    if report["hard"]:
        lines.append("[HARD DEFECTS] (Must fix before rendering):")
        for h in report["hard"]:
            lines.append(f"  - [{h['code']}] {h['message']}")
    else:
        lines.append("[HARD DEFECTS] None (All gate checks passed)")

    timing = report.get("timing") or []
    if timing:
        lines.append(f"[TIMING DEBT] ({len(timing)} advisory, Phase-2 queue -- does not block):")
        for t in timing:
            lines.append(f"  - [{t['code']}] {t['message']}")

    if report["warn"]:
        lines.append("[WARNINGS]:")
        for w in report["warn"]:
            lines.append(f"  - [{w['code']}] {w['message']}")
    else:
        lines.append("[WARNINGS] None")
    return "\n".join(lines)
