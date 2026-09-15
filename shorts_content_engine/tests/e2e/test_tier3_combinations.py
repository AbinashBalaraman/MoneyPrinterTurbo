"""Tier 3 E2E Cross-Feature Pairwise Interaction Tests.

Validates all 13 pairwise cross-feature combinations specified in PROJECT.md and DISPATCH.md (>= 13 tests).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from scripts.validate_flowkit_payloads import validate_manifest_payloads
from src.cli import main
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
# Combination 1: F4 (Character Registry) + F6 (Decoupling Guard)
# =============================================================================
class TestCombinationF4CharacterAndF6Decoupling:
    """Pairwise interaction between Character Registry profiles and Decoupling Guard quarantine."""

    def test_c01_f4_character_registry_and_f6_decoupling_guard(self):
        reg = CharacterRegistry()
        rex = CharacterProfile(
            character_id="c_rex",
            name="Detective Rex Vance",
            visual_summary="Rugged detective with graphite trench coat and salt-and-pepper stubble.",
            voice_profile="en-US-ChristopherNeural",
        )
        reg.register_character(rex)

        # 1. Clean situational prompt with bound token -> PASS
        clean_prompt = "Detective Rex Vance enters the abandoned archive and searches the titanium console."
        valid, warnings = DecouplingGuard.validate_prompt(clean_prompt, bound_profiles=reg.list_characters())
        assert valid is True
        assert len(warnings) == 0

        # 2. Leaked attribute prompt -> FAIL
        leaked_prompt = "Detective Rex Vance buttons his graphite trench coat against the rain."
        valid_bad, warnings_bad = DecouplingGuard.validate_prompt(leaked_prompt, bound_profiles=reg.list_characters())
        assert valid_bad is False
        assert any("trench coat" in w or "graphite" in w for w in warnings_bad)


# =============================================================================
# Combination 2: F5 (Story Director) + F8 (FlowKit Models / Client)
# =============================================================================
class TestCombinationF5DirectorAndF8FlowKitModels:
    """Pairwise interaction between Story Director manifests and FlowKit Pydantic models."""

    def test_c02_f5_story_director_and_f8_flowkit_models(self):
        state = SeriesState(
            series_id="combo_f5_f8",
            title="Director to FlowKit",
            genre="Sci-Fi",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)

        # Project payload validation
        proj_payload = FlowKitPayloadAdapter.to_project_payload(manifest)
        assert isinstance(proj_payload, FlowKitProjectCreate)
        assert proj_payload.material == "realistic"

        # Video payload validation
        video_payload = FlowKitPayloadAdapter.to_video_payload(manifest, project_id="proj_100")
        assert isinstance(video_payload, FlowKitVideoCreate)
        assert video_payload.orientation == "VERTICAL"

        # Scene payloads validation
        scene_pairs = FlowKitPayloadAdapter.to_scene_payloads(manifest, video_id="vid_100")
        assert len(scene_pairs) == len(manifest.scenes)
        for sc_create, narrator_text in scene_pairs:
            assert isinstance(sc_create, FlowKitSceneCreate)
            assert sc_create.video_id == "vid_100"
            assert isinstance(narrator_text, str)


# =============================================================================
# Combination 3: F5 (Story Director) + F10 (FlowKit Orchestrator)
# =============================================================================
class TestCombinationF5DirectorAndF10Orchestrator:
    """Pairwise interaction between Story Director and FlowKit End-to-End Orchestrator."""

    @pytest.mark.asyncio
    async def test_c03_f5_story_director_and_f10_flowkit_orchestrator(self, tmp_path: Path):
        state = SeriesState(
            series_id="combo_f5_f10",
            title="Direct to Video Pipeline",
            genre="Mystery",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=35.0)

        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        result = await orchestrator.run_pipeline(manifest)

        assert isinstance(result, OrchestrationResult)
        assert result.status == "SUCCESS"
        assert result.is_mock is True
        assert result.assembled_video_path is not None
        assert os.path.exists(result.assembled_video_path)


# =============================================================================
# Combination 4: F5 (Story Director) + F11 (Episodic Ledger)
# =============================================================================
class TestCombinationF5DirectorAndF11EpisodicLedger:
    """Pairwise interaction between Story Director output and Episodic Ledger persistence."""

    def test_c04_f5_story_director_and_f11_episodic_ledger(self, tmp_path: Path):
        db_path = tmp_path / "combo_ledger.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="combo_s1", title="Director-Ledger Series", genre="Noir")

        state = SeriesState(
            series_id="combo_s1",
            title="Director-Ledger Series",
            genre="Noir",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)

        # Persist and retrieve
        ledger.save_episode_manifest(manifest)
        retrieved = ledger.get_episode_manifest("combo_s1", episode_num=1)

        assert retrieved is not None
        assert retrieved.title == manifest.title
        assert retrieved.actual_duration == manifest.actual_duration
        assert len(retrieved.scenes) == len(manifest.scenes)
        assert retrieved.cliffhanger == manifest.cliffhanger


# =============================================================================
# Combination 5: F6 (Decoupling) + F8 (FlowKit Adapter)
# =============================================================================
class TestCombinationF6DecouplingAndF8FlowKitAdapter:
    """Pairwise interaction between Prompt Decoupling and FlowKit Payload Adapter."""

    def test_c05_f6_decoupling_and_f8_flowkit_adapter(self):
        characters = build_default_characters()
        rex_name = characters[0].name
        scenes = [
            SceneBeat(
                scene_index=0,
                time_start=0.0,
                time_end=3.0,
                narration="Rex Vance was observing the rain outside.",
                action_prompt=f"[{rex_name}] stands near the broken glass window looking outside.",
                video_prompt=f"0-1.5s: [{rex_name}] moves forward; 1.5-3.0s: camera circles.",
                bound_characters=[rex_name],
                phase=EngagementPhase.HOOK,
            )
        ]
        manifest = EpisodeManifest(
            series_id="adapter_series",
            season_num=1,
            episode_num=1,
            title="Adapter Test",
            premise="Testing adapter decoupling",
            target_duration=30.0,
            scenes=scenes,
            character_profiles=[characters[0]],
            cliffhanger="A gunshot rings out.",
            next_episode_hook="Who pulled the trigger?",
        )

        scene_pairs = FlowKitPayloadAdapter.to_scene_payloads(manifest, video_id="vid_adapter_1")
        assert len(scene_pairs) == 1
        sc_create, narrator_text = scene_pairs[0]
        assert rex_name in sc_create.character_names
        assert "trench coat" not in sc_create.prompt.lower()
        assert "stubble" not in sc_create.prompt.lower()


# =============================================================================
# Combination 6: F8 (FlowKit Client) + F9 (Payload Validator)
# =============================================================================
class TestCombinationF8FlowKitClientAndF9PayloadValidator:
    """Pairwise interaction between FlowKit Pydantic models and pre-flight validation."""

    def test_c06_f8_flowkit_client_and_f9_payload_validator(self):
        state = SeriesState(
            series_id="combo_f8_f9",
            title="Validator Client Sync",
            genre="Cyberpunk",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=40.0)

        # 1. Run validator
        valid, report = validate_manifest_payloads(manifest)
        assert valid is True

        # 2. Verify payloads serialize to JSON and parse back cleanly
        proj = FlowKitPayloadAdapter.to_project_payload(manifest)
        proj_json = proj.model_dump_json()
        reparsed_proj = FlowKitProjectCreate.model_validate_json(proj_json)
        assert reparsed_proj.name == proj.name


# =============================================================================
# Combination 7: F10 (FlowKit Orchestrator) + F11 (Ledger Renders)
# =============================================================================
class TestCombinationF10OrchestratorAndF11LedgerRenders:
    """Pairwise interaction between Orchestrator completion and Ledger render recording."""

    @pytest.mark.asyncio
    async def test_c07_f10_orchestrator_and_f11_ledger_renders(self, tmp_path: Path):
        db_path = tmp_path / "renders_ledger.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="s_render", title="Render Test Series", genre="Thriller")

        state = SeriesState(
            series_id="s_render",
            title="Render Test Series",
            genre="Thriller",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=30.0)
        ledger.save_episode_manifest(manifest)

        # Run orchestrator
        orchestrator = FlowKitOrchestrator(output_dir=str(tmp_path), mock=True)
        res = await orchestrator.run_pipeline(manifest)
        assert res.status == "SUCCESS"

        # Record render output
        render_id = ledger.record_render_output(
            series_id="s_render",
            episode_num=1,
            output_path=res.assembled_video_path or "mock_path.mp4",
            duration=30.0,
            generation_mode="mock",
            metadata={"phases": res.phases_completed},
        )
        assert render_id > 0

        latest = ledger.get_latest_render("s_render", episode_num=1)
        assert latest is not None
        assert latest["status"] == "completed"
        assert latest["duration"] == 30.0


# =============================================================================
# Combination 8: F11 (Episodic Ledger) + F12 (CLI Batch Continuity)
# =============================================================================
class TestCombinationF11LedgerAndF12CLIBatchContinuity:
    """Pairwise interaction between Episodic Ledger continuity state and CLI batch generator."""

    def test_c08_f11_episodic_ledger_and_f12_cli_batch_continuity(self, tmp_path: Path):
        db_path = tmp_path / "batch_continuity.db"
        out_dir = tmp_path / "batch_out"

        # 1. Init series
        main([
            "init-series",
            "--series-id", "s_batch_cont",
            "--title", "Batch Continuity",
            "--genre", "Noir",
            "--target-duration", "35.0",
            "--db-path", str(db_path),
        ])

        # 2. Batch generate 2 episodes
        code1 = main([
            "batch",
            "--series-id", "s_batch_cont",
            "-n", "2",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code1 == 0

        ledger = EpisodicLedger(db_path=db_path)
        series_v1 = ledger.get_series("s_batch_cont")
        assert series_v1["current_episode"] == 2
        assert len(ledger.list_episodes("s_batch_cont")) == 2

        # 3. Batch generate 2 more episodes -> resumes at episode 3
        code2 = main([
            "batch",
            "--series-id", "s_batch_cont",
            "-n", "2",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code2 == 0

        series_v2 = ledger.get_series("s_batch_cont")
        assert series_v2["current_episode"] == 4
        assert len(ledger.list_episodes("s_batch_cont")) == 4


# =============================================================================
# Combination 9: F3 (Pacing) + F10 (Audio Ducking)
# =============================================================================
class TestCombinationF3PacingAndF10AudioDucking:
    """Pairwise interaction between Pacing Budgeter timelines and Orchestrator audio mixing."""

    def test_c09_f3_pacing_and_f10_audio_ducking(self, tmp_path: Path):
        # Generate 5-phase timeline
        timeline = PacingBudgeter.generate_scene_timeline(45.0, rhythm=PacingRhythm.PULSE_ACTION)
        hook_dur = timeline[0]["duration"]
        assert hook_dur == 3.0

        # Simulate audio ducking for hook scene duration
        dummy_vid = tmp_path / "hook_clip.mp4"
        dummy_aud = tmp_path / "hook_narr.wav"
        dummy_out = tmp_path / "hook_mixed.mp4"
        dummy_vid.write_bytes(b"\x00" * 20)
        dummy_aud.write_bytes(b"\x00" * 20)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="")
            ok = mix_narration_resilient(
                video_path=str(dummy_vid),
                audio_path=str(dummy_aud),
                output_path=str(dummy_out),
                sfx_vol=0.4,
                narration_vol=1.0,
            )
            assert ok is True


# =============================================================================
# Combination 10: F7 (3-Part Arc) + F11 (Ledger State Deltas)
# =============================================================================
class TestCombinationF7ContinuousArcAndF11LedgerStateDeltas:
    """Pairwise interaction between 3-Part Continuous Arc and character state deltas in Ledger."""

    def test_c10_f7_3part_arc_and_f11_ledger_state_deltas(self, tmp_path: Path):
        db_path = tmp_path / "arc_deltas.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="s_arc_delta", title="Arc Delta Series", genre="Noir")

        state = SeriesState(
            series_id="s_arc_delta",
            title="Arc Delta Series",
            genre="Noir",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        episodes = [
            director.direct_episode(state, episode_num=i, target_duration=45.0)
            for i in (1, 2, 3)
        ]

        # Record deltas for each episode
        char_name = "Detective Rex Vance"
        deltas = [
            ("Ep 1 Discovery", "Discovered temporal chronometer in the vault"),
            ("Ep 2 Confrontation", "Narrowly escaped Thorne's ambush; wounded left shoulder"),
            ("Ep 3 Resolution", "Deactivated singularity vortex; sealed temporal fracture"),
        ]
        for ep, (d_type, d_desc) in zip(episodes, deltas):
            ledger.save_episode_manifest(ep)
            ledger.record_character_delta(
                series_id="s_arc_delta",
                episode_num=ep.episode_num,
                character_name=char_name,
                delta_type=d_type,
                description=d_desc,
            )

        history = ledger.get_character_history("s_arc_delta", char_name)
        assert len(history) == 3
        assert [h["episode_num"] for h in history] == [1, 2, 3]
        assert "chronometer" in history[0]["description"]
        assert "singularity" in history[2]["description"]


# =============================================================================
# Combination 11: F4 (Character Registry) + F12 (CLI Init Series)
# =============================================================================
class TestCombinationF4CharacterAndF12CLIInitSeries:
    """Pairwise interaction between Character Registry seeding and CLI init-series command."""

    def test_c11_f4_character_and_f12_cli_init_series(self, tmp_path: Path):
        db_path = tmp_path / "init_chars.db"
        code = main([
            "init-series",
            "--series-id", "s_init_chars",
            "--title", "Init Chars Series",
            "--genre", "Sci-Fi",
            "--db-path", str(db_path),
        ])
        assert code == 0

        ledger = EpisodicLedger(db_path=db_path)
        characters = ledger.get_characters("s_init_chars")
        assert len(characters) >= 3
        names = {c.name for c in characters}
        assert "Detective Rex Vance" in names
        assert "Dr. Aris Thorne" in names
        assert "Maya Lin" in names


# =============================================================================
# Combination 12: F8 (FlowKit Models) + F12 (CLI Generate Mock)
# =============================================================================
class TestCombinationF8FlowKitAndF12CLIGenerateMock:
    """Pairwise interaction between FlowKit models and CLI generate --mock command."""

    def test_c12_f8_flowkit_and_f12_cli_generate_mock(self, tmp_path: Path):
        db_path = tmp_path / "cli_gen_mock.db"
        out_dir = tmp_path / "renders"

        # 1. Init
        main([
            "init-series",
            "--series-id", "s_gen_mock",
            "--title", "Gen Mock",
            "--genre", "Noir",
            "--db-path", str(db_path),
        ])

        # 2. Direct
        main([
            "direct",
            "--series-id", "s_gen_mock",
            "--episode", "1",
            "--db-path", str(db_path),
        ])

        # 3. Generate Mock
        code = main([
            "generate",
            "--series-id", "s_gen_mock",
            "--episode", "1",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code == 0

        ledger = EpisodicLedger(db_path=db_path)
        render = ledger.get_latest_render("s_gen_mock", episode_num=1)
        assert render is not None
        assert render["status"] == "completed"
        assert render["generation_mode"] == "mock"


# =============================================================================
# Combination 13: F11 (Episodic Ledger) + F12 (CLI Status Reporting)
# =============================================================================
class TestCombinationF11LedgerAndF12CLIStatusReporting:
    """Pairwise interaction between Episodic Ledger records and CLI status subcommand."""

    def test_c13_f11_ledger_and_f12_cli_status_reporting(self, tmp_path: Path):
        db_path = tmp_path / "cli_status.db"

        # Init and direct
        main([
            "init-series",
            "--series-id", "s_status_test",
            "--title", "Status Test",
            "--genre", "Mystery",
            "--db-path", str(db_path),
        ])
        main([
            "direct",
            "--series-id", "s_status_test",
            "--episode", "1",
            "--db-path", str(db_path),
        ])

        # Query status via CLI
        code = main([
            "status",
            "--series-id", "s_status_test",
            "--db-path", str(db_path),
        ])
        assert code == 0

        # Query all series status via CLI
        code_all = main([
            "status",
            "--db-path", str(db_path),
        ])
        assert code_all == 0
