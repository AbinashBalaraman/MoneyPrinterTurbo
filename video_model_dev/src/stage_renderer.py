"""High-Definition (1280x720, 16:9) Stage Renderer for the Puppet Stage Platform.

Composites multi-layer scenes matching the production quality of goal_videos/:
- Background & Perspective Floor/Ceiling
- Architectural Colonnade & Scenery Props
- Dynamic Hand-held & Environmental Props
- Antialiased Stickman Puppets with Contact Shadows
- Kinetic Typography & Split-Screen Panels
- Streams directly into ffmpeg for pristine 720p H.264 video encoding.
"""

import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw
from typing import Dict, Any, List, Optional, Tuple, Union

from .rig import FPS, decode, forward_kinematics
from .renderer import BONE_SEGMENTS, apply_contact_correction, apply_camera_impulses
from .stage.theme import StageTheme, get_theme, LIGHT_THEME, DARK_THEME
from .stage.perspective import PerspectiveStage
from .stage.props import (
    draw_speech_bubble,
    draw_giant_gavel,
    draw_prison_cage,
    draw_shattered_pillar_rubble,
    draw_ground_and_ceiling_cracks,
    draw_red_fluid_splash,
    draw_envelope_with_x
)
from .stage.panels import SplitScreenPanels, draw_thought_bubble, draw_organic_spline_web
from .stage.text_overlay import draw_kinetic_text


class StageRendererHD:
    """Renders 1280x720 widescreen HD videos with multi-layer puppet stage scenery."""

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        theme_name: str = "light",
        supersample: int = 2,
        scale: float = 340.0
    ):
        self.width = width
        self.height = height
        self.ss = supersample
        self.r_w = width * supersample
        self.r_h = height * supersample
        self.theme = get_theme(theme_name)
        self.scale = scale * supersample
        self.center_x = self.r_w // 2
        self.ground_y = int(self.r_h * 0.84)
        self.world_ground_y = -0.42
        self.perspective = PerspectiveStage(width=self.r_w, height=self.r_h, vanishing_pt=(self.center_x, int(self.r_h * 0.44)))

    def world_to_canvas(self, points: np.ndarray, camera_x: float = 0.0) -> np.ndarray:
        """Converts world coordinates to 720p canvas coordinates."""
        pts = np.asarray(points, dtype=np.float32)
        cx = self.center_x + (pts[..., 0] - camera_x) * self.scale
        cy = self.ground_y - (pts[..., 1] - self.world_ground_y) * self.scale
        return np.stack([cx, cy], axis=-1)

    def draw_puppet(self, draw: ImageDraw.ImageDraw, joints_2d: np.ndarray, joints_world: np.ndarray,
                    custom_color: Optional[Tuple[int, int, int]] = None,
                    show_face: bool = False, face_emotion: str = "neutral"):
        """Draws an expressive stickman puppet with rounded joints and head."""
        body_col = custom_color or self.theme.stickman_color
        head_col = body_col
        line_w = int(5.5 * self.ss)
        half_w = max(1, line_w // 2)

        # 1. Contact Drop Shadow (Light Theme)
        if self.theme.name == "light":
            root_y = joints_world[0, 1]
            elevation = max(0.0, float(root_y))
            factor = 1.0 / (1.0 + 3.5 * elevation)
            sw = int(45 * self.ss * factor)
            sh = max(2, int(9 * self.ss * factor))
            pcx = float(joints_2d[0, 0])
            draw.ellipse([pcx - sw, self.ground_y - sh, pcx + sw, self.ground_y + sh],
                         fill=self.theme.shadow_color)

        # 2. 2.5D Layering & Depth Shading
        # Background limbs (Right Arm, Right Leg) are drawn first with depth tint/shading.
        # Foreground limbs (Left Arm, Left Leg) are drawn in front of torso with primary color.
        fg_col = body_col
        if self.theme.name == "dark":
            # Background limbs slightly dimmed (~28% darker) for depth separation
            bg_col = (max(0, int(fg_col[0] * 0.72)),
                      max(0, int(fg_col[1] * 0.72)),
                      max(0, int(fg_col[2] * 0.72)))
        else:
            # Background limbs tinted lighter towards the paper/canvas background
            bg_col = (min(255, int(fg_col[0] * 0.35 + 160 * 0.65)),
                      min(255, int(fg_col[1] * 0.35 + 160 * 0.65)),
                      min(255, int(fg_col[2] * 0.35 + 160 * 0.65)))

        def _draw_segment(ja: int, jb: int, col: Tuple[int, int, int]):
            pa = (float(joints_2d[ja, 0]), float(joints_2d[ja, 1]))
            pb = (float(joints_2d[jb, 0]), float(joints_2d[jb, 1]))
            draw.line([pa, pb], fill=col, width=line_w)
            # Circular end caps prevent corner tearing and vertex gaps
            draw.ellipse([pa[0] - half_w, pa[1] - half_w, pa[0] + half_w, pa[1] + half_w], fill=col)
            draw.ellipse([pb[0] - half_w, pb[1] - half_w, pb[0] + half_w, pb[1] + half_w], fill=col)

        # Layer A: Background Limbs (Right Arm: 2->7->8, Right Leg: 0->12->13->14)
        for ja, jb in [(2, 7), (7, 8), (0, 12), (12, 13), (13, 14)]:
            _draw_segment(ja, jb, bg_col)

        # Layer B: Torso (0->1->2->3)
        for ja, jb in [(0, 1), (1, 2), (2, 3)]:
            _draw_segment(ja, jb, fg_col)

        # Layer C: Head
        hx, hy = float(joints_2d[4, 0]), float(joints_2d[4, 1])
        hr = int(24 * self.ss)
        if self.theme.name == "dark":
            # Solid white with dark outline
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255), outline=(15, 15, 15), width=max(1, int(2 * self.ss)))
        else:
            # Solid black
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=head_col)

        # Layer D: Foreground Limbs (Left Arm: 2->5->6, Left Leg: 0->9->10->11)
        for ja, jb in [(2, 5), (5, 6), (0, 9), (9, 10), (10, 11)]:
            _draw_segment(ja, jb, fg_col)

        # 5. Optional Facial Expressions (for dark theme / closeups)
        if show_face:
            self._draw_face(draw, hx, hy, hr, face_emotion)

    def _draw_face(self, draw: ImageDraw.ImageDraw, hx: float, hy: float, hr: float, emotion: str):
        """Draws expressive cartoon facial features on stickman head."""
        eye_col = (15, 15, 15)
        eye_r = int(3 * self.ss)
        # Eyes
        draw.ellipse([hx - hr * 0.35 - eye_r, hy - hr * 0.1 - eye_r, hx - hr * 0.35 + eye_r, hy - hr * 0.1 + eye_r], fill=eye_col)
        draw.ellipse([hx + hr * 0.35 - eye_r, hy - hr * 0.1 - eye_r, hx + hr * 0.35 + eye_r, hy - hr * 0.1 + eye_r], fill=eye_col)
        
        if emotion == "angry":
            # Angled angry eyebrows
            draw.line([(hx - hr * 0.5, hy - hr * 0.35), (hx - hr * 0.15, hy - hr * 0.2)], fill=eye_col, width=int(2 * self.ss))
            draw.line([(hx + hr * 0.5, hy - hr * 0.35), (hx + hr * 0.15, hy - hr * 0.2)], fill=eye_col, width=int(2 * self.ss))
            # Shouting mouth
            draw.ellipse([hx - hr * 0.2, hy + hr * 0.15, hx + hr * 0.2, hy + hr * 0.45], fill=eye_col)
        elif emotion == "distress":
            # Distressed mouth
            draw.arc([hx - hr * 0.25, hy + hr * 0.15, hx + hr * 0.25, hy + hr * 0.5], start=180, end=360, fill=eye_col, width=int(2 * self.ss))

    def _draw_joint_prop(self, draw: ImageDraw.ImageDraw, p: Dict[str, Any], c_pts_all: List[np.ndarray]):
        """Draws a weapon or object rigidly anchored to a puppet joint."""
        pidx = p.get("anchor_puppet", 0)
        if pidx >= len(c_pts_all):
            return
        pts = c_pts_all[pidx]
        joint = p.get("joint", 8)  # default right wrist/hand
        if joint == 8:
            parent_joint = 7
        elif joint == 6:
            parent_joint = 5
        else:
            parent_joint = p.get("parent_joint", max(0, joint - 1))

        p_hand = pts[joint]
        p_elbow = pts[parent_joint]
        dx = float(p_hand[0] - p_elbow[0])
        dy = float(p_hand[1] - p_elbow[1])
        L = float(np.hypot(dx, dy)) + 1e-5
        u = np.array([dx / L, dy / L], dtype=np.float32)
        n = np.array([-dy / L, dx / L], dtype=np.float32)

        kind = p.get("kind")
        scale = float(p.get("scale", 1.0))

        if kind == "sword":
            col = p.get("color", (240, 240, 245) if self.theme.name == "dark" else (40, 40, 50))
            guard_col = (190, 160, 40)
            p_pommel = p_hand - u * (14.0 * self.ss * scale)
            draw.line([tuple(p_hand), tuple(p_pommel)], fill=col, width=int(3 * self.ss))
            g1 = p_hand - n * (12.0 * self.ss * scale)
            g2 = p_hand + n * (12.0 * self.ss * scale)
            draw.line([tuple(g1), tuple(g2)], fill=guard_col, width=int(3.5 * self.ss))
            p_tip = p_hand + u * (75.0 * self.ss * scale)
            draw.line([tuple(p_hand), tuple(p_tip)], fill=col, width=int(3.5 * self.ss))

        elif kind == "staff":
            col = p.get("color", (139, 69, 19) if self.theme.name == "light" else (205, 133, 63))
            p_back = p_hand - u * (55.0 * self.ss * scale)
            p_front = p_hand + u * (95.0 * self.ss * scale)
            draw.line([tuple(p_back), tuple(p_front)], fill=col, width=int(4.5 * self.ss))

        elif kind == "joint_gavel":
            handle_col = (139, 69, 19)
            head_col = (160, 82, 45)
            p_head_center = p_hand + u * (42.0 * self.ss * scale)
            draw.line([tuple(p_hand), tuple(p_head_center)], fill=handle_col, width=int(3.5 * self.ss))
            h1 = p_head_center - n * (16.0 * self.ss * scale)
            h2 = p_head_center + n * (16.0 * self.ss * scale)
            draw.line([tuple(h1), tuple(h2)], fill=head_col, width=int(12 * self.ss))

        elif kind == "shield":
            col = p.get("color", self.theme.accent_purple)
            mid = (p_elbow + p_hand) * 0.5
            sr = int(24 * self.ss * scale)
            fill_col = (45, 45, 60) if self.theme.name == "dark" else (230, 230, 240)
            draw.ellipse([mid[0] - sr, mid[1] - sr, mid[0] + sr, mid[1] + sr], fill=fill_col, outline=col, width=int(3 * self.ss))

    def _draw_vector_vfx(self, draw: ImageDraw.ImageDraw, v: Dict[str, Any], c_pts_all: List[np.ndarray]):
        """Renders procedural comic/anime stop-motion visual impact effects."""
        kind = v.get("kind")
        scale = float(v.get("scale", 1.0))
        if "anchor_puppet" in v and "anchor_joint" in v:
            pidx = int(v["anchor_puppet"])
            if pidx < len(c_pts_all):
                joint = v["anchor_joint"]
                if isinstance(joint, str):
                    from .rig import JOINT_NAMES
                    joint = JOINT_NAMES.get(joint.strip().lower(), 0)
                cx, cy = float(c_pts_all[pidx][joint, 0]), float(c_pts_all[pidx][joint, 1])
            else:
                cx, cy = float(v.get("x", self.center_x)), float(v.get("y", self.ground_y))
        else:
            cx = float(v.get("x", self.center_x) * self.ss)
            cy = float(v.get("y", self.ground_y) * self.ss)

        if kind == "impact_burst":
            b_col = v.get("color", (255, 235, 70) if self.theme.name == "dark" else (220, 50, 20))
            r_inner = 8.0 * self.ss * scale
            r_outer = 32.0 * self.ss * scale
            rot = float(v.get("rotation", 22.5))
            for k in range(8):
                ang = np.radians(k * 45.0 + rot)
                p1 = (cx + np.cos(ang) * r_inner, cy + np.sin(ang) * r_inner)
                p2 = (cx + np.cos(ang) * r_outer, cy + np.sin(ang) * r_outer)
                draw.line([p1, p2], fill=b_col, width=max(1, int(3 * self.ss)))
            flash_r = 6.0 * self.ss * scale
            draw.ellipse([cx - flash_r, cy - flash_r, cx + flash_r, cy + flash_r], fill=(255, 255, 255))

        elif kind == "dust_puff":
            d_col = v.get("color", (180, 180, 195) if self.theme.name == "dark" else (160, 160, 165))
            dr = 20.0 * self.ss * scale
            draw.ellipse([cx - dr * 1.6, self.ground_y - dr * 0.9, cx + dr * 1.6, self.ground_y + dr * 0.3], outline=d_col, width=max(1, int(2 * self.ss)))
            draw.ellipse([cx - dr * 0.9, self.ground_y - dr * 1.3, cx + dr * 0.9, self.ground_y], outline=d_col, width=max(1, int(1.5 * self.ss)))

        elif kind == "speed_lines":
            sl_col = v.get("color", (210, 210, 220) if self.theme.name == "dark" else (120, 120, 130))
            dir_s = float(v.get("direction", 1.0))
            line_len = 55.0 * self.ss * scale
            for dy in [-16.0, 0.0, 16.0]:
                y_pos = cy + dy * self.ss
                x1 = cx - dir_s * (20.0 * self.ss)
                x2 = x1 - dir_s * line_len
                draw.line([(x1, y_pos), (x2, y_pos)], fill=sl_col, width=max(1, int(2 * self.ss)))

    def render_stage_frame(
        self,
        joints_frame: np.ndarray,
        camera_x: float = 0.0,
        scenery: Optional[Dict[str, Any]] = None,
        props: Optional[List[Dict[str, Any]]] = None,
        text_overlay: Optional[Dict[str, Any]] = None,
        vfx: Optional[List[Dict[str, Any]]] = None
    ) -> Image.Image:
        """Renders one 1280x720 frame compositing scenery, props, puppets, and overlays."""
        img = Image.new("RGB", (self.r_w, self.r_h), self.theme.bg_color)
        draw = ImageDraw.Draw(img)
        scenery = scenery or {}

        # -------------------------------------------------------------
        # LAYER 1: Background Scenery & Perspective
        # -------------------------------------------------------------
        scene_type = scenery.get("type", "plain")

        if scene_type == "perspective_hall":
            # 1-Point Perspective Colonnade matching light_5s.png
            self.perspective.draw_perspective_grid(draw, self.theme)
            if scenery.get("colonnade", True):
                self.perspective.draw_pillar_colonnade(draw, self.theme)
            if scenery.get("baroque_frame", False):
                self.perspective.draw_baroque_ornate_frame(draw, center_x=self.center_x, center_y=int(self.r_h * 0.52), theme=self.theme)

        elif scene_type == "spline_web":
            # Cosmic glowing purple spline strands matching dark_0s.png
            draw_organic_spline_web(draw, width=self.r_w, height=self.r_h, seed=scenery.get("seed", 0))

        elif scene_type == "split_screen_3":
            # 3-Panel comic layout matching dark_5s.png
            panels = SplitScreenPanels(width=self.r_w, height=self.r_h, num_panels=3)
            panels.draw_panel_dividers(draw, color=self.theme.accent_purple, border_width=int(6 * self.ss))

        # Ground line (default for plain or hall)
        if scene_type in ("plain", "perspective_hall"):
            draw.line([(0, self.ground_y), (self.r_w, self.ground_y)], fill=self.theme.grid_line_color, width=max(1, int(2.5 * self.ss)))

        # -------------------------------------------------------------
        # LAYER 2: Structural / Environmental Props & Destruction
        # -------------------------------------------------------------
        if scenery.get("prison_cage", False):
            draw_prison_cage(draw, cx=self.center_x, cy=int(self.r_h * 0.54), width=int(500 * self.ss), height=int(460 * self.ss))

        if scenery.get("shattered_pillars", False):
            draw_shattered_pillar_rubble(draw, self.theme, ground_y=self.ground_y)

        if scenery.get("ground_cracks", False):
            draw_ground_and_ceiling_cracks(draw, self.theme, impact_cx=self.center_x, ground_y=self.ground_y)

        # -------------------------------------------------------------
        # LAYER 3: Stickman Puppets
        # -------------------------------------------------------------
        N = len(joints_frame)
        c_pts_all = []
        for n in range(N):
            c_pts = self.world_to_canvas(joints_frame[n], camera_x=camera_x)
            c_pts_all.append(c_pts)
            show_face = scenery.get("show_face", self.theme.name == "dark")
            emotion = scenery.get("face_emotion", "neutral")
            self.draw_puppet(draw, c_pts, joints_frame[n], show_face=show_face, face_emotion=emotion)

        # -------------------------------------------------------------
        # LAYER 4: Dynamic Hand-held & Foreground Props
        # -------------------------------------------------------------
        if props:
            for p in props:
                kind = p.get("kind")
                if kind in ("sword", "staff", "joint_gavel", "shield"):
                    self._draw_joint_prop(draw, p, c_pts_all)

                elif kind == "speech_bubble":
                    # Can anchor to puppet hand (joint 6) or specific coordinate
                    if "anchor_puppet" in p and p["anchor_puppet"] < N:
                        pidx = p["anchor_puppet"]
                        hand_pt = self.world_to_canvas(joints_frame[pidx, 6:7], camera_x=camera_x)[0]
                        bx = hand_pt[0] + p.get("offset_x", 60) * self.ss
                        by = hand_pt[1] + p.get("offset_y", -40) * self.ss
                    else:
                        bx = p.get("x", 640) * self.ss
                        by = p.get("y", 360) * self.ss
                    draw_speech_bubble(draw, bx, by, width=p.get("w", 150) * self.ss, height=p.get("h", 90) * self.ss,
                                       color=self.theme.accent_red, tail_dir=p.get("tail", "bottom_left"))

                elif kind == "gavel":
                    gx = p.get("x", 640) * self.ss
                    gy = p.get("y", 320) * self.ss
                    draw_giant_gavel(draw, head_cx=gx, head_cy=gy, angle_deg=p.get("angle", 25.0), scale=self.ss * p.get("scale", 1.0))

                elif kind == "red_fluid_splash":
                    sx = p.get("x", 680) * self.ss
                    sy = p.get("y", 380) * self.ss
                    draw_red_fluid_splash(draw, cx=sx, cy=sy, scale=self.ss * p.get("scale", 1.0), color=self.theme.accent_red)

                elif kind == "envelope_x":
                    ex = p.get("x", 640) * self.ss
                    ey = p.get("y", 360) * self.ss
                    draw_envelope_with_x(draw, cx=ex, cy=ey, width=p.get("w", 240) * self.ss, height=p.get("h", 160) * self.ss)

        # -------------------------------------------------------------
        # LAYER 4.5: Procedural Vector Stop-Motion VFX
        # -------------------------------------------------------------
        if vfx:
            for v in vfx:
                self._draw_vector_vfx(draw, v, c_pts_all)

        # -------------------------------------------------------------
        # LAYER 5: Foreground Cutouts / Thought Bubbles & Typography
        # -------------------------------------------------------------
        if scenery.get("thought_bubble", False):
            draw_thought_bubble(draw, cx=int(self.r_w * 0.28), cy=int(self.r_h * 0.52), radius=int(180 * self.ss))

        if text_overlay:
            text_str = text_overlay.get("text", "")
            tx = text_overlay.get("x", 260) * self.ss
            ty = text_overlay.get("y", 420) * self.ss
            font_size = int(text_overlay.get("font_size", 44) * self.ss)
            draw_kinetic_text(draw, text_str, cx=tx, cy=ty, font_size=font_size, color=self.theme.text_color)

        # Downsample 2x with Lanczos for anti-aliasing
        if self.ss > 1:
            img = img.resize((self.width, self.height), resample=Image.Resampling.LANCZOS)
        return img


# apply_camera_impulses lives in .renderer (single home); re-exported here
# for backward compatibility with existing callers and tests.
def render_stage_video(
    feat_or_joints: Any,
    output_path: str,
    theme_name: str = "light",
    scenery: Optional[Dict[str, Any]] = None,
    props: Optional[List[Dict[str, Any]]] = None,
    text_overlay: Optional[Dict[str, Any]] = None,
    vfx: Optional[List[Dict[str, Any]]] = None,
    fps: int = FPS,
    width: int = 1280,
    height: int = 720,
    fix_contact: bool = False,
    cam_impulse: Optional[List[Dict[str, Any]]] = None
) -> str:
    """Renders a complete 1280x720 HD video clip with stage scenery, props, and ffmpeg encoding."""
    from .renderer import decode_motion_features, compute_smooth_camera_track

    if isinstance(feat_or_joints, (dict, np.ndarray)) and (
        isinstance(feat_or_joints, dict) or feat_or_joints.shape[-1] in (30, 60)
    ):
        joints = decode_motion_features(feat_or_joints)
    else:
        joints = np.asarray(feat_or_joints, dtype=np.float32)
        if joints.ndim == 3:
            joints = joints[:, np.newaxis, :, :]

    if fix_contact:
        joints = apply_contact_correction(joints)
    T, N, _, _ = joints.shape

    stage = StageRendererHD(width=width, height=height, theme_name=theme_name)
    cam_track = compute_smooth_camera_track(joints, alpha=0.10) if scenery and scenery.get("auto_camera", True) else np.zeros(T, dtype=np.float32)
    # Hit-shake: explicit impulses + auto-derived from impact VFX (1-2f kicks)
    auto_impulses: List[Dict[str, Any]] = []
    if vfx:
        for v in vfx:
            if v.get("kind") in ("impact_burst", "heavy_landing") and "start_frame" in v:
                auto_impulses.append({
                    "start_frame": int(v["start_frame"]),
                    "magnitude": float(v.get("cam_impulse", 0.02)),
                })
    cam_track = apply_camera_impulses(cam_track, [*auto_impulses, *(cam_impulse or [])])

    from .video_encode import open_ffmpeg_writer, close_ffmpeg_writer

    proc = open_ffmpeg_writer(output_path, width=width, height=height, fps=fps, crf=20, preset="fast")

    try:
        for t in range(T):
            # Dynamic props or effects that evolve over time
            frame_props = []
            if props:
                for p in props:
                    p_copy = dict(p)
                    # Support gavel animation if animated
                    if p_copy.get("kind") == "gavel" and "start_frame" in p_copy:
                        sf = p_copy["start_frame"]
                        if t >= sf:
                            dt = min(1.0, (t - sf) / 10.0)
                            p_copy["y"] = p_copy["start_y"] + dt * (p_copy["target_y"] - p_copy["start_y"])
                            p_copy["angle"] = p_copy["start_angle"] + dt * (p_copy["target_angle"] - p_copy["start_angle"])
                            frame_props.append(p_copy)
                    else:
                        frame_props.append(p_copy)

            frame_vfx = []
            if vfx:
                for v in vfx:
                    sf = int(v.get("start_frame", v.get("frame", -1)))
                    dur = int(v.get("duration", 1))
                    ef = int(v.get("end_frame", sf + dur - 1)) if sf >= 0 else -1
                    if (sf <= t <= ef) or (v.get("frame") == t):
                        frame_vfx.append(v)

            img = stage.render_stage_frame(
                joints[t],
                camera_x=cam_track[t],
                scenery=scenery,
                props=frame_props,
                text_overlay=text_overlay,
                vfx=frame_vfx
            )
            proc.stdin.write(img.tobytes())
            
        close_ffmpeg_writer(proc)
    except Exception:
        proc.kill()
        raise

    return output_path
