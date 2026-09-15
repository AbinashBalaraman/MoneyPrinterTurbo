"""Unit tests for multi-platform distribution and social media publishing."""

import asyncio
import json
import os
import pytest

from src.distribution.adapters.base import BasePlatformAdapter
from src.distribution.adapters.instagram import InstagramReelsAdapter
from src.distribution.adapters.mock import MockPlatformAdapter
from src.distribution.adapters.tiktok import TikTokAdapter
from src.distribution.adapters.youtube import YouTubeShortsAdapter
from src.distribution.manager import DistributionManager
from src.distribution.models import (
    BatchPublishReport,
    PlatformType,
    PrivacyStatus,
    PublishRequest,
    PublishResult,
)
from src.models import EpisodeManifest
from src.storage.ledger import EpisodicLedger


class _ConfirmedAdapter(BasePlatformAdapter):
    """A non-mock adapter that returns a real, confirmed publication.

    Used to prove the ledger path still works for genuine uploads after mock
    results were excluded from it.
    """

    platform = PlatformType.YOUTUBE

    async def authenticate(self) -> bool:
        return True

    async def publish(self, request: PublishRequest) -> PublishResult:
        return PublishResult(
            platform=self.platform,
            success=True,
            post_id="real_video_id",
            video_url="https://youtube.com/shorts/real_video_id",
            is_mock=False,
        )

    async def check_status(self, post_id: str) -> str:
        return "LIVE"


class TestDistributionModels:
    """Validates data structures and reporting properties."""

    def test_publish_request_creation(self):
        req = PublishRequest(
            video_path="sample.mp4",
            title="Episode 1 - The Awakening",
            tags=["Shorts", "Trending"],
            privacy=PrivacyStatus.PUBLIC,
            series_id="sci_fi_noir",
            episode_num=1,
        )
        assert req.video_path == "sample.mp4"
        assert req.title == "Episode 1 - The Awakening"
        assert req.privacy == PrivacyStatus.PUBLIC
        assert req.tags == ["Shorts", "Trending"]

    def test_batch_report_aggregates(self):
        res1 = PublishResult(
            platform=PlatformType.YOUTUBE,
            success=True,
            post_id="yt_123",
            video_url="https://youtube.com/shorts/yt_123",
        )
        res2 = PublishResult(
            platform=PlatformType.TIKTOK,
            success=False,
            error="API down",
        )
        report = BatchPublishReport(
            series_id="test_series",
            episode_num=1,
            results=[res1, res2],
        )
        assert report.all_successful is False
        assert "youtube" in report.platform_urls
        assert "tiktok" not in report.platform_urls


class TestMockPlatformAdapter:
    """Validates the simulated platform adapter behavior."""

    @pytest.mark.asyncio
    async def test_mock_publish_success(self, tmp_path):
        dummy_video = tmp_path / "test_ep.mp4"
        dummy_video.write_bytes(b"VIDEO_DATA")

        adapter = MockPlatformAdapter(PlatformType.YOUTUBE, simulate_delay=0.0)
        req = PublishRequest(video_path=str(dummy_video), title="Mock Episode")

        result = await adapter.publish(req)
        assert result.success is True
        assert result.platform == PlatformType.YOUTUBE
        assert "youtube.com/shorts/" in result.video_url
        assert result.is_mock is True

    @pytest.mark.asyncio
    async def test_mock_publish_missing_file(self):
        adapter = MockPlatformAdapter(PlatformType.TIKTOK, simulate_delay=0.0)
        req = PublishRequest(video_path="missing_file.mp4", title="Missing")
        result = await adapter.publish(req)
        assert result.success is False
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_mock_forced_failure(self, tmp_path):
        dummy_video = tmp_path / "test_ep.mp4"
        dummy_video.write_bytes(b"VIDEO_DATA")

        adapter = MockPlatformAdapter(PlatformType.INSTAGRAM, simulate_delay=0.0, fail_next=True)
        req = PublishRequest(video_path=str(dummy_video), title="Fail Ep")
        result = await adapter.publish(req)
        assert result.success is False
        assert "timeout" in result.error.lower()


class TestDistributionManager:
    """Validates multi-platform publishing coordination and ledger persistence."""

    def _ledger(self, tmp_path) -> EpisodicLedger:
        ledger = EpisodicLedger(db_path=str(tmp_path / "test_ledger.db"))
        ledger.register_series("series_test", "Test Series", "Adventure")
        ledger.save_episode_manifest(
            EpisodeManifest(
                series_id="series_test",
                episode_num=1,
                title="Episode 1",
                target_duration=45.0,
                actual_duration=45.0,
                scenes=[],
                character_profiles=[],
                cliffhanger="",
                next_episode_hook="",
            )
        )
        return ledger

    @pytest.mark.asyncio
    async def test_mock_success_is_recorded_as_dry_run_not_published(self, tmp_path):
        """A mock result carries a fabricated URL.

        Recording it as 'published' would make the ledger claim an episode is live
        when nothing was uploaded, and nothing would ever retry it. The mock is
        still recorded so a simulated pass is visible -- but under the
        unambiguous 'dry_run' status, and it must never transition the episode.
        """
        ledger = self._ledger(tmp_path)
        dummy_video = tmp_path / "render.mp4"
        dummy_video.write_bytes(b"TEST_RENDER_DATA")

        manager = DistributionManager(ledger=ledger, use_mock=True, delay_between_platforms=0.0)
        req = PublishRequest(
            video_path=str(dummy_video),
            title="Episode 1: Dawn",
            series_id="series_test",
            episode_num=1,
        )

        report = await manager.publish_episode(
            req,
            platforms=[PlatformType.YOUTUBE, PlatformType.TIKTOK, PlatformType.INSTAGRAM],
        )

        assert report.all_successful is True
        assert len(report.results) == 3
        assert all(r.is_mock for r in report.results)

        # Recorded, but never as "published".
        pubs = ledger.get_episode_publications("series_test", 1)
        assert len(pubs) == 3
        assert all(p["status"] == "dry_run" for p in pubs)
        assert all(json.loads(p["metadata"])["is_mock"] is True for p in pubs)

        ep = ledger.get_episode("series_test", 1)
        assert ep["status"] != "published"

    @pytest.mark.asyncio
    async def test_dry_run_urls_are_not_reported_as_live(self, tmp_path):
        """platform_urls promises live URLs, so it must exclude fabricated ones."""
        ledger = self._ledger(tmp_path)
        dummy_video = tmp_path / "render.mp4"
        dummy_video.write_bytes(b"TEST_RENDER_DATA")

        manager = DistributionManager(ledger=ledger, use_mock=True, delay_between_platforms=0.0)
        req = PublishRequest(
            video_path=str(dummy_video),
            title="Episode 1: Dawn",
            series_id="series_test",
            episode_num=1,
        )
        report = await manager.publish_episode(req, platforms=[PlatformType.YOUTUBE])

        assert report.results[0].video_url  # the mock did produce a URL
        assert report.platform_urls == {}   # but it is not a live URL
        assert report.is_dry_run is True
        assert report.live_publications == 0

    @pytest.mark.asyncio
    async def test_confirmed_publication_is_recorded(self, tmp_path):
        """A real, confirmed upload still flows through to the ledger."""
        ledger = self._ledger(tmp_path)
        dummy_video = tmp_path / "render.mp4"
        dummy_video.write_bytes(b"TEST_RENDER_DATA")

        manager = DistributionManager(ledger=ledger, use_mock=True, delay_between_platforms=0.0)
        manager.register_adapter(PlatformType.YOUTUBE, _ConfirmedAdapter())

        req = PublishRequest(
            video_path=str(dummy_video),
            title="Episode 1: Dawn",
            series_id="series_test",
            episode_num=1,
        )
        report = await manager.publish_episode(req, platforms=[PlatformType.YOUTUBE])

        assert report.all_successful is True
        pubs = ledger.get_episode_publications("series_test", 1)
        assert len(pubs) == 1
        assert pubs[0]["platform"] == "youtube"
        ep = ledger.get_episode("series_test", 1)
        assert ep["status"] == "published"


class TestLiveAdapterGuards:
    """Verifies that live adapters fail honestly rather than reporting fake success."""

    @pytest.mark.asyncio
    async def test_youtube_browser_adapter_refuses_to_publish(self, tmp_path):
        """It used to return success=True with a fabricated pending_upload URL."""
        dummy_video = tmp_path / "test.mp4"
        dummy_video.write_bytes(b"DATA")

        adapter = YouTubeShortsAdapter(session_path=str(tmp_path / "no_session.json"))
        req = PublishRequest(video_path=str(dummy_video), title="Test")
        res = await adapter.publish(req)
        assert res.success is False
        assert res.video_url is None
        assert "youtubeapiadapter" in res.error.lower()

    @pytest.mark.asyncio
    async def test_tiktok_missing_session(self, tmp_path):
        dummy_video = tmp_path / "test.mp4"
        dummy_video.write_bytes(b"DATA")

        adapter = TikTokAdapter(session_path=str(tmp_path / "no_tiktok.json"))
        req = PublishRequest(video_path=str(dummy_video), title="Test")
        res = await adapter.publish(req)
        assert res.success is False
        assert res.video_url is None

    @pytest.mark.asyncio
    async def test_instagram_missing_session(self, tmp_path):
        dummy_video = tmp_path / "test.mp4"
        dummy_video.write_bytes(b"DATA")

        adapter = InstagramReelsAdapter(session_path=str(tmp_path / "no_ig.json"))
        req = PublishRequest(video_path=str(dummy_video), title="Test")
        res = await adapter.publish(req)
        assert res.success is False
        assert res.video_url is None

    @pytest.mark.asyncio
    async def test_browser_adapters_never_authenticate(self, tmp_path):
        """A stored cookie file is not evidence of a live session."""
        session = tmp_path / "state.json"
        session.write_text("{}")
        for adapter in (
            YouTubeShortsAdapter(session_path=str(session)),
            TikTokAdapter(session_path=str(session)),
            InstagramReelsAdapter(session_path=str(session)),
        ):
            assert await adapter.authenticate() is False

