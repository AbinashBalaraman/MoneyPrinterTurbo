"""Character Profile Registry and persistence management for recurring episodic characters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from src.models import CharacterProfile, EntityType


class CharacterRegistry:
    """Registry maintaining persistent character profiles across episodes and series."""

    def __init__(self, initial_profiles: Optional[list[CharacterProfile]] = None) -> None:
        self._profiles_by_id: dict[str, CharacterProfile] = {}
        self._id_by_name: dict[str, str] = {}
        if initial_profiles:
            for profile in initial_profiles:
                self.register_character(profile)

    def register_character(self, profile: CharacterProfile) -> CharacterProfile:
        """Registers or updates a persistent character profile in the registry."""
        if not profile.character_id or not profile.character_id.strip():
            raise ValueError("CharacterProfile must have a non-empty character_id")
        if not profile.name or not profile.name.strip():
            raise ValueError("CharacterProfile must have a non-empty name")
        if not profile.visual_summary or not profile.visual_summary.strip():
            raise ValueError("CharacterProfile must have a non-empty visual_summary")

        self._profiles_by_id[profile.character_id] = profile
        self._id_by_name[profile.name.strip().lower()] = profile.character_id
        return profile

    def get_character(self, identifier: str) -> Optional[CharacterProfile]:
        """Retrieves a character by character_id or display name (case-insensitive)."""
        if identifier in self._profiles_by_id:
            return self._profiles_by_id[identifier]
        lookup = identifier.strip().lower()
        if lookup in self._id_by_name:
            char_id = self._id_by_name[lookup]
            return self._profiles_by_id.get(char_id)
        return None

    def list_characters(self) -> list[CharacterProfile]:
        """Returns all registered character profiles."""
        return list(self._profiles_by_id.values())

    def remove_character(self, identifier: str) -> bool:
        """Removes a character from the registry by ID or name."""
        char = self.get_character(identifier)
        if not char:
            return False
        self._profiles_by_id.pop(char.character_id, None)
        self._id_by_name.pop(char.name.strip().lower(), None)
        return True

    def add_relationship(self, char1_identifier: str, char2_identifier: str, dynamic: str) -> None:
        """Records a relationship dynamic between two registered characters."""
        c1 = self.get_character(char1_identifier)
        c2 = self.get_character(char2_identifier)
        if not c1 or not c2:
            raise KeyError(f"Both characters must exist to add relationship: '{char1_identifier}', '{char2_identifier}'")
        c1.relationships[c2.name] = dynamic

    def get_relationships(self, identifier: str) -> dict[str, str]:
        """Returns the relationship dictionary for a specified character."""
        char = self.get_character(identifier)
        if not char:
            raise KeyError(f"Character '{identifier}' not found in registry")
        return dict(char.relationships)

    def export_flowkit_entities(self) -> list[dict[str, Any]]:
        """Converts all registered profiles into FlowKit entity dictionaries."""
        return [p.to_flowkit_entity() for p in self.list_characters()]

    def save_to_file(self, file_path: str | Path) -> None:
        """Serializes the character registry to a JSON file."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in self.list_characters()]
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load_from_file(cls, file_path: str | Path) -> "CharacterRegistry":
        """Loads a character registry from a JSON file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Registry file not found: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        profiles = [CharacterProfile.model_validate(item) for item in raw]
        return cls(initial_profiles=profiles)


def build_default_characters() -> list[CharacterProfile]:
    """Builds the canonical set of persistent recurring characters and location entities."""
    return [
        CharacterProfile(
            character_id="char_rex_vance",
            name="Detective Rex Vance",
            entity_type=EntityType.CHARACTER,
            visual_summary="Rugged 40-year-old male detective, square jaw, salt-and-pepper stubble, intense grey eyes, dark charcoal fedora, tailored graphite trench coat.",
            personality="Methodical, world-weary, razor-sharp instincts, tense noir dialogue cadence.",
            voice_profile="en-US-ChristopherNeural",
            seed=104928,
            reference_image_url="http://127.0.0.1:8100/assets/characters/rex_vance_portrait.png",
            media_id="ref_rex_vance_98fc1c",
            relationships={
                "Dr. Aris Thorne": "former university colleague turned rogue temporal adversary",
                "Maya Lin": "trusted intelligence handler and digital archivist",
            },
            tags=["protagonist", "detective", "noir"],
        ),
        CharacterProfile(
            character_id="char_aris_thorne",
            name="Dr. Aris Thorne",
            entity_type=EntityType.CHARACTER,
            visual_summary="Distinguished 55-year-old physicist, silver-streaked dark hair swept back, wire-rimmed round glasses, dark velvet tailored suit, silver signet ring.",
            personality="Cultured, enigmatic, intellectually condescending, calculating.",
            voice_profile="en-US-GuyNeural",
            seed=209481,
            reference_image_url="http://127.0.0.1:8100/assets/characters/aris_thorne_portrait.png",
            media_id="ref_aris_thorne_44fa21",
            relationships={
                "Detective Rex Vance": "obsessive rival whom he views as an unwitting pawn in the loop",
            },
            tags=["antagonist", "physicist", "temporal"],
        ),
        CharacterProfile(
            character_id="char_maya_lin",
            name="Maya Lin",
            entity_type=EntityType.CHARACTER,
            visual_summary="Sharp 28-year-old female intelligence specialist, asymmetrical dark bob haircut, high-collar cyber-tactical vest, luminous AR contact lenses.",
            personality="Fast-talking, hyper-competent, pragmatic, technologically brilliant.",
            voice_profile="en-US-JennyNeural",
            seed=304958,
            reference_image_url="http://127.0.0.1:8100/assets/characters/maya_lin_portrait.png",
            media_id="ref_maya_lin_77cb33",
            relationships={
                "Detective Rex Vance": "loyal tactical ally and surveillance coordinator",
            },
            tags=["ally", "technologist", "surveillance"],
        ),
        CharacterProfile(
            character_id="loc_subterranean_vault",
            name="Subterranean Bank Vault",
            entity_type=EntityType.LOCATION,
            visual_summary="Reinforced titanium blast vault with heavy hydraulic teeth, shattered concrete floor, dangling electrical conduits, and dim amber emergency beacons.",
            personality="Oppressive, cold, subterranean, echoing with industrial resonance.",
            voice_profile="en-US-ChristopherNeural",
            seed=401923,
            reference_image_url="http://127.0.0.1:8100/assets/locations/vault_wide.png",
            media_id="ref_vault_loc_55fa11",
            tags=["location", "vault", "crime_scene"],
        ),
    ]

