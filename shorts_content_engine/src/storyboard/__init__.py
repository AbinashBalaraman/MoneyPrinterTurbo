"""Slideshow storyboard package for PowerPoint-style video production.

Converts an EpisodeManifest (already-written script) into multiple
still-image prompts per scene, resolves character reference photos from
the Charectors/ folder, and builds a printable storyboard PDF.
"""

from src.storyboard.models import StillImageIdea, StoryboardScene, StoryboardDocument
from src.storyboard.generator import StoryboardGenerator
from src.storyboard.characters import CharacterPhotoResolver
from src.storyboard.pdf import StoryboardPDFBuilder

__all__ = [
    "StillImageIdea",
    "StoryboardScene",
    "StoryboardDocument",
    "StoryboardGenerator",
    "CharacterPhotoResolver",
    "StoryboardPDFBuilder",
]
