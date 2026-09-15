"""Pydantic models for the slideshow storyboard subsystem."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class StillImageIdea(BaseModel):
    """Single still-image keyframe idea for a PowerPoint-style slideshow video."""

    image_index: int = Field(description="0-indexed keyframe within the scene")
    label: str = Field(description="Human label e.g. 'S1-IMG2'")
    time_start: float = Field(description="Slideshow hold start (episode seconds)")
    time_end: float = Field(description="Slideshow hold end (episode seconds)")
    shot_type: str = Field(description="Shot framing e.g. 'Wide establishing'")
    focus: str = Field(description="What this keyframe captures narratively")
    image_prompt: str = Field(min_length=1, description="Copy-paste prompt for image model")
    negative_prompt: str = Field(default="", description="Negative prompt for image model")
    hold_seconds: float = Field(description="How long to hold this still in the video")
    transition: str = Field(default="cross-dissolve", description="Slideshow transition into next still")
    motion_hint: str = Field(default="", description="Ken Burns pan/zoom hint for slideshow assembly")


class StoryboardScene(BaseModel):
    """Storyboard view of one SceneBeat with its still-image keyframes."""

    scene_index: int
    time_start: float
    time_end: float
    duration: float
    phase: str
    narration: str = ""
    dialogue_speaker: Optional[str] = None
    dialogue_text: Optional[str] = None
    dialogue_emotion: Optional[str] = None
    action_prompt: str = ""
    video_prompt: str = ""
    camera_directive: Optional[str] = None
    bound_characters: list[str] = Field(default_factory=list)
    stills: list[StillImageIdea] = Field(default_factory=list)


class StoryboardDocument(BaseModel):
    """Full storyboard document for one episode."""

    series_id: str
    episode_num: int
    title: str
    target_duration: float
    actual_duration: float
    style: str = "cinematic_photorealistic"
    cliffhanger: str = ""
    next_episode_hook: str = ""
    character_visuals: dict[str, str] = Field(
        default_factory=dict, description="character name -> visual_summary"
    )
    character_photos: dict[str, list[str]] = Field(
        default_factory=dict, description="character name -> list of photo file paths"
    )
    scenes: list[StoryboardScene] = Field(default_factory=list)

    @property
    def total_stills(self) -> int:
        return sum(len(s.stills) for s in self.scenes)
