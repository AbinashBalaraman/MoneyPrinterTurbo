"""Core domain models and interface schemas for the episodic directing engine."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, model_validator


class EngagementPhase(str, Enum):
    """5-Phase Short-Form Engagement Arc phases."""
    HOOK = "hook"                         # 0.0s – 3.0s: Pattern interrupt, shock discovery, ticking clock
    RISING_TENSION = "rising_tension"     # 3.0s – 15.0s: Dilemma established, stakes introduced
    COMPLICATION = "complication"         # 15.0s – 35.0s: Attempted resolution backfires, stakes escalate
    CLIMAX_TWIST = "climax_twist"         # 35.0s – 50.0s: Peak emotional/physical intensity, sudden revelation
    CLIFFHANGER_LOOP = "cliffhanger_loop" # 50.0s – 60.0s: Unresolved dilemma, next episode hook, loop closure


class EntityType(str, Enum):
    """Entity classification matching FlowKit reference entity model."""
    CHARACTER = "character"
    LOCATION = "location"
    CREATURE = "creature"
    VISUAL_ASSET = "visual_asset"
    GENERIC_TROOP = "generic_troop"
    FACTION = "faction"


class CharacterProfile(BaseModel):
    """Persistent character profile isolating visual attributes, voice, and traits."""
    character_id: str = Field(min_length=1, description="Unique identifier for character, e.g. char_rex_vance")
    name: str = Field(min_length=1, description="Display name, e.g. Detective Rex Vance")
    entity_type: EntityType = Field(default=EntityType.CHARACTER, description="Entity type classification")
    visual_summary: str = Field(min_length=1, description="Permanent physical attributes, facial features, attire, and signature props")
    personality: str = Field(default="", description="Behavioral quirks, emotional baseline, and dialogue cadence")
    voice_profile: str = Field(default="en-US-ChristopherNeural", description="TTS voice identifier or description")
    seed: Optional[int] = Field(default=None, description="Deterministic seed for face/image consistency")
    reference_image_url: Optional[str] = Field(default=None, description="URL or local path to canonical portrait")
    media_id: Optional[str] = Field(default=None, description="FlowKit/Veo media asset ID for image conditioning")
    relationships: dict[str, str] = Field(default_factory=dict, description="Mapping of other character names to relationship dynamic")
    tags: list[str] = Field(default_factory=list, description="Descriptive search/categorization tags")

    @model_validator(mode="before")
    @classmethod
    def check_non_empty_strings(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ("character_id", "name", "visual_summary"):
                val = data.get(field)
                if val is not None and isinstance(val, str) and not val.strip():
                    raise ValueError(f"{field} cannot be empty or whitespace")
        return data

    def to_flowkit_entity(self) -> dict[str, Any]:
        """Converts profile into FlowKit CharacterCreate payload."""
        if self.entity_type == EntityType.LOCATION:
            return {
                "name": self.name,
                "entity_type": "location",
                "description": self.visual_summary,
                "voice_description": None,
                "image_prompt": (
                    f"Wide establishing shot of {self.name}, {self.visual_summary}. "
                    "Balanced level composition, straight horizon, rich architectural detail, "
                    "deep atmospheric perspective, landscape 16:9 framing."
                ),
            }

        return {
            "name": self.name,
            "entity_type": self.entity_type.value,
            "description": f"{self.personality} - {self.visual_summary}".strip(" -"),
            "voice_description": self.voice_profile,
            "image_prompt": (
                f"Canonical full-body portrait of {self.name}, {self.visual_summary}. "
                "Standing upright, centered, facing camera, neutral studio background, "
                "sharp focus, cinematic lighting, photorealistic, 8k vertical framing."
            ),
        }


def _count_words(text: str) -> int:
    """Helper to count words in narration or dialogue string."""
    if not text:
        return 0
    # Normalize dashes: replace double-dash, em-dash, en-dash with space
    normalized = re.sub(r"--+|—|–", " ", text)
    clean = re.sub(r"[^\w\s\'-]", " ", normalized)
    tokens = [w for w in clean.split() if w.strip()]
    return len(tokens)


class DialogueLine(BaseModel):
    """Direct in-scene spoken character dialogue line with vocal delivery directive."""
    speaker: str = Field(min_length=1, description="Bound character name speaking the dialogue")
    text: str = Field(min_length=1, description="Direct spoken dialogue text")
    emotion: str = Field(default="neutral", description="Vocal delivery or emotional directive e.g. tense whisper, defiant snarl")
    word_count: int = Field(default=0, description="Word count of spoken dialogue")
    wpm: float = Field(default=0.0, description="Words Per Minute pace of this dialogue line")

    @model_validator(mode="after")
    def compute_dialogue_metrics(self) -> "DialogueLine":
        """Compute word count if not explicitly provided."""
        if self.word_count == 0 and self.text:
            self.word_count = _count_words(self.text)
        return self


class SceneBeat(BaseModel):
    """Scene specification conforming to the FlowKit adapter and director interface."""
    scene_index: int = Field(description="0-indexed scene sequence order")
    time_start: float = Field(description="Timestamp in seconds when this scene begins")
    time_end: float = Field(description="Timestamp in seconds when this scene ends")
    narration: str = Field(default="", description="Verbal voiceover text spoken during this scene")
    dialogue: Optional[DialogueLine] = Field(default=None, description="Direct in-scene spoken character dialogue")
    action_prompt: str = Field(description="Decoupled visual prompt focusing on situational action and atmosphere")
    video_prompt: str = Field(description="Sub-clip timed action directives with bound character tokens")
    bound_characters: list[str] = Field(default_factory=list, description="Names of character entities in frame")
    phase: EngagementPhase = Field(default=EngagementPhase.HOOK, description="Narrative arc phase")
    camera_directive: Optional[str] = Field(default=None, description="Camera movement and cinematography specification")
    word_count: int = Field(default=0, description="Total word count of verbal audio (narration + dialogue)")
    wpm: float = Field(default=0.0, description="Words Per Minute pace of this scene")

    @property
    def duration(self) -> float:
        """Returns the scene duration in seconds."""
        return max(0.0, self.time_end - self.time_start)

    @model_validator(mode="after")
    def compute_metrics(self) -> "SceneBeat":
        """Compute word count and WPM combining narration and dialogue."""
        narr_words = _count_words(self.narration) if self.narration else 0
        diag_words = self.dialogue.word_count if self.dialogue else 0
        total_words = narr_words + diag_words
        if self.word_count == 0:
            self.word_count = total_words
        dur = self.duration
        if dur > 0 and self.wpm == 0.0:
            self.wpm = round((self.word_count / dur) * 60.0, 1)
        return self


class EpisodeManifest(BaseModel):
    """Complete episodic directing package for a 30-60s Short."""
    series_id: str = Field(description="Unique identifier for the parent series")
    episode_num: int = Field(description="1-based episode index in the series/season")
    title: str = Field(description="Episode title")
    target_duration: float = Field(description="Target video duration in seconds (30.0 to 60.0s)")
    scenes: list[SceneBeat] = Field(default_factory=list, description="Ordered scene beats")
    character_profiles: list[CharacterProfile] = Field(default_factory=list, description="Registered characters featured in episode")
    cliffhanger: str = Field(default="", description="The episode's ending unresolved tension/peril")
    next_episode_hook: str = Field(default="", description="Teaser hook for the next episode")
    season_num: int = Field(default=1, description="Season number")
    premise: str = Field(default="", description="High-level narrative logline or dilemma")
    actual_duration: float = Field(default=0.0, description="Sum of scene beat durations")
    total_word_count: int = Field(default=0, description="Total words spoken across all scenes")
    overall_wpm: float = Field(default=0.0, description="Overall Words Per Minute rate")
    micro_loop: Optional[str] = Field(default=None, description="Closing phrase engineered to loop into this episode's opening hook")
    loop_phrase: Optional[str] = Field(default=None, description="Closing phrase engineered to loop into Episode 1's hook")

    @model_validator(mode="after")
    def compute_totals(self) -> "EpisodeManifest":
        """Compute aggregated duration and WPM metrics from scenes."""
        if self.scenes:
            self.actual_duration = round(sum(s.duration for s in self.scenes), 2)
            self.total_word_count = sum(s.word_count for s in self.scenes)
            if self.actual_duration > 0:
                self.overall_wpm = round((self.total_word_count / self.actual_duration) * 60.0, 1)
        return self

    def validate_integrity(self) -> tuple[bool, list[str]]:
        """Validate timing constraints, WPM limits, and narrative integrity."""
        errors: list[str] = []
        if not (30.0 <= self.target_duration <= 60.0):
            errors.append(f"Target duration {self.target_duration}s outside valid range [30.0, 60.0]s")
        if abs(self.actual_duration - self.target_duration) > 1.5:
            errors.append(f"Actual duration {self.actual_duration}s deviates from target {self.target_duration}s by >1.5s")
        if not (135.0 <= self.overall_wpm <= 165.0):
            errors.append(f"Overall WPM {self.overall_wpm} outside acceptable bounds [135.0, 165.0]")
        
        # Verify scene ordering and phase progression
        phases_present = {s.phase for s in self.scenes}
        for req_phase in EngagementPhase:
            if req_phase not in phases_present:
                errors.append(f"Missing required 5-phase arc stage: {req_phase.value}")
        
        return len(errors) == 0, errors


class SeriesState(BaseModel):
    """Persistent series narrative state tracking characters, arcs, and cliffhangers."""
    series_id: str = Field(description="Series unique ID")
    title: str = Field(description="Series display title")
    genre: str = Field(description="Series genre e.g. Cyberpunk Noir, Sci-Fi Mystery")
    premise: str = Field(default="", description="Core premise and universe rules")
    current_season: int = Field(default=1, description="Current season index")
    current_episode: int = Field(default=0, description="Last generated episode index")
    characters: dict[str, Any] = Field(default_factory=dict, description="Character profiles indexed by name or ID")
    last_cliffhanger: Optional[str] = Field(default=None, description="Cliffhanger pending resolution from last episode")
    unresolved_threads: list[str] = Field(default_factory=list, description="Active unresolved narrative questions")
    episode_history: list[dict[str, Any]] = Field(default_factory=list, description="Historical summary of generated episodes")

    def advance_episode(self, manifest: EpisodeManifest) -> None:
        """Updates series state after an episode is successfully directed."""
        self.current_episode = manifest.episode_num
        self.last_cliffhanger = manifest.cliffhanger
        if manifest.next_episode_hook and manifest.next_episode_hook not in self.unresolved_threads:
            self.unresolved_threads.append(manifest.next_episode_hook)
        self.episode_history.append({
            "episode_num": manifest.episode_num,
            "title": manifest.title,
            "duration": manifest.actual_duration,
            "word_count": manifest.total_word_count,
            "wpm": manifest.overall_wpm,
            "cliffhanger": manifest.cliffhanger,
        })
