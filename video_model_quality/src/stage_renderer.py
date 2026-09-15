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
from typing import Callable, Dict, Any, List, Optional, Tuple, Union

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
        if show_face:
            # Expressive cartoon head: white background with body outline so decals pop
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255), outline=body_col, width=max(1, int(2.5 * self.ss)))
            self._draw_face(draw, hx, hy, hr, face_emotion)
        elif self.theme.name == "dark":
            # Solid white with dark outline
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=(255, 255, 255), outline=(15, 15, 15), width=max(1, int(2 * self.ss)))
        else:
            # Solid black
            draw.ellipse([hx - hr, hy - hr, hx + hr, hy + hr], fill=head_col)

        # Layer D: Foreground Limbs (Left Arm: 2->5->6, Left Leg: 0->9->10->11)
        for ja, jb in [(2, 5), (5, 6), (0, 9), (9, 10), (10, 11)]:
            _draw_segment(ja, jb, fg_col)

    def _draw_face(self, draw: ImageDraw.ImageDraw, hx: float, hy: float, hr: float, emotion: str):
        """Draws one of 16 expressive cartoon facial decals on stickman head in UV space."""
        from .contract import resolve_expression
        emo = resolve_expression(emotion) or "neutral"
        eye_col = (15, 15, 15)
        line_w = max(1, int(2.2 * self.ss))

        def uv(u: float, v: float) -> Tuple[float, float]:
            return (hx + u * hr, hy + v * hr)

        if emo == "neutral":
            er = int(2.5 * self.ss)
            draw.ellipse([hx - hr * 0.30 - er, hy - hr * 0.05 - er, hx - hr * 0.30 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.ellipse([hx + hr * 0.30 - er, hy - hr * 0.05 - er, hx + hr * 0.30 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.line([uv(-0.18, 0.32), uv(0.18, 0.32)], fill=eye_col, width=line_w)

        elif emo == "happy":
            draw.arc([hx - hr * 0.45, hy - hr * 0.20, hx - hr * 0.15, hy + hr * 0.05], start=180, end=360, fill=eye_col, width=line_w)
            draw.arc([hx + hr * 0.15, hy - hr * 0.20, hx + hr * 0.45, hy + hr * 0.05], start=180, end=360, fill=eye_col, width=line_w)
            draw.arc([hx - hr * 0.35, hy + hr * 0.05, hx + hr * 0.35, hy + hr * 0.50], start=0, end=180, fill=eye_col, width=line_w)

        elif emo == "sad":
            draw.line([uv(-0.45, -0.22), uv(-0.18, -0.32)], fill=eye_col, width=line_w)
            draw.line([uv(0.18, -0.32), uv(0.45, -0.22)], fill=eye_col, width=line_w)
            er = int(2.5 * self.ss)
            draw.ellipse([hx - hr * 0.30 - er, hy - hr * 0.05 - er, hx - hr * 0.30 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.ellipse([hx + hr * 0.30 - er, hy - hr * 0.05 - er, hx + hr * 0.30 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.arc([hx - hr * 0.28, hy + hr * 0.28, hx + hr * 0.28, hy + hr * 0.65], start=180, end=360, fill=eye_col, width=line_w)

        elif emo == "angry":
            draw.line([uv(-0.45, -0.35), uv(-0.12, -0.18)], fill=eye_col, width=int(line_w * 1.3))
            draw.line([uv(0.45, -0.35), uv(0.12, -0.18)], fill=eye_col, width=int(line_w * 1.3))
            er = int(2.5 * self.ss)
            draw.ellipse([hx - hr * 0.28 - er, hy - hr * 0.02 - er, hx - hr * 0.28 + er, hy - hr * 0.02 + er], fill=eye_col)
            draw.ellipse([hx + hr * 0.28 - er, hy - hr * 0.02 - er, hx + hr * 0.28 + er, hy - hr * 0.02 + er], fill=eye_col)
            draw.ellipse([hx - hr * 0.22, hy + hr * 0.15, hx + hr * 0.22, hy + hr * 0.45], fill=eye_col)

        elif emo == "effort":
            draw.line([uv(-0.42, -0.28), uv(-0.15, -0.18)], fill=eye_col, width=line_w)
            draw.line([uv(0.42, -0.28), uv(0.15, -0.18)], fill=eye_col, width=line_w)
            draw.line([uv(-0.38, -0.05), uv(-0.18, -0.05)], fill=eye_col, width=int(line_w * 1.2))
            draw.line([uv(0.18, -0.05), uv(0.38, -0.05)], fill=eye_col, width=int(line_w * 1.2))
            draw.rectangle([hx - hr * 0.32, hy + hr * 0.18, hx + hr * 0.32, hy + hr * 0.42], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.line([uv(-0.32, 0.30), uv(0.32, 0.30)], fill=eye_col, width=1)
            for tu in [-0.16, 0.0, 0.16]:
                draw.line([uv(tu, 0.18), uv(tu, 0.42)], fill=eye_col, width=1)

        elif emo == "shocked":
            draw.arc([hx - hr * 0.45, hy - hr * 0.60, hx - hr * 0.15, hy - hr * 0.30], start=180, end=360, fill=eye_col, width=line_w)
            draw.arc([hx + hr * 0.15, hy - hr * 0.60, hx + hr * 0.45, hy - hr * 0.30], start=180, end=360, fill=eye_col, width=line_w)
            sr = int(hr * 0.18)
            draw.ellipse([hx - hr * 0.30 - sr, hy - hr * 0.08 - sr, hx - hr * 0.30 + sr, hy - hr * 0.08 + sr], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.ellipse([hx + hr * 0.30 - sr, hy - hr * 0.08 - sr, hx + hr * 0.30 + sr, hy - hr * 0.08 + sr], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.ellipse([hx - hr * 0.30 - 2, hy - hr * 0.08 - 2, hx - hr * 0.30 + 2, hy - hr * 0.08 + 2], fill=eye_col)
            draw.ellipse([hx + hr * 0.30 - 2, hy - hr * 0.08 - 2, hx + hr * 0.30 + 2, hy - hr * 0.08 + 2], fill=eye_col)
            draw.ellipse([hx - hr * 0.16, hy + hr * 0.18, hx + hr * 0.16, hy + hr * 0.55], fill=eye_col)

        elif emo == "focused":
            draw.line([uv(-0.45, -0.22), uv(0.45, -0.22)], fill=eye_col, width=int(line_w * 1.3))
            draw.line([uv(-0.38, -0.06), uv(-0.18, -0.06)], fill=eye_col, width=int(line_w * 1.2))
            draw.line([uv(0.18, -0.06), uv(0.38, -0.06)], fill=eye_col, width=int(line_w * 1.2))
            draw.line([uv(-0.20, 0.32), uv(0.20, 0.32)], fill=eye_col, width=line_w)
            draw.line([uv(0.20, 0.32), uv(0.25, 0.36)], fill=eye_col, width=line_w)

        elif emo == "sleepy":
            draw.arc([hx - hr * 0.42, hy - hr * 0.15, hx - hr * 0.18, hy + hr * 0.05], start=0, end=180, fill=eye_col, width=line_w)
            draw.arc([hx + hr * 0.18, hy - hr * 0.15, hx + hr * 0.42, hy + hr * 0.05], start=0, end=180, fill=eye_col, width=line_w)
            draw.ellipse([hx - hr * 0.10, hy + hr * 0.22, hx + hr * 0.10, hy + hr * 0.42], fill=eye_col)
            zx, zy = hx + hr * 0.52, hy - hr * 0.52
            draw.line([(zx, zy), (zx + 10, zy), (zx, zy + 10), (zx + 10, zy + 10)], fill=(80, 140, 240), width=max(1, int(1.5 * self.ss)))

        elif emo == "crying":
            draw.line([uv(-0.42, -0.15), uv(-0.25, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(-0.42, 0.05), uv(-0.25, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(0.42, -0.15), uv(0.25, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(0.42, 0.05), uv(0.25, -0.05)], fill=eye_col, width=line_w)
            tear_col = (40, 160, 240)
            draw.line([uv(-0.30, 0.05), uv(-0.30, 0.55)], fill=tear_col, width=int(2.5 * self.ss))
            draw.line([uv(0.30, 0.05), uv(0.30, 0.55)], fill=tear_col, width=int(2.5 * self.ss))
            draw.arc([hx - hr * 0.28, hy + hr * 0.25, hx + hr * 0.28, hy + hr * 0.60], start=180, end=360, fill=eye_col, width=line_w)

        elif emo == "pensive":
            draw.arc([hx - hr * 0.45, hy - hr * 0.48, hx - hr * 0.15, hy - hr * 0.20], start=180, end=360, fill=eye_col, width=line_w)
            draw.line([uv(0.15, -0.25), uv(0.45, -0.25)], fill=eye_col, width=line_w)
            er = int(2.5 * self.ss)
            draw.ellipse([hx - hr * 0.25 - er, hy - hr * 0.16 - er, hx - hr * 0.25 + er, hy - hr * 0.16 + er], fill=eye_col)
            draw.ellipse([hx + hr * 0.35 - er, hy - hr * 0.16 - er, hx + hr * 0.35 + er, hy - hr * 0.16 + er], fill=eye_col)
            draw.line([uv(0.02, 0.32), uv(0.28, 0.28)], fill=eye_col, width=line_w)

        elif emo == "manic":
            draw.ellipse([hx - hr * 0.32 - int(hr * 0.18), hy - hr * 0.08 - int(hr * 0.18), hx - hr * 0.32 + int(hr * 0.18), hy - hr * 0.08 + int(hr * 0.18)], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.ellipse([hx + hr * 0.30 - int(hr * 0.12), hy - hr * 0.08 - int(hr * 0.12), hx + hr * 0.30 + int(hr * 0.12), hy - hr * 0.08 + int(hr * 0.12)], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.ellipse([hx - hr * 0.32 - 2, hy - hr * 0.08 - 2, hx - hr * 0.32 + 2, hy - hr * 0.08 + 2], fill=eye_col)
            draw.ellipse([hx + hr * 0.30 - 2, hy - hr * 0.08 - 2, hx + hr * 0.30 + 2, hy - hr * 0.08 + 2], fill=eye_col)
            draw.line([uv(-0.40, 0.25), uv(-0.25, 0.40), uv(-0.10, 0.25), uv(0.05, 0.40), uv(0.20, 0.25), uv(0.35, 0.40)], fill=eye_col, width=line_w)

        elif emo == "ecstasy":
            draw.line([uv(-0.18, -0.15), uv(-0.35, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(-0.18, 0.05), uv(-0.35, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(0.18, -0.15), uv(0.35, -0.05)], fill=eye_col, width=line_w)
            draw.line([uv(0.18, 0.05), uv(0.35, -0.05)], fill=eye_col, width=line_w)
            draw.chord([hx - hr * 0.35, hy + hr * 0.15, hx + hr * 0.35, hy + hr * 0.60], start=0, end=180, fill=eye_col)

        elif emo == "wink":
            er = int(3.5 * self.ss)
            draw.ellipse([hx - hr * 0.30 - er, hy - hr * 0.08 - er, hx - hr * 0.30 + er, hy - hr * 0.08 + er], fill=eye_col)
            draw.arc([hx + hr * 0.15, hy - hr * 0.18, hx + hr * 0.45, hy + hr * 0.02], start=0, end=180, fill=eye_col, width=line_w)
            draw.arc([hx - hr * 0.15, hy + hr * 0.15, hx + hr * 0.38, hy + hr * 0.45], start=0, end=140, fill=eye_col, width=line_w)

        elif emo == "suspicious":
            draw.line([uv(-0.45, -0.22), uv(-0.15, -0.18)], fill=eye_col, width=line_w)
            draw.line([uv(0.15, -0.18), uv(0.45, -0.28)], fill=eye_col, width=line_w)
            er = int(2.5 * self.ss)
            draw.ellipse([hx - hr * 0.18 - er, hy - hr * 0.05 - er, hx - hr * 0.18 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.ellipse([hx + hr * 0.42 - er, hy - hr * 0.05 - er, hx + hr * 0.42 + er, hy - hr * 0.05 + er], fill=eye_col)
            draw.line([uv(-0.25, 0.34), uv(-0.05, 0.28), uv(0.15, 0.36), uv(0.30, 0.30)], fill=eye_col, width=line_w)

        elif emo == "despair":
            draw.line([uv(-0.45, -0.18), uv(-0.18, -0.35)], fill=eye_col, width=line_w)
            draw.line([uv(0.45, -0.18), uv(0.18, -0.35)], fill=eye_col, width=line_w)
            er = int(3.5 * self.ss)
            draw.ellipse([hx - hr * 0.30 - er, hy - hr * 0.05 - er, hx - hr * 0.30 + er, hy - hr * 0.05 + er], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.ellipse([hx + hr * 0.30 - er, hy - hr * 0.05 - er, hx + hr * 0.30 + er, hy - hr * 0.05 + er], fill=(255, 255, 255), outline=eye_col, width=line_w)
            draw.arc([hx - hr * 0.28, hy + hr * 0.18, hx + hr * 0.28, hy + hr * 0.58], start=180, end=360, fill=eye_col, width=line_w)

        elif emo == "dead":
            xw = int(hr * 0.12)
            for cx_eye in [hx - hr * 0.30, hx + hr * 0.30]:
                cy_eye = hy - hr * 0.05
                draw.line([(cx_eye - xw, cy_eye - xw), (cx_eye + xw, cy_eye + xw)], fill=eye_col, width=line_w)
                draw.line([(cx_eye - xw, cy_eye + xw), (cx_eye + xw, cy_eye - xw)], fill=eye_col, width=line_w)
            draw.ellipse([hx - hr * 0.18, hy + hr * 0.22, hx + hr * 0.18, hy + hr * 0.48], fill=eye_col)
            draw.chord([hx - hr * 0.08, hy + hr * 0.35, hx + hr * 0.08, hy + hr * 0.60], start=0, end=180, fill=(240, 80, 80))

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

    def _draw_world_prop(self, draw: ImageDraw.ImageDraw, p: Dict[str, Any], camera_x: float = 0.0):
        """Draws a placed/thrown object at its world (x, y) in the HD stage."""
        kind = p.get("kind", "")
        scale = float(p.get("scale", 1.0))
        wx = float(p.get("x", 0.0))
        wy = float(p.get("y", self.world_ground_y))
        cpt = self.world_to_canvas(np.array([[wx, wy]]), camera_x=camera_x)[0]
        cx, cy = float(cpt[0]), float(cpt[1])
        s = self.ss * scale

        if kind == "ball":
            r = int(22 * s)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                         fill=(220, 70, 60), outline=(150, 30, 30), width=max(1, int(2 * s)))
        elif kind == "box":
            w, h = int(34 * s), int(30 * s)
            draw.rectangle([cx - w, cy - h, cx + w, cy + h], fill=(150, 110, 70),
                           outline=(90, 60, 35), width=max(1, int(2 * s)))
            draw.line([(cx - w, cy - h), (cx + w, cy + h)], fill=(90, 60, 35), width=max(1, int(1.5 * s)))
            draw.line([(cx + w, cy - h), (cx - w, cy + h)], fill=(90, 60, 35), width=max(1, int(1.5 * s)))
        elif kind == "chair":
            cw, ch = int(26 * s), int(44 * s)
            col = (130, 90, 60)
            lw = max(1, int(3 * s))
            draw.line([(cx - cw, cy), (cx - cw, cy - ch // 2)], fill=col, width=lw)
            draw.line([(cx + cw, cy), (cx + cw, cy - ch // 2)], fill=col, width=lw)
            draw.line([(cx - cw - 5, cy - ch // 2), (cx + cw + 5, cy - ch // 2)], fill=col, width=lw + 1)
            draw.line([(cx - cw, cy - ch // 2), (cx - cw, cy - ch)], fill=col, width=lw)
        elif kind == "tree":
            tw = max(2, int(8 * s))
            th = int(130 * s)
            draw.line([(cx, cy), (cx, cy - th)], fill=(120, 100, 80), width=tw)
            fr = int(48 * s)
            fy = cy - th - int(8 * s)
            draw.ellipse([cx - fr, fy - fr, cx + fr, fy + fr], fill=(75, 140, 75),
                         outline=(50, 110, 50), width=max(1, int(2 * s)))
        elif kind == "crowd":
            sil = (200, 200, 215) if self.theme.name == "light" else (70, 70, 90)
            for off in (-1.4, -1.0, -0.6, 0.6, 1.0, 1.4):
                scpt = self.world_to_canvas(np.array([[wx + off, wy]]), camera_x=camera_x)[0]
                sh = int(80 * s)
                draw.line([(scpt[0], scpt[1]), (scpt[0], scpt[1] - sh)], fill=sil, width=int(3 * s))
                hr = int(11 * s)
                draw.ellipse([scpt[0] - hr, scpt[1] - sh - 2 * hr, scpt[0] + hr, scpt[1] - sh], fill=sil)
        elif kind == "confetti":
            rng = np.random.default_rng(1234)
            for _ in range(28):
                cxp = cx + rng.uniform(-90, 90) * s
                cyp = cy - rng.uniform(0, 160) * s
                col = ((230, 60, 80), (60, 160, 230), (245, 200, 60), (80, 200, 120))[int(rng.integers(0, 4))]
                draw.rectangle([cxp, cyp, cxp + 5 * s, cyp + 3 * s], fill=col)
        elif kind in ("desk", "table"):
            dw, dh = int(70 * s), int(50 * s)
            col = (110, 75, 45) if self.theme.name == "light" else (60, 65, 80)
            top_col = (145, 100, 60) if self.theme.name == "light" else (85, 90, 110)
            lw = max(1, int(3.5 * s))
            top_y = cy - dh
            draw.rectangle([cx - dw, top_y - int(8 * s), cx + dw, top_y], fill=top_col, outline=col, width=max(1, int(2 * s)))
            draw.line([(cx - dw + int(12 * s), top_y), (cx - dw + int(12 * s), cy)], fill=col, width=lw)
            draw.line([(cx + dw - int(12 * s), top_y), (cx + dw - int(12 * s), cy)], fill=col, width=lw)
            draw.rectangle([cx - dw + int(14 * s), top_y + int(4 * s), cx + dw - int(14 * s), top_y + int(24 * s)], fill=col)
        elif kind in ("laptop", "computer"):
            lw, lh = int(22 * s), int(16 * s)
            base_col = (70, 75, 85) if self.theme.name == "light" else (45, 50, 60)
            screen_col = (40, 160, 220) if self.theme.name == "dark" else (30, 120, 190)
            draw.rectangle([cx - lw, cy - int(4 * s), cx + lw, cy], fill=base_col, outline=(30, 30, 40), width=max(1, int(1.5 * s)))
            screen_poly = [
                (cx - lw + int(2 * s), cy - int(4 * s)),
                (cx + lw - int(2 * s), cy - int(4 * s)),
                (cx + lw - int(6 * s), cy - lh - int(8 * s)),
                (cx - lw + int(6 * s), cy - lh - int(8 * s))
            ]
            draw.polygon(screen_poly, fill=base_col, outline=(30, 30, 40))
            inner_poly = [
                (cx - lw + int(4 * s), cy - int(6 * s)),
                (cx + lw - int(4 * s), cy - int(6 * s)),
                (cx + lw - int(7 * s), cy - lh - int(6 * s)),
                (cx - lw + int(7 * s), cy - lh - int(6 * s))
            ]
            draw.polygon(inner_poly, fill=screen_col)

    def _draw_vector_vfx(self, draw: ImageDraw.ImageDraw, v: Dict[str, Any], c_pts_all: List[np.ndarray], camera_x: float = 0.0):
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
                cx, cy = float(v.get("x", 0.0)), float(v.get("y", self.world_ground_y))
                cpt = self.world_to_canvas(np.array([[cx, cy]]))
                cx, cy = float(cpt[0][0]), float(cpt[0][1])
        else:
            wx = float(v.get("x", 0.0))
            wy = float(v.get("y", self.world_ground_y))
            cpt = self.world_to_canvas(np.array([[wx, wy]]))
            cx, cy = float(cpt[0][0]), float(cpt[0][1])

        if kind in ("impact_burst", "starburst"):
            b_col = v.get("color", (255, 220, 40) if self.theme.name == "dark" else (240, 75, 20))
            r_outer = float(v.get("radius", 38.0 * self.ss * scale))
            r_inner = r_outer * 0.38
            rot = float(v.get("rotation", 0.0))
            poly_pts = []
            for k in range(16):
                ang = np.radians(k * 22.5 + rot)
                r = r_outer if (k % 2 == 0) else r_inner
                poly_pts.append((cx + np.cos(ang) * r, cy + np.sin(ang) * r))
            draw.polygon(poly_pts, fill=b_col, outline=(255, 255, 255), width=max(1, int(1.5 * self.ss)))
            flash_poly = []
            for k in range(16):
                ang = np.radians(k * 22.5 + rot)
                r = (r_outer * 0.45) if (k % 2 == 0) else (r_inner * 0.45)
                flash_poly.append((cx + np.cos(ang) * r, cy + np.sin(ang) * r))
            draw.polygon(flash_poly, fill=(255, 255, 255))
            for k in range(8):
                ang = np.radians(k * 45.0 + rot + 22.5)
                p1 = (cx + np.cos(ang) * (r_outer * 0.75), cy + np.sin(ang) * (r_outer * 0.75))
                p2 = (cx + np.cos(ang) * (r_outer * 1.40), cy + np.sin(ang) * (r_outer * 1.40))
                draw.line([p1, p2], fill=b_col, width=max(1, int(2.5 * self.ss)))

        elif kind in ("swing_arc", "smear_arc"):
            arc_col = v.get("color", (245, 245, 250) if self.theme.name == "dark" else (220, 50, 30))
            r = float(v.get("radius", 45.0 * self.ss * scale))
            start_ang = float(v.get("start_angle", 0.0))
            end_ang = float(v.get("end_angle", 140.0))
            draw.arc([cx - r, cy - r, cx + r, cy + r], start=start_ang, end=end_ang, fill=arc_col, width=int(4.5 * self.ss))

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
        vfx: Optional[List[Dict[str, Any]]] = None,
        zoom: float = 1.0,
        actor_expressions: Optional[List[str]] = None,
        actor_colors: Optional[List[Any]] = None,
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
                self.perspective.draw_pillar_colonnade(draw, self.theme, ground_y=self.ground_y)
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
        from .stage.theme import resolve_color
        N = len(joints_frame)
        c_pts_all = []
        for n in range(N):
            c_pts = self.world_to_canvas(joints_frame[n], camera_x=camera_x)
            c_pts_all.append(c_pts)
            show_face = scenery.get("show_face", True)
            if actor_expressions and n < len(actor_expressions) and actor_expressions[n]:
                emotion = actor_expressions[n]
            else:
                emotion = scenery.get("face_emotion", "neutral")
            custom_color = None
            if actor_colors and n < len(actor_colors) and actor_colors[n]:
                custom_color = resolve_color(actor_colors[n], fallback=self.theme.stickman_color)
            self.draw_puppet(draw, c_pts, joints_frame[n], custom_color=custom_color, show_face=show_face, face_emotion=emotion)

        # -------------------------------------------------------------
        # LAYER 4: Dynamic Hand-held & Foreground Props
        # -------------------------------------------------------------
        if props:
            for p in props:
                kind = p.get("kind")
                if kind in ("sword", "staff", "joint_gavel", "shield", "laptop", "computer"):
                    self._draw_joint_prop(draw, p, c_pts_all)
                elif kind in ("ball", "box", "chair", "tree", "crowd", "confetti", "desk", "table", "laptop", "computer"):
                    self._draw_world_prop(draw, p, camera_x=camera_x)
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
                self._draw_vector_vfx(draw, v, c_pts_all, camera_x=camera_x)

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
    cam_impulse: Optional[List[Dict[str, Any]]] = None,
    prop_tracks: Optional[List[List[Dict[str, Any]]]] = None,
    camera_track: Optional[Dict[str, Any]] = None,
    impacts: Optional[List[Dict[str, Any]]] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    actor_colors: Optional[List[Any]] = None,
) -> str:
    """Renders a complete 1280x720 HD video clip with stage scenery, props, and ffmpeg encoding."""
    from .renderer import decode_motion_features, compute_smooth_camera_track, impacts_to_vfx

    actor_expression_tracks = None
    if isinstance(feat_or_joints, (dict, np.ndarray)) and (
        isinstance(feat_or_joints, dict) or feat_or_joints.shape[-1] in (30, 60)
    ):
        if isinstance(feat_or_joints, dict):
            actor_expression_tracks = feat_or_joints.get("actor_expression_tracks")
            if actor_colors is None:
                actor_colors = feat_or_joints.get("actor_colors")
        joints = decode_motion_features(feat_or_joints)
    else:
        joints = np.asarray(feat_or_joints, dtype=np.float32)
        if joints.ndim == 3:
            joints = joints[:, np.newaxis, :, :]

    if fix_contact:
        joints = apply_contact_correction(joints)
    T, N, _, _ = joints.shape

    if impacts:
        vfx = list(vfx or []) + impacts_to_vfx(impacts)

    stage = StageRendererHD(width=width, height=height, theme_name=theme_name)
    if camera_track and "camera_x" in camera_track:
        cam_track = np.asarray(camera_track["camera_x"], dtype=np.float32)[:T]
        if len(cam_track) < T:
            cam_track = np.pad(cam_track, (0, T - len(cam_track)), mode="edge")
    elif scenery and scenery.get("auto_camera", True):
        cam_track = compute_smooth_camera_track(joints, alpha=0.10)
    else:
        cam_track = np.zeros(T, dtype=np.float32)
    # Hit-shake: explicit impulses + auto-derived from impact VFX (1-2f kicks)
    auto_impulses: List[Dict[str, Any]] = []
    if vfx:
        for v in vfx:
            if v.get("kind") in ("impact_burst", "heavy_landing", "starburst") and "start_frame" in v:
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
            if prop_tracks is not None:
                frame_props = [dict(p) for p in prop_tracks[t]]
            elif props:
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

            frame_expressions = None
            if actor_expression_tracks and t < len(actor_expression_tracks):
                frame_expressions = actor_expression_tracks[t]

            img = stage.render_stage_frame(
                joints[t],
                camera_x=cam_track[t],
                scenery=scenery,
                props=frame_props,
                text_overlay=text_overlay,
                vfx=frame_vfx,
                actor_expressions=frame_expressions,
                actor_colors=actor_colors
            )
            proc.stdin.write(img.tobytes())
            if progress_cb is not None and (t % 4 == 0 or t == T - 1):
                progress_cb(t + 1, T)

        close_ffmpeg_writer(proc)
    except Exception:
        proc.kill()
        raise

    return output_path
