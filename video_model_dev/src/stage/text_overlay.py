"""Kinetic typography and bold text overlays for the Puppet Stage Platform.

Reproduces bold graphic design slogans and text emphasis (e.g. "NOT A VERDICT" in light_8s.png).
"""

from typing import Tuple, Optional
from PIL import ImageDraw, ImageFont


def draw_kinetic_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: float,
    cy: float,
    font_size: int = 42,
    color: Tuple[int, int, int] = (17, 17, 17),
    letter_spacing: int = 4,
    shadow: bool = True
):
    """Draws bold kinetic title typography with letter spacing and shadow."""
    try:
        # Try loading Windows system fonts: Impact, Arial-Bold, SegoeUI-Bold
        font = ImageFont.truetype("arialbd.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("impact.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    # Calculate total text length with spacing
    total_w = 0
    char_widths = []
    for char in text:
        bbox = draw.textbbox((0, 0), char, font=font)
        w = bbox[2] - bbox[0] + letter_spacing
        char_widths.append(w)
        total_w += w
        
    start_x = cx - total_w / 2.0
    
    # Draw drop shadow first
    if shadow:
        sx = start_x + 3
        sy = cy - font_size / 2.0 + 3
        shadow_col = (200, 200, 200)
        curr_x = sx
        for idx, char in enumerate(text):
            draw.text((curr_x, sy), char, fill=shadow_col, font=font)
            curr_x += char_widths[idx]

    # Draw primary text
    curr_x = start_x
    sy = cy - font_size / 2.0
    for idx, char in enumerate(text):
        draw.text((curr_x, sy), char, fill=color, font=font)
        curr_x += char_widths[idx]
