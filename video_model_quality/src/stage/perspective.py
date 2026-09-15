"""1-Point Linear Perspective Engine and Classical Architectural Scenery.

Reproduces the cinematic depth, receding floorboards, classical columns,
and ornate baroque framing observed in goal_videos/ (light_5s.png).
"""

import math
import numpy as np
from typing import Tuple, List, Optional
from PIL import ImageDraw

from .theme import StageTheme


class PerspectiveStage:
    """Calculates 1-point perspective projections and draws architectural environments."""

    def __init__(
        self,
        width: int = 1280,
        height: int = 720,
        vanishing_pt: Tuple[int, int] = (640, 320),
        focal_length: float = 600.0
    ):
        self.width = width
        self.height = height
        self.vx, self.vy = vanishing_pt
        self.focal_length = focal_length

    def project_point(self, x: float, y: float, z: float) -> Tuple[float, float, float]:
        """Projects 3D world coordinate (x, y, z) into 2D screen coordinate (sx, sy, scale).
        
        Coordinate conventions:
        - x: Horizontal (-left, +right)
        - y: Vertical (+up, -down)
        - z: Depth (+into screen, 0 = screen plane)
        """
        depth = max(0.01, z + self.focal_length)
        scale = self.focal_length / depth
        sx = self.vx + x * scale
        sy = self.vy - y * scale
        return sx, sy, scale

    def draw_perspective_grid(self, draw: ImageDraw.ImageDraw, theme: StageTheme,
                              floor_lines: int = 12, ceiling_lines: int = 10,
                              line_width: int = 2):
        """Draws receding linear perspective floorboards and ceiling beams."""
        col = theme.grid_line_color

        # 1. Floorboard lines (radiate from vanishing point to bottom edge)
        # Floor extends from y=0 down to negative Y
        for i in range(floor_lines + 1):
            t = i / max(1, floor_lines)
            # Spread along the bottom width of the screen
            bx = -800 + t * (self.width + 1600)
            draw.line([(self.vx, self.vy), (bx, self.height)], fill=col, width=line_width)

        # 2. Ceiling lines (radiate from vanishing point to top edge)
        for i in range(ceiling_lines + 1):
            t = i / max(1, ceiling_lines)
            tx = -400 + t * (self.width + 800)
            draw.line([(self.vx, self.vy), (tx, 0)], fill=col, width=line_width)

    def draw_classical_pillar(
        self,
        draw: ImageDraw.ImageDraw,
        x: float,
        z: float,
        pillar_height: float = 550.0,
        pillar_width: float = 120.0,
        theme: StageTheme = None,
        ground_y: Optional[float] = None
    ):
        """Draws a classical architectural pillar in receding perspective with capital and plinth base."""
        sx, sy_base, scale = self.project_point(x, -280.0, z)
        if ground_y is not None:
            sy_base = float(ground_y)
        w = pillar_width * scale
        h = pillar_height * scale
        half_w = w / 2.0
        sy_top = sy_base - h

        col_fill = (15, 15, 15) if theme and theme.name == "light" else (240, 240, 240)
        col_line = (240, 240, 240) if theme and theme.name == "light" else (20, 20, 20)

        # 1. Stepped Plinth Base (Bottom Pedestal)
        base_h = h * 0.12
        step1_w = half_w * 1.3
        step2_w = half_w * 1.15
        
        # Lower base block
        draw.rectangle([sx - step1_w, sy_base - base_h * 0.45, sx + step1_w, sy_base],
                       fill=col_fill, outline=col_line, width=max(1, int(2 * scale)))
        # Upper base step
        draw.rectangle([sx - step2_w, sy_base - base_h, sx + step2_w, sy_base - base_h * 0.45],
                       fill=col_fill, outline=col_line, width=max(1, int(2 * scale)))

        # 2. Column Shaft (Vertical Body with Fluting)
        shaft_top = sy_top + h * 0.12
        shaft_bot = sy_base - base_h
        draw.rectangle([sx - half_w, shaft_top, sx + half_w, shaft_bot],
                       fill=col_fill, outline=col_line, width=max(1, int(2 * scale)))

        # White vertical fluting highlight lines along column edge
        flute_inset = half_w * 0.82
        draw.line([(sx - flute_inset, shaft_top + 4), (sx - flute_inset, shaft_bot - 4)],
                  fill=col_line, width=max(1, int(1.5 * scale)))
        draw.line([(sx + flute_inset, shaft_top + 4), (sx + flute_inset, shaft_bot - 4)],
                  fill=col_line, width=max(1, int(1.5 * scale)))

        # 3. Capital Molding (Top Crown)
        cap_h = h * 0.12
        draw.rectangle([sx - step2_w, shaft_top - cap_h * 0.55, sx + step2_w, shaft_top],
                       fill=col_fill, outline=col_line, width=max(1, int(2 * scale)))
        draw.rectangle([sx - step1_w, shaft_top - cap_h, sx + step1_w, shaft_top - cap_h * 0.55],
                       fill=col_fill, outline=col_line, width=max(1, int(2 * scale)))

    def draw_pillar_colonnade(self, draw: ImageDraw.ImageDraw, theme: StageTheme, ground_y: Optional[float] = None):
        """Draws the 3 pairs of receding pillars on left and right sides matching goal_videos/."""
        # 3 depth tiers: Forefront (z=50), Mid (z=320), Deep (z=700)
        depths = [700.0, 320.0, 60.0]  # Draw back-to-front
        x_offsets = [380.0, 520.0, 720.0]  # Width distance from center

        for i, z in enumerate(depths):
            x_off = x_offsets[i]
            # Left pillar
            self.draw_classical_pillar(draw, -x_off, z, theme=theme, ground_y=ground_y)
            # Right pillar
            self.draw_classical_pillar(draw, x_off, z, theme=theme, ground_y=ground_y)

    def draw_baroque_ornate_frame(
        self,
        draw: ImageDraw.ImageDraw,
        center_x: float = 640,
        center_y: float = 380,
        width: float = 380,
        height: float = 360,
        theme: StageTheme = None
    ):
        """Draws central baroque decorative picture/mirror frame (light_5s.png)."""
        hw = width / 2.0
        hh = height / 2.0
        x0, y0 = center_x - hw, center_y - hh
        x1, y1 = center_x + hw, center_y + hh

        col_frame = (15, 15, 15)
        col_gold_white = (255, 255, 255)
        border_thickness = 28

        # Outer frame border
        draw.rectangle([x0, y0, x1, y1], fill=col_frame, outline=col_gold_white, width=2)
        # Inner window cutout
        draw.rectangle([x0 + border_thickness, y0 + border_thickness,
                        x1 - border_thickness, y1 - border_thickness],
                       fill=(250, 250, 248), outline=col_gold_white, width=2)

        # Ornate corner scrollwork filigree flourishes
        corners = [
            (x0, y0, 1, 1),
            (x1, y0, -1, 1),
            (x0, y1, 1, -1),
            (x1, y1, -1, -1)
        ]
        for cx, cy, dx, dy in corners:
            # Curved filigree scallops
            for r in [8, 16, 24]:
                bx0 = min(cx, cx + dx * r)
                bx1 = max(cx, cx + dx * r)
                by0 = min(cy, cy + dy * r)
                by1 = max(cy, cy + dy * r)
                draw.arc([bx0, by0, bx1, by1], start=0, end=360, fill=col_gold_white, width=2)

        # Crest atop the frame
        crest_w = 40
        draw.ellipse([center_x - crest_w, y0 - 16, center_x + crest_w, y0 + 16],
                     fill=col_frame, outline=col_gold_white, width=2)
        draw.ellipse([center_x - crest_w + 10, y1 - 16, center_x + crest_w - 10, y1 + 16],
                     fill=col_frame, outline=col_gold_white, width=2)
