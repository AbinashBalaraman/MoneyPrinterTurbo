"""Pydantic V2 schemas mirroring FlowKit API request and response specifications."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, model_validator


# --- FlowKit Domain Enumerations / Types ---

EntityType = Literal[
    "character",
    "location",
    "creature",
    "visual_asset",
    "generic_troop",
    "faction",
]

Orientation = Literal["VERTICAL", "HORIZONTAL"]

ChainType = Literal["ROOT", "CONTINUATION", "INSERT"]

SceneSource = Literal["root", "user", "system"]

RequestType = Literal[
    "GENERATE_IMAGE",
    "REGENERATE_IMAGE",
    "EDIT_IMAGE",
    "GENERATE_VIDEO",
    "REGENERATE_VIDEO",
    "GENERATE_VIDEO_REFS",
    "UPSCALE_VIDEO",
    "GENERATE_CHARACTER_IMAGE",
    "REGENERATE_CHARACTER_IMAGE",
    "EDIT_CHARACTER_IMAGE",
]

PaygateTier = Literal["PAYGATE_TIER_ONE", "PAYGATE_TIER_TWO"]

ProjectStatus = Literal["DRAFT", "IN_PROGRESS", "COMPLETED", "FAILED"]

VideoStatus = Literal["DRAFT", "GENERATING", "COMPLETED", "FAILED"]


# --- Entity / Character Schemas ---

class CharacterInput(BaseModel):
    """Reference entity stub provided at project creation time."""
    name: str = Field(..., min_length=1, description="Entity display name")
    entity_type: EntityType = Field(default="character", description="Entity type classification")
    description: Optional[str] = Field(default=None, description="Physical traits or visual details")
    voice_description: Optional[str] = Field(
        default=None,
        description="Vocal description (e.g. 'deep gravelly baritone, calm'), max ~30 words",
    )


class FlowKitCharacterCreate(BaseModel):
    """Payload for registering a standalone reference entity (POST /api/characters)."""
    name: str = Field(..., min_length=1, description="Entity display name")
    entity_type: EntityType = Field(default="character", description="Entity type classification")
    description: Optional[str] = Field(default=None, description="Physical traits or visual details")
    image_prompt: Optional[str] = Field(default=None, description="Explicit reference generation prompt")
    voice_description: Optional[str] = Field(default=None, description="Vocal delivery description")
    reference_image_url: Optional[str] = Field(default=None, description="URL or local path to reference image")
    media_id: Optional[str] = Field(default=None, description="Flow media asset ID if already uploaded")


class FlowKitCharacterUpdate(BaseModel):
    """Payload for updating an entity (PATCH /api/characters/{id})."""
    name: Optional[str] = None
    entity_type: Optional[EntityType] = None
    description: Optional[str] = None
    image_prompt: Optional[str] = None
    voice_description: Optional[str] = None
    reference_image_url: Optional[str] = None
    media_id: Optional[str] = None


# --- Project Schemas ---

class FlowKitProjectCreate(BaseModel):
    """Payload for creating a project container in FlowKit (POST /api/projects)."""
    name: str = Field(..., min_length=1, description="Project title")
    description: Optional[str] = Field(default=None, description="Short project premise")
    story: Optional[str] = Field(default=None, description="Full story/script context")
    language: str = Field(default="en", description="ISO language code")
    user_paygate_tier: PaygateTier = Field(default="PAYGATE_TIER_ONE", description="Flow tier")
    tool_name: str = Field(default="PINHOLE", description="Flow internal tool designation")
    flow_project_id: Optional[str] = Field(default=None, description="Google Flow project UUID")
    material: str = Field(
        default="realistic",
        pattern=r"^[a-z0-9][a-z0-9_]{1,63}$",
        description="Material style ID from GET /api/materials (e.g. realistic, 3d_pixar, anime)",
    )
    style: Optional[str] = Field(default=None, description="Deprecated: legacy style mapping")
    allow_music: bool = Field(default=False, description="When True, allows background music in Veo prompt")
    allow_voice: bool = Field(default=False, description="When True, retains character dialogue audio")
    characters: Optional[list[CharacterInput]] = Field(default=None, description="Initial entities to register")

    @model_validator(mode="before")
    @classmethod
    def map_style_to_material(cls, data: Any) -> Any:
        if isinstance(data, dict):
            style = data.get("style")
            if style and "material" not in data:
                compat_map = {
                    "3D": "3d_pixar",
                    "3d": "3d_pixar",
                    "photorealistic": "realistic",
                    "realistic": "realistic",
                }
                data["material"] = compat_map.get(style, style.lower().replace(" ", "_"))
        return data


# --- Video Schemas ---

class FlowKitVideoCreate(BaseModel):
    """Payload for creating a video container within a project (POST /api/videos)."""
    project_id: str = Field(..., min_length=1, description="Parent project ID")
    title: str = Field(..., min_length=1, description="Video container title")
    description: Optional[str] = Field(default=None, description="Video description")
    display_order: int = Field(default=0, ge=0, description="Display order sequence index")
    orientation: Orientation = Field(default="VERTICAL", description="Target aspect ratio: VERTICAL for Shorts")


# --- Scene Schemas ---

class FlowKitSceneCreate(BaseModel):
    """Payload for creating a scene under a video container (POST /api/scenes).
    
    NOTE: FlowKit's SceneCreate schema intentionally omits narrator_text.
    narrator_text must be updated in a subsequent PATCH /api/scenes/{id} call!
    """
    video_id: str = Field(..., min_length=1, description="Parent video container ID")
    display_order: int = Field(default=0, ge=0, description="0-indexed scene sequence order")
    prompt: str = Field(..., min_length=1, description="Decoupled visual prompt for frame 0 image generation")
    image_prompt: Optional[str] = Field(default=None, description="Explicit override for still image generation")
    video_prompt: Optional[str] = Field(default=None, description="Sub-clip timed action directives (e.g. '0-3s: ... 3-6s: ...')")
    transition_prompt: Optional[str] = Field(default=None, description="Motion prompt when chaining start/end frames")
    character_names: Optional[list[str]] = Field(default=None, description="Slugs or names of entities bound to scene")
    parent_scene_id: Optional[str] = Field(default=None, description="Previous scene ID for continuity")
    chain_type: ChainType = Field(default="ROOT", description="Scene continuity type")
    source: Optional[SceneSource] = Field(default="root", description="Scene source designation")


class FlowKitSceneUpdate(BaseModel):
    """Payload for updating scene properties (PATCH /api/scenes/{id})."""
    prompt: Optional[str] = None
    image_prompt: Optional[str] = None
    video_prompt: Optional[str] = None
    character_names: Optional[list[str]] = None
    parent_scene_id: Optional[str] = None
    chain_type: Optional[ChainType] = None
    source: Optional[SceneSource] = None
    display_order: Optional[int] = None
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    duration: Optional[float] = None
    narrator_text: Optional[str] = Field(default=None, description="Narration voiceover transcript for TTS")


# --- Request & Batch Schemas ---

class FlowKitRequestCreate(BaseModel):
    """Payload for dispatching a generation job (POST /api/requests)."""
    type: RequestType = Field(..., description="Generation request type")
    orientation: Optional[Orientation] = Field(default="VERTICAL", description="Rendering orientation")
    scene_id: Optional[str] = Field(default=None, description="Scene ID for scene image/video generation")
    character_id: Optional[str] = Field(default=None, description="Character ID for entity reference generation")
    project_id: Optional[str] = Field(default=None, description="Parent project ID")
    video_id: Optional[str] = Field(default=None, description="Parent video ID")
    source_media_id: Optional[str] = Field(default=None, description="Source media asset ID")

    @model_validator(mode="after")
    def validate_dependencies(self) -> "FlowKitRequestCreate":
        """Enforces FlowKit prerequisite validation rules."""
        req_type = self.type
        if req_type in ("GENERATE_CHARACTER_IMAGE", "REGENERATE_CHARACTER_IMAGE", "EDIT_CHARACTER_IMAGE"):
            if not self.character_id:
                raise ValueError(f"character_id is required for {req_type}")
            if not self.project_id:
                raise ValueError(f"project_id is required for {req_type}")
        elif req_type in (
            "GENERATE_IMAGE",
            "REGENERATE_IMAGE",
            "EDIT_IMAGE",
            "GENERATE_VIDEO",
            "REGENERATE_VIDEO",
            "GENERATE_VIDEO_REFS",
            "UPSCALE_VIDEO",
        ):
            if not self.scene_id:
                raise ValueError(f"scene_id is required for {req_type}")
            if not self.project_id:
                raise ValueError(f"project_id is required for {req_type}")
            if not self.video_id:
                raise ValueError(f"video_id is required for {req_type}")
        return self


class FlowKitBatchRequestCreate(BaseModel):
    """Payload for submitting a batch of generation requests (POST /api/requests/batch)."""
    requests: list[FlowKitRequestCreate] = Field(..., min_length=1, description="List of generation requests")


class BatchStatus(BaseModel):
    """Response model for batch status polling (GET /api/requests/batch-status)."""
    total: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    processing: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    done: bool = Field(default=False)
    all_succeeded: bool = Field(default=False)
    orientation: Optional[str] = None


# --- TTS & Audio Narration Schemas ---

class FlowKitNarrateVideoRequest(BaseModel):
    """Payload for generating narration and mixing audio (POST /api/videos/{id}/narrate)."""
    project_id: str = Field(..., min_length=1, description="Parent project ID")
    orientation: Orientation = Field(default="VERTICAL", description="Target video orientation")
    speed: float = Field(default=1.0, ge=0.5, le=3.0, description="Speech rate multiplier")
    instruct: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Natural language vocal description e.g. 'male, energetic narrator, deep tone'",
    )
    ref_audio: Optional[str] = Field(default=None, max_length=500, description="Path to voice reference WAV")
    ref_text: Optional[str] = Field(default=None, description="Transcript of voice reference audio")
    template: Optional[str] = Field(
        default=None,
        pattern=r"^[a-zA-Z0-9_-]{1,64}$",
        description="Saved voice template identifier",
    )
    mix: bool = Field(default=True, description="When True, automatically mixes narration into video files")
    sfx_volume: float = Field(default=0.4, ge=0.0, le=2.0, description="Background SFX ducking volume level")
    from_scene: Optional[int] = Field(default=None, ge=0, description="Starting scene index")
    to_scene: Optional[int] = Field(default=None, ge=0, description="Ending scene index")


class SceneNarrationResult(BaseModel):
    """Per-scene narration synthesis outcome."""
    scene_id: str
    display_order: int
    narrator_text: Optional[str] = None
    audio_path: Optional[str] = None
    duration: Optional[float] = None
    status: str = "COMPLETED"
    error: Optional[str] = None


class NarrateVideoResponse(BaseModel):
    """Response returned by POST /api/videos/{id}/narrate."""
    video_id: str
    project_id: str
    scenes: list[SceneNarrationResult] = Field(default_factory=list)
    scenes_narrated: int = 0
    scenes_skipped: int = 0
    scenes_failed: int = 0
    total_narration_duration: Optional[float] = None


# --- Aliases for 100% interoperability with FlowKit naming ---
ProjectCreate = FlowKitProjectCreate
CharacterCreate = FlowKitCharacterCreate
CharacterUpdate = FlowKitCharacterUpdate
VideoCreate = FlowKitVideoCreate
SceneCreate = FlowKitSceneCreate
SceneUpdate = FlowKitSceneUpdate
RequestCreate = FlowKitRequestCreate
BatchRequestCreate = FlowKitBatchRequestCreate
NarrateVideoRequest = FlowKitNarrateVideoRequest
