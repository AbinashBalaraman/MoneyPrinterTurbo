"""Puppet Stage Scenery & Perspective Platform.

Modular 2.5D visual components matching the quality and details of goal_videos/:
- Dual Themes: Light Theme (parchment/ink/red) & Dark Theme (black/glow/white).
- 1-Point Perspective Stage (colonnade, receding floorboards, baroque frame).
- Procedural Props (speech bubble, giant gavel, prison cage, shattered pillars, cracks, splashes, stamps).
- Comic Panels & Thought Bubble Vignettes.
- Kinetic Typography.
"""

from .theme import StageTheme, LIGHT_THEME, DARK_THEME, get_theme
from .perspective import PerspectiveStage
from .props import (
    draw_speech_bubble,
    draw_giant_gavel,
    draw_prison_cage,
    draw_shattered_pillar_rubble,
    draw_ground_and_ceiling_cracks,
    draw_red_fluid_splash,
    draw_envelope_with_x
)
from .panels import SplitScreenPanels, draw_thought_bubble, draw_organic_spline_web
from .text_overlay import draw_kinetic_text
