"""Split-screen comic panels, thought bubble vignettes, and glowing spline webs.

Implements the multi-camera framing and abstract space effects from goal_videos/:
- 3-panel split-screen with neon divider borders (dark_5s.png).
- Thought-bubble circular vignette cutouts (dark_3s.png).
- Luminous organic purple/lavender spline energy webs (dark_0s.png).
"""

import math
import numpy as np
from typing import Tuple, List, Optional
from PIL import Image, ImageDraw

from .theme import StageTheme


class SplitScreenPanels:
    """Manages 3-panel vertical split-screen compositions (dark_5s.png)."""

    def __init__(self, width: int = 1280, height: int = 720, num_panels: int = 3):
        self.width = width
        self.height = height
        self.num_panels = num_panels
        self.panel_width = width / float(num_panels)

    def get_panel_bounds(self, panel_idx: int) -> Tuple[int, int, int, int]:
        """Returns (x0, y0, x1, y1) bounding box for a given panel index (0, 1, 2)."""
        x0 = int(panel_idx * self.panel_width)
        x1 = int((panel_idx + 1) * self.panel_width)
        return x0, 0, x1, self.height

    def draw_panel_dividers(
        self,
        draw: ImageDraw.ImageDraw,
        color: Tuple[int, int, int] = (139, 114, 214),
        border_width: int = 6
    ):
        """Draws glowing vertical dividing bars between comic panels."""
        for i in range(1, self.num_panels):
            x = int(i * self.panel_width)
            draw.line([(x, 0), (x, self.height)], fill=color, width=border_width)


def draw_thought_bubble(
    draw: ImageDraw.ImageDraw,
    cx: float = 320.0,
    cy: float = 380.0,
    radius: float = 190.0,
    border_color: Tuple[int, int, int] = (139, 114, 214),
    bg_color: Tuple[int, int, int] = (255, 255, 255)
):
    """Draws circular thought bubble vignette cutout with trail bubbles (dark_3s.png)."""
    # Main thought bubble circle
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=bg_color, outline=border_color, width=12)

    # Ascending small thought connector bubbles
    trail = [
        (cx + radius * 0.72, cy - radius * 0.72, 32.0),
        (cx + radius * 0.95, cy - radius * 0.95, 24.0),
        (cx + radius * 1.15, cy - radius * 1.15, 16.0),
        (cx + radius * 1.30, cy - radius * 1.30, 10.0)
    ]
    for bx, by, br in trail:
        draw.ellipse([bx - br, by - br, bx + br, by + br],
                     fill=bg_color, outline=border_color, width=6)


def draw_organic_spline_web(
    draw: ImageDraw.ImageDraw,
    width: int = 1280,
    height: int = 720,
    seed: int = 0,
    color: Tuple[int, int, int] = (139, 114, 214)
):
    """Draws looping, curved lavender energy splines across dark space (dark_0s.png)."""
    rng = np.random.default_rng(seed)
    num_strands = 14
    
    for s in range(num_strands):
        # Generate random smooth parametric control points
        num_pts = 6
        xs = np.linspace(-100, width + 100, num_pts)
        ys = rng.uniform(50, height - 50, num_pts)
        # Random vertical wave modulation
        ys += 60.0 * np.sin(np.linspace(0, 3 * np.pi, num_pts) + s)

        # Smooth cubic interpolation
        fine_t = np.linspace(0, 1, 60)
        curve_pts = []
        for i in range(len(fine_t)):
            idx_float = fine_t[i] * (num_pts - 1)
            idx = int(idx_float)
            frac = idx_float - idx
            if idx >= num_pts - 1:
                curve_pts.append((float(xs[-1]), float(ys[-1])))
            else:
                x = (1.0 - frac) * xs[idx] + frac * xs[idx + 1]
                y = (1.0 - frac) * ys[idx] + frac * ys[idx + 1]
                curve_pts.append((float(x), float(y)))

        # Draw smooth line strand
        line_w = int(rng.choice([4, 6, 8, 10]))
        for k in range(len(curve_pts) - 1):
            draw.line([curve_pts[k], curve_pts[k + 1]], fill=color, width=line_w)
