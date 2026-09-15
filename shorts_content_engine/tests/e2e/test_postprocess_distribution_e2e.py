"""End-to-end pipeline test for watermark scrubbing, metadata sanitization, and auto-distribution."""

import os
import pytest

from src.cli import main
from src.director.character import CharacterRegistry, build_default_characters
from src.director.director import StoryDirector
from src.distribution.manager import DistributionManager
from src.distribution.models import PlatformType, PublishRequest
from src.render_client.orchestrator import FlowKitOrchestrator
from src.models import EpisodeManifest, SeriesState
from src.storage.ledger import EpisodicLedger


@pytest.mark.asyncio
async def test_full_pipeline_with_scrub_and_distribution(tmp_path):
    """Verifies complete end-to-end flow:
    1. Direct narrative episode
    2. Render with FlowKit mock pipeline + auto-scrub (Phase 7)
    3. Publish to multi-platform distribution channels (YouTube, TikTok, Instagram)
    4. Verify ledger records and publication history
    """
    db_path = str(tmp_path / "e2e_ledger.db")
    output_dir = str(tmp_path / "e2e_output")
    ledger = EpisodicLedger(db_path=db_path)

    series_id = "e2e_arthur_rusty"
    ledger.register_series(series_id=series_id, title="Arthur and Rusty", genre="Pastoral Adventure")

    # 1. Direct Episode
    registry = CharacterRegistry()
    for c in build_default_characters():
        registry.register_character(c)
        ledger.save_character(series_id, c)

    director = StoryDirector(character_registry=registry)
    state = ledger.get_series_state(series_id)
    manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)
    ledger.save_episode_manifest(manifest)

    # 2. Render & Auto-Scrub
    orchestrator = FlowKitOrchestrator(output_dir=output_dir, mock=True, scrub_watermarks=True)
    res = await orchestrator.run_pipeline(manifest=manifest)

    assert res.status == "SUCCESS"
    assert "Phase 6: Narration & Assembly Complete (Simulated)" in res.phases_completed
    assert "Phase 7: Watermark & Metadata Scrubbed (Simulated)" in res.phases_completed
    assert res.assembled_video_path is not None
    assert os.path.exists(res.assembled_video_path)

    # 3. Record render in ledger
    ledger.record_render_output(
        series_id=series_id,
        episode_num=1,
        output_path=res.assembled_video_path,
        duration=manifest.actual_duration,
        generation_mode="mock",
    )

    # 4. Multi-Platform Distribution
    dist_manager = DistributionManager(ledger=ledger, use_mock=True, delay_between_platforms=0.0)
    pub_req = PublishRequest(
        video_path=res.assembled_video_path,
        title=manifest.title,
        description="Episode 1 of Arthur and Rusty",
        tags=["Shorts", "Dogs", "Adventure"],
        series_id=series_id,
        episode_num=1,
    )

    report = await dist_manager.publish_episode(
        request=pub_req,
        platforms=[PlatformType.YOUTUBE, PlatformType.TIKTOK, PlatformType.INSTAGRAM],
    )

    assert report.all_successful is True
    assert len(report.results) == 3
    # use_mock=True means nothing was actually posted; the report must say so.
    assert report.is_dry_run is True
    assert report.live_publications == 0

    # 5. Verify Ledger: the simulated pass is recorded, but never as a live post,
    # and it must not transition the episode to "published".
    ep_pubs = ledger.get_episode_publications(series_id, 1)
    assert len(ep_pubs) == 3
    platforms = {p["platform"] for p in ep_pubs}
    assert platforms == {"youtube", "tiktok", "instagram"}
    assert all(p["status"] == "dry_run" for p in ep_pubs)

    ep_record = ledger.get_episode(series_id, 1)
    assert ep_record["status"] != "published"


def test_cli_scrub_and_publish_commands(tmp_path):
    """Verifies that CLI commands 'scrub' and 'publish' run cleanly via main()."""
    db_path = str(tmp_path / "cli_test_ledger.db")
    video_path = str(tmp_path / "sample_video.mp4")
    clean_path = str(tmp_path / "clean_sample_video.mp4")

    # Create dummy video
    with open(video_path, "wb") as f:
        f.write(b"MOCK_VIDEO_DATA_FOR_TESTING")

    # 1. Test CLI scrub
    ret_scrub = main(["scrub", "--input", video_path, "--output", clean_path])
    assert ret_scrub == 0
    assert os.path.exists(clean_path)

    # 2. Setup ledger for CLI publish
    ledger = EpisodicLedger(db_path=db_path)
    ledger.register_series("cli_series", "CLI Test Series", "Drama")
    ledger.save_episode_manifest(
        EpisodeManifest(
            series_id="cli_series",
            episode_num=1,
            title="CLI Ep 1",
            target_duration=45.0,
            actual_duration=45.0,
            scenes=[],
            character_profiles=[],
            cliffhanger="",
            next_episode_hook="",
        )
    )
    ledger.record_render_output("cli_series", 1, clean_path, 45.0)

    # 3. Test CLI publish
    ret_pub = main([
        "publish",
        "--series-id", "cli_series",
        "--episode", "1",
        "--video-path", clean_path,
        "--platforms", "youtube,tiktok",
        "--mock",
        "--db-path", db_path,
    ])
    assert ret_pub == 0

    # 4. Verify status command shows publication
    ret_status = main(["status", "--series-id", "cli_series", "--db-path", db_path])
    assert ret_status == 0
