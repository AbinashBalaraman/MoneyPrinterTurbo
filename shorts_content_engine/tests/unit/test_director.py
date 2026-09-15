"""Unit tests for the story directing engine, character persistence, pacing, and S2P prompt compilation."""

import json
import pytest
from pydantic import ValidationError

from src.director.character import CharacterRegistry
from src.director.compiler import DecouplingGuard, PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.models import (
    CharacterProfile,
    DialogueLine,
    EngagementPhase,
    EntityType,
    EpisodeManifest,
    SceneBeat,
    SeriesState,
)


class TestCharacterProfileAndRegistry:
    """Tests for CharacterProfile model and CharacterRegistry persistence."""

    def test_character_profile_creation_and_flowkit_export(self, rex_profile):
        """Verifies CharacterProfile field integrity and conversion to FlowKit entity."""
        assert rex_profile.character_id == "char_rex_vance"
        assert rex_profile.name == "Detective Rex Vance"
        assert rex_profile.entity_type == EntityType.CHARACTER
        assert rex_profile.seed == 104928

        flowkit_entity = rex_profile.to_flowkit_entity()
        assert flowkit_entity["name"] == "Detective Rex Vance"
        assert flowkit_entity["entity_type"] == "character"
        assert "Detective Rex Vance" in flowkit_entity["image_prompt"]
        assert "8k vertical framing" in flowkit_entity["image_prompt"]
        assert flowkit_entity["voice_description"] == "en-US-ChristopherNeural"

    def test_location_entity_flowkit_export(self):
        """Verifies that LOCATION entity exports 16:9 landscape framing and voice_description=None."""
        vault = CharacterProfile(
            character_id="loc_vault",
            name="Subterranean Vault",
            entity_type=EntityType.LOCATION,
            visual_summary="Reinforced concrete vault with heavy blast doors and sparking conduits",
            personality="Cold and industrial",
        )
        flowkit_entity = vault.to_flowkit_entity()
        assert flowkit_entity["name"] == "Subterranean Vault"
        assert flowkit_entity["entity_type"] == "location"
        assert flowkit_entity["voice_description"] is None
        assert "landscape 16:9 framing" in flowkit_entity["image_prompt"]
        assert "portrait" not in flowkit_entity["image_prompt"].lower()

    def test_character_profile_empty_validation(self):
        """Verifies that invalid or empty fields trigger appropriate errors."""
        with pytest.raises(ValidationError):
            CharacterProfile(character_id="", name="Valid Name", visual_summary="Valid summary")

    def test_registry_registration_and_lookup(self, character_registry, rex_profile):
        """Verifies lookup by exact ID and case-insensitive name."""
        by_id = character_registry.get_character("char_rex_vance")
        assert by_id is not None
        assert by_id.name == "Detective Rex Vance"

        by_name = character_registry.get_character("detective rex vance")
        assert by_name is not None
        assert by_name.character_id == "char_rex_vance"

        assert character_registry.get_character("nonexistent_char") is None

    def test_registry_relationships(self, character_registry):
        """Verifies recording and querying relationship dynamics."""
        rels = character_registry.get_relationships("Detective Rex Vance")
        assert "Dr. Aris Thorne" in rels
        assert rels["Dr. Aris Thorne"] == "adversary"

        character_registry.add_relationship("Maya Lin", "Dr. Aris Thorne", "monitoring target")
        updated_rels = character_registry.get_relationships("Maya Lin")
        assert updated_rels["Dr. Aris Thorne"] == "monitoring target"

    def test_registry_removal(self, character_registry):
        """Verifies character removal from registry."""
        assert character_registry.remove_character("char_maya_lin") is True
        assert character_registry.get_character("char_maya_lin") is None
        assert character_registry.get_character("Maya Lin") is None
        assert character_registry.remove_character("char_maya_lin") is False

    def test_registry_file_roundtrip(self, character_registry, tmp_path):
        """Verifies JSON persistence saving and loading without loss."""
        dump_file = tmp_path / "registry_dump.json"
        character_registry.save_to_file(dump_file)
        assert dump_file.exists()

        loaded_registry = CharacterRegistry.load_from_file(dump_file)
        assert len(loaded_registry.list_characters()) == 3
        rex = loaded_registry.get_character("Detective Rex Vance")
        assert rex is not None
        assert rex.character_id == "char_rex_vance"
        assert rex.seed == 104928


class TestPacingBudgeter:
    """Tests for PacingBudgeter mathematical pacing and scene timestamp allocations."""

    def test_word_counter(self):
        """Verifies word counting under varied punctuation and spacing."""
        assert PacingBudgeter.count_words("") == 0
        assert PacingBudgeter.count_words("Hello world!") == 2
        assert PacingBudgeter.count_words("The pocket-watch was ticking--ominously in the dark.") == 8

    def test_calculate_word_budget_standards(self):
        """Verifies 140-160 WPM budget boundaries for 30s, 45s, 60s."""
        min_w, tgt_w, max_w = PacingBudgeter.calculate_word_budget(30.0)
        assert min_w == 70
        assert tgt_w == 75
        assert max_w == 80

        min_w45, tgt_w45, max_w45 = PacingBudgeter.calculate_word_budget(45.0)
        assert 104 <= min_w45 <= 106
        assert 111 <= tgt_w45 <= 114
        assert 119 <= max_w45 <= 121

        min_w60, tgt_w60, max_w60 = PacingBudgeter.calculate_word_budget(60.0)
        assert min_w60 == 140
        assert tgt_w60 == 150
        assert max_w60 == 160

    def test_duration_boundary_rejection(self):
        """Verifies rejection of durations outside [30.0, 60.0] seconds."""
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(25.0)
        with pytest.raises(ValueError):
            PacingBudgeter.calculate_word_budget(65.0)

    def test_validate_narration_pacing(self):
        """Verifies classification of narration speed."""
        valid, wpm, msg = PacingBudgeter.validate_narration_pacing("One two three four five six seven eight nine ten", 10.0)
        assert valid is False
        assert wpm == 60.0
        assert "too sluggish" in msg

        text_25 = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three twenty-four twenty-five"
        valid, wpm, msg = PacingBudgeter.validate_narration_pacing(text_25, 10.0)
        assert valid is True
        assert 140.0 <= wpm <= 160.0
        assert "Optimal pacing" in msg

        text_35 = text_25 + " extra words running way too fast for vertical video subtitles and listener cognitive overload"
        valid, wpm, msg = PacingBudgeter.validate_narration_pacing(text_35, 10.0)
        assert valid is False
        assert wpm > 160.0
        assert "too hurried" in msg

    def test_phase_allocations_structure(self):
        """Verifies that 5-phase retention arc has correct sequence and covers full duration."""
        alloc = PacingBudgeter.calculate_phase_allocations(45.0)
        assert alloc[EngagementPhase.HOOK]["start"] == 0.0
        assert alloc[EngagementPhase.HOOK]["end"] == 3.0
        assert alloc[EngagementPhase.HOOK]["duration"] == 3.0

        assert alloc[EngagementPhase.RISING_TENSION]["start"] == 3.0
        assert alloc[EngagementPhase.CLIFFHANGER_LOOP]["end"] == 45.0

        total_dur = sum(p["duration"] for p in alloc.values())
        assert abs(total_dur - 45.0) < 0.1

    def test_scene_timeline_generation(self):
        """Verifies scene timeline generates contiguous non-overlapping time slices."""
        timeline = PacingBudgeter.generate_scene_timeline(45.0)
        assert len(timeline) >= 8

        assert timeline[0]["time_start"] == 0.0
        for i in range(len(timeline) - 1):
            assert abs(timeline[i]["time_end"] - timeline[i + 1]["time_start"]) < 0.01
            assert timeline[i]["scene_index"] == i

        assert abs(timeline[-1]["time_end"] - 45.0) < 0.1

    def test_pacing_rhythms_and_non_linear_curves(self):
        """Verifies non-linear duration curves for various PacingRhythm values."""
        assert PacingRhythm.PULSE_ACTION == "pulse_action"
        assert PacingRhythm.NOIR_SUSPENSE == "noir_suspense"
        assert PacingRhythm.VIRAL_REVELATION == "viral_revelation"
        assert PacingRhythm.COMEDIC_SNAPPY == "comedic_snappy"

        timeline_pulse = PacingBudgeter.generate_scene_timeline(45.0, rhythm=PacingRhythm.PULSE_ACTION)
        complication_pulse = [s for s in timeline_pulse if s["phase"] == EngagementPhase.COMPLICATION]
        # In PULSE_ACTION, complication scenes accelerate (subsequent scenes are shorter than the first)
        assert complication_pulse[0]["duration"] > complication_pulse[-1]["duration"], (
            f"Expected accelerating cuts in PULSE_ACTION complication, got: {[s['duration'] for s in complication_pulse]}"
        )

        timeline_noir = PacingBudgeter.generate_scene_timeline(45.0, rhythm=PacingRhythm.NOIR_SUSPENSE)
        assert len(timeline_noir) == len(timeline_pulse)
        assert abs(timeline_noir[-1]["time_end"] - 45.0) < 0.1

    def test_syntactic_pacing_adjustment_no_truncation_no_canned_fillers(self):
        """Verifies that adjust_narration_syntactically prunes adverbs without dumb ellipsis or canned fillers."""
        # Sentence slightly hurried with non-essential adverbs
        hurried = "Detective Rex Vance suddenly and furiously ran towards the portal while desperately holding the device."
        adjusted = PacingBudgeter.adjust_narration_syntactically(hurried, duration=5.0)
        assert "..." not in adjusted, "Should never end with ellipsis"
        assert not any(f in adjusted for f in ["Every second matters", "Time is running out", "There is no turning back"])
        assert adjusted.endswith((".", "!", "?"))

        # Pure sentence that is short should not be polluted with canned fillers
        short_line = "The watch was ticking backwards."
        adjusted_short = PacingBudgeter.adjust_narration_syntactically(short_line, duration=5.0)
        assert adjusted_short == short_line
        assert "Every second matters" not in adjusted_short


class TestPromptCompiler:
    """Tests for S2P Prompt Decoupling Compiler and DecouplingGuard."""

    def test_bind_entity_tokens(self):
        """Verifies proper token wrapping without double bracketing."""
        raw_text = "Detective Rex Vance rushed toward Maya Lin inside the facility."
        bound = PromptCompiler.bind_entity_tokens(raw_text, ["Detective Rex Vance", "Maya Lin"])
        assert "[Detective Rex Vance]" in bound
        assert "[Maya Lin]" in bound
        assert "[[Detective Rex Vance]]" not in bound

        # Already bracketed should remain untouched
        already_bound = "[Detective Rex Vance] observed the console."
        bound2 = PromptCompiler.bind_entity_tokens(already_bound, ["Detective Rex Vance"])
        assert bound2 == "[Detective Rex Vance] observed the console."

    def test_subclip_timeline_generation(self):
        """Verifies generation of sub-clip timed prompts."""
        timeline = PromptCompiler.generate_subclip_timeline(
            time_start=0.0,
            time_end=4.5,
            action_beats=[
                (0.0, 2.0, "Detective Rex Vance breaches the blast door"),
                (2.0, 4.5, "Rex examines the glowing mechanism"),
            ],
            bound_characters=["Detective Rex Vance", "Rex"],
        )
        assert "0.0-2.0s: [Detective Rex Vance] breaches the blast door" in timeline
        assert "2.0-4.5s: [Rex] examines the glowing mechanism" in timeline

    def test_compile_scene_prompts(self):
        """Verifies compilation of decoupled action_prompt and video_prompt."""
        action_p, video_p = PromptCompiler.compile_scene_prompts(
            situational_action="Detective Rex Vance clutches the brass chronometer",
            duration=4.5,
            bound_characters=["Detective Rex Vance"],
            camera_directive="Low angle tracking shot",
            environment="Darkened bank vault",
        )
        assert "[Detective Rex Vance]" in action_p
        assert "Environment: Darkened bank vault" in action_p
        assert "Cinematography: Low angle tracking shot" in action_p
        assert "0-2.2s:" in video_p
        assert "2.2-4.5s:" in video_p

    def test_staging_bijectivity_enforcement(self):
        """Verifies that omitting a bound character from action directives raises ValueError."""
        with pytest.raises(ValueError, match="Directorial Staging Violation"):
            PromptCompiler.compile_scene_prompts(
                situational_action="[Dr. Aris Thorne] activates the console.",
                duration=4.5,
                bound_characters=["Detective Rex Vance", "Dr. Aris Thorne"],
            )

    def test_environmental_cutaway_clean_prompt(self):
        """Verifies that pure environmental cutaways compile with bound_characters=[]."""
        action_p, video_p = PromptCompiler.compile_scene_prompts(
            situational_action="Red emergency strobe lights flash across the empty corridor",
            duration=4.0,
            bound_characters=[],
            camera_directive="Rapid whip pan",
            environment="Industrial corridor",
        )
        assert "Featuring" not in action_p
        assert "Red emergency strobe lights" in action_p
        assert "0-2.0s:" in video_p

    def test_mixed_mode_dialogue_video_prompt_compilation(self):
        """Verifies that DialogueLine injects speech action directives into video_prompt."""
        dialogue = DialogueLine(
            speaker="Dr. Aris Thorne",
            text="The true target was never the vault.",
            emotion="cold sneer",
        )
        action_p, video_p = PromptCompiler.compile_scene_prompts(
            situational_action="[Dr. Aris Thorne] smiles across the room at [Detective Rex Vance]",
            duration=4.0,
            bound_characters=["Detective Rex Vance", "Dr. Aris Thorne"],
            dialogue=dialogue,
        )
        assert "[Dr. Aris Thorne] says coldly: 'The true target was never the vault.'" in video_p

    def test_dynamic_ngram_decoupling_guard_catches_clothing_glasses_scar(self):
        """Verifies that DecouplingGuard catches multi-word tokens like 'trench coat', glasses, and scars."""
        char = CharacterProfile(
            character_id="char_test",
            name="Detective Rex Vance",
            visual_summary="Rugged detective with leather jacket, round glasses, tailored graphite trench coat, and deep facial scar.",
        )

        # Multi-word attire leakage: trench coat
        leaky_coat = "[Detective Rex Vance] wraps his trench coat tight as wind howls."
        valid_coat, warn_coat = DecouplingGuard.validate_prompt(leaky_coat, [char])
        assert not valid_coat
        assert any("trench coat" in w for w in warn_coat)

        # Multi-word attire leakage: leather jacket
        leaky_jacket = "[Detective Rex Vance] adjusts his leather jacket in the alley."
        valid_jacket, warn_jacket = DecouplingGuard.validate_prompt(leaky_jacket, [char])
        assert not valid_jacket
        assert any("leather jacket" in w for w in warn_jacket)

        # Glasses and facial scar leakage
        leaky_face = "[Detective Rex Vance] removes his round glasses to inspect the deep facial scar."
        valid_face, warn_face = DecouplingGuard.validate_prompt(leaky_face, [char])
        assert not valid_face
        assert any("round glasses" in w or "glasses" in w for w in warn_face)
        assert any("deep facial scar" in w or "scar" in w for w in warn_face)

        # Situational action should pass cleanly
        situational = "[Detective Rex Vance] sprints violently down the slick corridor with white knuckles."
        valid_sit, warn_sit = DecouplingGuard.validate_prompt(situational, [char])
        assert valid_sit
        assert len(warn_sit) == 0


class TestStoryDirector:
    """Tests for StoryDirector episodic directing, retention arc, dialogue, and continuity."""

    def test_direct_single_episode(self, story_director, series_state):
        """Verifies generation of a complete valid episode conforming to all constraints."""
        manifest = story_director.direct_episode(
            series_state=series_state,
            episode_num=1,
            target_duration=45.0,
        )

        assert manifest.series_id == series_state.series_id
        assert manifest.episode_num == 1
        assert len(manifest.scenes) >= 8
        assert len(manifest.character_profiles) >= 1

        # Check all 5 phases present
        phases = {s.phase for s in manifest.scenes}
        for expected_phase in EngagementPhase:
            assert expected_phase in phases, f"Missing phase: {expected_phase.value}"

        # Check timing and word counts
        assert abs(manifest.actual_duration - 45.0) < 1.0
        assert manifest.total_word_count >= 95
        assert 135.0 <= manifest.overall_wpm <= 165.0

        # Validate manifest integrity
        is_valid, errors = manifest.validate_integrity()
        assert is_valid, f"Validation errors: {errors}"

    def test_3part_continuous_episodic_arc(self, story_director, series_state):
        """Verifies sequential 3-part arc continuity, cliffhanger resolution, and loopback."""
        ep1 = story_director.direct_episode(series_state, 1, 45.0)
        assert series_state.current_episode == 1
        assert series_state.last_cliffhanger == ep1.cliffhanger
        assert len(ep1.cliffhanger) > 0

        ep2 = story_director.direct_episode(series_state, 2, 45.0)
        assert series_state.current_episode == 2
        assert series_state.last_cliffhanger == ep2.cliffhanger
        # Verify ep2 opening hook addresses ep1 dilemma
        assert "pulse" in ep2.scenes[0].narration.lower() or "chronometer" in ep2.scenes[0].narration.lower() or "bullet" in ep2.scenes[0].narration.lower()

        ep3 = story_director.direct_episode(series_state, 3, 45.0)
        assert series_state.current_episode == 3
        # Verify ep3 opening hook addresses ep2 cliffhanger
        assert "beam" in ep3.scenes[0].narration.lower() or "fell" in ep3.scenes[0].narration.lower() or "caught" in ep3.scenes[0].narration.lower()

        # Verify loop phrase
        assert ep3.loop_phrase is not None
        assert "pocket watch ticks backwards" in ep3.loop_phrase.lower()
        assert "pocket watch was ticking backwards" in ep1.scenes[0].narration.lower()

        # Check persistent character presence across all 3
        for ep in [ep1, ep2, ep3]:
            names = [c.name for c in ep.character_profiles]
            assert "Detective Rex Vance" in names

        # Verify series history tracking
        assert len(series_state.episode_history) == 3
        assert series_state.episode_history[0]["episode_num"] == 1
        assert series_state.episode_history[1]["episode_num"] == 2
        assert series_state.episode_history[2]["episode_num"] == 3

    def test_dual_loop_engine_micro_and_macro(self, story_director, series_state):
        """Verifies intra-episode micro-loops and season macro-looping."""
        ep1 = story_director.direct_episode(series_state, 1, 45.0)
        assert ep1.micro_loop is not None
        assert "Nobody could explain" in ep1.micro_loop

        ep2 = story_director.direct_episode(series_state, 2, 45.0)
        assert ep2.micro_loop is not None
        assert "blinding chronal fire" in ep2.micro_loop

        ep3 = story_director.direct_episode(series_state, 3, 45.0)
        assert ep3.micro_loop is not None
        assert ep3.loop_phrase == "Because when the pocket watch ticks backwards, the cycle begins anew."

    def test_mixed_mode_dialogue_in_episodes(self, story_director, series_state):
        """Verifies that episodes produce spoken character dialogue lines."""
        ep1 = story_director.direct_episode(series_state, 1, 45.0)
        dialogue_scenes = [s for s in ep1.scenes if s.dialogue is not None]
        assert len(dialogue_scenes) >= 1
        diag = dialogue_scenes[0].dialogue
        assert diag.speaker == "Dr. Aris Thorne"
        assert len(diag.text) > 0
        assert diag.emotion == "cold sneer"

    def test_environmental_cutaways_in_episodes(self, story_director, series_state):
        """Verifies pure environmental cutaways have bound_characters=[] and no leaked tokens."""
        ep1 = story_director.direct_episode(series_state, 1, 45.0)
        s5 = ep1.scenes[5]
        assert s5.bound_characters == []
        assert "Featuring" not in s5.action_prompt

        ep2 = story_director.direct_episode(series_state, 2, 45.0)
        s7 = ep2.scenes[7]
        assert s7.bound_characters == []
        assert "Featuring" not in s7.action_prompt

    def test_duration_boundary_generation(self, story_director, series_state):
        """Verifies generating episodes at boundary durations 30.0s and 60.0s."""
        # 30 seconds
        manifest_30 = story_director.direct_episode(series_state, 4, 30.0)
        assert abs(manifest_30.actual_duration - 30.0) < 1.0
        assert 135.0 <= manifest_30.overall_wpm <= 165.0
        valid_30, err_30 = manifest_30.validate_integrity()
        assert valid_30, f"30s integrity errors: {err_30}"

        # 60 seconds
        manifest_60 = story_director.direct_episode(series_state, 5, 60.0)
        assert abs(manifest_60.actual_duration - 60.0) < 1.0
        assert 135.0 <= manifest_60.overall_wpm <= 165.0
        valid_60, err_60 = manifest_60.validate_integrity()
        assert valid_60, f"60s integrity errors: {err_60}"
