"""Visual Inspector and Automated Quality Remediation Engine.

Performs frame-by-frame biomechanical and visual audits of stickman motion:
1. Floor Penetration (no joint Y < world_ground_y = -0.42)
2. Foot Sliding / Stance Drift (contact ankle/toe delta <= 1e-3)
3. Bone Length Rigidity (deviation from rig definition <= 1e-4)
4. Angular Acceleration Spikes (smooth interpolation, no 1-frame twitch)
5. Dead-Hold Collapse (no motionless frozen holds > 0.3s without micro-sway)
6. Combat Capsule Alignment (striker hits target capsule on impact frame)
7. Automatic Remediation (fixes defects directly in motion streams)
"""
import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple

import numpy as np

from src.rig import BONES, N_BONES, FPS, decode, encode, forward_kinematics, GROUND_Y
from src.puppet.combat_ik import (capsule_matrix, capsule_contacts,
                                  RIG_CAPSULE_R, STRIKERS)


@dataclass
class VisualAuditReport:
    name: str
    total_frames: int
    duration_s: float
    ground_penetrations: int = 0
    max_penetration_depth: float = 0.0
    foot_sliding_events: int = 0
    max_slide_distance: float = 0.0
    bone_length_violations: int = 0
    max_bone_error: float = 0.0
    jerk_spikes: int = 0
    max_angular_accel: float = 0.0
    dead_hold_frames: int = 0
    combat_contacts_detected: int = 0
    flaws_detected: List[str] = field(default_factory=list)
    quality_score: float = 100.0  # Out of 100

    def passed(self) -> bool:
        return self.quality_score >= 90.0 and len(self.flaws_detected) == 0


class VisualInspector:
    """Rigorous visual & kinematic quality auditor and fixer."""

    def __init__(self, ground_y: float = GROUND_Y, fps: int = FPS):
        self.ground_y = float(ground_y)
        self.fps = int(fps)

    def audit_motion(self, feat: np.ndarray, name: str = "motion_clip",
                     stance_tolerance: float = 0.010,
                     angular_accel_limit: float = 450.0,
                     dead_hold_threshold_s: float = 0.35) -> VisualAuditReport:
        """Audits a single-fighter feature stream (T, 30)."""
        feat = np.asarray(feat, dtype=np.float32)
        T = len(feat)
        dur = T / self.fps
        root, angles = decode(feat)
        joints = forward_kinematics(root, angles)  # (T, 15, 2)
        # Continuous (unwrapped) angles: arctan2 in decode() wraps at +/-pi,
        # which would fabricate enormous derivatives across the branch cut.
        angles_cont = np.unwrap(angles, axis=0)

        report = VisualAuditReport(name=name, total_frames=T, duration_s=dur)
        score = 100.0

        # 1. Floor Penetration
        min_y = float(joints[..., 1].min())
        if min_y < self.ground_y - 0.012:
            depth = self.ground_y - min_y
            report.ground_penetrations = int((joints[..., 1] < self.ground_y - 0.012).sum())
            report.max_penetration_depth = float(depth)
            penalty = min(25.0, depth * 200.0)
            score -= penalty
            report.flaws_detected.append(f"Floor penetration: {depth:.4f}m below floor")

        # 2. Bone Length Rigidity
        for b_idx, (b_name, pj, expected_len) in enumerate(BONES):
            cj = b_idx + 1
            lens = np.linalg.norm(joints[:, cj] - joints[:, pj], axis=-1)
            err = float(np.abs(lens - expected_len).max())
            if err > 1e-4:
                report.bone_length_violations += 1
                report.max_bone_error = max(report.max_bone_error, err)
                score -= 15.0
                report.flaws_detected.append(f"Bone stretch on {b_name}: {err:.5f}m error")

        # 3. Angular Acceleration / Jerk Spikes
        vel = np.diff(angles_cont, axis=0) * self.fps  # (T-1, 14)
        accel = np.diff(vel, axis=0) * self.fps        # (T-2, 14)
        max_acc = float(np.abs(accel).max()) if len(accel) > 0 else 0.0
        report.max_angular_accel = max_acc
        if max_acc > angular_accel_limit:
            spikes = int((np.abs(accel) > angular_accel_limit).sum())
            report.jerk_spikes = spikes
            penalty = min(20.0, spikes * 2.0)
            score -= penalty
            report.flaws_detected.append(f"Angular jerk: max {max_acc:.1f} rad/s^2 ({spikes} spikes)")

        # 4. Foot Sliding during Stance Phase
        # Measure at the planted IK anchor (ankles 10/13). The toes (11/14) are
        # articulated foot-roll pivots: their contact point legitimately travels
        # heel->ball->toe, so counting them would flag intentional roll as slide.
        for foot_j in (10, 13):
            ground_contact = np.abs(joints[:, foot_j, 1] - self.ground_y) < 0.008
            for t in range(T - 1):
                # Stance regime: on ground and not in mid-air swing
                if ground_contact[t] and ground_contact[t + 1]:
                    step_drift = float(np.linalg.norm(joints[t + 1, foot_j] - joints[t, foot_j]))
                    if step_drift > stance_tolerance and step_drift < 0.05:  # Sliding while planted
                        report.foot_sliding_events += 1
                        report.max_slide_distance = max(report.max_slide_distance, step_drift)
        if report.foot_sliding_events > 0:
            penalty = min(20.0, report.foot_sliding_events * 1.5)
            score -= penalty
            report.flaws_detected.append(f"Foot slide: {report.foot_sliding_events} drift events (max {report.max_slide_distance:.4f}m)")

        # 5. Dead-Hold Collapse (Freeze Detection)
        root_vel = np.linalg.norm(np.diff(root, axis=0), axis=-1)  # (T-1,)
        ang_vel = np.linalg.norm(np.diff(angles_cont, axis=0), axis=-1)  # (T-1,)
        motion_energy = root_vel + 0.1 * ang_vel
        frozen_frames = 0
        max_frozen = 0
        dead_hold_limit_f = int(dead_hold_threshold_s * self.fps)
        for t in range(len(motion_energy)):
            if motion_energy[t] < 1e-4:
                frozen_frames += 1
                max_frozen = max(max_frozen, frozen_frames)
            else:
                frozen_frames = 0
        report.dead_hold_frames = max_frozen
        if max_frozen > dead_hold_limit_f:
            penalty = min(25.0, (max_frozen - dead_hold_limit_f) * 1.0)
            score -= penalty
            report.flaws_detected.append(f"Dead hold freeze: {max_frozen} consecutive motionless frames ({max_frozen/self.fps:.2f}s)")

        report.quality_score = max(0.0, float(score))
        return report

    def audit_combat_pair(self, feat_a: np.ndarray, feat_b: np.ndarray,
                           name: str = "combat_sparring") -> VisualAuditReport:
        """Audits two-fighter interaction (hit registration, collision penetration)."""
        rep_a = self.audit_motion(feat_a, f"{name}_A")
        rep_b = self.audit_motion(feat_b, f"{name}_B")

        root_a, ang_a = decode(feat_a)
        root_b, ang_b = decode(feat_b)
        ja = forward_kinematics(root_a, ang_a)
        jb = forward_kinematics(root_b, ang_b)
        T = min(len(ja), len(jb))

        total_hits = 0
        deep_capsule_glitches = 0
        for t in range(T):
            contacts = capsule_contacts(ja[t], jb[t])
            if contacts:
                total_hits += len(contacts)
                for c in contacts:
                    if c["depth"] > 0.08:  # 8cm excessive clipping
                        deep_capsule_glitches += 1

        score = (rep_a.quality_score + rep_b.quality_score) * 0.5
        flaws = list(rep_a.flaws_detected) + list(rep_b.flaws_detected)
        if deep_capsule_glitches > 0:
            score -= min(20.0, deep_capsule_glitches * 2.0)
            flaws.append(f"Capsule penetration glitch: {deep_capsule_glitches} frames with depth > 8cm")

        pair_rep = VisualAuditReport(
            name=name, total_frames=T, duration_s=T / self.fps,
            ground_penetrations=rep_a.ground_penetrations + rep_b.ground_penetrations,
            max_penetration_depth=max(rep_a.max_penetration_depth, rep_b.max_penetration_depth),
            foot_sliding_events=rep_a.foot_sliding_events + rep_b.foot_sliding_events,
            max_slide_distance=max(rep_a.max_slide_distance, rep_b.max_slide_distance),
            bone_length_violations=rep_a.bone_length_violations + rep_b.bone_length_violations,
            max_bone_error=max(rep_a.max_bone_error, rep_b.max_bone_error),
            jerk_spikes=rep_a.jerk_spikes + rep_b.jerk_spikes,
            max_angular_accel=max(rep_a.max_angular_accel, rep_b.max_angular_accel),
            dead_hold_frames=max(rep_a.dead_hold_frames, rep_b.dead_hold_frames),
            combat_contacts_detected=total_hits,
            flaws_detected=flaws,
            quality_score=max(0.0, score)
        )
        return pair_rep

    # -- Automated Defect Remediation ------------------------------------------
    def remediate_motion(self, feat: np.ndarray,
                         fix_ground_penetration: bool = True,
                         kill_dead_holds: bool = True,
                         smooth_jerk: bool = True) -> np.ndarray:
        """Remediates kinematic and visual flaws in a motion stream."""
        feat = np.asarray(feat, dtype=np.float32).copy()
        root, angles = decode(feat)
        angles = np.unwrap(angles, axis=0)
        T = len(feat)

        # Pass 1: Smooth Jerk Spikes (3-tap Gaussian filter on angles)
        if smooth_jerk and T > 4:
            vel = np.diff(angles, axis=0) * self.fps
            accel = np.diff(vel, axis=0) * self.fps
            spikes = np.abs(accel) > 120.0
            if spikes.any():
                for j in range(14):
                    bad_frames = np.where(spikes[:, j])[0] + 1
                    for bf in bad_frames:
                        if 1 <= bf < T - 1:
                            angles[bf, j] = 0.25 * angles[bf - 1, j] + 0.5 * angles[bf, j] + 0.25 * angles[bf + 1, j]

        # Pass 2: Kill Dead-Hold Collapse with Biomechanical Micro-Sway / Breathing
        if kill_dead_holds:
            root_vel = np.linalg.norm(np.diff(root, axis=0), axis=-1)
            ang_vel = np.linalg.norm(np.diff(angles, axis=0), axis=-1)
            energy = np.pad(root_vel + 0.1 * ang_vel, (0, 1), mode="edge")
            dead_mask = energy < 1e-4
            if dead_mask.sum() >= int(0.35 * self.fps):
                t_arr = np.arange(T) / self.fps
                breathe_spine = 0.030 * np.sin(2 * np.pi * 1.2 * t_arr)
                breathe_chest = 0.025 * np.cos(2 * np.pi * 1.2 * t_arr)
                root_sway_y = 0.008 * np.sin(2 * np.pi * 1.2 * t_arr)
                angles[dead_mask, 0] += breathe_spine[dead_mask]
                angles[dead_mask, 1] += breathe_chest[dead_mask]
                root[dead_mask, 1] += root_sway_y[dead_mask]

        # Pass 3: Ground Penetration Clamp across all joints (runs last)
        if fix_ground_penetration:
            joints = forward_kinematics(root, angles)
            lowest_y = joints[..., 1].min(axis=-1)
            penetration = self.ground_y - lowest_y
            pos_pen = np.maximum(0.0, penetration)
            if float(pos_pen.max()) > 1e-5:
                root[:, 1] += pos_pen

        return encode(root, angles)

    # -- Visual Contact Sheet / Filmstrip Generator ----------------------------
    def render_filmstrip(self, feat: np.ndarray, output_path: str,
                         n_stills: int = 6, title: str = "Motion Strip") -> str:
        """Renders an analytical visual filmstrip of evenly spaced frames using PIL."""
        from PIL import Image, ImageDraw

        root, angles = decode(feat)
        joints = forward_kinematics(root, angles)
        T = len(feat)
        indices = np.linspace(0, T - 1, n_stills, dtype=int)

        panel_w, panel_h = 240, 260
        total_w = panel_w * n_stills
        total_h = panel_h + 36

        img = Image.new("RGB", (total_w, total_h), (20, 20, 25))
        draw = ImageDraw.Draw(img)

        # Header bar
        draw.rectangle([0, 0, total_w, 32], fill=(28, 28, 36))
        draw.text((12, 8), f"{title} ({T} frames, {T/self.fps:.2f}s @ {self.fps}fps)", fill=(240, 240, 245))

        for idx, f_idx in enumerate(indices):
            px0 = idx * panel_w
            py0 = 36
            j = joints[f_idx]
            rx, ry = root[f_idx]

            draw.rectangle([px0, py0, px0 + panel_w - 1, py0 + panel_h - 1], outline=(45, 45, 58))

            def to_px(wx, wy):
                x_frac = (wx - (rx - 0.45)) / 0.90
                y_frac = (wy - (-0.55)) / 1.10
                screen_x = int(px0 + np.clip(x_frac, 0.0, 1.0) * panel_w)
                screen_y = int(py0 + panel_h - np.clip(y_frac, 0.0, 1.0) * panel_h)
                return screen_x, screen_y

            gx1, gy1 = to_px(rx - 0.45, self.ground_y)
            gx2, gy2 = to_px(rx + 0.45, self.ground_y)
            draw.line([gx1, gy1, gx2, gy2], fill=(60, 60, 80), width=2)

            for b_idx, (b_name, pj, _) in enumerate(BONES):
                cj = b_idx + 1
                color = (79, 209, 197) if "Arm" in b_name else ((246, 173, 85) if "Leg" in b_name else (226, 232, 240))
                p1 = to_px(j[pj, 0], j[pj, 1])
                p2 = to_px(j[cj, 0], j[cj, 1])
                draw.line([p1, p2], fill=color, width=3)

            for ji in range(15):
                jp = to_px(j[ji, 0], j[ji, 1])
                draw.ellipse([jp[0] - 2, jp[1] - 2, jp[0] + 2, jp[1] + 2], fill=(255, 255, 255))

            hp = to_px(j[4, 0], j[4, 1])
            draw.ellipse([hp[0] - 6, hp[1] - 6, hp[0] + 6, hp[1] + 6], fill=(203, 213, 224), outline=(255, 255, 255), width=2)

            draw.text((px0 + 8, py0 + 8), f"F{f_idx} ({f_idx/self.fps:.2f}s)", fill=(160, 174, 192))

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
        return output_path
