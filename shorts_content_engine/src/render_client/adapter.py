"""Adapter transforming EpisodeManifest and CharacterProfile domain objects into FlowKit payloads."""

from __future__ import annotations

import re
from typing import Optional

from src.render_client.models import (
    CharacterInput,
    FlowKitCharacterCreate,
    FlowKitNarrateVideoRequest,
    FlowKitProjectCreate,
    FlowKitRequestCreate,
    FlowKitSceneCreate,
    FlowKitVideoCreate,
    Orientation,
    RequestType,
)
from src.models import CharacterProfile, EntityType, EpisodeManifest


def slugify_name(name: str) -> str:
    """Converts display name into an alphanumeric slug format matching FlowKit conventions."""
    slug = re.sub(r"[^\w\s-]", "", name.lower()).strip()
    return re.sub(r"[-\s]+", "_", slug)


class FlowKitPayloadAdapter:
    """Converts domain entities from the directing engine into FlowKit API request payloads."""

    @staticmethod
    def to_project_payload(
        manifest: EpisodeManifest,
        material: str = "realistic",
        allow_music: bool = False,
        allow_voice: bool = True,
    ) -> FlowKitProjectCreate:
        """Constructs FlowKitProjectCreate from an EpisodeManifest."""
        characters_input: list[CharacterInput] = []
        for profile in manifest.character_profiles:
            # Locations do not have voice descriptions
            voice_desc = profile.voice_profile if profile.entity_type != EntityType.LOCATION else None
            characters_input.append(
                CharacterInput(
                    name=profile.name,
                    entity_type=profile.entity_type.value,
                    description=profile.visual_summary,
                    voice_description=voice_desc,
                )
            )

        # Sanitize and validate material
        safe_material = material if re.match(r"^[a-z0-9][a-z0-9_]{1,63}$", material) else "realistic"

        project_title = f"{manifest.series_id} - Ep {manifest.episode_num}: {manifest.title}"
        description = manifest.premise or f"Episode {manifest.episode_num} of {manifest.series_id}"
        story = (
            f"Series: {manifest.series_id}, Season {manifest.season_num}, Episode {manifest.episode_num}.\n"
            f"Premise: {manifest.premise}\n"
            f"Cliffhanger: {manifest.cliffhanger}"
        )

        return FlowKitProjectCreate(
            name=project_title,
            description=description,
            story=story,
            language="en",
            material=safe_material,
            allow_music=allow_music,
            allow_voice=allow_voice,
            characters=characters_input if characters_input else None,
        )

    @staticmethod
    def to_character_payloads(profiles: list[CharacterProfile]) -> list[FlowKitCharacterCreate]:
        """Converts domain CharacterProfiles into FlowKitCharacterCreate payloads."""
        payloads: list[FlowKitCharacterCreate] = []
        for profile in profiles:
            entity_dict = profile.to_flowkit_entity()
            payloads.append(
                FlowKitCharacterCreate(
                    name=entity_dict["name"],
                    entity_type=entity_dict["entity_type"],
                    description=entity_dict.get("description"),
                    image_prompt=entity_dict.get("image_prompt"),
                    voice_description=entity_dict.get("voice_description"),
                    reference_image_url=profile.reference_image_url,
                    media_id=profile.media_id,
                )
            )
        return payloads

    @staticmethod
    def to_video_payload(
        manifest: EpisodeManifest,
        project_id: str,
        orientation: Orientation = "VERTICAL",
    ) -> FlowKitVideoCreate:
        """Constructs FlowKitVideoCreate container for an episode."""
        video_title = f"Ep {manifest.episode_num}: {manifest.title}"
        return FlowKitVideoCreate(
            project_id=project_id,
            title=video_title,
            description=manifest.premise,
            display_order=manifest.episode_num,
            orientation=orientation,
        )

    @staticmethod
    def to_scene_payloads(
        manifest: EpisodeManifest,
        video_id: str,
    ) -> list[tuple[FlowKitSceneCreate, Optional[str]]]:
        """Converts SceneBeats into pairs of (FlowKitSceneCreate, narrator_text).
        
        Returns a list of tuples: (scene_create_payload, narration_string).
        This cleanly supports FlowKit's two-step scene creation sequence:
        Step 1: POST /api/scenes with FlowKitSceneCreate
        Step 2: PATCH /api/scenes/{id} with narrator_text
        """
        pairs: list[tuple[FlowKitSceneCreate, Optional[str]]] = []
        for scene in manifest.scenes:
            scene_create = FlowKitSceneCreate(
                video_id=video_id,
                display_order=scene.scene_index,
                prompt=scene.action_prompt,
                video_prompt=scene.video_prompt,
                character_names=scene.bound_characters if scene.bound_characters else None,
                chain_type="ROOT" if scene.scene_index == 0 else "CONTINUATION",
                source="root",
            )
            narration_text = scene.narration.strip() if scene.narration else None
            pairs.append((scene_create, narration_text))
        return pairs

    @staticmethod
    def to_batch_requests(
        scene_ids: list[str],
        project_id: str,
        video_id: str,
        req_type: RequestType = "GENERATE_IMAGE",
        orientation: Orientation = "VERTICAL",
    ) -> list[FlowKitRequestCreate]:
        """Generates batch requests for a set of scene IDs."""
        return [
            FlowKitRequestCreate(
                type=req_type,
                scene_id=sid,
                project_id=project_id,
                video_id=video_id,
                orientation=orientation,
            )
            for sid in scene_ids
        ]

    @staticmethod
    def to_character_batch_requests(
        character_ids: list[str],
        project_id: str,
    ) -> list[FlowKitRequestCreate]:
        """Generates batch requests for character reference image generation."""
        return [
            FlowKitRequestCreate(
                type="GENERATE_CHARACTER_IMAGE",
                character_id=cid,
                project_id=project_id,
            )
            for cid in character_ids
        ]

    @staticmethod
    def to_narrate_payload(
        project_id: str,
        orientation: Orientation = "VERTICAL",
        speed: float = 1.0,
        instruct: Optional[str] = None,
        mix: bool = True,
        sfx_volume: float = 0.4,
    ) -> FlowKitNarrateVideoRequest:
        """Constructs FlowKitNarrateVideoRequest for audio synthesis and mixing."""
        return FlowKitNarrateVideoRequest(
            project_id=project_id,
            orientation=orientation,
            speed=speed,
            instruct=instruct,
            mix=mix,
            sfx_volume=sfx_volume,
        )
