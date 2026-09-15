"""Styling themes for the Puppet Stage Platform (Light & Dark Themes).

Matches the exact aesthetic discovered in goal_videos/ (1280x720 24fps):
- Light Theme: Textured paper/cream background, ink stickmen, red narrative accents.
- Dark Theme: Deep cosmic black, solid white stickmen, glowing purple splines, red cages.
"""

from typing import Dict, Any, Tuple
from PIL import Image, ImageDraw


class StageTheme:
    """Color palette and rendering parameters for a stage theme."""

    def __init__(
        self,
        name: str,
        bg_color: Tuple[int, int, int],
        floor_color: Tuple[int, int, int],
        stickman_color: Tuple[int, int, int],
        stickman_outline: Tuple[int, int, int],
        accent_red: Tuple[int, int, int],
        accent_purple: Tuple[int, int, int],
        shadow_color: Tuple[int, int, int],
        grid_line_color: Tuple[int, int, int],
        rubble_color: Tuple[int, int, int],
        text_color: Tuple[int, int, int]
    ):
        self.name = name
        self.bg_color = bg_color
        self.floor_color = floor_color
        self.stickman_color = stickman_color
        self.stickman_outline = stickman_outline
        self.accent_red = accent_red
        self.accent_purple = accent_purple
        self.shadow_color = shadow_color
        self.grid_line_color = grid_line_color
        self.rubble_color = rubble_color
        self.text_color = text_color


# Exact color profiles sampled from goal_videos/
LIGHT_THEME = StageTheme(
    name="light",
    bg_color=(244, 244, 242),           # Off-white / parchment cream
    floor_color=(240, 240, 238),
    stickman_color=(17, 17, 17),         # Solid charcoal ink black
    stickman_outline=(17, 17, 17),
    accent_red=(229, 57, 53),            # Vibrant vermillion red (speech bubble, gavel, X)
    accent_purple=(139, 114, 214),       # Royal purple
    shadow_color=(210, 210, 210),        # Soft floor contact shadow
    grid_line_color=(22, 22, 22),        # High-contrast 1-point perspective lines
    rubble_color=(22, 22, 22),           # Black architectural stone debris
    text_color=(17, 17, 17)              # Bold black kinetic text
)

DARK_THEME = StageTheme(
    name="dark",
    bg_color=(10, 10, 14),               # Deep cosmic black
    floor_color=(15, 15, 20),
    stickman_color=(255, 255, 255),      # Solid white stickman
    stickman_outline=(17, 17, 17),       # Dark outlines for character definition
    accent_red=(211, 47, 47),            # Vibrant prison cage red / stamp red
    accent_purple=(139, 114, 214),       # Luminous glowing lavender splines
    shadow_color=(5, 5, 8),              # Deep contact occlusion
    grid_line_color=(60, 60, 80),        # Subtle wireframe grid
    rubble_color=(35, 35, 45),           # Dark stone debris
    text_color=(255, 255, 255)           # Luminous white kinetic text
)


def get_theme(theme_name: str = "light") -> StageTheme:
    """Retrieve theme by name ('light' or 'dark')."""
    if theme_name.lower() in ("dark", "black", "night"):
        return DARK_THEME
    return LIGHT_THEME
