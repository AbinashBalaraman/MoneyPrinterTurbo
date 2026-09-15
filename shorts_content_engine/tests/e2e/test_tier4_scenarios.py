"""Tier 4 E2E Real-World Multi-Episode Workload Scenarios.

Validates 7 comprehensive real-world end-to-end production scenarios:
1. Noir Detective Miniseries (3-part continuous arc with state deltas & validation).
2. Cyberpunk Thriller with rapid pacing rhythm (PULSE_ACTION).
3. Comedic Snappy Shorts with alternating character dialogue beats.
4. Daily Batch 5-Episode Production with cliffhanger resolution chain.
5. Full Mock Generation Pipeline producing assembled MP4 and ledger record.
6. FlowKit API pre-flight validation on dynamically generated series.
7. State Recovery & Resume after simulated interrupted batch.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.validate_flowkit_payloads import validate_manifest_payloads
from src.cli import main
from src.director.character import CharacterRegistry, build_default_characters
from src.director.compiler import DecouplingGuard, PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.render_client.adapter import FlowKitPayloadAdapter
from src.render_client.models import (
    FlowKitCharacterCreate,
    FlowKitProjectCreate,
    FlowKitSceneCreate,
    FlowKitVideoCreate,
)
from src.render_client.orchestrator import FlowKitOrchestrator, OrchestrationResult
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
# Scenario 1: Noir Detective Miniseries
# =============================================================================
class TestScenario1NoirDetectiveMiniseries:
    """Scenario 1: Noir Detective 3-Part Miniseries with state deltas, manifests, and validation."""

    def test_scenario_1_noir_miniseries(self, tmp_path: Path):
        db_path = tmp_path / "noir_miniseries.db"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(
            series_id="s_noir_miniseries",
            title="The Chrono Cipher: Noir Chronicle",
            genre="Cyberpunk Noir Mystery",
            logline="A detective investigates temporal chronometers ticking backwards.",
            target_duration=45.0,
            pacing_rhythm="noir_suspense",
        )

        state = SeriesState(
            series_id="s_noir_miniseries",
            title="The Chrono Cipher: Noir Chronicle",
            genre="Cyberpunk Noir Mystery",
            premise="A detective investigates temporal chronometers ticking backwards.",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()

        episodes: list[EpisodeManifest] = []
        for ep_num in range(1, 4):
            manifest = director.direct_episode(
                series_state=state,
                episode_num=ep_num,
                target_duration=45.0,
                rhythm=PacingRhythm.NOIR_SUSPENSE,
            )
            episodes.append(manifest)

            # Validate manifest payloads against FlowKit schemas
            is_valid, report = validate_manifest_payloads(manifest)
            assert is_valid is True, f"Manifest validation failed in Ep {ep_num}: {report['errors']}"

            # Save in ledger
            ledger.save_episode_manifest(manifest)

        # Track character state deltas across episodes
        ledger.record_character_delta(
            series_id="s_noir_miniseries",
            episode_num=1,
            character_name="Detective Rex Vance",
            delta_type="evidence_found",
            new_value="Pocket watch ticking backwards",
            description="Found chronometer at crime scene",
        )
        ledger.record_character_delta(
            series_id="s_noir_miniseries",
            episode_num=2,
            character_name="Detective Rex Vance",
            delta_type="combat_injury",
            new_value="Shoulder graze from laser fire",
            description="Ambushed in the subterranean archive",
        )
        ledger.record_character_delta(
            series_id="s_noir_miniseries",
            episode_num=3,
            character_name="Detective Rex Vance",
            delta_type="case_closed",
            new_value="Temporal rift sealed",
            description="Contained the singularity loop",
        )

        # Verify continuity and ledger records
        stored_episodes = ledger.list_episodes("s_noir_miniseries")
        assert len(stored_episodes) == 3
        history = ledger.get_character_history("s_noir_miniseries", "Detective Rex Vance")
        assert len(history) == 3
        assert history[0]["episode_num"] == 1
        assert history[2]["episode_num"] == 3


# =============================================================================
# Scenario 2: Cyberpunk Thriller with Rapid Pacing Rhythm
# =============================================================================
class TestScenario2CyberpunkPulseAction:
    """Scenario 2: Cyberpunk Thriller with rapid pacing rhythm (PULSE_ACTION)."""

    def test_scenario_2_cyberpunk_pulse_action(self):
        state = SeriesState(
            series_id="cyber_pulse",
            title="Neon Overdrive",
            genre="High-Octane Cyberpunk",
            premise="A rogue netrunner sprints through neon highway blockades.",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(
            series_state=state,
            episode_num=1,
            target_duration=45.0,
            rhythm=PacingRhythm.PULSE_ACTION,
        )

        # 1. Pacing & Timing validation
        assert abs(manifest.actual_duration - 45.0) <= 0.5
        assert len(manifest.scenes) >= 7, "PULSE_ACTION rhythm should generate high scene density"

        # Hook is strictly 0.0s to 3.0s
        hook = manifest.scenes[0]
        assert hook.time_start == 0.0
        assert hook.time_end == 3.0
        assert hook.duration == 3.0

        # Verify overall episode WPM satisfies 140-160 WPM sweet spot
        assert 135.0 <= manifest.overall_wpm <= 165.0
        for scene in manifest.scenes:
            if scene.narration:
                assert scene.word_count > 0
                assert scene.wpm > 0

        # 2. Prompt Decoupling validation
        for s in manifest.scenes:
            valid, warnings = DecouplingGuard.validate_prompt(s.action_prompt, manifest.character_profiles)
            assert valid is True, f"Prompt leak in scene {s.scene_index}: {warnings}"


# =============================================================================
# Scenario 3: Comedic Snappy Shorts with Alternating Dialogue
# =============================================================================
class TestScenario3ComedicSnappyShortsDialogue:
    """Scenario 3: Comedic Snappy Shorts with alternating character dialogue beats."""

    def test_scenario_3_comedic_snappy_dialogue(self):
        c1 = CharacterProfile(
            character_id="c_maya",
            name="Maya Lin",
            visual_summary="Sharp operative in high-collar vest.",
            voice_profile="en-US-JennyNeural",
        )
        c2 = CharacterProfile(
            character_id="c_rex",
            name="Detective Rex Vance",
            visual_summary="Rugged detective in charcoal coat.",
            voice_profile="en-US-ChristopherNeural",
        )
        state = SeriesState(
            series_id="comedy_shorts",
            title="Midnight Banter",
            genre="Buddy Cop Comedy",
            premise="Two mismatched partners argue while defusing a cyber bomb.",
            characters={"c_maya": c1, "c_rex": c2},
        )

        # Custom dialogue plot
        custom_plot = {
            "title": "Wire Dilemma",
            "premise": "Which wire do we cut?",
            "cliffhanger": "Rex reaches for the green wire as the countdown timer hits 01.",
            "next_episode_hook": "Does the green wire blow the city to pieces?",
            "scenes": [
                {
                    "narration": "The countdown timer flashed thirty seconds inside the dark server room.",
                    "action_desc": "[Detective Rex Vance] and [Maya Lin] crouch beside the humming device.",
                    "camera_directive": "Close-up split focus",
                    "bound_characters": ["Detective Rex Vance", "Maya Lin"],
                    "dialogue": DialogueLine(speaker="Detective Rex Vance", text="Cut the blue wire.", emotion="dry calm"),
                },
                {
                    "narration": "Maya pulled the wire cutters back with a mocking expression.",
                    "action_desc": "[Maya Lin] snatches the cutters away from [Detective Rex Vance].",
                    "camera_directive": "Rapid snap zoom",
                    "bound_characters": ["Maya Lin", "Detective Rex Vance"],
                    "dialogue": DialogueLine(speaker="Maya Lin", text="Blue triggers the EMP, genius.", emotion="urgent retort"),
                },
                {
                    "narration": "Rex pointed to the schematic on the glowing screen.",
                    "action_desc": "[Detective Rex Vance] gestures toward the digital tablet.",
                    "camera_directive": "Over the shoulder shot",
                    "bound_characters": ["Detective Rex Vance"],
                    "dialogue": DialogueLine(speaker="Detective Rex Vance", text="The manual was written upside down.", emotion="whisper"),
                },
                {
                    "narration": "Maya stared at the tablet in utter disbelief.",
                    "action_desc": "[Maya Lin] tilts her head with wide eyes.",
                    "camera_directive": "Extreme close-up",
                    "bound_characters": ["Maya Lin"],
                },
                {
                    "narration": "The timer dropped to five seconds as sparks showered the concrete floor.",
                    "action_desc": "[Detective Rex Vance] reaches for the green wire as sparks rain down.",
                    "camera_directive": "Fast push-in",
                    "bound_characters": ["Detective Rex Vance"],
                },
            ],
        }

        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=35.0, custom_plot=custom_plot)

        assert manifest.title == "Wire Dilemma"
        assert len(manifest.scenes) >= 5

        # Check that mixed-mode dialogue was compiled with proper speaker tokens
        dialogue_scenes = [s for s in manifest.scenes if s.dialogue is not None]
        assert len(dialogue_scenes) >= 3
        speakers = {s.dialogue.speaker for s in dialogue_scenes}
        assert "Detective Rex Vance" in speakers
        assert "Maya Lin" in speakers

        for s in dialogue_scenes:
            assert f"[{s.dialogue.speaker}]" in s.video_prompt


# =============================================================================
# Scenario 4: Daily Batch 5-Episode Production
# =============================================================================
class TestScenario4DailyBatch5EpisodeProduction:
    """Scenario 4: Daily Batch 5-Episode Production with cliffhanger resolution chain."""

    def test_scenario_4_daily_batch_5_episodes(self, tmp_path: Path):
        db_path = tmp_path / "batch_5ep.db"
        out_dir = tmp_path / "batch_5ep_renders"

        # Initialize series
        init_code = main([
            "init-series",
            "--series-id", "s_daily_batch_5",
            "--title", "The 5-Day Chronicle",
            "--genre", "Sci-Fi Mystery",
            "--target-duration", "35.0",
            "--db-path", str(db_path),
        ])
        assert init_code == 0

        # Execute 5-episode batch in mock mode
        batch_code = main([
            "batch",
            "--series-id", "s_daily_batch_5",
            "-n", "5",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert batch_code == 0

        ledger = EpisodicLedger(db_path=db_path)
        series = ledger.get_series("s_daily_batch_5")
        assert series["current_episode"] == 5

        episodes = ledger.list_episodes("s_daily_batch_5")
        assert len(episodes) == 5

        # Verify cliffhanger resolution chain
        for i in range(len(episodes)):
            ep = episodes[i]
            assert ep["episode_num"] == i + 1
            assert len(ep["cliffhanger"]) > 5
            assert len(ep["next_episode_hook"]) > 5


# =============================================================================
# Scenario 5: Full Mock Generation Pipeline
# =============================================================================
class TestScenario5FullMockGenerationPipeline:
    """Scenario 5: Full Mock Generation Pipeline producing real assembled MP4 and ledger record."""

    @pytest.mark.asyncio
    async def test_scenario_5_full_mock_generation(self, tmp_path: Path):
        db_path = tmp_path / "mock_gen.db"
        render_dir = tmp_path / "assembled_output"
        ledger = EpisodicLedger(db_path=db_path)
        ledger.register_series(series_id="s_full_gen", title="Full Gen Series", genre="Action")

        state = SeriesState(
            series_id="s_full_gen",
            title="Full Gen Series",
            genre="Action",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=30.0)
        ledger.save_episode_manifest(manifest)

        # Execute pipeline
        orchestrator = FlowKitOrchestrator(output_dir=str(render_dir), mock=True)
        res = await orchestrator.run_pipeline(manifest)

        assert res.status == "SUCCESS"
        assert res.assembled_video_path is not None
        assert os.path.exists(res.assembled_video_path)

        # Record in ledger
        render_id = ledger.record_render_output(
            series_id="s_full_gen",
            episode_num=1,
            output_path=res.assembled_video_path,
            duration=30.0,
            generation_mode="mock",
        )
        assert render_id > 0

        # Retrieve and verify artifact linkage
        render_rec = ledger.get_latest_render("s_full_gen", episode_num=1)
        assert render_rec is not None
        assert os.path.exists(render_rec["output_path"])


# =============================================================================
# Scenario 6: Dynamic Series Preflight Validation
# =============================================================================
class TestScenario6DynamicSeriesPreflightValidation:
    """Scenario 6: FlowKit API pre-flight validation on dynamically generated series."""

    def test_scenario_6_preflight_validation(self):
        state = SeriesState(
            series_id="dyn_val_series",
            title="Dynamic Validation",
            genre="Sci-Fi Thriller",
            characters={c.character_id: c for c in build_default_characters()},
        )
        director = StoryDirector()

        total_payloads_checked = 0
        for ep_i in (1, 2, 3):
            manifest = director.direct_episode(state, episode_num=ep_i, target_duration=40.0)
            valid, report = validate_manifest_payloads(manifest)
            assert valid is True, f"Validation failure in episode {ep_i}: {report['errors']}"
            total_payloads_checked += report["payloads_checked"]

        assert total_payloads_checked > 30


# =============================================================================
# Scenario 7: State Recovery & Resume after Interrupted Batch
# =============================================================================
class TestScenario7StateRecoveryAndBatchResume:
    """Scenario 7: State Recovery & Resume after simulated interrupted batch."""

    def test_scenario_7_interrupted_batch_resume(self, tmp_path: Path):
        db_path = tmp_path / "resume_batch.db"
        out_dir = tmp_path / "resume_renders"

        # 1. Initialize series
        main([
            "init-series",
            "--series-id", "s_resume_series",
            "--title", "Resilient Production",
            "--genre", "Cyberpunk",
            "--target-duration", "30.0",
            "--db-path", str(db_path),
        ])

        # 2. Run initial batch of 2 episodes
        code_batch1 = main([
            "batch",
            "--series-id", "s_resume_series",
            "-n", "2",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code_batch1 == 0

        ledger = EpisodicLedger(db_path=db_path)
        series_state1 = ledger.get_series("s_resume_series")
        assert series_state1["current_episode"] == 2

        # 3. Simulate process exit / interruption, then resume with 2 more episodes
        code_batch2 = main([
            "batch",
            "--series-id", "s_resume_series",
            "-n", "2",
            "--start-episode", "3",
            "--mock",
            "--output-dir", str(out_dir),
            "--db-path", str(db_path),
        ])
        assert code_batch2 == 0

        series_state2 = ledger.get_series("s_resume_series")
        assert series_state2["current_episode"] == 4

        episodes = ledger.list_episodes("s_resume_series")
        assert len(episodes) == 4
        assert [e["episode_num"] for e in episodes] == [1, 2, 3, 4]
