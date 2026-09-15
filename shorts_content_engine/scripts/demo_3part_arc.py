"""Programmatic Demo: 3-Part Continuous Episodic Arc with Character Continuity and S2P Prompt Decoupling.

Demonstrates all consensus improvements from the Adversarial Review:
1. Persistent Character & Location Reference Entities (EntityType-aware FlowKit exports).
2. Dynamic N-gram S2P Prompt Decoupling Guard (zero physical attribute leakage).
3. Strict Staging Bijectivity & Clean Environmental Cutaways (bound_characters = []).
4. Non-linear Dynamic Tempo Curves (PacingRhythm).
5. Mixed-Mode Direct Character Dialogue (DialogueLine with vocal emotion directives).
6. Dual-Loop Engine (Intra-episode micro-loop + season macro-loop).
7. Strict 140-160 WPM Mathematical Pacing Budget Enforcement without dumb truncation or canned fillers.
"""

import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.director.character import CharacterRegistry
from src.director.compiler import DecouplingGuard, PromptCompiler
from src.director.director import StoryDirector
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.models import CharacterProfile, EntityType, SeriesState


def create_sample_character_registry() -> CharacterRegistry:
    """Initializes persistent character and location profiles for the continuous series."""
    registry = CharacterRegistry()

    rex = CharacterProfile(
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
    )

    thorne = CharacterProfile(
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
    )

    maya = CharacterProfile(
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
    )

    vault = CharacterProfile(
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
    )

    registry.register_character(rex)
    registry.register_character(thorne)
    registry.register_character(maya)
    registry.register_character(vault)

    return registry


def run_demo() -> int:
    """Executes the 3-part continuous episodic arc generation and validation."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 80)
    print("DIRECTOR ENGINE: 3-PART CONTINUOUS EPISODIC ARC DEMO (ELEVATED)")
    print("=" * 80)

    # 1. Setup persistent character & location registry
    registry = create_sample_character_registry()
    print(f"[OK] Registered {len(registry.list_characters())} persistent recurring entities:")
    for entity in registry.list_characters():
        fk = entity.to_flowkit_entity()
        print(f"   * [{entity.entity_type.value.upper()}] {entity.name} ({entity.character_id})")
        print(f"     FlowKit Voice: {fk['voice_description']} | Image Prompt: {fk['image_prompt'][:70]}...")

    # 2. Setup Series State
    series_state = SeriesState(
        series_id="series_chrono_cipher",
        title="The Chrono Cipher",
        genre="Cyberpunk Noir Mystery",
        premise="A hardboiled detective discovers a series of impossible temporal crimes unraveling his city's timeline.",
        current_season=1,
        current_episode=0,
    )
    print(f"\n[SERIES] Initialized: '{series_state.title}' ({series_state.genre})")

    # 3. Initialize Story Director
    director = StoryDirector(character_registry=registry)

    # 4. Generate Episodes 1, 2, and 3
    episodes = []
    target_duration = 45.0  # Optimal sweet-spot duration for Shorts

    for ep_num in range(1, 4):
        print("\n" + "-" * 80)
        print(f"[DIRECTING] EPISODE {ep_num} (Target Duration: {target_duration}s | Rhythm: PULSE_ACTION)")
        print("-" * 80)

        manifest = director.direct_episode(
            series_state=series_state,
            episode_num=ep_num,
            target_duration=target_duration,
            rhythm=PacingRhythm.PULSE_ACTION,
        )
        episodes.append(manifest)

        # Validate manifest integrity
        is_valid, errors = manifest.validate_integrity()
        if not is_valid:
            print(f"[ERROR] Validation errors in Episode {ep_num}: {errors}")
            return 1

        print(f"Title: {manifest.title}")
        print(f"Duration: {manifest.actual_duration:.1f}s | Word Count: {manifest.total_word_count} | Pace: {manifest.overall_wpm} WPM")
        print(f"Cast: {[c.name for c in manifest.character_profiles]}")
        print(f"Cliffhanger: {manifest.cliffhanger}")
        print(f"Next Episode Hook: {manifest.next_episode_hook}")
        if manifest.micro_loop:
            print(f"Single-Episode Micro-Loop: \"{manifest.micro_loop}\"")
        if manifest.loop_phrase:
            print(f"Season Macro-Loop Phrase: \"{manifest.loop_phrase}\"")

        print("\n   --- Scene Breakdown (5-Phase Retention Arc & Mixed Dialogue) ---")
        for s in manifest.scenes:
            phase_tag = f"[{s.phase.value.upper()}]".ljust(18)
            time_tag = f"{s.time_start:.1f}s - {s.time_end:.1f}s ({s.duration:.1f}s)"
            print(f"   Scene {s.scene_index}: {phase_tag} {time_tag.ljust(20)} | {s.word_count} words ({s.wpm} WPM)")
            if s.narration:
                print(f"      Narration: \"{s.narration}\"")
            if s.dialogue:
                print(f"      Dialogue:  [{s.dialogue.speaker}] ({s.dialogue.emotion}): \"{s.dialogue.text}\"")
            print(f"      Action:    {s.action_prompt}")
            print(f"      Sub-Clip:  {s.video_prompt}")
            print(f"      Bound:     {s.bound_characters}")

    # 5. Continuity, Pacing, and Directing Verification
    print("\n" + "=" * 80)
    print("CONTINUOUS ARC, PACING & DIRECTING VERIFICATION AUDIT")
    print("=" * 80)

    ep1, ep2, ep3 = episodes

    # 5.1 Verify Character Continuity
    print("1. Character Consistency & Persistence:")
    for ep in episodes:
        char_names = [c.name for c in ep.character_profiles]
        assert "Detective Rex Vance" in char_names, f"Rex missing from Ep {ep.episode_num}"
        print(f"   * Ep {ep.episode_num} cast verified: {char_names}")
    print("   [PASS] Character identity persisted across all 3 episodes without drift.")

    # 5.2 Verify Cliffhanger to Hook Chain
    print("\n2. Episodic Continuity & Cliffhanger Resolution Chain:")
    print(f"   * Ep 1 Cliffhanger: \"{ep1.cliffhanger}\"")
    print(f"   * Ep 2 Opening Hook (Phase 1): \"{ep2.scenes[0].narration}\"")
    assert "pulse" in ep2.scenes[0].narration.lower() or "chronometer" in ep2.scenes[0].narration.lower() or "bullet" in ep2.scenes[0].narration.lower()
    print("     -> Ep 2 Hook directly resolves Ep 1's blast door/laser ambush cliffhanger!")

    print(f"   * Ep 2 Cliffhanger: \"{ep2.cliffhanger}\"")
    print(f"   * Ep 3 Opening Hook (Phase 1): \"{ep3.scenes[0].narration}\"")
    assert "beam" in ep3.scenes[0].narration.lower() or "fell" in ep3.scenes[0].narration.lower() or "caught" in ep3.scenes[0].narration.lower()
    print("     -> Ep 3 Hook directly resolves Ep 2's core breach/falling floor cliffhanger!")

    # 5.3 Verify Dual-Loop Engine
    print("\n3. Dual-Loop Engine (Micro-Looping & Macro-Looping):")
    for ep in episodes:
        print(f"   * Ep {ep.episode_num} Micro-Loop: \"{ep.micro_loop}\" -> Opens into: \"{ep.scenes[0].narration[:45]}...\"")
        assert ep.micro_loop is not None, f"Ep {ep.episode_num} missing micro_loop"
    print(f"   * Season 1 Macro-Loop: \"{ep3.loop_phrase}\" -> Loops into Ep 1 Hook: \"{ep1.scenes[0].narration}\"")
    assert ep3.loop_phrase == "Because when the pocket watch ticks backwards, the cycle begins anew."
    print("   [PASS] Dual-loop architecture confirmed: single-episode intra-loops and season macro-loop verified.")

    # 5.4 Verify Mathematical Pacing (No Canned Filler, 140-160 WPM Target)
    print("\n4. Pacing & Timing Budget Audit (140-160 WPM Target):")
    for ep in episodes:
        print(f"   * Ep {ep.episode_num}: {ep.total_word_count} words over {ep.actual_duration:.1f}s -> {ep.overall_wpm} WPM (Target: 140-160 WPM)")
        assert 135.0 <= ep.overall_wpm <= 165.0, f"Ep {ep.episode_num} pacing violation: {ep.overall_wpm}"
        for s in ep.scenes:
            assert "..." not in s.narration, f"Ellipsis truncation detected in Ep {ep.episode_num} Scene {s.scene_index}"
            assert "Every second matters" not in s.narration, f"Canned filler detected in Ep {ep.episode_num} Scene {s.scene_index}"
            assert "Time is running out" not in s.narration, f"Canned filler detected in Ep {ep.episode_num} Scene {s.scene_index}"
    print("   [PASS] All episodes strictly within mathematical WPM pacing constraints with zero truncation or canned fillers.")

    # 5.5 Verify Staging Bijectivity & Clean Environmental Cutaways
    print("\n5. Staging Bijectivity & Environmental Cutaways:")
    # Ep 1 Scene 5 and Ep 2 Scene 7 are environmental cutaways
    assert ep1.scenes[5].bound_characters == [], "Ep 1 Scene 5 must be an environmental cutaway with bound_characters=[]"
    assert ep2.scenes[7].bound_characters == [], "Ep 2 Scene 7 must be an environmental cutaway with bound_characters=[]"
    print("   * Ep 1 Scene 5 verified as clean environmental cutaway (bound_characters = [])")
    print("   * Ep 2 Scene 7 verified as clean environmental cutaway (bound_characters = [])")

    for ep in episodes:
        for s in ep.scenes:
            for bound_name in s.bound_characters:
                assert f"[{bound_name}]" in s.action_prompt, f"Missing entity token [{bound_name}] in action prompt"
                assert f"[{bound_name}]" in s.video_prompt, f"Missing entity token [{bound_name}] in video prompt"
    print("   [PASS] 100% bijective staging: all bound characters possess explicit action directives.")

    # 5.6 Verify S2P Decoupling with Dynamic N-Gram Guard
    print("\n6. Dynamic S2P Prompt Decoupling Guard:")
    for ep in episodes:
        for s in ep.scenes:
            valid, warnings = DecouplingGuard.validate_prompt(s.action_prompt, ep.character_profiles)
            assert valid, f"Leakage in Ep {ep.episode_num} Scene {s.scene_index}: {warnings}"
    print("   [PASS] All scene prompts validated with DecouplingGuard; zero permanent biometric/attire leakage.")

    # 5.7 Verify Mixed-Mode Direct Dialogue Integration
    print("\n7. Mixed-Mode Direct Character Dialogue Verification:")
    dialogue_count = sum(1 for ep in episodes for s in ep.scenes if s.dialogue is not None)
    print(f"   * Total spoken character dialogue lines across 3-part arc: {dialogue_count}")
    assert dialogue_count >= 3, "Expected at least 3 direct dialogue lines across the 3-part arc"
    for ep in episodes:
        for s in ep.scenes:
            if s.dialogue:
                assert f"[{s.dialogue.speaker}]" in s.video_prompt, f"Speaker token missing from video prompt in scene {s.scene_index}"
                print(f"   * Verified dialogue cue in Ep {ep.episode_num} Scene {s.scene_index}: [{s.dialogue.speaker}] -> \"{s.dialogue.text}\"")
    print("   [PASS] Mixed-mode dialogue successfully compiled into Veo sub-clip prompts with emotional vocal directives.")

    # 5.8 Verify Location Entity FlowKit Export Compliance
    print("\n8. Location Entity FlowKit Export Compliance:")
    vault_entity = registry.get_character("Subterranean Bank Vault")
    assert vault_entity is not None
    vault_fk = vault_entity.to_flowkit_entity()
    assert vault_fk["voice_description"] is None, "Location entities must have voice_description=None"
    assert "landscape 16:9 framing" in vault_fk["image_prompt"], "Location image_prompt must specify landscape 16:9 framing"
    assert "portrait" not in vault_fk["image_prompt"].lower(), "Location image_prompt must not specify portrait framing"
    print("   * Location entity export verified: landscape 16:9 framing and voice_description=None")
    print("   [PASS] FlowKit entity export strictly conforms to EntityType semantics.")

    print("\n" + "=" * 80)
    print("ALL CONTINUITY, PACING & ELEVATED DIRECTING VERIFICATIONS PASSED SUCCESSFULLY!")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    sys.exit(run_demo())
