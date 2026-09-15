"""Procedural scenery props, hand-held objects, and destruction elements.

Matches the key visual motifs from goal_videos/:
- Speech bubble (held in stickman hands).
- Giant red judge's gavel slamming downward.
- Classical pillars (intact, cracked, and shattered rubble polygons).
- 3D red prison cage with padlock keyhole box.
- Ground fracture fissures and ceiling cracks.
- Red fluid ribbon splashes.
- Stamped letters and envelopes with red 'X' brush strokes.
"""

import math
import numpy as np
from typing import Tuple, List, Optional
from PIL import ImageDraw

from .theme import StageTheme, LIGHT_THEME, DARK_THEME


def draw_speech_bubble(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    width: float = 140.0,
    height: float = 85.0,
    color: Tuple[int, int, int] = (229, 57, 53),
    tail_dir: str = "bottom_left"
):
    """Draws rounded speech bubble prop matching light_1s.png."""
    r = 20.0
    x0, y0 = x - width / 2.0, y - height / 2.0
    x1, y1 = x + width / 2.0, y + height / 2.0
    
    # Rounded rectangle body
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=color)
    
    # Pointer tail
    if tail_dir == "bottom_left":
        tail_poly = [(x0 + 20, y1 - 2), (x0 + 45, y1 - 2), (x0 + 10, y1 + 22)]
        draw.polygon(tail_poly, fill=color)
    elif tail_dir == "left":
        tail_poly = [(x0 + 2, y + 10), (x0 + 2, y - 10), (x0 - 20, y + 5)]
        draw.polygon(tail_poly, fill=color)


def draw_giant_gavel(
    draw: ImageDraw.ImageDraw,
    head_cx: float,
    head_cy: float,
    angle_deg: float = 25.0,
    scale: float = 1.0,
    color: Tuple[int, int, int] = (229, 57, 53)
):
    """Draws massive red judge's mallet/gavel slamming downward (light_7s.png)."""
    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    
    # Normal vector perpendicular to angle
    nx, ny = -sin_a, cos_a
    # Axial vector along handle direction
    ax, ay = cos_a, sin_a

    # 1. Gavel Head (Cylinder)
    head_len = 160.0 * scale
    head_rad = 65.0 * scale
    
    # Head ends
    top_x = head_cx + nx * (head_len / 2.0)
    top_y = head_cy + ny * (head_len / 2.0)
    bot_x = head_cx - nx * (head_len / 2.0)
    bot_y = head_cy - ny * (head_len / 2.0)

    # 4 corners of gavel cylinder
    p1 = (top_x + ax * head_rad, top_y + ay * head_rad)
    p2 = (top_x - ax * head_rad, top_y - ay * head_rad)
    p3 = (bot_x - ax * head_rad, bot_y - ay * head_rad)
    p4 = (bot_x + ax * head_rad, bot_y + ay * head_rad)
    
    draw.polygon([p1, p2, p3, p4], fill=color)
    
    # End caps & ridges
    ridge_color = (max(0, color[0] - 30), max(0, color[1] - 20), max(0, color[2] - 20))
    draw.ellipse([top_x - head_rad, top_y - head_rad * 0.4, top_x + head_rad, top_y + head_rad * 0.4],
                 fill=ridge_color)
    draw.ellipse([bot_x - head_rad, bot_y - head_rad * 0.4, bot_x + head_rad, bot_y + head_rad * 0.4],
                 fill=color)

    # 2. Long Wooden Handle
    handle_len = 380.0 * scale
    handle_w = 26.0 * scale
    
    h_start_x = head_cx
    h_start_y = head_cy
    h_end_x = head_cx + ax * handle_len
    h_end_y = head_cy + ay * handle_len
    
    h1 = (h_start_x + nx * (handle_w / 2.0), h_start_y + ny * (handle_w / 2.0))
    h2 = (h_start_x - nx * (handle_w / 2.0), h_start_y - ny * (handle_w / 2.0))
    h3 = (h_end_x - nx * (handle_w / 2.0), h_end_y - ny * (handle_w / 2.0))
    h4 = (h_end_x + nx * (handle_w / 2.0), h_end_y + ny * (handle_w / 2.0))
    
    draw.polygon([h1, h2, h3, h4], fill=color)
    # Rounded handle end grip
    draw.ellipse([h_end_x - handle_w, h_end_y - handle_w, h_end_x + handle_w, h_end_y + handle_w], fill=color)


def draw_prison_cage(
    draw: ImageDraw.ImageDraw,
    cx: float = 640.0,
    cy: float = 400.0,
    width: float = 480.0,
    height: float = 440.0,
    color: Tuple[int, int, int] = (211, 47, 47)
):
    """Draws 3D perspective red iron prison cage with keyhole padlock (dark_8s.png)."""
    hw = width / 2.0
    hh = height / 2.0
    
    # Outer frame
    draw.rectangle([cx - hw, cy - hh, cx + hw, cy + hh], outline=color, width=12)
    # Intermediate horizontal framing beams
    draw.line([(cx - hw, cy - hh * 0.65), (cx + hw, cy - hh * 0.65)], fill=color, width=10)
    draw.line([(cx - hw, cy + hh * 0.65), (cx + hw, cy + hh * 0.65)], fill=color, width=10)

    # Vertical iron bars
    num_bars = 10
    for i in range(1, num_bars):
        bx = cx - hw + i * (width / num_bars)
        draw.line([(bx, cy - hh), (bx, cy + hh)], fill=color, width=8)

    # Receding back-wall perspective cage bars
    back_inset = 60.0
    b_hw = hw - back_inset
    b_hh = hh - back_inset
    draw.rectangle([cx - b_hw, cy - b_hh, cx + b_hw, cy + b_hh], outline=(150, 30, 30), width=6)
    
    # Corner depth connecting struts
    draw.line([(cx - hw, cy - hh), (cx - b_hw, cy - b_hh)], fill=color, width=8)
    draw.line([(cx + hw, cy - hh), (cx + b_hw, cy - b_hh)], fill=color, width=8)
    draw.line([(cx - hw, cy + hh), (cx - b_hw, cy + b_hh)], fill=color, width=8)
    draw.line([(cx + hw, cy + hh), (cx + b_hw, cy + b_hh)], fill=color, width=8)

    # Center Door & Padlock Box with Keyhole
    door_w = 110.0
    door_h = height * 0.85
    draw.rectangle([cx - door_w / 2.0, cy - door_h / 2.0, cx + door_w / 2.0, cy + door_h / 2.0],
                   outline=color, width=10)

    # Red rectangular lock box
    lock_w, lock_h = 56.0, 50.0
    lx, ly = cx - 40.0, cy - 10.0
    draw.rectangle([lx - lock_w / 2.0, ly - lock_h / 2.0, lx + lock_w / 2.0, ly + lock_h / 2.0],
                   fill=color)
    
    # White keyhole cutout
    draw.ellipse([lx - 6, ly - 14, lx + 6, ly - 2], fill=(255, 255, 255))
    draw.polygon([(lx - 5, ly - 4), (lx + 5, ly - 4), (lx + 7, ly + 12), (lx - 7, ly + 12)],
                 fill=(255, 255, 255))


def draw_shattered_pillar_rubble(
    draw: ImageDraw.ImageDraw,
    theme: StageTheme,
    left_rubble_cx: float = 180.0,
    right_rubble_cx: float = 1100.0,
    ground_y: float = 600.0
):
    """Draws broken fallen pillar trunks and sharp rubble polygon chunks (light_8s.png)."""
    col = (15, 15, 15)
    line_col = (245, 245, 245)

    # Left collapsed pillar base & fallen drum
    p_left_base = [
        (40, ground_y), (80, ground_y - 120), (190, ground_y - 160),
        (230, ground_y - 100), (250, ground_y)
    ]
    draw.polygon(p_left_base, fill=col, outline=line_col)
    
    # Horizontal fallen column barrel
    p_left_barrel = [
        (160, ground_y - 20), (280, ground_y - 80), (380, ground_y - 45), (370, ground_y), (180, ground_y)
    ]
    draw.polygon(p_left_barrel, fill=col, outline=line_col)

    # Right collapsed pillar base
    p_right_base = [
        (1050, ground_y), (1080, ground_y - 140), (1220, ground_y - 180),
        (1260, ground_y - 100), (1270, ground_y)
    ]
    draw.polygon(p_right_base, fill=col, outline=line_col)

    p_right_barrel = [
        (880, ground_y), (900, ground_y - 50), (1020, ground_y - 75), (1080, ground_y - 20), (1060, ground_y)
    ]
    draw.polygon(p_right_barrel, fill=col, outline=line_col)

    # Scattered polygonal splinter rocks across the center
    rubble_stones = [
        [(380, ground_y), (410, ground_y - 25), (440, ground_y)],
        [(460, ground_y), (480, ground_y - 15), (510, ground_y - 5), (495, ground_y)],
        [(770, ground_y), (800, ground_y - 28), (830, ground_y - 10), (815, ground_y)],
        [(850, ground_y), (875, ground_y - 18), (890, ground_y)]
    ]
    for stone in rubble_stones:
        draw.polygon(stone, fill=col, outline=line_col)


def draw_ground_and_ceiling_cracks(
    draw: ImageDraw.ImageDraw,
    theme: StageTheme,
    impact_cx: float = 640.0,
    ground_y: float = 600.0
):
    """Draws fracture cracks on floor and ceiling fissures radiating from impact (light_8s.png)."""
    col = theme.grid_line_color
    
    # Floor cracks radiating out from center
    cracks = [
        # Center-left fissures
        [(impact_cx, ground_y), (impact_cx - 60, ground_y + 20), (impact_cx - 150, ground_y + 15), (impact_cx - 240, ground_y + 35)],
        [(impact_cx - 60, ground_y + 20), (impact_cx - 110, ground_y + 55), (impact_cx - 180, ground_y + 70)],
        # Center-right fissures
        [(impact_cx, ground_y), (impact_cx + 80, ground_y + 18), (impact_cx + 170, ground_y + 12), (impact_cx + 260, ground_y + 40)],
        [(impact_cx + 80, ground_y + 18), (impact_cx + 130, ground_y + 50), (impact_cx + 210, ground_y + 65)]
    ]
    for seg in cracks:
        for i in range(len(seg) - 1):
            draw.line([seg[i], seg[i + 1]], fill=col, width=2)

    # Ceiling crack fracture web
    ceiling_cracks = [
        [(300, 0), (380, 50), (490, 40), (560, 90), (640, 70), (740, 110), (880, 50), (980, 0)],
        [(490, 40), (450, 95), (410, 120)],
        [(640, 70), (650, 140), (620, 180)],
        [(740, 110), (790, 160)]
    ]
    for seg in ceiling_cracks:
        for i in range(len(seg) - 1):
            draw.line([seg[i], seg[i + 1]], fill=col, width=2)


def draw_red_fluid_splash(
    draw: ImageDraw.ImageDraw,
    cx: float = 670.0,
    cy: float = 380.0,
    scale: float = 1.0,
    color: Tuple[int, int, int] = (229, 57, 53)
):
    """Draws the dynamic swirling red ink / fluid ribbon splash (light_8s.png)."""
    # Stylized ribbon spline segments
    ribbon_points = [
        (cx - 120 * scale, cy - 80 * scale),
        (cx - 60 * scale, cy - 95 * scale),
        (cx + 20 * scale, cy - 65 * scale),
        (cx + 80 * scale, cy - 90 * scale),
        (cx + 60 * scale, cy - 30 * scale),
        (cx + 10 * scale, cy + 10 * scale),
        (cx + 70 * scale, cy + 40 * scale),
        (cx + 40 * scale, cy + 90 * scale),
        (cx - 20 * scale, cy + 70 * scale),
        (cx - 10 * scale, cy + 20 * scale),
        (cx - 50 * scale, cy - 20 * scale)
    ]
    for i in range(len(ribbon_points) - 1):
        pt1 = ribbon_points[i]
        pt2 = ribbon_points[i + 1]
        draw.line([pt1, pt2], fill=color, width=int(18 * scale))
        draw.ellipse([pt1[0] - 9 * scale, pt1[1] - 9 * scale, pt1[0] + 9 * scale, pt1[1] + 9 * scale], fill=color)


def draw_envelope_with_x(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    width: float = 240.0,
    height: float = 160.0
):
    """Draws white envelope with thick red 'X' brush stroke (dark_5s.png)."""
    hw, hh = width / 2.0, height / 2.0
    x0, y0 = cx - hw, cy - hh
    x1, y1 = cx + hw, cy + hh

    # Envelope base
    draw.rectangle([x0, y0, x1, y1], fill=(255, 255, 255), outline=(15, 15, 15), width=3)
    # Envelope flap lines
    draw.line([(x0, y0), (cx, cy + 10)], fill=(80, 80, 80), width=2)
    draw.line([(x1, y0), (cx, cy + 10)], fill=(80, 80, 80), width=2)
    draw.line([(x0, y1), (cx - 30, cy + 15)], fill=(120, 120, 120), width=2)
    draw.line([(x1, y1), (cx + 30, cy + 15)], fill=(120, 120, 120), width=2)

    # Big red 'X' cross
    col_x = (229, 57, 53)
    x_inset = 25.0
    draw.line([(x0 + x_inset, y0 + x_inset), (x1 - x_inset, y1 - x_inset)], fill=col_x, width=28)
    draw.line([(x0 + x_inset, y1 - x_inset), (x1 - x_inset, y0 + x_inset)], fill=col_x, width=28)
