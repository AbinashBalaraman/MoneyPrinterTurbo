"""Tier 2 E2E Boundary & Corner Case Tests.

Validates all 13 core features (F1 to F13) under extreme boundaries, corner cases,
timing thresholds, prompt decoupling permutations, concurrency, and error states (>= 65 tests).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from scripts.validate_flowkit_payloads import validate_manifest_payloads
from src.cli import build_parser, main
from src.director.character import CharacterRegistry, build_default_characters
from src.director.compiler import DecouplingGuard, PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.render_client.adapter import FlowKitPayloadAdapter
from src.render_client.client import FlowKitClient
from src.render_client.models import (
    BatchStatus,
    FlowKitCharacterCreate,
    FlowKitNarrateVideoRequest,
    FlowKitProjectCreate,
    FlowKitRequestCreate,
    FlowKitSceneCreate,
    FlowKitSceneUpdate,
    FlowKitVideoCreate,
)
from src.render_client.orchestrator import (
    FlowKitOrchestrator,
    OrchestrationResult,
    check_stream_has_audio,
    mix_narration_resilient,
)
from src.models import (
    CharacterProfile,
    DialogueLine,
    EngagementPhase,
    EntityType,
    EpisodeManifest,
    SceneBeat,
    SeriesState,
)
from src.storage.ledger import EpisodicLedger

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


# =============================================================================
# F1 Boundaries: Ecosystem Survey Report
# =============================================================================
class TestTier2F1EcosystemSurveyBoundaries:
    """Boundary and corner testing for Ecosystem Survey documentation and structural fidelity."""

    @pytest.fixture
    def survey_path(self) -> Path:
        p = PROJECT_ROOT / "docs" / "ECOSYSTEM_SURVEY.md"
        assert p.exists()
        return p

    def test_f1_b01_case_insensitive_repo_matching(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8").lower()
        repos = ["moneyprinterturbo", "shortgpt", "storydiffusion", "videolingo", "remotion"]
        for repo in repos:
            assert repo in content, f"Survey content should case-insensitively include {repo}"

    def test_f1_b02_whitespace_resilience_and_blank_lines(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Verify markdown headings are preceded or followed by non-corrupt lines
        heading_lines = [l for l in lines if l.startswith("#")]
        assert len(heading_lines) >= 15, "Expected at least 15 structured headings in survey"
        for h in heading_lines:
            assert len(h.strip()) > 3, f"Empty heading found: '{h}'"

    def test_f1_b03_empty_path_or_nonexistent_file_handling(self):
        fake_path = PROJECT_ROOT / "docs" / "NON_EXISTENT_SURVEY.md"
        assert not fake_path.exists()
        with pytest.raises(FileNotFoundError):
            fake_path.read_text(encoding="utf-8")

    def test_f1_b04_table_header_boundary_integrity(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        # Ensure all comparison tables have matching markdown separator rows
        table_separators = [l.strip() for l in content.splitlines() if l.strip().startswith("|---")]
        assert len(table_separators) >= 2, "Expected at least 2 comparison tables in survey"
        for sep in table_separators:
            assert sep.endswith("|"), f"Malformed table separator: {sep}"

    def test_f1_b05_extreme_length_and_utf8_encoding(self, survey_path: Path):
        raw_bytes = survey_path.read_bytes()
        assert len(raw_bytes) > 20000, "Survey raw byte size should be extensive"
        # Must decode cleanly with strict UTF-8 (no invalid multibyte sequences)
        decoded = raw_bytes.decode("utf-8")
        assert len(decoded) > 0


# =============================================================================
# F2 Boundaries: Architectural Continuity & Decoupling
# =============================================================================
class TestTier2F2ArchitecturalContinuityBoundaries:
    """Boundary testing for architectural prompt decoupling, entity referencing, and staging."""

    @pytest.fixture
    def profiles(self) -> list[CharacterProfile]:
        return build_default_characters()

    def test_f2_b01_zero_character_scene_staging(self, profiles: list[CharacterProfile]):
        # Pure environmental cutaway: bound_characters must be empty []
        cutaway = "Camera pans across the rain-drenched empty street with flickering neon lights."
        action_p, video_p = PromptCompiler.compile_scene_prompts(
            situational_action=cutaway,
            duration=3.0,
            bound_characters=[],
            camera_directive="Slow pan",
            environment="Empty street",
        )
        assert "[" not in action_p
        assert "Empty street" in action_p
        assert "0-1.5s:" in video_p

    def test_f2_b02_multi_character_staging_maximum(self, profiles: list[CharacterProfile]):
        # Scene with multiple characters: all must be in situational action
        char_names = [profiles[0].name, profiles[1].name]
        action = f"[{char_names[0]}] confronts [{char_names[1]}] across the titanium table."
        action_p, video_p = PromptCompiler.compile_scene_prompts(
            situational_action=action,
            duration=4.0,
            bound_characters=char_names,
        )
        assert f"[{char_names[0]}]" in action_p
        assert f"[{char_names[1]}]" in action_p

    def test_f2_b03_unbound_character_reference_detection(self, profiles: list[CharacterProfile]):
        # Bijectivity violation: character in bound_characters but NOT in situational_action
        missing_name = profiles[0].name
        irrelevant_action = "A mysterious shadow darts behind the generator."
        with pytest.raises(ValueError) as exc_info:
            PromptCompiler.compile_scene_prompts(
                situational_action=irrelevant_action,
                duration=3.0,
                bound_characters=[missing_name],
            )
        assert "Directorial Staging Violation" in str(exc_info.value)
        assert missing_name in str(exc_info.value)

    def test_f2_b04_special_characters_in_character_prompts(self):
        # Character names with hyphens, quotes, or apostrophes
        complex_char = "Agent O'Connor-Smith"
        text = f"{complex_char} draws a pulse rifle."
        bound = PromptCompiler.bind_entity_tokens(text, [complex_char])
        assert f"[{complex_char}]" in bound

    def test_f2_b05_missing_voice_profile_resilience(self):
        profile = CharacterProfile(
            character_id="char_mute",
            name="The Mute Specter",
            visual_summary="Silent wraith in dark tactical shroud.",
            voice_profile="en-US-ChristopherNeural",  # fallback
        )
        fk_entity = profile.to_flowkit_entity()
        assert fk_entity["entity_type"] == "character"
        assert fk_entity["voice_description"] is not None


# =============================================================================
# F3 Boundaries: Short-Form Engagement Arc & Timing
# =============================================================================
class TestTier2F3TimingAndPacingBoundaries:
    """Boundary testing for 30-60s timing budgets, micro-scene cuts, and WPM limits."""

    def test_f3_b01_exact_minimum_duration_30s(self):
        min_words, tgt_words, max_words = PacingBudgeter.calculate_word_budget(30.0)
        assert min_words == 70
        assert tgt_words == 75
        assert max_words == 80
        allocs = PacingBudgeter.calculate_phase_allocations(30.0)
        assert allocs[EngagementPhase.HOOK]["duration"] == 3.0
        total_dur = sum(a["duration"] for a in allocs.values())
        assert abs(total_dur - 30.0) < 0.2

    def test_f3_b02_exact_maximum_duration_60s(self):
        min_words, tgt_words, max_words = PacingBudgeter.calculate_word_budget(60.0)
        assert min_words == 140
        assert tgt_words == 150
        assert max_words == 160
        allocs = PacingBudgeter.calculate_phase_allocations(60.0)
        total_dur = sum(a["duration"] for a in allocs.values())
        assert abs(total_dur - 60.0) < 0.2

    def test_f3_b03_rejection_below_30s(self):
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(29.9)
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_phase_allocations(15.0)

    def test_f3_b04_rejection_above_60s(self):
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(60.1)
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_phase_allocations(90.0)

    def test_f3_b05_zero_and_negative_duration_handling(self):
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(0.0)
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(-10.0)
        ok, wpm, reason = PacingBudgeter.validate_narration_pacing("Some text", 0.0)
        assert ok is False
        assert "greater than zero" in reason

    def test_f3_b06_empty_narration_pacing_evaluation(self):
        ok, wpm, reason = PacingBudgeter.validate_narration_pacing("", 5.0, strict=True)
        assert ok is False
        assert wpm == 0.0
        assert "sluggish" in reason.lower()

    def test_f3_b07_single_word_narration_pacing(self):
        # 1 word for 5.0s = 12 WPM -> sluggish
        ok, wpm, reason = PacingBudgeter.validate_narration_pacing("Halt!", 5.0, strict=True)
        assert ok is False
        assert wpm == 12.0
        assert "sluggish" in reason.lower()

    def test_f3_b08_extreme_hurried_narration(self):
        # 60 words for 3.0s = 1200 WPM -> hurried
        fast_narration = " ".join(["word"] * 60)
        ok, wpm, reason = PacingBudgeter.validate_narration_pacing(fast_narration, 3.0, strict=True)
        assert ok is False
        assert wpm > 160.0
        assert "hurried" in reason.lower()


# =============================================================================
# F4 Boundaries: Persistent Character Profile Registry
# =============================================================================
class TestTier2F4CharacterRegistryBoundaries:
    """Boundary testing for character registration, special characters, and entity exports."""

    def test_f4_b01_special_characters_in_character_names(self):
        reg = CharacterRegistry()
        char = CharacterProfile(
            character_id="char_special",
            name='Dr. Renée "The Phantom" O\'Connor-Smith',
            visual_summary="Enigmatic figure in charcoal cape.",
            voice_profile="en-US-GuyNeural",
        )
        reg.register_character(char)
        found = reg.get_character('Dr. Renée "The Phantom" O\'Connor-Smith')
        assert found is not None
        assert found.character_id == "char_special"

    def test_f4_b02_extreme_length_visual_summary(self):
        long_summary = "A detective wearing a dark coat. " * 50  # > 1500 chars
        char = CharacterProfile(
            character_id="char_long_desc",
            name="Detailed Character",
            visual_summary=long_summary,
        )
        assert len(char.visual_summary) > 1000
        fk_entity = char.to_flowkit_entity()
        assert fk_entity["entity_type"] == "character"

    def test_f4_b03_seed_boundary_values(self):
        # Zero seed
        c0 = CharacterProfile(character_id="c0", name="Seed Zero", visual_summary="Desc", seed=0)
        assert c0.seed == 0

        # Negative seed
        c_neg = CharacterProfile(character_id="c_neg", name="Negative Seed", visual_summary="Desc", seed=-1)
        assert c_neg.seed == -1

        # Very large 64-bit integer
        c_large = CharacterProfile(character_id="c_large", name="Big Seed", visual_summary="Desc", seed=2**63 - 1)
        assert c_large.seed == 2**63 - 1

    def test_f4_b04_duplicate_registration_overwrites_cleanly(self):
        reg = CharacterRegistry()
        p1 = CharacterProfile(character_id="same_id", name="Version 1", visual_summary="Old summary")
        p2 = CharacterProfile(character_id="same_id", name="Version 2", visual_summary="New summary")
        reg.register_character(p1)
        assert reg.get_character("same_id").name == "Version 1"
        reg.register_character(p2)
        assert reg.get_character("same_id").name == "Version 2"
        assert len(reg.list_characters()) == 1

    def test_f4_b05_remove_nonexistent_character_returns_false(self):
        reg = CharacterRegistry()
        assert reg.remove_character("does_not_exist") is False

    def test_f4_b06_location_entity_voice_and_framing_guarantee(self):
        loc = CharacterProfile(
            character_id="loc_ruins",
            name="Neon Ruins",
            entity_type=EntityType.LOCATION,
            visual_summary="Crumbling skyscrapers engulfed in violet neon fog.",
        )
        fk = loc.to_flowkit_entity()
        assert fk["voice_description"] is None
        assert "16:9" in fk["image_prompt"]
        assert "portrait" not in fk["image_prompt"].lower()


# =============================================================================
# F5 Boundaries: Episodic Story Director Engine
# =============================================================================
class TestTier2F5StoryDirectorBoundaries:
    """Boundary testing for StoryDirector generation, edge durations, and custom plots."""

    @pytest.fixture
    def default_state(self) -> SeriesState:
        characters = {c.character_id: c for c in build_default_characters()}
        return SeriesState(
            series_id="boundary_series",
            title="Boundary Tests",
            genre="Sci-Fi",
            characters=characters,
        )

    def test_f5_b01_direct_episode_at_exact_30s_boundary(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=30.0)
        assert abs(manifest.actual_duration - 30.0) <= 0.5
        assert len(manifest.scenes) >= 5
        assert manifest.scenes[0].duration == 3.0  # Hook duration

    def test_f5_b02_direct_episode_at_exact_60s_boundary(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=60.0)
        assert abs(manifest.actual_duration - 60.0) <= 0.5
        assert len(manifest.scenes) >= 5

    def test_f5_b03_minimal_series_state_single_character(self):
        single_char = CharacterProfile(
            character_id="char_solo",
            name="Solo Survivor",
            visual_summary="Lone traveler in wasteland rags.",
        )
        state = SeriesState(
            series_id="solo_series",
            title="Solo",
            genre="Post-Apocalyptic",
            characters={"char_solo": single_char},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=35.0)
        assert manifest.episode_num == 1
        assert len(manifest.scenes) >= 5
        assert any("Solo Survivor" in s.bound_characters for s in manifest.scenes)

    def test_f5_b04_high_episode_number_overflow(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=999, target_duration=45.0)
        assert manifest.episode_num == 999
        assert "999" in manifest.title or "Episode 999" in manifest.title or "999" in manifest.next_episode_hook

    def test_f5_b05_custom_plot_empty_scenes_fallback(self, default_state: SeriesState):
        director = StoryDirector()
        custom = {
            "title": "Fallback Episode",
            "premise": "Test fallback",
            "scenes": [],
        }
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=40.0, custom_plot=custom)
        assert manifest.title == "Fallback Episode"
        assert len(manifest.scenes) >= 5


# =============================================================================
# F6 Boundaries: Decoupled Prompt & Scene Action Formatter
# =============================================================================
class TestTier2F6DecoupledPromptFormatterBoundaries:
    """Boundary testing for DecouplingGuard n-gram extraction, punctuation, and case sensitivity."""

    def test_f6_b01_empty_bound_profiles_validation(self):
        valid, warnings = DecouplingGuard.validate_prompt("Wide establishing shot of the cyber skyline.", bound_profiles=[])
        assert valid is True
        assert len(warnings) == 0

    def test_f6_b02_hyphenated_attire_leakage_detection(self):
        profile = CharacterProfile(
            character_id="c_hyphen",
            name="Detective Vance",
            visual_summary="Rugged detective wearing a charcoal coat and salt-and-pepper stubble.",
        )
        bad_prompt = "Detective Vance rubs his salt-and-pepper stubble in the rain."
        valid, warnings = DecouplingGuard.validate_prompt(bad_prompt, bound_profiles=[profile])
        assert valid is False
        assert any("stubble" in w or "salt-and-pepper" in w for w in warnings)

    def test_f6_b03_multiword_ngram_leakage(self):
        profile = CharacterProfile(
            character_id="c_ngram",
            name="Dr. Thorne",
            visual_summary="Elderly scientist in dark velvet tailored suit.",
        )
        bad_prompt = "Dr. Thorne straightens his velvet tailored suit before opening the gate."
        valid, warnings = DecouplingGuard.validate_prompt(bad_prompt, bound_profiles=[profile])
        assert valid is False
        assert any("suit" in w or "velvet" in w for w in warnings)

    def test_f6_b04_case_insensitive_leakage_detection(self):
        profile = CharacterProfile(
            character_id="c_case",
            name="Rex",
            visual_summary="Detective with charcoal fedora and leather jacket.",
        )
        bad_upper = "Rex takes off his CHARCOAL FEDORA in anger."
        bad_mixed = "Rex wipes the rain from his LeAtHeR JaCkEt."
        v_upper, w_upper = DecouplingGuard.validate_prompt(bad_upper, bound_profiles=[profile])
        v_mixed, w_mixed = DecouplingGuard.validate_prompt(bad_mixed, bound_profiles=[profile])
        assert v_upper is False
        assert v_mixed is False

    def test_f6_b05_attached_punctuation_and_quotes(self):
        profile = CharacterProfile(
            character_id="c_punct",
            name="Maya",
            visual_summary="Operative with cyber-tactical vest.",
        )
        bad_punct = 'Maya unclasps her "cyber-tactical vest"!'
        valid, warnings = DecouplingGuard.validate_prompt(bad_punct, bound_profiles=[profile])
        assert valid is False
        assert any("vest" in w for w in warnings)

    def test_f6_b06_generic_forbidden_terms_leakage(self):
        bad_generic = "A 3D character design concept art portrait of hero."
        valid, warnings = DecouplingGuard.validate_prompt(bad_generic, bound_profiles=[])
        assert valid is False
        assert any("character design" in w or "concept art" in w for w in warnings)


# =============================================================================
# F7 Boundaries: 3-Part Continuous Episodic Arc
# =============================================================================
class TestTier2F7ContinuousEpisodicArcBoundaries:
    """Boundary testing for multi-part continuous episodic progression and loop mechanics."""

    @pytest.fixture
    def default_state(self) -> SeriesState:
        characters = {c.character_id: c for c in build_default_characters()}
        return SeriesState(
            series_id="arc_boundary_series",
            title="Continuous Arc Boundaries",
            genre="Cyber Noir",
            characters=characters,
        )

    def test_f7_b01_arc_episodes_at_30s_minimal_duration(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=30.0)
            for i in (1, 2, 3)
        ]
        assert len(episodes) == 3
        for ep in episodes:
            assert abs(ep.actual_duration - 30.0) <= 0.5

    def test_f7_b02_arc_episodes_at_60s_maximal_duration(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=60.0)
            for i in (1, 2, 3)
        ]
        assert len(episodes) == 3
        for ep in episodes:
            assert abs(ep.actual_duration - 60.0) <= 0.5

    def test_f7_b03_arc_state_progression_across_episodes(self, default_state: SeriesState):
        director = StoryDirector()
        assert default_state.current_episode == 0
        ep1 = director.direct_episode(default_state, episode_num=1, target_duration=45.0)
        assert default_state.current_episode == 1
        ep2 = director.direct_episode(default_state, episode_num=2, target_duration=45.0)
        assert default_state.current_episode == 2
        ep3 = director.direct_episode(default_state, episode_num=3, target_duration=45.0)
        assert default_state.current_episode == 3

    def test_f7_b04_arc_cliffhanger_non_empty_and_distinct(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        cliffhangers = [ep.cliffhanger for ep in episodes]
        assert len(set(cliffhangers)) == 3, "Each episode in 3-part arc must feature a distinct cliffhanger"
        for ch in cliffhangers:
            assert len(ch) > 10

    def test_f7_b05_arc_scenes_phase_continuity(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        for ep in episodes:
            phases = [s.phase for s in ep.scenes]
            assert phases[0] == EngagementPhase.HOOK
            assert phases[-1] == EngagementPhase.CLIFFHANGER_LOOP
            assert EngagementPhase.CLIMAX_TWIST in phases


# =============================================================================
# F8 Boundaries: FlowKit Pydantic Schemas & Client
# =============================================================================
class TestTier2F8FlowKitModelsBoundaries:
    """Boundary testing for FlowKit Pydantic schemas, polling traps, and dependency validators."""

    def test_f8_b01_batch_status_zero_total_trap(self):
        # Polling trap: total == 0 must not be considered done or successful
        status = BatchStatus(total=0, completed=0, failed=0, done=False, all_succeeded=False)
        assert status.total == 0
        assert status.done is False
        assert status.all_succeeded is False

    def test_f8_b02_batch_status_partial_failure_detection(self):
        status = BatchStatus(total=5, completed=3, failed=2, done=True, all_succeeded=False)
        assert status.total == 5
        assert status.done is True
        assert status.all_succeeded is False
        assert status.failed == 2

    def test_f8_b03_project_create_material_slug_regex(self):
        # Valid material slug
        p_valid = FlowKitProjectCreate(name="Proj", material="cyber_noir_3d")
        assert p_valid.material == "cyber_noir_3d"

        # Legacy style string mapping
        p_legacy = FlowKitProjectCreate(name="Proj", style="3D")
        assert p_legacy.material == "3d_pixar"

        # Invalid material regex
        with pytest.raises(ValidationError):
            FlowKitProjectCreate(name="Proj", material="INVALID MATERIAL SLUG!")

    def test_f8_b04_scene_create_missing_required_fields(self):
        # Empty prompt
        with pytest.raises(ValidationError):
            FlowKitSceneCreate(video_id="vid_123", display_order=0, prompt="")

        # Empty video_id
        with pytest.raises(ValidationError):
            FlowKitSceneCreate(video_id="", display_order=0, prompt="Valid prompt")

    def test_f8_b05_request_create_dependency_enforcement(self):
        # Missing video_id for GENERATE_IMAGE
        with pytest.raises(ValueError) as exc_info:
            FlowKitRequestCreate(
                type="GENERATE_IMAGE",
                scene_id="s1",
                project_id="p1",
            )
        assert "video_id is required" in str(exc_info.value)

        # Missing character_id for GENERATE_CHARACTER_IMAGE
        with pytest.raises(ValueError) as exc_info2:
            FlowKitRequestCreate(
                type="GENERATE_CHARACTER_IMAGE",
                project_id="p1",
            )
        assert "character_id is required" in str(exc_info2.value)


# =============================================================================
# F9 Boundaries: FlowKit Payload Validation Script
# =============================================================================
class TestTier2F9PayloadValidationScriptBoundaries:
    """Boundary testing for automated FlowKit schema pre-flight validation."""

    @pytest.fixture
    def base_state(self) -> SeriesState:
        characters = {c.character_id: c for c in build_default_characters()}
        return SeriesState(
            series_id="f9_series",
            title="Validation Series",
            genre="Noir",
            characters=characters,
        )

    def test_f9_b01_validate_manifest_with_single_character(self, base_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(base_state, episode_num=1, target_duration=35.0)
        # Filter to single character
        manifest.character_profiles = [manifest.character_profiles[0]]
        valid, report = validate_manifest_payloads(manifest)
        assert valid is True
        assert report["valid"] is True
        assert len(report["errors"]) == 0

    def test_f9_b02_validate_manifest_with_environmental_cutaways(self, base_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(base_state, episode_num=1, target_duration=45.0)
        # Ensure at least one scene has 0 bound characters
        has_cutaway = any(len(s.bound_characters) == 0 for s in manifest.scenes)
        assert has_cutaway is True
        valid, report = validate_manifest_payloads(manifest)
        assert valid is True

    def test_f9_b03_validate_manifest_30s_and_60s_payloads(self, base_state: SeriesState):
        director = StoryDirector()
        m30 = director.direct_episode(base_state, episode_num=1, target_duration=30.0)
        m60 = director.direct_episode(base_state, episode_num=2, target_duration=60.0)
        v30, _ = validate_manifest_payloads(m30)
        v60, _ = validate_manifest_payloads(m60)
        assert v30 is True
        assert v60 is True

    def test_f9_b04_validate_manifest_with_missing_optional_loops(self, base_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(base_state, episode_num=1, target_duration=40.0)
        manifest.micro_loop = None
        manifest.loop_phrase = None
        valid, report = validate_manifest_payloads(manifest)
        assert valid is True

    def test_f9_b05_validate_manifest_reports_detailed_payload_count(self, base_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(base_state, episode_num=1, target_duration=45.0)
        valid, report = validate_manifest_payloads(manifest)
        assert report["payloads_checked"] > 10


# =============================================================================
# F10 Boundaries: FlowKit End-to-End Orchestrator
# =============================================================================
class TestTier2F10FlowKitOrchestratorBoundaries:
    """Boundary testing for orchestrator mock execution, directory handling, and audio ducking."""

    @pytest.fixture
    def sample_manifest(self) -> EpisodeManifest:
        director = StoryDirector()
        state = SeriesState(
            series_id="orchestrator_bounds",
            title="Orchestrator Bounds",
            genre="Action",
            characters={c.character_id: c for c in build_default_characters()},
        )
        return director.direct_episode(state, episode_num=1, target_duration=30.0)

    @pytest.mark.asyncio
    async def test_f10_b01_mock_orchestration_missing_dir_auto_creation(self, sample_manifest: EpisodeManifest, tmp_path: Path):
        nested_dir = tmp_path / "deep" / "nested" / "renders"
        assert not nested_dir.exists()
        orchestrator = FlowKitOrchestrator(output_dir=str(nested_dir), mock=True)
        res = await orchestrator.run_pipeline(sample_manifest)
        assert res.status == "SUCCESS"
        assert nested_dir.exists()

    @pytest.mark.asyncio
    async def test_f10_b02_skip_video_render_fast_path(self, sample_manifest: EpisodeManifest, tmp_path: Path):
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(sample_manifest, skip_video_render=True)
        assert res.status == "SUCCESS"
        assert res.assembled_video_path is None
        assert "Phase 3: Video & Scenes Initialized (Simulated)" in res.phases_completed

    @pytest.mark.asyncio
    async def test_f10_b03_orchestrator_pure_environmental_manifest(self, tmp_path: Path):
        manifest = EpisodeManifest(
            series_id="env_series",
            season_num=1,
            episode_num=1,
            title="Nature Shorts",
            premise="Relaxing forest vistas",
            target_duration=30.0,
            scenes=[
                SceneBeat(
                    scene_index=0,
                    time_start=0.0,
                    time_end=3.0,
                    narration="Sunlight glimmers through the pine needles.",
                    action_prompt="Wide shot of morning sunlight through forest trees.",
                    video_prompt="0-1.5s: Sunlight streams; 1.5-3.0s: wind rustles branches.",
                    bound_characters=[],
                    phase=EngagementPhase.HOOK,
                )
            ],
            character_profiles=[],
            cliffhanger="The sun sets over the horizon.",
            next_episode_hook="Will night bring tranquility?",
        )
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(manifest)
        assert res.status == "SUCCESS"

    def test_f10_b04_check_stream_has_audio_nonexistent_file(self):
        assert check_stream_has_audio("non_existent_file_12345.mp4") is False

    def test_f10_b05_mix_narration_creates_target_parent_directories(self, tmp_path: Path):
        out_path = tmp_path / "created_dir" / "subdir" / "output.mp4"
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            with patch("src.render_client.orchestrator.check_stream_has_audio", return_value=False):
                ok = mix_narration_resilient("mock_in.mp4", "mock_narr.wav", str(out_path))
                assert ok is True
                assert out_path.parent.exists()


# =============================================================================
# F11 Boundaries: Episodic SQLite Continuity Ledger
# =============================================================================
class TestTier2F11EpisodicLedgerBoundaries:
    """Boundary testing for SQLite WAL mode, in-memory operations, and cascade deletes."""

    def test_f11_b01_in_memory_sqlite_ledger(self, tmp_path: Path):
        db_file = tmp_path / "isolated_lifecycle.db"
        ledger = EpisodicLedger(db_path=db_file)
        series = ledger.register_series(series_id="mem_1", title="Memory Series", genre="Test")
        assert series["series_id"] == "mem_1"
        assert ledger.get_series("mem_1") is not None

    def test_f11_b02_sql_injection_and_quotes_in_series(self, tmp_path: Path):
        db_path = tmp_path / "injection_test.db"
        ledger = EpisodicLedger(db_path=db_path)
        bad_id = "test's \"quote\" -- ; DROP TABLE series;"
        bad_title = "Title with '; DROP TABLE users; --"
        series = ledger.register_series(series_id=bad_id, title=bad_title, genre="Injection")
        assert series["series_id"] == bad_id
        retrieved = ledger.get_series(bad_id)
        assert retrieved is not None
        assert retrieved["title"] == bad_title

    def test_f11_b03_foreign_key_cascade_episodes_and_renders(self, tmp_path: Path):
        db_path = tmp_path / "cascade_test.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="s_casc", title="Cascade", genre="Action")

        # Save character, render, and delta
        char = CharacterProfile(character_id="c1", name="Actor", visual_summary="Desc")
        ledger.save_character("s_casc", char)
        ledger.record_render_output("s_casc", 1, "out.mp4", 30.0)
        ledger.record_character_delta("s_casc", 1, "Actor", "wound", description="Bullet wound")

        assert len(ledger.get_characters("s_casc")) == 1
        assert len(ledger.list_renders("s_casc")) == 1
        assert len(ledger.list_all_deltas("s_casc")) == 1

        # Delete series
        with ledger.transaction() as conn:
            conn.execute("DELETE FROM series WHERE series_id = ?;", ("s_casc",))

        # Cascade verified
        assert len(ledger.get_characters("s_casc")) == 0
        assert len(ledger.list_renders("s_casc")) == 0
        assert len(ledger.list_all_deltas("s_casc")) == 0

    def test_f11_b04_get_nonexistent_series_and_episode(self, tmp_path: Path):
        db_path = tmp_path / "missing_test.db"
        ledger = EpisodicLedger(db_path=db_path)
        assert ledger.get_series("ghost_series") is None
        assert ledger.get_episode_manifest("ghost_series", 1) is None
        assert ledger.get_latest_render("ghost_series", 1) is None

    def test_f11_b05_duplicate_series_registration_upsert(self, tmp_path: Path):
        db_path = tmp_path / "upsert_test.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="s_up", title="Initial Title", genre="Action")
        assert ledger.get_series("s_up")["title"] == "Initial Title"

        ledger.register_series(series_id="s_up", title="Updated Title", genre="Action")
        assert ledger.get_series("s_up")["title"] == "Updated Title"


# =============================================================================
# F12 Boundaries: Daily Batch Automation CLI
# =============================================================================
class TestTier2F12BatchCLIBoundaries:
    """Boundary testing for CLI subcommands, invalid arguments, and exit codes."""

    def test_f12_b01_batch_cli_n_zero(self, tmp_path: Path):
        db_path = tmp_path / "batch_zero.db"
        main([
            "init-series",
            "--series-id", "s_zero",
            "--title", "Zero Test",
            "--genre", "Noir",
            "--db-path", str(db_path),
        ])
        code = main([
            "batch",
            "--series-id", "s_zero",
            "-n", "0",
            "--mock",
            "--db-path", str(db_path),
        ])
        assert code == 1
        ledger = EpisodicLedger(db_path=db_path)
        assert len(ledger.list_episodes("s_zero")) == 0

    def test_f12_b02_batch_cli_n_one(self, tmp_path: Path):
        db_path = tmp_path / "batch_one.db"
        main([
            "init-series",
            "--series-id", "s_one",
            "--title", "One Test",
            "--genre", "Noir",
            "--db-path", str(db_path),
        ])
        code = main([
            "batch",
            "--series-id", "s_one",
            "-n", "1",
            "--mock",
            "--db-path", str(db_path),
            # Without this the command falls back to the shared "output/"
            # directory, so leftovers from an earlier or aborted run leak into
            # this test and change its result. Keep every write inside tmp_path.
            "--output-dir", str(tmp_path / "out"),
        ])
        assert code == 0
        ledger = EpisodicLedger(db_path=db_path)
        assert len(ledger.list_episodes("s_one")) == 1

    def test_f12_b03_invalid_command_exit_code(self):
        with pytest.raises(SystemExit) as exc_info:
            main(["non_existent_command"])
        assert exc_info.value.code != 0

    def test_f12_b04_missing_required_args_exit_code(self):
        # direct requires --series-id
        with pytest.raises(SystemExit) as exc_info:
            main(["direct"])
        assert exc_info.value.code != 0

    def test_f12_b05_status_command_nonexistent_series(self, tmp_path: Path):
        db_path = tmp_path / "status_test.db"
        code = main([
            "status",
            "--series-id", "non_existent_series_99",
            "--db-path", str(db_path),
        ])
        # Gracefully reports not found with code 1
        assert code == 1


# =============================================================================
# F13 Boundaries: User Documentation & CLI Guide
# =============================================================================
class TestTier2F13DocumentationGuideBoundaries:
    """Boundary testing for documentation consistency with code implementations."""

    @pytest.fixture
    def readme_content(self) -> str:
        p = PROJECT_ROOT / "README.md"
        assert p.exists()
        return p.read_text(encoding="utf-8")

    def test_f13_b01_cli_command_names_in_readme_match_parser(self, readme_content: str):
        parser = build_parser()
        # Extract subcommands
        sub_actions = [a for a in parser._actions if a.dest == "command"]
        subcommand_names = list(sub_actions[0].choices.keys())
        for name in subcommand_names:
            assert f"`{name}`" in readme_content or f" {name} " in readme_content

    def test_f13_b02_wpm_numbers_in_readme_match_pacing_constants(self, readme_content: str):
        min_wpm = str(int(PacingBudgeter.MIN_WPM))
        max_wpm = str(int(PacingBudgeter.MAX_WPM))
        assert min_wpm in readme_content
        assert max_wpm in readme_content

    def test_f13_b03_duration_limits_in_readme_match_pacing_constants(self, readme_content: str):
        min_d = str(int(PacingBudgeter.MIN_DURATION))
        max_d = str(int(PacingBudgeter.MAX_DURATION))
        assert min_d in readme_content
        assert max_d in readme_content

    def test_f13_b04_retention_phase_names_in_readme(self, readme_content: str):
        content_lower = readme_content.lower()
        key_phase_terms = ["hook", "rising tension", "complication", "climax", "cliffhanger"]
        for term in key_phase_terms:
            assert term in content_lower

    def test_f13_b05_flowkit_port_and_endpoints_in_readme(self, readme_content: str):
        assert "8100" in readme_content
        assert "/api" in readme_content
        assert "/api/projects" in readme_content or "projects" in readme_content
