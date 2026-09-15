"""Terminal / ASCII Symbolic Stage Preview.

Allows LLMs and terminal users to visualize the 2D puppet stage as text and symbols.
Renders joints, bones, perspective grids, props, and face emotions into an ASCII character grid.
"""

from typing import Any, Dict, List, Optional
import numpy as np

# Bone connectivity segments between joint indices (0..14)
BONE_SEGMENTS = [
    (0, 1), (1, 2), (2, 3), (3, 4),      # Torso & Head
    (2, 5), (5, 6),                      # Left Arm
    (2, 7), (7, 8),                      # Right Arm
    (0, 9), (9, 10), (10, 11),           # Left Leg
    (0, 12), (12, 13), (13, 14)          # Right Leg
]


def bresenham_line(x0: int, y0: int, x1: int, y1: int):
    """Yields integer grid coordinates between (x0, y0) and (x1, y1)."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    cx, cy = x0, y0
    while True:
        yield cx, cy
        if cx == x1 and cy == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy


class TerminalStagePreview:
    """Renders puppet skeletons, stage geometry, and props onto a 2D ASCII character grid."""

    def __init__(self, cols: int = 80, rows: int = 24):
        self.cols = cols
        self.rows = rows
        # World boundaries: x in [-1.6, 1.6], y in [-0.55, 0.75]
        self.x_min = -1.6
        self.x_max = 1.6
        self.y_min = -0.55
        self.y_max = 0.75

    def world_to_grid(self, wx: float, wy: float) -> tuple[int, int]:
        """Maps world coordinates to terminal (col, row) coordinates."""
        gx = int((wx - self.x_min) / (self.x_max - self.x_min) * (self.cols - 1))
        # Invert row so +Y is up
        gy = int((self.y_max - wy) / (self.y_max - self.y_min) * (self.rows - 1))
        gx = max(0, min(self.cols - 1, gx))
        gy = max(0, min(self.rows - 1, gy))
        return gx, gy

    def render_ascii_frame(
        self,
        joints_frame: np.ndarray,
        scenery: Optional[Dict[str, Any]] = None,
        props: Optional[List[Dict[str, Any]]] = None,
        text_overlay: Optional[Dict[str, Any]] = None,
        frame_idx: int = 0,
        actor_labels: Optional[List[str]] = None,
        x_bounds: Optional[tuple] = None,
    ) -> str:
        """Renders one frame into a multi-line ASCII string.

        x_bounds: optional (x_min, x_max) override. When given, the frame is
        framed tightly around the actors so their relative spacing is legible.
        actor_labels: per-actor marker, e.g. ["A", "B"] (head cell).
        """
        if x_bounds is not None:
            self.x_min, self.x_max = float(x_bounds[0]), float(x_bounds[1])
        grid = [[" " for _ in range(self.cols)] for _ in range(self.rows)]
        scenery = scenery or {}
        props = props or []

        # 1. Ground plane
        _, ground_row = self.world_to_grid(0.0, -0.50)
        for c in range(self.cols):
            if 0 <= ground_row < self.rows:
                grid[ground_row][c] = "_"

        # 2. Scenery elements
        scene_type = scenery.get("type", "plain")
        if scene_type == "perspective_hall":
            # Vanishing point
            vx, vy = self.world_to_grid(0.0, 0.15)
            if 0 <= vy < self.rows and 0 <= vx < self.cols:
                grid[vy][vx] = "+"
            # Floor perspective lines radiating from vanishing point
            for fx in np.linspace(-1.5, 1.5, 9):
                gx, gy = self.world_to_grid(fx, -0.50)
                for px, py in bresenham_line(vx, vy, gx, gy):
                    if py >= vy and grid[py][px] == " ":
                        grid[py][px] = "."

            # Pillars
            if scenery.get("colonnade", True):
                for px in [-1.2, -0.7, 0.7, 1.2]:
                    col, bot = self.world_to_grid(px, -0.50)
                    _, top = self.world_to_grid(px, 0.45)
                    for r in range(top, bot):
                        if 0 <= r < self.rows:
                            grid[r][col] = "|"
                            if col + 1 < self.cols:
                                grid[r][col + 1] = "|"

            # Rubble
            if scenery.get("shattered_pillars", False):
                for rx in [-1.1, -0.6, 0.6, 1.1]:
                    c, r = self.world_to_grid(rx, -0.48)
                    for dc in [-1, 0, 1]:
                        if 0 <= c + dc < self.cols and 0 <= r < self.rows:
                            grid[r][c + dc] = "#"

            # Baroque frame
            if scenery.get("baroque_frame", False):
                c0, r0 = self.world_to_grid(-0.25, 0.40)
                c1, r1 = self.world_to_grid(0.25, -0.15)
                for c in range(c0, c1 + 1):
                    if 0 <= r0 < self.rows and 0 <= c < self.cols:
                        grid[r0][c] = "="
                    if 0 <= r1 < self.rows and 0 <= c < self.cols:
                        grid[r1][c] = "="
                for r in range(r0, r1 + 1):
                    if 0 <= r < self.rows and 0 <= c0 < self.cols:
                        grid[r][c0] = "|"
                    if 0 <= r < self.rows and 0 <= c1 < self.cols:
                        grid[r][c1] = "|"

        elif scene_type == "spline_web":
            for r in range(4, self.rows - 4, 3):
                for c in range(self.cols):
                    if (c + r * 3) % 7 == 0:
                        grid[r][c] = "~"

        elif scenery.get("prison_cage", False):
            # 3D Prison Cage
            c0, r0 = self.world_to_grid(-0.6, 0.55)
            c1, r1 = self.world_to_grid(0.6, -0.50)
            for c in range(c0, c1 + 1):
                if 0 <= r0 < self.rows:
                    grid[r0][c] = "="
                if 0 <= r1 < self.rows:
                    grid[r1][c] = "="
            for bar_c in range(c0, c1 + 1, 3):
                for r in range(r0, r1 + 1):
                    grid[r][bar_c] = "|"
            # Lock
            mid_c = (c0 + c1) // 2
            mid_r = (r0 + r1) // 2
            grid[mid_r][mid_c] = "@"

        # 3. Props
        for p in props:
            kind = p.get("kind", "")
            if kind == "speech_bubble":
                # Bubble representation
                b_c = p.get("grid_c", 45)
                b_r = p.get("grid_r", 8)
                msg = "[ ... ]"
                for i, ch in enumerate(msg):
                    if 0 <= b_c + i < self.cols and 0 <= b_r < self.rows:
                        grid[b_r][b_c + i] = ch
            elif kind == "gavel":
                g_c = p.get("grid_c", 45)
                g_r = p.get("grid_r", 10)
                if 0 <= g_r < self.rows and 0 <= g_c < self.cols:
                    grid[g_r][g_c] = "T"
                    if g_c + 1 < self.cols:
                        grid[g_r][g_c + 1] = "="
            elif kind == "envelope_x":
                e_c = 38
                e_r = 10
                for dc in range(-5, 6):
                    grid[e_r - 2][e_c + dc] = "-"
                    grid[e_r + 2][e_c + dc] = "-"
                grid[e_r][e_c] = "X"

        # 4. Stickmen Puppets
        joints_arr = np.asarray(joints_frame)
        if joints_arr.ndim == 2:
            joints_arr = joints_arr[np.newaxis, :, :]

        N = len(joints_arr)
        for n in range(N):
            pts = joints_arr[n]
            # Draw bones
            for ja, jb in BONE_SEGMENTS:
                x0, y0 = self.world_to_grid(float(pts[ja, 0]), float(pts[ja, 1]))
                x1, y1 = self.world_to_grid(float(pts[jb, 0]), float(pts[jb, 1]))
                # Choose bone character based on slope
                dx = x1 - x0
                dy = y1 - y0
                if abs(dx) > 2 * abs(dy):
                    ch = "-"
                elif abs(dy) > 2 * abs(dx):
                    ch = "|"
                elif (dx > 0 and dy > 0) or (dx < 0 and dy < 0):
                    ch = "\\"
                else:
                    ch = "/"

                for px, py in bresenham_line(x0, y0, x1, y1):
                    if 0 <= py < self.rows and 0 <= px < self.cols:
                        grid[py][px] = ch

            # Head (joint 4)
            hx, hy = self.world_to_grid(float(pts[4, 0]), float(pts[4, 1]))
            if 0 <= hy < self.rows and 0 <= hx < self.cols:
                emotion = scenery.get("face_emotion", "")
                label = ""
                if actor_labels and n < len(actor_labels):
                    label = str(actor_labels[n])
                if emotion == "angry":
                    grid[hy][hx] = "X"
                elif emotion == "distress":
                    grid[hy][hx] = "@"
                else:
                    grid[hy][hx] = label or "O"

        # 5. Kinetic text overlay
        if text_overlay:
            txt = text_overlay.get("text", "")
            tr = 12
            tc = max(2, (self.cols - len(txt)) // 2 - 10)
            for i, ch in enumerate(txt):
                if 0 <= tc + i < self.cols and 0 <= tr < self.rows:
                    grid[tr][tc + i] = ch

        # Header banner
        header = f"=== PUPPET STAGE PREVIEW | Frame: {frame_idx:03d} | Scene: {scene_type.upper()} ==="
        body = "\n".join("".join(row) for row in grid)
        return f"{header}\n{body}\n{'=' * len(header)}"
