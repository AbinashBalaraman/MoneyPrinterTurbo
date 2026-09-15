"""Script to initialize Arthur & Rusty series and direct Episode 1 (max 10s per scene)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import (
    CharacterProfile,
    DialogueLine,
    EngagementPhase,
    EntityType,
    EpisodeManifest,
    SceneBeat,
)
from src.storage.ledger import EpisodicLedger
from src.render_client.adapter import FlowKitPayloadAdapter

def main():
    ledger = EpisodicLedger(db_path=str(ROOT / "continuity_ledger.db"))

    series_id = "farmer_and_rusty"
    title = "Arthur & Rusty: The Whispering Earth"
    genre = "Pastoral Fantasy / Adventure"
    logline = "A poor farmer and his loyal terrier discover an ancient glowing seed that could restore their parched farm—or awaken something slumbering deep beneath."

    # 1. Register series in SQLite ledger
    ledger.register_series(
        series_id=series_id,
        title=title,
        genre=genre,
        logline=logline,
        target_duration=45.0,
        pacing_rhythm="pulse_action",
    )

    # 2. Define Character Profiles
    arthur = CharacterProfile(
        character_id="char_arthur",
        name="Arthur",
        entity_type=EntityType.CHARACTER,
        visual_summary="Elderly impoverished farmer with kind crinkling eyes, sun-weathered wrinkles, short silver beard, patched blue denim dungarees, faded red flannel shirt, worn rustic straw hat, sturdy scuffed work boots",
        personality="Gentle, resilient, patient, deeply loyal to his companion",
        voice_profile="Elderly warm gravelly grandfather voice, gentle and rustic",
    )

    rusty = CharacterProfile(
        character_id="char_rusty",
        name="Rusty",
        entity_type=EntityType.CREATURE,
        visual_summary="Scruffy golden-brown terrier mix dog with one floppy ear, one perked ear, white fur patch on chest, big expressive golden-amber eyes, faded red bandanna tied neatly around neck",
        personality="Curious, hyper-alert, brave protector, loyal shadow",
        voice_profile="Expressive dog vocalizations, whines, barks, soft huffs",
    )

    farmstead = CharacterProfile(
        character_id="loc_farmstead",
        name="Dusty Creek Farm",
        entity_type=EntityType.LOCATION,
        visual_summary="Dry sun-baked farmstead with cracked arid earth, weathered wooden split-rail fence, rustic leaning barn, creaking vintage windmill against a blazing golden-hour sky",
        personality="Drought-stricken, desolate yet peaceful rustic pastoral landscape",
    )

    ledger.save_character(series_id, arthur)
    ledger.save_character(series_id, rusty)
    ledger.save_character(series_id, farmstead)

    # 3. Build Episode 1 Scene Beats (each scene strictly <= 10s, total = 45s)
    # Scene 1: 0.0s - 6.0s (6.0s duration) - Hook
    scene1 = SceneBeat(
        scene_index=0,
        time_start=0.0,
        time_end=6.0,
        phase=EngagementPhase.HOOK,
        narration="The well was bone dry, and Arthur had only one cup of water left.",
        action_prompt="Arthur stares down into an empty cracked stone well with a wooden bucket while Rusty suddenly sniffs the arid wind with perked ears.",
        video_prompt="0-3s: Low angle push-in as [Arthur] tips an empty wooden bucket over the stone well. 3-6s: [Rusty] abruptly snaps his head toward the dry field, sniffing intensely.",
        bound_characters=["Arthur", "Rusty"],
        camera_directive="Low angle dynamic push-in transitioning to a rapid snap focus",
        word_count=14,
        wpm=140.0,
    )

    # Scene 2: 6.0s - 13.0s (7.0s duration) - Rising Action
    scene2 = SceneBeat(
        scene_index=1,
        time_start=6.0,
        time_end=13.0,
        phase=EngagementPhase.RISING_TENSION,
        narration="Rusty suddenly darted into the barren field, tearing at the baked earth like his life depended on it.",
        action_prompt="Rusty frantically digs into the dry furrow with both paws, dirt flying into the air, as Arthur hurries across the cracked field.",
        video_prompt="0-3s: Rapid ground-level tracking shot following [Rusty] sprint across dry ground. 3-7s: [Rusty] vigorously claws into the soil as [Arthur] hobbles into frame.",
        bound_characters=["Rusty", "Arthur"],
        camera_directive="Ground-level tracking dolly following dog movement",
        word_count=17,
        wpm=145.7,
    )

    # Scene 3: 13.0s - 21.0s (8.0s duration) - The Discovery
    scene3 = SceneBeat(
        scene_index=2,
        time_start=13.0,
        time_end=21.0,
        phase=EngagementPhase.COMPLICATION,
        narration="Deep beneath the parched dust lay a crystalline seed, pulsing with a faint emerald glow.",
        dialogue=DialogueLine(
            speaker="Arthur",
            text="What did you find there, boy?",
            emotion="awed gentle whisper",
        ),
        action_prompt="Arthur kneels beside Rusty, carefully brushing aside dirt clods to reveal an ancient glowing seed pod radiating soft green light.",
        video_prompt="0-4s: Close-up over-the-shoulder shot as [Arthur] gently wipes dry soil away. 4-8s: The exposed seed pulses with emerald light, reflecting in [Rusty]'s wide eyes.",
        bound_characters=["Arthur", "Rusty"],
        camera_directive="Over-the-shoulder slow descending crane shot to macro close-up",
        word_count=21,
        wpm=157.5,
    )

    # Scene 4: 21.0s - 29.0s (8.0s duration) - The Choice / Sacrifice
    scene4 = SceneBeat(
        scene_index=3,
        time_start=21.0,
        time_end=29.0,
        phase=EngagementPhase.COMPLICATION,
        narration="With their pantry empty and crops withered, Arthur uncapped his last canteen and made a desperate gamble.",
        action_prompt="Arthur holds his dented tin canteen over the glowing seed, tilting it slowly as the final drops of crystal water fall.",
        video_prompt="0-4s: Medium shot of [Arthur] unthreading the metal canteen cap with trembling hands. 4-8s: Slow motion macro shot of water droplets splashing onto the luminous seed.",
        bound_characters=["Arthur"],
        camera_directive="Cinematic slow dolly-in with shallow depth of field",
        word_count=18,
        wpm=135.0,
    )

    # Scene 5: 29.0s - 37.0s (8.0s duration) - The Miracle Eruption (Climax)
    scene5 = SceneBeat(
        scene_index=4,
        time_start=29.0,
        time_end=37.0,
        phase=EngagementPhase.CLIMAX_TWIST,
        narration="The soil exploded. Massive jade vines shot skyward, unfurling radiant golden blossoms in seconds!",
        action_prompt="Vibrant green vines violently erupt from the ground, spiraling upwards toward the sky as Arthur and Rusty shield their eyes in amazement.",
        video_prompt="0-4s: Wide dynamic low-angle crane ascending rapidly as massive emerald vines surge from the earth. 4-8s: Golden blossoms burst open overhead, showering luminescent pollen.",
        bound_characters=["Arthur", "Rusty"],
        camera_directive="Rapid ascending vertical crane tracking vine growth",
        word_count=15,
        wpm=112.5,
    )

    # Scene 6: 37.0s - 45.0s (8.0s duration) - Cliffhanger / Loop
    scene6 = SceneBeat(
        scene_index=5,
        time_start=37.0,
        time_end=45.0,
        phase=EngagementPhase.CLIFFHANGER_LOOP,
        narration="Before Arthur could celebrate, the earth trembled—and a deep chasm cracked open beneath the roots.",
        action_prompt="The ground fractures open with an ominous subterranean glow while Rusty steps in front of Arthur, growling fiercely into the abyss.",
        video_prompt="0-4s: Ground camera shakes as a glowing fissure rips through the soil. 4-8s: [Rusty] bares his teeth defensively in front of [Arthur] as strange blue vapor rises from below.",
        bound_characters=["Rusty", "Arthur"],
        camera_directive="Dutch angle ground-level tilt with camera shake into black",
        word_count=16,
        wpm=120.0,
    )

    manifest = EpisodeManifest(
        series_id=series_id,
        episode_num=1,
        title="The Whispering Furrow",
        target_duration=45.0,
        actual_duration=45.0,
        scenes=[scene1, scene2, scene3, scene4, scene5, scene6],
        character_profiles=[arthur, rusty, farmstead],
        cliffhanger="The ground fractures open with a deep rumble, and blue subterranean vapor rises from the chasm as Rusty growls.",
        next_episode_hook="Will Arthur and Rusty escape the collapsing fissure before the guardian awakens?",
        micro_loop="Everyone in the county thought Arthur's farm was dead, but...",
        loop_phrase="Because when the last drop of water hit the seed, the ground came alive.",
        total_word_count=101,
        overall_wpm=134.7,
    )

    # 4. Save to JSON and SQLite Continuity Ledger
    ledger.save_episode_manifest(manifest)
    print(f"Episode 1 saved into SQLite continuity ledger: {manifest.title}")

    out_dir = ROOT / "output" / "manifests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "farmer_and_rusty_ep01.json"
    out_file.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    print(f"Manifest saved to: {out_file}")

    # 5. Validate with FlowKit adapter
    adapter = FlowKitPayloadAdapter()
    project_payload = adapter.to_project_payload(manifest, material="3d_pixar")
    print(f"FlowKit Project Payload generated: {project_payload.name} (Material: {project_payload.material})")
    print(f"Entities in payload: {[c.name for c in project_payload.characters]}")

    scene_pairs = adapter.to_scene_payloads(manifest, video_id="vid_test_123")
    print(f"FlowKit Scene Payloads generated: {len(scene_pairs)} scenes (all <= 10s):")
    for s_create, narr in scene_pairs:
        print(f"  Scene #{s_create.display_order}: {s_create.chain_type} | Characters: {s_create.character_names} | Action: {s_create.prompt[:60]}...")
        print(f"    Sub-clip Prompt: {s_create.video_prompt}")
        print(f"    Narration: \"{narr}\"")

if __name__ == "__main__":
    main()
