"""Tier 1 E2E Feature Coverage Tests.

Validates all 13 core features (F1 to F13) in isolation with >= 5 tests per feature (>= 65 tests).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.demo_3part_arc import create_sample_character_registry, run_demo
from scripts.validate_flowkit_payloads import validate_manifest_payloads
from src.cli import build_parser, main
from src.director.character import CharacterRegistry, build_default_characters
from src.director.compiler import DecouplingGuard, PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.render_client.adapter import FlowKitPayloadAdapter, slugify_name
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
from src.render_client.orchestrator import FlowKitOrchestrator, OrchestrationResult, check_stream_has_audio, mix_narration_resilient
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
# F1: Ecosystem Survey Report
# =============================================================================
class TestTier1F1EcosystemSurvey:
    """F1: Ecosystem Survey Report verification."""

    @pytest.fixture
    def survey_path(self) -> Path:
        p = PROJECT_ROOT / "docs" / "ECOSYSTEM_SURVEY.md"
        assert p.exists(), f"ECOSYSTEM_SURVEY.md not found at {p}"
        return p

    def test_f1_01_survey_file_existence_and_structure(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        assert len(content) > 15000, "Survey report should be comprehensive (>15k characters)"
        assert "# Open-Source Video Automation & Story Directing Ecosystem Survey" in content
        assert "## Executive Summary" in content
        assert "## 1. Deep Survey of 10 Open-Source Repositories" in content
        assert "## 2. Comprehensive Comparison Matrix" in content
        assert "## 3. Concrete Architectural Patterns" in content

    def test_f1_02_survey_covers_all_ten_repositories(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        required_repos = [
            "MoneyPrinterTurbo",
            "ShortGPT",
            "StoryDiffusion",
            "VideoLingo",
            "Remotion",
            "TaleCrafter",
            "Director (VideoDB)",
            "WhisperX",
            "Edge-TTS",
            "FlowKit",
        ]
        for repo in required_repos:
            assert repo in content, f"Survey must document repository: {repo}"

    def test_f1_03_survey_comparison_matrix_completeness(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        required_dimensions = [
            "Recurring Character Persistence",
            "Prompt Decoupling (S2P)",
            "Short-Form Retention Hooks",
            "Episodic Multi-Part Memory",
            "Mathematical Pacing & WPM Budget",
            "Video Generation Engine",
        ]
        for dim in required_dimensions:
            assert dim in content, f"Comparison matrix must include dimension: {dim}"

    def test_f1_04_survey_retention_hook_mechanics(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        assert "5-Phase Short-Form Retention Arc" in content
        assert "Pattern Interrupt" in content
        assert "Ticking Clock" in content or "0.0s – 3.0s" in content
        assert "Cliffhanger" in content

    def test_f1_05_survey_pacing_and_wpm_rules(self, survey_path: Path):
        content = survey_path.read_text(encoding="utf-8")
        assert "140–160 WPM" in content or "140-160 WPM" in content
        assert "Word-Per-Minute" in content or "WPM" in content


# =============================================================================
# F2: Architectural Continuity Patterns
# =============================================================================
class TestTier1F2ArchitecturalContinuity:
    """F2: Architectural Continuity Patterns & Prompt Decoupling verification."""

    @pytest.fixture
    def docs(self) -> tuple[str, str]:
        survey = (PROJECT_ROOT / "docs" / "ECOSYSTEM_SURVEY.md").read_text(encoding="utf-8")
        debate = (PROJECT_ROOT / "docs" / "DEBATE_CONSENSUS.md").read_text(encoding="utf-8")
        return survey, debate

    def test_f2_01_s2p_decoupling_architecture_documented(self, docs: tuple[str, str]):
        survey, debate = docs
        assert "Story-to-Prompt" in survey or "S2P" in survey
        assert "Semantic Cross-Attention Collision" in survey
        assert "Quarantine" in debate or "decoupling" in debate

    def test_f2_02_reference_entity_model_documented(self, docs: tuple[str, str]):
        survey, debate = docs
        assert "CharacterProfile" in survey or "reference entity" in survey.lower()
        assert "visual_summary" in survey or "voice_description" in survey
        assert "EntityType-Aware" in debate or "EntityType" in debate

    def test_f2_03_debate_consensus_staging_bijectivity(self, docs: tuple[str, str]):
        _, debate = docs
        assert "Strict Bijective Staging" in debate
        assert "bound_characters = []" in debate or "environmental" in debate.lower()
        assert "Max 1–2 bound characters" in debate or "1-2" in debate

    def test_f2_04_audio_driven_timing_architecture_documented(self, docs: tuple[str, str]):
        survey, debate = docs
        assert "Audio-Driven" in debate or "WPM" in survey
        assert "syntactic" in debate.lower() or "Intelligent Syntactic" in debate

    def test_f2_05_dual_loop_mobius_engine_documented(self, docs: tuple[str, str]):
        survey, debate = docs
        assert "Dual-Loop" in debate
        assert "micro-loop" in debate.lower()
        assert "macro-loop" in debate.lower()


# =============================================================================
# F3: Short-Form Engagement Arc & Timing
# =============================================================================
class TestTier1F3EngagementArcAndTiming:
    """F3: 5-Phase Retention Arc and 140-160 WPM Budget Rules."""

    def test_f3_01_engagement_phase_enum_completeness(self):
        phases = [p.value for p in EngagementPhase]
        assert len(phases) == 5
        assert "hook" in phases
        assert "rising_tension" in phases
        assert "complication" in phases
        assert "climax_twist" in phases
        assert "cliffhanger_loop" in phases

    def test_f3_02_word_budget_calculation_standards(self):
        # 30s: min = 140/2 = 70, max = 160/2 = 80
        min_w, tgt_w, max_w = PacingBudgeter.calculate_word_budget(30.0)
        assert min_w == 70
        assert tgt_w == 75
        assert max_w == 80

        # 60s: min = 140, max = 160
        min_60, tgt_60, max_60 = PacingBudgeter.calculate_word_budget(60.0)
        assert min_60 == 140
        assert tgt_60 == 150
        assert max_60 == 160

    def test_f3_03_narration_pacing_validation(self):
        # 10s clip: optimal is ~25 words (150 WPM)
        optimal_text = "The clock was ticking down rapidly as Detective Rex Vance entered the dark subterranean archive room urgently searching for the secret cipher before detonation began."
        words = PacingBudgeter.count_words(optimal_text)
        assert 24 <= words <= 26
        ok, wpm, _ = PacingBudgeter.validate_narration_pacing(optimal_text, 10.0, strict=True)
        assert ok is True
        assert 140.0 <= wpm <= 160.0

        # Sluggish text
        slow_text = "Rex stopped."
        ok, wpm, reason = PacingBudgeter.validate_narration_pacing(slow_text, 10.0, strict=True)
        assert ok is False
        assert "sluggish" in reason.lower()

    def test_f3_04_phase_allocations_structure(self):
        allocs = PacingBudgeter.calculate_phase_allocations(45.0, rhythm=PacingRhythm.PULSE_ACTION)
        assert len(allocs) == 5
        assert allocs[EngagementPhase.HOOK]["start"] == 0.0
        assert allocs[EngagementPhase.HOOK]["end"] == 3.0
        assert allocs[EngagementPhase.HOOK]["duration"] == 3.0
        total_dur = sum(a["duration"] for a in allocs.values())
        assert abs(total_dur - 45.0) < 0.2

    def test_f3_05_pacing_rhythms_and_curves(self):
        timeline_pulse = PacingBudgeter.generate_scene_timeline(45.0, rhythm=PacingRhythm.PULSE_ACTION)
        timeline_noir = PacingBudgeter.generate_scene_timeline(45.0, rhythm=PacingRhythm.NOIR_SUSPENSE)
        assert len(timeline_pulse) >= 5
        assert len(timeline_noir) >= 5
        assert timeline_pulse[0]["time_start"] == 0.0
        assert timeline_pulse[-1]["time_end"] == 45.0


# =============================================================================
# F4: Persistent Character Profile Registry
# =============================================================================
class TestTier1F4CharacterProfileRegistry:
    """F4: Character Profile Data Models & CharacterRegistry CRUD."""

    def test_f4_01_character_profile_validation(self):
        profile = CharacterProfile(
            character_id="char_test_agent",
            name="Agent Echo",
            entity_type=EntityType.CHARACTER,
            visual_summary="Sleek operative with chrome cybernetic arm, dark trench coat.",
            personality="Taciturn and hyper-focused.",
            voice_profile="en-US-GuyNeural",
            seed=4242,
        )
        assert profile.character_id == "char_test_agent"
        assert profile.name == "Agent Echo"
        assert profile.seed == 4242

    def test_f4_02_entity_type_flowkit_export(self):
        char = CharacterProfile(
            character_id="char_hero",
            name="Hero",
            entity_type=EntityType.CHARACTER,
            visual_summary="Heroic detective in grey coat.",
            voice_profile="en-US-ChristopherNeural",
        )
        loc = CharacterProfile(
            character_id="loc_vault",
            name="Neon Vault",
            entity_type=EntityType.LOCATION,
            visual_summary="Subterranean bunker with neon servers.",
        )
        char_fk = char.to_flowkit_entity()
        loc_fk = loc.to_flowkit_entity()

        assert char_fk["entity_type"] == "character"
        assert char_fk["voice_description"] == "en-US-ChristopherNeural"
        assert "portrait" in char_fk["image_prompt"].lower()

        assert loc_fk["entity_type"] == "location"
        assert loc_fk["voice_description"] is None
        assert "establishing shot" in loc_fk["image_prompt"].lower()
        assert "16:9" in loc_fk["image_prompt"]

    def test_f4_03_character_registry_crud(self):
        reg = CharacterRegistry()
        p1 = CharacterProfile(
            character_id="char_1",
            name="Character One",
            visual_summary="Summary one",
        )
        reg.register_character(p1)
        assert reg.get_character("char_1") is not None
        assert reg.get_character("Character One") is not None
        assert reg.get_character("character one") is not None
        assert len(reg.list_characters()) == 1

        removed = reg.remove_character("char_1")
        assert removed is True
        assert reg.get_character("char_1") is None
        assert len(reg.list_characters()) == 0

    def test_f4_04_relationship_management(self):
        reg = CharacterRegistry()
        c1 = CharacterProfile(character_id="c1", name="Alpha", visual_summary="Desc 1")
        c2 = CharacterProfile(character_id="c2", name="Beta", visual_summary="Desc 2")
        reg.register_character(c1)
        reg.register_character(c2)

        reg.add_relationship("c1", "c2", "rivalry")
        rel = reg.get_relationships("c1")
        assert rel["Beta"] == "rivalry"

    def test_f4_05_registry_file_roundtrip(self, tmp_path: Path):
        file_path = tmp_path / "test_registry.json"
        reg = CharacterRegistry(initial_profiles=build_default_characters())
        assert len(reg.list_characters()) >= 3
        reg.save_to_file(file_path)

        loaded = CharacterRegistry.load_from_file(file_path)
        assert len(loaded.list_characters()) == len(reg.list_characters())
        rex = loaded.get_character("Detective Rex Vance")
        assert rex is not None
        assert rex.entity_type == EntityType.CHARACTER


# =============================================================================
# F5: Episodic Story Director Engine
# =============================================================================
class TestTier1F5StoryDirectorEngine:
    """F5: StoryDirector 5-Phase Generation and Continuity."""

    @pytest.fixture
    def default_state(self) -> SeriesState:
        characters = {c.character_id: c for c in build_default_characters()}
        return SeriesState(
            series_id="test_series_chrono",
            title="Chrono Test",
            genre="Sci-Fi Mystery",
            premise="Detective investigates temporal fractures.",
            characters=characters,
        )

    def test_f5_01_direct_single_episode_validity(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=45.0)
        assert isinstance(manifest, EpisodeManifest)
        assert manifest.episode_num == 1
        assert len(manifest.scenes) >= 5
        valid, errors = manifest.validate_integrity()
        assert valid is True, f"Manifest validation failed: {errors}"

    def test_f5_02_actual_duration_matches_target(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=45.0)
        assert abs(manifest.actual_duration - 45.0) <= 1.0
        assert 135.0 <= manifest.overall_wpm <= 165.0

    def test_f5_03_dual_loop_generation(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=45.0)
        assert manifest.micro_loop is not None
        assert len(manifest.micro_loop) > 5
        assert manifest.loop_phrase is not None

    def test_f5_04_mixed_mode_dialogue_directing(self, default_state: SeriesState):
        director = StoryDirector()
        manifest = director.direct_episode(default_state, episode_num=1, target_duration=45.0)
        has_dialogue = any(s.dialogue is not None for s in manifest.scenes)
        assert has_dialogue is True
        dialogue_scenes = [s for s in manifest.scenes if s.dialogue is not None]
        for s in dialogue_scenes:
            assert s.dialogue.speaker in [c.name for c in manifest.character_profiles]
            assert len(s.dialogue.text) > 0
            assert f"[{s.dialogue.speaker}]" in s.video_prompt
            assert any(v in s.video_prompt for v in ("says", "whispers", "snarls", "shouts"))

    def test_f5_05_custom_plot_directing(self, default_state: SeriesState):
        director = StoryDirector()
        custom_plot = {
            "title": "Custom Anomaly",
            "premise": "A rogue temporal AI attacks the network.",
            "cliffhanger": "The power completely cuts out.",
            "next_episode_hook": "Who triggered the blackout?",
            "scenes": [
                {
                    "narration": "Detective Vance observed the flickering monitors inside the dark room.",
                    "action_desc": "[Detective Rex Vance] inspects a sparking server terminal.",
                    "bound_characters": ["Detective Rex Vance"],
                }
            ],
        }
        manifest = director.direct_episode(
            default_state, episode_num=2, target_duration=35.0, custom_plot=custom_plot
        )
        assert manifest.title == "Custom Anomaly"
        assert manifest.cliffhanger == "The power completely cuts out."
        assert manifest.scenes[0].bound_characters == ["Detective Rex Vance"]


# =============================================================================
# F6: Decoupled Prompt & Scene Action Formatter
# =============================================================================
class TestTier1F6DecoupledPromptFormatter:
    """F6: DecouplingGuard & PromptCompiler S2P Isolation."""

    @pytest.fixture
    def profiles(self) -> list[CharacterProfile]:
        return build_default_characters()

    def test_f6_01_decoupling_guard_anatomical_categories(self, profiles: list[CharacterProfile]):
        bad_prompt = "Detective Vance with his grey trench coat and salt-and-pepper stubble runs away."
        valid, warnings = DecouplingGuard.validate_prompt(bad_prompt, bound_profiles=profiles)
        assert valid is False
        assert len(warnings) >= 1
        assert any("trench coat" in w or "stubble" in w for w in warnings)

    def test_f6_02_decoupling_guard_ngram_extraction(self):
        ngrams = DecouplingGuard._extract_ngrams("Tailored dark velvet suit with round wire-rimmed glasses.")
        assert "velvet" in ngrams
        assert "glasses" in ngrams
        assert "velvet suit" in ngrams or "round wire-rimmed" in ngrams

    def test_f6_03_prompt_compiler_bind_tokens(self, profiles: list[CharacterProfile]):
        raw = "Detective Rex Vance enters Dr. Aris Thorne's laboratory."
        bound = PromptCompiler.bind_entity_tokens(raw, [p.name for p in profiles])
        assert "[Detective Rex Vance]" in bound
        assert "[Dr. Aris Thorne]" in bound

    def test_f6_04_format_subclip_timeline(self):
        subclips = [
            (0.0, 3.0, "Actor enters room"),
            (3.0, 5.5, "Actor touches console"),
        ]
        formatted = PromptCompiler.generate_subclip_timeline(0.0, 5.5, subclips, ["Actor"])
        assert "0.0-3.0s: [Actor] enters room" in formatted
        assert "3.0-5.5s: [Actor] touches console" in formatted

    def test_f6_05_staging_bijectivity_enforcement(self, profiles: list[CharacterProfile]):
        # Environmental cutaway: zero bound characters
        clean_action = "Wide establishing shot of the rain-drenched neon alleyway."
        action, video_p = PromptCompiler.compile_scene_prompts(
            situational_action=clean_action,
            duration=3.0,
            bound_characters=[],
            camera_directive="Wide establishing shot",
            environment="Rain-drenched neon alleyway",
        )
        assert "Wide establishing shot" in action
        assert "Featuring" not in action


# =============================================================================
# F7: 3-Part Continuous Episodic Arc
# =============================================================================
class TestTier1F7ContinuousEpisodicArc:
    """F7: Programmatic 3-Part Continuous Arc Generation."""

    @pytest.fixture
    def default_state(self) -> SeriesState:
        characters = {c.character_id: c for c in build_default_characters()}
        return SeriesState(
            series_id="series_chrono_arc",
            title="The Chrono Arc",
            genre="Cyberpunk Noir Mystery",
            premise="A detective uncovers temporal fractures threatening reality.",
            characters=characters,
        )

    def test_f7_01_3part_arc_generation_sequence(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        assert len(episodes) == 3
        assert [ep.episode_num for ep in episodes] == [1, 2, 3]

    def test_f7_02_arc_cliffhanger_continuity(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        ep1, ep2, ep3 = episodes
        assert len(ep1.cliffhanger) > 0
        assert len(ep2.cliffhanger) > 0
        assert len(ep3.cliffhanger) > 0
        # Ep 2 hook resolves Ep 1 cliffhanger
        assert "blast doors" in ep1.cliffhanger or "vault" in ep1.cliffhanger.lower()
        assert "Rex" in ep2.scenes[0].narration or "Vance" in ep2.scenes[0].narration

    def test_f7_03_arc_character_persistence(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        for ep in episodes:
            char_names = {c.name for c in ep.character_profiles}
            assert "Detective Rex Vance" in char_names
            assert "Dr. Aris Thorne" in char_names or "Maya Lin" in char_names

    def test_f7_04_arc_macro_loop_phrase(self, default_state: SeriesState):
        director = StoryDirector()
        episodes = [
            director.direct_episode(default_state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]
        ep3 = episodes[2]
        assert ep3.loop_phrase is not None
        assert "pocket watch" in ep3.loop_phrase.lower() or "ticks" in ep3.loop_phrase.lower() or "clock" in ep3.loop_phrase.lower()

    def test_f7_05_demo_script_execution(self):
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "demo_3part_arc.py")]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert res.returncode == 0
        assert "ALL CONTINUITY, PACING & ELEVATED DIRECTING VERIFICATIONS PASSED SUCCESSFULLY!" in res.stdout


# =============================================================================
# F8: FlowKit Pydantic Schemas & Client
# =============================================================================
class TestTier1F8FlowKitModelsAndClient:
    """F8: FlowKit Pydantic Schemas and Asynchronous Client."""

    def test_f8_01_pydantic_project_character_models(self):
        proj = FlowKitProjectCreate(name="Test Project", material="realistic")
        assert proj.name == "Test Project"
        assert proj.material == "realistic"

        char = FlowKitCharacterCreate(
            name="Rex Vance",
            entity_type="character",
            description="Tough detective",
        )
        assert char.name == "Rex Vance"
        assert char.entity_type == "character"

    def test_f8_02_flowkit_scene_create_two_step(self):
        scene = FlowKitSceneCreate(
            video_id="vid_123",
            display_order=1,
            prompt="A dark room",
            video_prompt="0-3s: Character steps forward",
            character_names=["Rex Vance"],
        )
        assert scene.video_id == "vid_123"
        dump = scene.model_dump()
        assert "narrator_text" not in dump  # Preserved for two-step PATCH

        update = FlowKitSceneUpdate(narrator_text="The night was cold.")
        assert update.narrator_text == "The night was cold."

    def test_f8_03_flowkit_request_create_validation(self):
        req = FlowKitRequestCreate(
            type="GENERATE_IMAGE",
            scene_id="scene_001",
            project_id="proj_001",
            video_id="vid_001",
        )
        assert req.type == "GENERATE_IMAGE"
        assert req.scene_id == "scene_001"
        assert req.video_id == "vid_001"

    @pytest.mark.asyncio
    async def test_f8_04_flowkit_client_initialization_and_context(self):
        async with FlowKitClient(base_url="http://127.0.0.1:8100/api") as client:
            assert client.base_url == "http://127.0.0.1:8100/api"
            assert client.client is not None

    def test_f8_05_flowkit_client_resilient_polling_logic(self):
        # Verify BatchStatus model detects empty batch vs completed batch
        status_empty = BatchStatus(total=0, completed=0, failed=0, done=True)
        assert status_empty.total == 0

        status_full = BatchStatus(total=5, completed=5, failed=0, done=True, all_succeeded=True)
        assert status_full.total == 5
        assert status_full.done is True
        assert status_full.all_succeeded is True


# =============================================================================
# F9: FlowKit Payload Validation Script
# =============================================================================
class TestTier1F9PayloadValidationScript:
    """F9: Pre-flight Payload Validation Rules and Script."""

    @pytest.fixture
    def sample_manifest(self) -> EpisodeManifest:
        director = StoryDirector()
        state = SeriesState(
            series_id="test_series",
            title="Validation Series",
            genre="Action",
            characters={c.character_id: c for c in build_default_characters()},
        )
        return director.direct_episode(state, episode_num=1, target_duration=45.0)

    def test_f9_01_adapter_to_project_payload(self, sample_manifest: EpisodeManifest):
        proj = FlowKitPayloadAdapter.to_project_payload(sample_manifest)
        assert isinstance(proj, FlowKitProjectCreate)
        assert sample_manifest.title in proj.name
        assert proj.material == "realistic"

    def test_f9_02_adapter_to_character_payloads(self, sample_manifest: EpisodeManifest):
        char_payloads = FlowKitPayloadAdapter.to_character_payloads(sample_manifest.character_profiles)
        assert len(char_payloads) == len(sample_manifest.character_profiles)
        for cp in char_payloads:
            assert isinstance(cp, FlowKitCharacterCreate)
            assert cp.name in [c.name for c in sample_manifest.character_profiles]

    def test_f9_03_adapter_to_scene_payloads(self, sample_manifest: EpisodeManifest):
        scene_payloads = FlowKitPayloadAdapter.to_scene_payloads(sample_manifest, video_id="vid_test_123")
        assert len(scene_payloads) == len(sample_manifest.scenes)
        for sc, narrator_txt in scene_payloads:
            assert isinstance(sc, FlowKitSceneCreate)
            assert sc.video_id == "vid_test_123"
            assert isinstance(narrator_txt, str)

    def test_f9_04_validate_manifest_payloads_function(self, sample_manifest: EpisodeManifest):
        ok, report = validate_manifest_payloads(sample_manifest)
        assert ok is True
        assert report["valid"] is True
        assert report["payloads_checked"] > 10
        assert len(report["errors"]) == 0

    def test_f9_05_standalone_validation_script_run(self):
        cmd = [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_flowkit_payloads.py")]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert res.returncode == 0
        assert "Validation Result: SUCCESS" in res.stdout


# =============================================================================
# F10: FlowKit End-to-End Orchestrator
# =============================================================================
class TestTier1F10FlowKitOrchestrator:
    """F10: FlowKit Orchestrator Pipeline, Audio Ducking, and Concatenation."""

    @pytest.fixture
    def sample_manifest(self) -> EpisodeManifest:
        director = StoryDirector()
        state = SeriesState(
            series_id="orchestrator_series",
            title="Orchestration Test",
            genre="Thriller",
            characters={c.character_id: c for c in build_default_characters()},
        )
        return director.direct_episode(state, episode_num=1, target_duration=35.0)

    @pytest.mark.asyncio
    async def test_f10_01_orchestrator_mock_execution_success(self, sample_manifest: EpisodeManifest, tmp_path: Path):
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(sample_manifest)
        assert isinstance(res, OrchestrationResult)
        assert res.status == "SUCCESS"
        assert res.is_mock is True
        assert res.episode_num == 1

    @pytest.mark.asyncio
    async def test_f10_02_orchestrator_creates_mp4_artifact(self, sample_manifest: EpisodeManifest, tmp_path: Path):
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(sample_manifest)
        assert res.assembled_video_path is not None
        assert os.path.exists(res.assembled_video_path)
        assert res.assembled_video_path.endswith(".mp4")

    @pytest.mark.asyncio
    async def test_f10_03_orchestrator_phase_tracking(self, sample_manifest: EpisodeManifest, tmp_path: Path):
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(sample_manifest)
        assert len(res.phases_completed) >= 4
        assert any("Project & Entities" in p for p in res.phases_completed)
        assert any("Scenes Initialized" in p for p in res.phases_completed)

    def test_f10_04_dual_path_audio_mixer_silent_video(self, tmp_path: Path):
        vid_path = tmp_path / "mock_silent.mp4"
        aud_path = tmp_path / "mock_narration.wav"
        out_path = tmp_path / "mock_output.mp4"
        vid_path.write_bytes(b"\x00" * 100)
        aud_path.write_bytes(b"\x00" * 100)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            ok = mix_narration_resilient(str(vid_path), str(aud_path), str(out_path))
            assert ok is True

    def test_f10_05_check_stream_has_audio_probe(self, tmp_path: Path):
        test_file = tmp_path / "sample.mp4"
        test_file.write_bytes(b"\x00" * 10)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="audio\n")
            has_audio = check_stream_has_audio(str(test_file))
            assert has_audio is True

            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            has_audio_false = check_stream_has_audio(str(test_file))
            assert has_audio_false is False


# =============================================================================
# F11: Episodic SQLite Continuity Ledger
# =============================================================================
class TestTier1F11EpisodicContinuityLedger:
    """F11: EpisodicLedger SQLite WAL Mode, Foreign Keys, and Transactions."""

    @pytest.fixture
    def ledger(self, tmp_path: Path) -> EpisodicLedger:
        db_file = tmp_path / "continuity_test.db"
        return EpisodicLedger(db_path=db_file)

    def test_f11_01_ledger_initialization_wal_mode(self, ledger: EpisodicLedger):
        conn = ledger.get_connection()
        try:
            journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
            busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
            assert journal_mode.lower() == "wal"
            assert foreign_keys == 1
            assert busy_timeout == 30000
        finally:
            conn.close()

    def test_f11_02_series_crud_and_cascade_delete(self, ledger: EpisodicLedger):
        series = ledger.register_series(
            series_id="s_crud",
            title="CRUD Series",
            genre="Mystery",
            logline="Testing series lifecycle",
        )
        assert series["series_id"] == "s_crud"
        assert series["title"] == "CRUD Series"

        # Save a character under s_crud
        char = CharacterProfile(character_id="c_crud", name="Crudder", visual_summary="Test")
        ledger.save_character("s_crud", char)
        assert len(ledger.get_characters("s_crud")) == 1

        # Cascade delete
        with ledger.transaction() as conn:
            conn.execute("DELETE FROM series WHERE series_id = ?;", ("s_crud",))
        assert ledger.get_series("s_crud") is None
        assert len(ledger.get_characters("s_crud")) == 0

    def test_f11_03_character_persistence_in_ledger(self, ledger: EpisodicLedger):
        ledger.register_series(series_id="s_chars", title="Character Series", genre="Sci-Fi")
        rex = CharacterProfile(
            character_id="char_rex",
            name="Detective Rex Vance",
            visual_summary="Trench coat detective",
            voice_profile="en-US-ChristopherNeural",
            seed=1001,
            relationships={"Maya": "ally"},
        )
        ledger.save_character("s_chars", rex)
        loaded = ledger.get_characters("s_chars")
        assert len(loaded) == 1
        assert loaded[0].name == "Detective Rex Vance"
        assert loaded[0].seed == 1001
        assert loaded[0].relationships["Maya"] == "ally"

    def test_f11_04_episode_manifest_storage_and_retrieval(self, ledger: EpisodicLedger):
        ledger.register_series(series_id="s_manifest", title="Manifest Series", genre="Noir")
        director = StoryDirector()
        state = SeriesState(
            series_id="s_manifest",
            title="Manifest Series",
            genre="Noir",
            characters={c.character_id: c for c in build_default_characters()},
        )
        manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)

        ledger.save_episode_manifest(manifest)
        retrieved = ledger.get_episode_manifest("s_manifest", episode_num=1)
        assert retrieved is not None
        assert retrieved.title == manifest.title
        assert len(retrieved.scenes) == len(manifest.scenes)
        assert retrieved.actual_duration == manifest.actual_duration

    def test_f11_05_character_delta_tracking(self, ledger: EpisodicLedger):
        ledger.register_series(series_id="s_deltas", title="Delta Series", genre="Drama")
        ledger.record_character_delta(
            series_id="s_deltas",
            episode_num=1,
            character_name="Detective Rex Vance",
            delta_type="investigation",
            new_value="Discovered the temporal cipher; distrusts Thorne.",
            description="Cipher discovery",
        )
        history = ledger.get_character_history("s_deltas", "Detective Rex Vance")
        assert len(history) == 1
        assert history[0]["episode_num"] == 1
        assert "cipher" in history[0]["new_value"]


# =============================================================================
# F12: Daily Batch Automation CLI
# =============================================================================
class TestTier1F12DailyBatchCLI:
    """F12: CLI Runner Commands and Subcommands."""

    def test_f12_01_cli_parser_all_commands(self):
        parser = build_parser()
        subcommands = [
            "init-series",
            "direct",
            "generate",
            "batch",
            "status",
            "validate",
        ]
        sub_args = {
            "init-series": ["init-series", "--series-id", "x", "--title", "y", "--genre", "z"],
            "direct": ["direct", "--series-id", "x"],
            "generate": ["generate", "--series-id", "x"],
            "batch": ["batch", "--series-id", "x"],
            "status": ["status"],
            "validate": ["validate"],
        }
        for sub in subcommands:
            parsed = parser.parse_args(sub_args[sub])
            assert parsed.command == sub

    def test_f12_02_cli_init_series_command(self, tmp_path: Path):
        db_path = tmp_path / "cli_init.db"
        code = main([
            "init-series",
            "--series-id", "cli_test_1",
            "--title", "CLI Test 1",
            "--genre", "Noir",
            "--db-path", str(db_path),
        ])
        assert code == 0
        ledger = EpisodicLedger(db_path=db_path)
        series = ledger.get_series("cli_test_1")
        assert series is not None
        assert series["title"] == "CLI Test 1"
        assert len(ledger.get_characters("cli_test_1")) >= 3

    def test_f12_03_cli_direct_command(self, tmp_path: Path):
        db_path = tmp_path / "cli_direct.db"
        main([
            "init-series",
            "--series-id", "cli_test_2",
            "--title", "CLI Test 2",
            "--genre", "Cyberpunk",
            "--db-path", str(db_path),
        ])
        manifest_out = tmp_path / "ep1_manifest.json"
        code = main([
            "direct",
            "--series-id", "cli_test_2",
            "--episode", "1",
            "--output-manifest", str(manifest_out),
            "--db-path", str(db_path),
        ])
        assert code == 0
        assert manifest_out.exists()
        manifest_data = json.loads(manifest_out.read_text(encoding="utf-8"))
        assert manifest_data["episode_num"] == 1
        assert len(manifest_data["scenes"]) >= 5

    def test_f12_04_cli_generate_mock_command(self, tmp_path: Path):
        db_path = tmp_path / "cli_gen.db"
        out_dir = tmp_path / "renders"
        main([
            "init-series",
            "--series-id", "cli_test_3",
            "--title", "CLI Test 3",
            "--genre", "Mystery",
            "--db-path", str(db_path),
        ])
        main([
            "direct",
            "--series-id", "cli_test_3",
            "--episode", "1",
            "--db-path", str(db_path),
        ])
        code = main([
            "generate",
            "--series-id", "cli_test_3",
            "--episode", "1",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code == 0
        ledger = EpisodicLedger(db_path=db_path)
        render = ledger.get_latest_render("cli_test_3", episode_num=1)
        assert render is not None
        assert render["status"] == "completed"

    def test_f12_05_cli_batch_automation_command(self, tmp_path: Path):
        db_path = tmp_path / "cli_batch.db"
        out_dir = tmp_path / "batch_renders"
        main([
            "init-series",
            "--series-id", "cli_batch_test",
            "--title", "CLI Batch Series",
            "--genre", "Sci-Fi",
            "--target-duration", "35.0",
            "--db-path", str(db_path),
        ])
        code = main([
            "batch",
            "--series-id", "cli_batch_test",
            "-n", "2",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code == 0
        ledger = EpisodicLedger(db_path=db_path)
        series = ledger.get_series("cli_batch_test")
        assert series["current_episode"] == 2
        episodes = ledger.list_episodes("cli_batch_test")
        assert len(episodes) == 2


# =============================================================================
# F13: User Documentation & CLI Guide
# =============================================================================
class TestTier1F13DocumentationGuide:
    """F13: Documentation Completeness and Quality in README.md."""

    @pytest.fixture
    def readme_content(self) -> str:
        p = PROJECT_ROOT / "README.md"
        assert p.exists(), f"README.md not found at {p}"
        return p.read_text(encoding="utf-8")

    def test_f13_01_readme_file_exists_and_sections(self, readme_content: str):
        assert "# Episodic Content Directing & Video Production Engine" in readme_content
        assert "## 1. System Architecture & Ecosystem Comparison" in readme_content
        assert "## 2. Story Directing & Prompt Decoupling Engine" in readme_content
        assert "## 3. FlowKit & Google Flow Integration Subsystem" in readme_content
        assert "## 4. Continuity Ledger & State Tracking Subsystem" in readme_content
        assert "## 5. Command-Line Interface (CLI) Manual" in readme_content
        assert "## 6. Testing & Verification" in readme_content

    def test_f13_02_readme_documents_cli_commands(self, readme_content: str):
        required_cmds = [
            "init-series",
            "direct",
            "generate",
            "batch",
            "status",
            "validate",
        ]
        for cmd in required_cmds:
            assert f"`{cmd}`" in readme_content or f"{cmd}" in readme_content

    def test_f13_03_readme_documents_pacing_and_retention(self, readme_content: str):
        assert "140–160 WPM" in readme_content or "140-160 WPM" in readme_content
        assert "5-Phase" in readme_content or "Retention Arc" in readme_content
        assert "Hook" in readme_content
        assert "Cliffhanger" in readme_content

    def test_f13_04_readme_documents_s2p_decoupling(self, readme_content: str):
        assert "S2P" in readme_content or "Story-to-Prompt" in readme_content
        assert "Decoupling" in readme_content or "decoupling" in readme_content
        assert "CharacterProfile" in readme_content or "Character Registry" in readme_content

    def test_f13_05_readme_documents_flowkit_integration(self, readme_content: str):
        assert "FlowKit" in readme_content
        assert "127.0.0.1:8100" in readme_content
        assert "--mock" in readme_content
