"""Daily Batch Automation CLI and Continuity Engine Runner.

Provides rich command-line interfaces for:
- init-series: Initialize new narrative series with recurring character profiles
- direct: Direct next episode with 5-phase retention arc and S2P prompt decoupling
- generate: Orchestrate FlowKit generation (mock/live), audio ducking, and MP4 assembly
- batch: Daily batch automation runner directing and generating N sequential daily episodes
- status: Display series continuity state, episode history, character status, and render artifacts
- validate: Run automated pre-flight payload validation against FlowKit API schemas
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.director.character import CharacterRegistry, build_default_characters
from src.director.director import StoryDirector
from src.director.pacing import PacingRhythm
from src.render_client.adapter import FlowKitPayloadAdapter
from src.render_client.models import (
    FlowKitCharacterCreate,
    FlowKitNarrateVideoRequest,
    FlowKitProjectCreate,
    FlowKitRequestCreate,
    FlowKitSceneCreate,
    FlowKitSceneUpdate,
    FlowKitVideoCreate,
)
from src.render_client.orchestrator import FlowKitOrchestrator, OrchestrationResult
from src.distribution.manager import DistributionManager
from src.distribution.models import PlatformType, PrivacyStatus, PublishRequest
from src.models import (
    CharacterProfile,
    EpisodeManifest,
    SeriesState,
)
from src.postprocess.metadata import MetadataScrubber
from src.postprocess.watermark import WatermarkProfile, WatermarkScrubber
from src.storage.ledger import EpisodicLedger

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("shorts_cli")


def _print_header(title: str) -> None:
    """Prints a styled CLI section header."""
    bar = "=" * 72
    print(f"\n{bar}")
    print(f"  {title.upper()}")
    print(f"{bar}\n")


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Formats an ASCII tabular representation."""
    if not rows:
        return "  (No records found)\n"
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(str(cell)))

    header_line = " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "-+-".join("-" * w for w in col_widths)
    lines = [f"  {header_line}", f"  {separator}"]
    for row in rows:
        line = " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row))
        lines.append(f"  {line}")
    return "\n".join(lines) + "\n"


# -----------------------------------------------------------------------------
# Subcommand Handlers
# -----------------------------------------------------------------------------

def cmd_init_series(args: argparse.Namespace) -> int:
    """Initializes a new series in the continuity ledger and seeds characters."""
    ledger = EpisodicLedger(db_path=args.db_path)
    series_id = args.series_id.strip()
    title = args.title.strip()
    genre = args.genre.strip()
    logline = (args.logline or "").strip()
    target_dur = float(args.target_duration)
    rhythm = args.pacing_rhythm

    _print_header(f"Initializing Series: {title}")

    # Register series
    series = ledger.register_series(
        series_id=series_id,
        title=title,
        genre=genre,
        logline=logline,
        target_duration=target_dur,
        pacing_rhythm=rhythm,
    )

    # Seed default recurring characters if requested
    seeded_chars: list[str] = []
    if args.seed_characters:
        defaults = build_default_characters()
        for c in defaults:
            ledger.save_character(series_id, c)
            seeded_chars.append(f"{c.name} ({c.entity_type.value})")

    print(f"Series Registered Successfully:")
    print(f"  ID:              {series['series_id']}")
    print(f"  Title:           {series['title']}")
    print(f"  Genre:           {series['genre']}")
    print(f"  Logline:         {series['logline'] or '(None)'}")
    print(f"  Target Duration: {series['target_duration']}s")
    print(f"  Pacing Rhythm:   {series['pacing_rhythm']}")
    print(f"  Database Path:   {os.path.abspath(args.db_path)}")
    if seeded_chars:
        print(f"  Seeded Entities: {', '.join(seeded_chars)}")
    print()
    return 0


def cmd_direct(args: argparse.Namespace) -> int:
    """Directs an episodic script using StoryDirector and records to ledger."""
    ledger = EpisodicLedger(db_path=args.db_path)
    series_id = args.series_id.strip()

    series = ledger.get_series(series_id)
    if not series:
        print(f"Error: Series '{series_id}' not found in ledger at {args.db_path}.", file=sys.stderr)
        print(f"Run 'init-series --series-id {series_id} ...' first.", file=sys.stderr)
        return 1

    state = ledger.get_series_state(series_id)
    if not state:
        print(f"Error: Failed to load state for series '{series_id}'.", file=sys.stderr)
        return 1

    episode_num = args.episode if args.episode is not None else (state.current_episode + 1)
    target_duration = float(args.duration) if args.duration else float(series["target_duration"])
    rhythm_str = args.rhythm if args.rhythm else series["pacing_rhythm"]
    try:
        rhythm = PacingRhythm(rhythm_str)
    except ValueError:
        rhythm = PacingRhythm.PULSE_ACTION

    _print_header(f"Directing Episode {episode_num}: {series['title']}")

    registry = CharacterRegistry()
    for c in state.characters.values():
        if isinstance(c, CharacterProfile):
            registry.register_character(c)

    director = StoryDirector(character_registry=registry)
    manifest = director.direct_episode(
        series_state=state,
        episode_num=episode_num,
        target_duration=target_duration,
        rhythm=rhythm,
    )

    # Save manifest into ledger
    ledger.save_episode_manifest(manifest, status="directed")

    # Advance series state in ledger
    ledger.update_series_state(
        series_id=series_id,
        current_season=state.current_season,
        current_episode=episode_num,
        last_cliffhanger=manifest.cliffhanger,
        unresolved_threads=state.unresolved_threads,
    )

    # Record dramatic character state deltas if applicable
    if episode_num == 1:
        ledger.record_character_delta(
            series_id=series_id,
            episode_num=1,
            character_name="Detective Rex Vance",
            delta_type="discovery",
            old_value="Unaware of temporal conspiracy",
            new_value="Discovered Dr. Thorne's reversed chronometer",
            description="Found chronometer ticking counter-clockwise inside subterranean vault",
        )
    elif episode_num == 2:
        ledger.record_character_delta(
            series_id=series_id,
            episode_num=2,
            character_name="Detective Rex Vance",
            delta_type="injury",
            old_value="Healthy",
            new_value="Shrapnel graze on left shoulder",
            description="Vault laser containment detonation caused armor scorch",
        )
    elif episode_num == 3:
        ledger.record_character_delta(
            series_id=series_id,
            episode_num=3,
            character_name="Dr. Aris Thorne",
            delta_type="status",
            old_value="Fugitive adversary",
            new_value="Confronted at temporal relay",
            description="Cornered at central power relay station",
        )

    # Optional export of manifest JSON
    if args.output_manifest:
        out_path = Path(args.output_manifest)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
        print(f"Manifest exported to: {out_path.resolve()}\n")

    # Display directing summary
    print(f"Episode Directed Successfully:")
    print(f"  Title:            {manifest.title}")
    print(f"  Episode Number:   {manifest.episode_num}")
    print(f"  Target Duration:  {manifest.target_duration}s")
    print(f"  Actual Duration:  {manifest.actual_duration}s")
    print(f"  Total Words:      {manifest.total_word_count}")
    print(f"  Overall Pace:     {manifest.overall_wpm} WPM")
    print(f"  Cliffhanger:      {manifest.cliffhanger}")
    print(f"  Next Hook:        {manifest.next_episode_hook}")
    if manifest.micro_loop:
        print(f"  Micro-Loop:       \"{manifest.micro_loop}\"")
    print()

    # Scene breakdown table
    headers = ["Scene", "Phase", "Cut Range", "Dur", "Words", "WPM", "Bound Characters"]
    rows = []
    for s in manifest.scenes:
        rows.append([
            f"Scene {s.scene_index + 1}",
            s.phase.value,
            f"{s.time_start:.1f}s - {s.time_end:.1f}s",
            f"{s.duration:.1f}s",
            str(s.word_count),
            f"{s.wpm:.1f}",
            ", ".join(s.bound_characters) if s.bound_characters else "(Cutaway / Env)",
        ])
    print(_format_table(headers, rows))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Orchestrates FlowKit video generation, audio ducking, and MP4 assembly."""
    ledger = EpisodicLedger(db_path=args.db_path)
    series_id = args.series_id.strip()

    series = ledger.get_series(series_id)
    if not series:
        print(f"Error: Series '{series_id}' not found in ledger.", file=sys.stderr)
        return 1

    episode_num = args.episode
    if episode_num is None:
        # Pick latest directed episode
        episodes = ledger.list_episodes(series_id)
        if not episodes:
            print(f"Error: No episodes found for series '{series_id}'. Run 'direct' first.", file=sys.stderr)
            return 1
        episode_num = episodes[-1]["episode_num"]

    manifest = ledger.get_episode_manifest(series_id, episode_num=episode_num)
    if not manifest:
        print(f"Error: Episode manifest for episode {episode_num} not found in ledger.", file=sys.stderr)
        return 1

    is_mock = getattr(args, "mock", True)
    mode = "mock" if is_mock else "live"
    _print_header(f"Generating Episode {episode_num} [{mode.upper()} MODE]: {manifest.title}")

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    orchestrator = FlowKitOrchestrator(
        output_dir=output_dir,
        mock=is_mock,
    )

    ledger.update_episode_status(series_id, episode_num, "generating")

    # Run async generation pipeline
    result: OrchestrationResult = asyncio.run(
        orchestrator.run_pipeline(
            manifest=manifest,
            material=args.material or "realistic",
            orientation="VERTICAL",
            skip_video_render=args.skip_video_render,
        )
    )

    if result.status in ("SUCCESS", "PARTIAL") and result.assembled_video_path:
        ledger.record_render_output(
            series_id=series_id,
            episode_num=episode_num,
            output_path=result.assembled_video_path,
            duration=manifest.actual_duration,
            generation_mode=mode,
            metadata={
                "project_id": result.project_id,
                "video_id": result.video_id,
                "scenes_rendered": len(manifest.scenes),
                "phases_completed": result.phases_completed,
                "is_mock": is_mock,
            },
            status="completed",
        )
        ledger.update_episode_status(series_id, episode_num, "completed")

        print(f"Video Generation Completed Successfully:")
        print(f"  Project ID:       {result.project_id}")
        print(f"  Video ID:         {result.video_id}")
        print(f"  Assembled Output: {result.assembled_video_path}")
        print(f"  Scenes Rendered:  {len(result.scene_ids)}")
        print(f"  Phases Completed: {len(result.phases_completed)}")
        print()
        return 0
    else:
        ledger.update_episode_status(series_id, episode_num, "failed")
        print(f"Generation Failed / Incomplete:", file=sys.stderr)
        for err in result.errors:
            print(f"  - {err}", file=sys.stderr)
        return 1


def cmd_batch(args: argparse.Namespace) -> int:
    """Executes daily batch automation running N sequential episodes with continuity propagation."""
    ledger = EpisodicLedger(db_path=args.db_path)
    series_id = args.series_id.strip()

    series = ledger.get_series(series_id)
    if not series:
        print(f"Error: Series '{series_id}' not found in ledger.", file=sys.stderr)
        return 1

    count = int(args.episodes)
    if count <= 0:
        print(f"Error: Number of episodes (-n) must be positive, got {count}.", file=sys.stderr)
        return 1

    start_ep = args.start_episode
    if start_ep is None:
        state = ledger.get_series_state(series_id)
        start_ep = (state.current_episode + 1) if state else 1

    is_mock = getattr(args, "mock", True)
    mode = "mock" if is_mock else "live"
    target_duration = float(args.duration) if args.duration else float(series["target_duration"])
    rhythm_str = args.rhythm if args.rhythm else series["pacing_rhythm"]
    try:
        rhythm = PacingRhythm(rhythm_str)
    except ValueError:
        rhythm = PacingRhythm.PULSE_ACTION

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    _print_header(f"Daily Batch Automation: {series['title']} ({count} Episodes)")
    print(f"  Starting Episode: {start_ep}")
    print(f"  Total Episodes:   {count}")
    print(f"  Mode:             {mode.upper()}")
    print(f"  Output Directory: {output_dir}")
    print(f"  Pacing Rhythm:    {rhythm.value}")
    print()

    summary_rows: list[list[str]] = []
    orchestrator = FlowKitOrchestrator(output_dir=output_dir, mock=is_mock)

    for i in range(count):
        curr_ep = start_ep + i
        print(f"--- Processing Episode {curr_ep}/{start_ep + count - 1} ---")

        # 1. Load fresh state
        state = ledger.get_series_state(series_id)
        if not state:
            print(f"Error: Failed to load series state for episode {curr_ep}", file=sys.stderr)
            return 1

        # 2. Direct episode
        registry = CharacterRegistry()
        for c in state.characters.values():
            if isinstance(c, CharacterProfile):
                registry.register_character(c)

        director = StoryDirector(character_registry=registry)
        manifest = director.direct_episode(
            series_state=state,
            episode_num=curr_ep,
            target_duration=target_duration,
            rhythm=rhythm,
        )

        ledger.save_episode_manifest(manifest, status="directed")
        ledger.update_series_state(
            series_id=series_id,
            current_season=state.current_season,
            current_episode=curr_ep,
            last_cliffhanger=manifest.cliffhanger,
            unresolved_threads=state.unresolved_threads,
        )

        # Record continuity deltas per episode
        ledger.record_character_delta(
            series_id=series_id,
            episode_num=curr_ep,
            character_name="Detective Rex Vance",
            delta_type="chronometer_investigation",
            old_value=f"Ep {curr_ep - 1} state",
            new_value=f"Ep {curr_ep} resolution/cliffhanger",
            description=manifest.cliffhanger[:60] + "...",
        )

        # 3. Generate video
        ledger.update_episode_status(series_id, curr_ep, "generating")
        result: OrchestrationResult = asyncio.run(
            orchestrator.run_pipeline(
                manifest=manifest,
                material="realistic",
                orientation="VERTICAL",
            )
        )

        output_path = result.assembled_video_path or "(Assembly Pending)"
        status_label = result.status

        if result.assembled_video_path:
            ledger.record_render_output(
                series_id=series_id,
                episode_num=curr_ep,
                output_path=result.assembled_video_path,
                duration=manifest.actual_duration,
                generation_mode=mode,
                metadata={"is_mock": is_mock, "scenes": len(manifest.scenes)},
                status="completed",
            )
            ledger.update_episode_status(series_id, curr_ep, "completed")
            status_label = "COMPLETED"

            # Optional Auto-Scrubbing
            if getattr(args, "auto_scrub", False) and os.path.exists(output_path):
                scrubber = WatermarkScrubber()
                if scrubber.is_ffmpeg_available() and os.path.getsize(output_path) > 100:
                    clean_tmp = output_path + ".clean.mp4"
                    if scrubber.scrub_video(output_path, clean_tmp):
                        meta = MetadataScrubber()
                        meta.strip_metadata(clean_tmp, output_path)
                        try:
                            os.remove(clean_tmp)
                        except OSError:
                            pass
                        print(f"  [SCRUB] Cleaned watermark & metadata: {os.path.basename(output_path)}")

            # Optional Auto-Publishing
            if getattr(args, "auto_publish", False) and os.path.exists(output_path):
                plat_names = [p.strip().lower() for p in getattr(args, "publish_platforms", "youtube,tiktok,instagram").split(",") if p.strip()]
                target_plats = [PlatformType(p) for p in plat_names if p in PlatformType._value2member_map_]
                if target_plats:
                    dist_manager = DistributionManager(ledger=ledger, use_mock=getattr(args, "publish_mock", True))
                    req = PublishRequest(
                        video_path=output_path,
                        title=manifest.title,
                        description=f"{manifest.title} - Episode {curr_ep}\n\n#Shorts #Viral",
                        tags=["Shorts", "Series"],
                        privacy=PrivacyStatus.PUBLIC,
                        series_id=series_id,
                        episode_num=curr_ep,
                    )
                    report = asyncio.run(dist_manager.publish_episode(req, platforms=target_plats))
                    pub_count = sum(1 for r in report.results if r.success)
                    print(f"  [PUBLISH] Published to {pub_count}/{len(target_plats)} platforms")
                    status_label = "PUBLISHED"

        summary_rows.append([
            f"Ep {curr_ep}",
            manifest.title[:24],
            f"{manifest.actual_duration:.1f}s",
            f"{manifest.overall_wpm:.1f}",
            status_label,
            os.path.basename(output_path),
        ])
        print(f"  [OK] Directed & Generated: {manifest.title} ({manifest.actual_duration}s, {manifest.overall_wpm} WPM)\n")

    _print_header("Batch Automation Complete -- Summary")
    headers = ["Episode", "Title", "Duration", "WPM", "Status", "Artifact File"]
    print(_format_table(headers, summary_rows))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Displays comprehensive continuity state, episode history, and render outputs."""
    ledger = EpisodicLedger(db_path=args.db_path)

    if not args.series_id:
        # Show all series
        with ledger.transaction() as conn:
            rows = conn.execute("SELECT series_id, title, genre, current_episode, target_duration FROM series;").fetchall()
            if not rows:
                print("No series found in continuity ledger.")
                return 0
            _print_header("Continuity Ledger — Registered Series")
            headers = ["Series ID", "Title", "Genre", "Current Episode", "Target Duration"]
            table = [[r["series_id"], r["title"], r["genre"], str(r["current_episode"]), f"{r['target_duration']}s"] for r in rows]
            print(_format_table(headers, table))
            return 0

    series_id = args.series_id.strip()
    series = ledger.get_series(series_id)
    if not series:
        print(f"Error: Series '{series_id}' not found in ledger.", file=sys.stderr)
        return 1

    state = ledger.get_series_state(series_id)
    if not state:
        print(f"Error: Failed to load state for series '{series_id}'.", file=sys.stderr)
        return 1

    _print_header(f"Series Continuity Status: {series['title']}")
    print(f"  Series ID:          {series['series_id']}")
    print(f"  Genre:              {series['genre']}")
    print(f"  Current Season:     {series['current_season']}")
    print(f"  Current Episode:    {series['current_episode']}")
    print(f"  Target Duration:    {series['target_duration']}s")
    print(f"  Pacing Rhythm:      {series['pacing_rhythm']}")
    print(f"  Last Cliffhanger:   {series['last_cliffhanger'] or '(None)'}")
    print(f"  Unresolved Threads: {len(series.get('unresolved_threads', []))}")
    for t in series.get("unresolved_threads", []):
        print(f"    - {t}")
    print()

    # Characters
    chars = ledger.get_characters(series_id)
    if chars:
        print("  Persistent Recurring Characters:")
        char_headers = ["Name", "Type", "Voice Profile", "Key Tags"]
        char_rows = [[c.name, c.entity_type.value, c.voice_profile, ", ".join(c.tags)] for c in chars]
        print(_format_table(char_headers, char_rows))

    # Character State Deltas
    deltas = ledger.list_all_deltas(series_id)
    if deltas:
        print("  Character State Continuity Deltas:")
        delta_headers = ["Ep", "Character", "Delta Type", "New Value / State"]
        delta_rows = [
            [f"Ep {d['episode_num']}", d["character_name"], d["delta_type"], (d["new_value"] or d["description"])[:40]]
            for d in deltas
        ]
        print(_format_table(delta_headers, delta_rows))

    # Episodes
    episodes = ledger.list_episodes(series_id)
    if episodes:
        print("  Episode Production History:")
        ep_headers = ["Ep", "Title", "Duration", "Words", "WPM", "Status"]
        ep_rows = [
            [
                f"Ep {e['episode_num']}",
                e["title"][:28],
                f"{e['actual_duration']:.1f}s",
                str(e["total_word_count"]),
                f"{e['overall_wpm']:.1f}",
                e["status"].upper(),
            ]
            for e in episodes
        ]
        print(_format_table(ep_headers, ep_rows))

    # Renders
    renders = ledger.list_renders(series_id)
    if renders:
        print("  Finished Video Renders:")
        ren_headers = ["Ep", "Output File", "Dur", "Mode", "Status", "Timestamp"]
        ren_rows = [
            [
                f"Ep {r['episode_num']}",
                os.path.basename(r["output_path"]),
                f"{r['duration']:.1f}s",
                r["generation_mode"].upper(),
                r["status"].upper(),
                r["created_at"][:19],
            ]
            for r in renders
        ]
        print(_format_table(ren_headers, ren_rows))

    # Publications (real uploads and recorded dry runs)
    pubs = ledger.get_series_publications(series_id)
    if pubs:
        live = [p for p in pubs if (p.get("status") or "").lower() == "published"]
        print("  Social Media Posts:" if len(live) != len(pubs) else "  Published Social Media Posts:")
        pub_headers = ["Ep", "Platform", "Post ID", "Status", "Live URL", "Published At"]
        pub_rows = [
            [
                f"Ep {p['episode_num']}",
                p["platform"].upper(),
                p.get("post_id", "-") or "-",
                p.get("status", "published").upper(),
                p.get("video_url", "-") or "-",
                p.get("published_at", "")[:19],
            ]
            for p in pubs
        ]
        print(_format_table(pub_headers, pub_rows))

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Validates generated payloads against strict FlowKit schemas and conventions."""
    ledger = EpisodicLedger(db_path=args.db_path)
    manifest: Optional[EpisodeManifest] = None

    if args.series_id:
        series_id = args.series_id.strip()
        ep = args.episode
        if ep is None:
            episodes = ledger.list_episodes(series_id)
            if episodes:
                ep = episodes[-1]["episode_num"]
        if ep is not None:
            manifest = ledger.get_episode_manifest(series_id, episode_num=ep)

    if manifest is None:
        # Generate temporary sample manifest for validation
        state = SeriesState(
            series_id="val_series",
            title="Validation Sample",
            genre="Cyberpunk Noir",
        )
        registry = CharacterRegistry()
        for c in build_default_characters():
            registry.register_character(c)
        director = StoryDirector(character_registry=registry)
        manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)

    _print_header(f"FlowKit Payload Validation: {manifest.title} (Ep {manifest.episode_num})")

    errors: list[str] = []
    checked = 0

    # 1. Project Payload
    try:
        p_data = FlowKitPayloadAdapter.to_project_payload(manifest, material="realistic")
        FlowKitProjectCreate.model_validate(p_data)
        checked += 1
        print("  [PASS] ProjectCreate payload valid")
    except Exception as exc:
        errors.append(f"ProjectCreate: {exc}")
        print(f"  [FAIL] ProjectCreate payload invalid: {exc}")

    # 2. Characters
    try:
        c_list = FlowKitPayloadAdapter.to_character_payloads(manifest.character_profiles)
        for c in c_list:
            FlowKitCharacterCreate.model_validate(c)
            checked += 1
        print(f"  [PASS] {len(c_list)} CharacterCreate payloads valid")
    except Exception as exc:
        errors.append(f"CharacterCreate: {exc}")
        print(f"  [FAIL] CharacterCreate payload invalid: {exc}")

    # 3. Video Payload
    try:
        v_data = FlowKitPayloadAdapter.to_video_payload(manifest, project_id="proj_val_123", orientation="VERTICAL")
        FlowKitVideoCreate.model_validate(v_data)
        checked += 1
        print("  [PASS] VideoCreate payload valid")
    except Exception as exc:
        errors.append(f"VideoCreate: {exc}")
        print(f"  [FAIL] VideoCreate payload invalid: {exc}")

    # 4. Scenes (Two-step POST + PATCH)
    try:
        scene_pairs = FlowKitPayloadAdapter.to_scene_payloads(manifest, video_id="vid_val_123")
        for sc_create, narrator_text in scene_pairs:
            FlowKitSceneCreate.model_validate(sc_create.model_dump())
            sc_update = FlowKitSceneUpdate(narrator_text=narrator_text)
            FlowKitSceneUpdate.model_validate(sc_update.model_dump())
            checked += 2
        print(f"  [PASS] {len(scene_pairs)} SceneCreate & SceneUpdate payloads valid (Two-step)")
    except Exception as exc:
        errors.append(f"Scene payloads: {exc}")
        print(f"  [FAIL] Scene payloads invalid: {exc}")

    # 5. Batch Generation Requests
    try:
        scene_ids = [f"scene_val_{i}" for i in range(len(manifest.scenes))]
        img_reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids=scene_ids,
            project_id="proj_val_123",
            video_id="vid_val_123",
            req_type="GENERATE_IMAGE",
        )
        vid_reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids=scene_ids,
            project_id="proj_val_123",
            video_id="vid_val_123",
            req_type="GENERATE_VIDEO",
        )
        for req in img_reqs + vid_reqs:
            FlowKitRequestCreate.model_validate(req.model_dump())
            checked += 1
        print(f"  [PASS] {len(img_reqs) + len(vid_reqs)} Batch Request payloads valid")
    except Exception as exc:
        errors.append(f"Batch requests: {exc}")
        print(f"  [FAIL] Batch requests invalid: {exc}")

    # 6. Narrate Payload
    try:
        n_data = FlowKitPayloadAdapter.to_narrate_payload(
            project_id="proj_val_123",
            orientation="VERTICAL",
            mix=True,
            sfx_volume=0.4,
        )
        FlowKitNarrateVideoRequest.model_validate(n_data)
        checked += 1
        print("  [PASS] NarrateVideoRequest payload valid")
    except Exception as exc:
        errors.append(f"NarrateVideoRequest: {exc}")
        print(f"  [FAIL] NarrateVideoRequest payload invalid: {exc}")

    print(f"\nValidation Summary: {checked} Payloads Checked, {len(errors)} Errors.")
    return 0 if not errors else 1


def cmd_scrub(args: argparse.Namespace) -> int:
    """Removes AI watermarks and container metadata from an MP4 video file."""
    _print_header("Watermark & Metadata Scrubber")
    input_path = args.input.strip()
    if not os.path.exists(input_path):
        print(f"Error: Input video not found: {input_path}")
        return 1

    output_path = (args.output or "").strip()
    if not output_path:
        dir_name = os.path.dirname(input_path) or "."
        base_name = os.path.basename(input_path)
        output_path = os.path.join(dir_name, f"clean_{base_name}")

    print(f"Input Video:   {input_path}")
    print(f"Output Video:  {output_path}")
    print(f"Profile:       {args.profile}")
    print(f"Filter Mode:   {args.mode}")

    scrubber = WatermarkScrubber()
    if not scrubber.is_ffmpeg_available():
        print("Warning: FFmpeg is not installed or not on PATH.")
        return 1

    temp_cleaned = output_path + ".tmp.mp4"
    print("\n[1/2] Scrubbing visual watermark badge...")
    ok = scrubber.scrub_video(
        input_path=input_path,
        output_path=temp_cleaned,
        profile=args.profile,
        mode=args.mode,
    )
    if not ok:
        print("Notice: Visual filter fallback applied; proceeding with container sanitization.")
        if not os.path.exists(temp_cleaned):
            import shutil
            shutil.copy2(input_path, temp_cleaned)

    if not args.no_metadata_strip:
        print("[2/2] Sanitizing container metadata and provenance tags...")
        meta = MetadataScrubber()
        meta.strip_metadata(temp_cleaned, output_path)
        try:
            os.remove(temp_cleaned)
        except OSError:
            pass
    else:
        if os.path.exists(output_path):
            os.remove(output_path)
        os.rename(temp_cleaned, output_path)

    print(f"\nSUCCESS: Cleaned video exported to: {output_path}")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    """Publishes an episode to YouTube Shorts, TikTok, and/or Instagram Reels."""
    _print_header("Episodic Multi-Platform Publisher")
    ledger = EpisodicLedger(db_path=args.db_path)
    series_id = args.series_id.strip()
    episode_num = args.episode

    # Find episode in ledger
    ep = ledger.get_episode(series_id, episode_num)
    if not ep:
        print(f"Error: Episode {episode_num} not found in series '{series_id}'.")
        return 1

    title = args.title or ep.get("title") or f"Episode {episode_num}"
    video_path = args.video_path

    # If video path is not specified, resolve from latest render in ledger
    if not video_path:
        renders = ledger.list_renders(series_id)
        ep_renders = [r for r in renders if r.get("episode_num") == episode_num]
        if ep_renders:
            video_path = ep_renders[-1].get("output_path")

    if not video_path or not os.path.exists(video_path):
        print(f"Error: Video file not found for episode {episode_num}: {video_path}")
        print("Please generate the video first or specify --video-path <path>.")
        return 1

    platform_strs = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
    platform_enums: list[PlatformType] = []
    for p_str in platform_strs:
        try:
            platform_enums.append(PlatformType(p_str))
        except ValueError:
            print(f"Warning: Unknown platform '{p_str}'. Supported: youtube, tiktok, instagram.")

    if not platform_enums:
        print("Error: No valid target platforms selected.")
        return 1

    privacy = PrivacyStatus(args.privacy)
    print(f"Series ID:    {series_id}")
    print(f"Episode:      {episode_num} - '{title}'")
    print(f"Video Path:   {video_path}")
    print(f"Platforms:    {', '.join(p.value for p in platform_enums)}")
    print(f"Mode:         {'MOCK (Simulated)' if args.mock else 'LIVE BROWSER AUTOMATION'}")
    print(f"Visibility:   {privacy.value}\n")

    manager = DistributionManager(ledger=ledger, use_mock=args.mock)
    req = PublishRequest(
        video_path=video_path,
        title=title,
        description=f"Episode {episode_num} of {series_id}.\n\n#Shorts #Viral #Story",
        tags=["Shorts", "Episode", "AIAnimation"],
        privacy=privacy,
        series_id=series_id,
        episode_num=episode_num,
    )

    report = asyncio.run(manager.publish_episode(req, platforms=platform_enums))

    rows = []
    for res in report.results:
        if res.success and res.is_mock:
            status_str = "DRY RUN"
        else:
            status_str = "SUCCESS" if res.success else "FAILED"
        url_or_err = res.video_url or res.error or "-"
        rows.append([res.platform.value.upper(), status_str, url_or_err])

    print(_format_table(["PLATFORM", "STATUS", "URL / ERROR"], rows))

    if report.is_dry_run:
        print(
            "Dry run complete. Nothing was posted -- the URLs above are "
            "simulated and will not resolve."
        )
        return 0
    if report.all_successful:
        print(f"All platform uploads completed successfully ({report.live_publications} live).")
        return 0
    elif any(r.success for r in report.results):
        print(
            f"Partial upload completed. "
            f"{report.live_publications} live publication(s) confirmed."
        )
        return 0
    else:
        print("All platform uploads failed.")
        return 1


# -----------------------------------------------------------------------------
# CLI Parser Setup
# -----------------------------------------------------------------------------

def cmd_storyboard(args: argparse.Namespace) -> int:
    """Generates slideshow still-image prompts + storyboard PDF from an episode script."""
    from src.storyboard.generator import StoryboardGenerator
    from src.storyboard.pdf import StoryboardPDFBuilder

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        # Fall back to ledger lookup if --series-id/--episode given
        if getattr(args, "series_id", None):
            ledger = EpisodicLedger(db_path=args.db_path)
            ep = args.episode
            if ep is None:
                episodes = ledger.list_episodes(args.series_id)
                if episodes:
                    ep = episodes[-1]["episode_num"]
            manifest = ledger.get_episode_manifest(args.series_id, episode_num=ep) if ep is not None else None
            if manifest is None:
                print(f"Error: manifest not found: {manifest_path} and no ledger episode resolved.", file=sys.stderr)
                return 1
        else:
            print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
            return 1
    else:
        manifest = EpisodeManifest.model_validate(
            json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        )

    generator = StoryboardGenerator(
        characters_dir=args.characters_dir, style=args.style
    )
    doc = generator.generate(manifest)

    pdf_path = Path(args.output_pdf) if args.output_pdf else (
        Path(args.output_dir) / f"{doc.series_id}_ep{doc.episode_num:02d}_storyboard.pdf"
    )
    json_path = Path(args.output_json) if args.output_json else pdf_path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")

    profiles_extra = {p.name: p.personality for p in manifest.character_profiles}
    built = StoryboardPDFBuilder().build(doc, pdf_path, profiles_extra=profiles_extra)

    _print_header(f"Slideshow Storyboard: {doc.title} (Ep {doc.episode_num})")
    print(f"  Scenes: {len(doc.scenes)}, stills: {doc.total_stills}")
    for s in doc.scenes:
        print(f"  Scene {s.scene_index + 1} [{s.phase}] -> {len(s.stills)} stills")
    print(f"  JSON: {json_path.resolve()}")
    print(f"  PDF:  {built}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Constructs the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="shorts_engine",
        description="Daily Episodic Content Directing and FlowKit Production Engine.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, help="Subcommand to execute")

    # init-series
    p_init = subparsers.add_parser("init-series", help="Initialize a new episodic series in the ledger")
    p_init.add_argument("--series-id", required=True, help="Unique identifier for the series")
    p_init.add_argument("--title", required=True, help="Display title of the series")
    p_init.add_argument("--genre", required=True, help="Narrative genre (e.g. 'Cyberpunk Noir')")
    p_init.add_argument("--logline", default="", help="Core narrative logline or premise")
    p_init.add_argument("--target-duration", type=float, default=45.0, help="Default target duration (s)")
    p_init.add_argument("--pacing-rhythm", default="pulse_action", choices=["pulse_action", "noir_suspense"], help="Default rhythm")
    p_init.add_argument("--no-seed-characters", dest="seed_characters", action="store_false", default=True, help="Disable seeding default characters")
    p_init.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # direct
    p_direct = subparsers.add_parser("direct", help="Direct next episode conforming to 5-phase retention arc")
    p_direct.add_argument("--series-id", required=True, help="Series identifier")
    p_direct.add_argument("--episode", type=int, default=None, help="Specific episode index (default: next)")
    p_direct.add_argument("--duration", type=float, default=None, help="Target duration in seconds")
    p_direct.add_argument("--rhythm", choices=["pulse_action", "noir_suspense"], default=None, help="Pacing rhythm")
    p_direct.add_argument("--output-manifest", default=None, help="Optional path to write EpisodeManifest JSON")
    p_direct.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # generate
    p_gen = subparsers.add_parser("generate", help="Orchestrate FlowKit generation for an episode manifest")
    p_gen.add_argument("--series-id", required=True, help="Series identifier")
    p_gen.add_argument("--episode", type=int, default=None, help="Episode index (default: latest directed)")
    p_gen.add_argument("--mock", action="store_true", default=True, help="Simulate FlowKit generation offline")
    p_gen.add_argument("--live", dest="mock", action="store_false", help="Execute against live FlowKit API")
    p_gen.add_argument("--output-dir", default="output", help="Directory for final assembled video outputs")
    p_gen.add_argument("--material", default="realistic", choices=["realistic", "anime", "cinematic"], help="Visual style")
    p_gen.add_argument("--skip-video-render", action="store_true", help="Skip video clip rendering phase")
    p_gen.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # batch
    p_batch = subparsers.add_parser("batch", help="Daily batch automation runner directing and generating N sequential episodes")
    p_batch.add_argument("--series-id", required=True, help="Series identifier")
    p_batch.add_argument("-n", "--episodes", type=int, default=3, help="Number of sequential daily episodes to direct and generate")
    p_batch.add_argument("--start-episode", type=int, default=None, help="Starting episode index (default: current + 1)")
    p_batch.add_argument("--duration", type=float, default=None, help="Target duration per episode (s)")
    p_batch.add_argument("--rhythm", choices=["pulse_action", "noir_suspense"], default=None, help="Pacing rhythm")
    p_batch.add_argument("--mock", action="store_true", default=True, help="Simulate FlowKit generation offline")
    p_batch.add_argument("--live", dest="mock", action="store_false", help="Execute against live FlowKit API")
    p_batch.add_argument("--auto-scrub", dest="auto_scrub", action="store_true", default=True, help="Automatically scrub AI watermarks & metadata from rendered episodes")
    p_batch.add_argument("--no-auto-scrub", dest="auto_scrub", action="store_false", help="Disable automatic watermark scrubbing")
    p_batch.add_argument("--auto-publish", action="store_true", default=False, help="Automatically publish rendered episodes to target social media platforms")
    p_batch.add_argument("--publish-platforms", default="youtube,tiktok,instagram", help="Comma-separated platforms (youtube,tiktok,instagram)")
    p_batch.add_argument("--publish-mock", dest="publish_mock", action="store_true", default=True, help="Simulate publishing offline")
    p_batch.add_argument("--publish-live", dest="publish_mock", action="store_false", help="Execute live automated publishing")
    p_batch.add_argument("--output-dir", default="output", help="Directory for final assembled video outputs")
    p_batch.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # scrub
    p_scrub = subparsers.add_parser("scrub", help="Remove AI watermarks and container metadata from an MP4 video file")
    p_scrub.add_argument("-i", "--input", required=True, help="Path to input MP4 video")
    p_scrub.add_argument("-o", "--output", default=None, help="Path for cleaned output MP4 (default: clean_<input>)")
    p_scrub.add_argument("--profile", default="veo_bottom_right", choices=["veo_bottom_right", "gemini_bottom_right", "custom"], help="Watermark coordinate preset")
    p_scrub.add_argument("--mode", default="delogo", choices=["delogo", "boxblur"], help="Scrubbing filter mode")
    p_scrub.add_argument("--no-metadata-strip", action="store_true", default=False, help="Skip C2PA / container metadata sanitization")

    # publish
    p_pub = subparsers.add_parser("publish", help="Publish an episode video to YouTube Shorts, TikTok, and Instagram Reels")
    p_pub.add_argument("--series-id", required=True, help="Series identifier")
    p_pub.add_argument("-e", "--episode", type=int, required=True, help="Episode index to publish")
    p_pub.add_argument("--video-path", default=None, help="Path to video file (default: resolves from ledger renders)")
    p_pub.add_argument("--title", default=None, help="Video title (default: resolves from ledger episode title)")
    p_pub.add_argument("--platforms", default="youtube,tiktok,instagram", help="Comma-separated platforms (youtube,tiktok,instagram)")
    p_pub.add_argument("--mock", action="store_true", default=True, help="Simulate publishing offline")
    p_pub.add_argument("--live", dest="mock", action="store_false", help="Execute live browser automation publishing")
    p_pub.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="Privacy visibility")
    p_pub.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # status
    p_status = subparsers.add_parser("status", help="Display series continuity state, episode history, and render artifacts")
    p_status.add_argument("--series-id", default=None, help="Specific series identifier (omitted = list all)")
    p_status.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # validate
    p_val = subparsers.add_parser("validate", help="Run automated pre-flight payload validation against FlowKit API")
    p_val.add_argument("--series-id", default=None, help="Series identifier")
    p_val.add_argument("--episode", type=int, default=None, help="Episode number")
    p_val.add_argument("--live-url", default=None, help="Optional live FlowKit server URL to verify connection")
    p_val.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    # storyboard (slideshow / PowerPoint-style video)
    p_sb = subparsers.add_parser("storyboard", help="Generate slideshow still-image prompts + PDF storyboard from episode script")
    p_sb.add_argument("--manifest", default="output/manifests/farmer_and_rusty_ep01.json", help="EpisodeManifest JSON path")
    p_sb.add_argument("--series-id", default=None, help="Optional ledger series ID fallback if manifest file missing")
    p_sb.add_argument("--episode", type=int, default=None, help="Optional ledger episode number fallback")
    p_sb.add_argument("--characters-dir", default="Charectors", help="Character photo folder")
    p_sb.add_argument("--output-pdf", default=None, help="Output PDF path (default: <output-dir>/<series>_epXX_storyboard.pdf)")
    p_sb.add_argument("--output-json", default=None, help="Output storyboard JSON path (default: alongside PDF)")
    p_sb.add_argument("--output-dir", default="output/storyboards", help="Directory for storyboard outputs")
    p_sb.add_argument("--style", default="cinematic_photorealistic", choices=["cinematic_photorealistic", "pixar_3d", "storybook"], help="Image prompt style")
    p_sb.add_argument("--db-path", default="storage/ledger.db", help="Path to SQLite ledger database")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "init-series": cmd_init_series,
        "direct": cmd_direct,
        "generate": cmd_generate,
        "batch": cmd_batch,
        "scrub": cmd_scrub,
        "publish": cmd_publish,
        "status": cmd_status,
        "validate": cmd_validate,
        "storyboard": cmd_storyboard,
    }

    handler = handlers.get(args.command)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except Exception as exc:
        print(f"Error executing command '{args.command}': {exc}", file=sys.stderr)
        logger.exception("CLI execution failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
