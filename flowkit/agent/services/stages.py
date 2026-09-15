"""Canonical pipeline stage vocabulary.

Why this is a module and not a string literal at each call site
---------------------------------------------------------------
The worker tags log records with a stage; the dashboard groups those records
into the six-stage rail. If the two sides invent their own spellings, the rail
silently shows empty panels — a stage that looks wired but never displays
anything. Keeping one list means a typo is a ``KeyError`` at import time
instead of a blank screen at runtime.

The vocabulary is deliberately finer-grained than the rail. A log line knows it
came from ``refs`` or ``video``; the rail only needs to know those belong under
*Images* and *Assemble*. Tagging precisely and grouping in the view keeps the
information instead of discarding it at the source.
"""

from __future__ import annotations

from typing import Optional

# ── The vocabulary ───────────────────────────────────────────────────────

STAGE_SCRIPT = "script"
STAGE_REFS = "refs"
STAGE_IMAGES = "images"
STAGE_VIDEO = "video"
STAGE_UPSCALE = "upscale"
STAGE_WATERMARK = "watermark"
STAGE_ASSEMBLE = "assemble"
STAGE_VOICEOVER = "voiceover"
STAGE_MUSIC = "music"
STAGE_PUBLISH = "publish"

ALL_STAGES: tuple[str, ...] = (
    STAGE_SCRIPT,
    STAGE_REFS,
    STAGE_IMAGES,
    STAGE_VIDEO,
    STAGE_UPSCALE,
    STAGE_WATERMARK,
    STAGE_ASSEMBLE,
    STAGE_VOICEOVER,
    STAGE_MUSIC,
    STAGE_PUBLISH,
)

# Which request types belong to which stage. Anything absent from this map is
# untagged rather than mis-tagged.
REQUEST_TYPE_STAGE: dict[str, str] = {
    # Character reference sheets
    "GENERATE_CHARACTER_IMAGE": STAGE_REFS,
    "REGENERATE_CHARACTER_IMAGE": STAGE_REFS,
    "EDIT_CHARACTER_IMAGE": STAGE_REFS,
    # Scene stills
    "GENERATE_IMAGE": STAGE_IMAGES,
    "REGENERATE_IMAGE": STAGE_IMAGES,
    "EDIT_IMAGE": STAGE_IMAGES,
    # Scene motion
    "GENERATE_VIDEO": STAGE_VIDEO,
    "REGENERATE_VIDEO": STAGE_VIDEO,
    "GENERATE_VIDEO_REFS": STAGE_VIDEO,
    # Resolution lift
    "UPSCALE_VIDEO": STAGE_UPSCALE,
}


def stage_for_request_type(req_type: Optional[str]) -> Optional[str]:
    """The stage a given request type belongs to, or ``None`` if untagged."""
    if not req_type:
        return None
    return REQUEST_TYPE_STAGE.get(req_type)


def is_known_stage(name: Optional[str]) -> bool:
    """Whether ``name`` is part of the shared vocabulary."""
    return bool(name) and name in ALL_STAGES
