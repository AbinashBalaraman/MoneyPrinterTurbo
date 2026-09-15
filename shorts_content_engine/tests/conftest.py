"""Pytest shared fixtures for shorts_content_engine unit and integration tests."""

import pytest

from src.director.character import CharacterRegistry
from src.director.compiler import PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter
from src.models import CharacterProfile, EntityType, SeriesState


@pytest.fixture
def rex_profile() -> CharacterProfile:
    """Fixture providing Detective Rex Vance character profile."""
    return CharacterProfile(
        character_id="char_rex_vance",
        name="Detective Rex Vance",
        entity_type=EntityType.CHARACTER,
        visual_summary="Rugged 40-year-old male detective, square jaw, salt-and-pepper stubble, grey eyes, charcoal fedora, graphite trench coat.",
        personality="Methodical, world-weary, razor-sharp instincts.",
        voice_profile="en-US-ChristopherNeural",
        seed=104928,
        reference_image_url="http://127.0.0.1:8100/assets/characters/rex_vance.png",
        media_id="media_rex_12345",
        relationships={"Dr. Aris Thorne": "adversary", "Maya Lin": "tactical ally"},
        tags=["protagonist", "detective"],
    )


@pytest.fixture
def thorne_profile() -> CharacterProfile:
    """Fixture providing Dr. Aris Thorne character profile."""
    return CharacterProfile(
        character_id="char_aris_thorne",
        name="Dr. Aris Thorne",
        entity_type=EntityType.CHARACTER,
        visual_summary="Distinguished 55-year-old physicist, silver hair, round wire-rimmed glasses, dark velvet suit.",
        personality="Cultured, enigmatic, condescending, calculating.",
        voice_profile="en-US-GuyNeural",
        seed=209481,
        reference_image_url="http://127.0.0.1:8100/assets/characters/thorne.png",
        media_id="media_thorne_67890",
        relationships={"Detective Rex Vance": "obsessive rival"},
        tags=["antagonist", "scientist"],
    )


@pytest.fixture
def maya_profile() -> CharacterProfile:
    """Fixture providing Maya Lin character profile."""
    return CharacterProfile(
        character_id="char_maya_lin",
        name="Maya Lin",
        entity_type=EntityType.CHARACTER,
        visual_summary="Sharp 28-year-old female analyst, dark bob cut, cyber-tactical vest, AR lenses.",
        personality="Hyper-competent, fast-talking, pragmatic.",
        voice_profile="en-US-JennyNeural",
        seed=304958,
        reference_image_url="http://127.0.0.1:8100/assets/characters/maya.png",
        media_id="media_maya_11223",
        relationships={"Detective Rex Vance": "handler and surveillance coordinator"},
        tags=["ally", "analyst"],
    )


@pytest.fixture
def character_registry(rex_profile, thorne_profile, maya_profile) -> CharacterRegistry:
    """Fixture providing a populated character registry."""
    reg = CharacterRegistry()
    reg.register_character(rex_profile)
    reg.register_character(thorne_profile)
    reg.register_character(maya_profile)
    return reg


@pytest.fixture
def series_state(rex_profile, thorne_profile, maya_profile) -> SeriesState:
    """Fixture providing a clean series state."""
    return SeriesState(
        series_id="series_chrono_cipher",
        title="The Chrono Cipher",
        genre="Cyberpunk Noir Mystery",
        premise="A detective uncovers temporal fractures threatening reality.",
        current_season=1,
        current_episode=0,
        characters={
            rex_profile.character_id: rex_profile,
            thorne_profile.character_id: thorne_profile,
            maya_profile.character_id: maya_profile,
        },
    )


@pytest.fixture
def story_director(character_registry) -> StoryDirector:
    """Fixture providing a StoryDirector wired with character registry."""
    return StoryDirector(character_registry=character_registry)
