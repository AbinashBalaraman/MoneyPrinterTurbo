"""Distribution manager coordinating multi-platform publishing and ledger persistence."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional, Sequence

from src.distribution.adapters.base import BasePlatformAdapter
from src.distribution.adapters.instagram import InstagramReelsAdapter
from src.distribution.adapters.mock import MockPlatformAdapter
from src.distribution.adapters.tiktok import TikTokAdapter
from src.distribution.adapters.youtube_api import YouTubeApiAdapter
from src.distribution.models import (
    BatchPublishReport,
    PlatformType,
    PublishRequest,
    PublishResult,
)
from src.storage.ledger import EpisodicLedger

logger = logging.getLogger(__name__)


class DistributionManager:
    """Orchestrates video distribution across YouTube Shorts, TikTok, and Instagram Reels."""

    def __init__(
        self,
        ledger: Optional[EpisodicLedger] = None,
        use_mock: bool = False,
        delay_between_platforms: float = 2.0,
        reporter: Optional[object] = None,
    ) -> None:
        self.ledger = ledger
        self.use_mock = use_mock
        self.delay_between_platforms = delay_between_platforms
        # Optional: an object with ``async report(video_id, PublishResult)``.
        # Duck-typed rather than imported so this module stays free of a hard
        # dependency on the FlowKit bridge.
        self.reporter = reporter
        self._adapters: dict[PlatformType, BasePlatformAdapter] = {}

        if use_mock:
            self.register_adapter(PlatformType.YOUTUBE, MockPlatformAdapter(PlatformType.YOUTUBE))
            self.register_adapter(PlatformType.TIKTOK, MockPlatformAdapter(PlatformType.TIKTOK))
            self.register_adapter(PlatformType.INSTAGRAM, MockPlatformAdapter(PlatformType.INSTAGRAM))
        else:
            # YouTube uses the official Data API and returns a real video id.
            # TikTok and Instagram have no supported unapproved posting route, so
            # their adapters fail closed with an explanation rather than
            # reporting a success that never happened.
            self.register_adapter(PlatformType.YOUTUBE, YouTubeApiAdapter())
            self.register_adapter(PlatformType.TIKTOK, TikTokAdapter())
            self.register_adapter(PlatformType.INSTAGRAM, InstagramReelsAdapter())

    async def _report(self, request: PublishRequest, result: PublishResult) -> None:
        """Forward an outcome to the dashboard.

        Never raises: the upload has already happened by this point, so a
        reporting failure must not turn a successful publish into a failed one.
        """
        if not self.reporter:
            return
        try:
            await self.reporter.report(request.flowkit_video_id, result)
        except Exception as e:
            logger.warning("Could not report %s outcome: %s", result.platform.value, e)

    def register_adapter(self, platform: PlatformType, adapter: BasePlatformAdapter) -> None:
        """Registers a custom or mock platform adapter."""
        self._adapters[platform] = adapter

    def get_adapter(self, platform: PlatformType) -> Optional[BasePlatformAdapter]:
        """Retrieves registered adapter for platform."""
        return self._adapters.get(platform)

    async def publish_episode(
        self,
        request: PublishRequest,
        platforms: Optional[Sequence[PlatformType]] = None,
    ) -> BatchPublishReport:
        """Publishes an episode video to specified platforms with staggered delays and ledger recording.
        
        Args:
            request: Video file and metadata payload.
            platforms: List of target platforms. Defaults to all registered platforms.

        Returns:
            BatchPublishReport with individual platform outcomes.
        """
        target_platforms = list(platforms) if platforms else list(self._adapters.keys())
        series_id = request.series_id or "default_series"
        episode_num = request.episode_num or 1

        results: list[PublishResult] = []

        for idx, plat in enumerate(target_platforms):
            if idx > 0 and self.delay_between_platforms > 0:
                logger.debug("Staggering publication: waiting %.1fs before %s", self.delay_between_platforms, plat.value)
                await asyncio.sleep(self.delay_between_platforms)

            adapter = self._adapters.get(plat)
            if not adapter:
                logger.warning("No adapter registered for platform: %s", plat.value)
                results.append(
                    PublishResult(
                        platform=plat,
                        success=False,
                        error=f"No adapter registered for {plat.value}",
                    )
                )
                continue

            try:
                res = await adapter.publish(request)
                results.append(res)
                logger.info("Published to %s: success=%s url=%s", plat.value, res.success, res.video_url)

                # Report every outcome, including failures and dry runs, so the
                # dashboard shows the whole picture rather than only good news.
                await self._report(request, res)

                # A mock result carries a fabricated URL, so it must never be
                # written under the "published" status -- that would make the
                # ledger claim an episode is live when nothing was uploaded.
                # It is still recorded, as "dry_run", so a simulated pass is
                # visible in the ledger instead of silently vanishing. Any
                # consumer that filters on status == "published" correctly
                # ignores it.
                if self.ledger and res.success:
                    if res.is_mock:
                        self.ledger.record_publication(
                            series_id=series_id,
                            episode_num=episode_num,
                            platform=plat.value,
                            post_id=res.post_id,
                            video_url=res.video_url,
                            status="dry_run",
                            metadata=json.dumps(
                                {
                                    "is_mock": True,
                                    "note": "simulated upload; nothing was posted",
                                }
                            ),
                        )
                        logger.info(
                            "recorded dry-run publication for %s (not a live post)",
                            plat.value,
                        )
                    else:
                        self.ledger.record_publication(
                            series_id=series_id,
                            episode_num=episode_num,
                            platform=plat.value,
                            post_id=res.post_id,
                            video_url=res.video_url,
                            status="published",
                            metadata=json.dumps({"is_mock": False}),
                        )
            except Exception as exc:
                logger.exception("Error publishing to %s: %s", plat.value, exc)
                results.append(
                    PublishResult(
                        platform=plat,
                        success=False,
                        error=str(exc),
                    )
                )

        report = BatchPublishReport(
            series_id=series_id,
            episode_num=episode_num,
            results=results,
        )

        # Only a real, confirmed publication may transition the episode. A mock
        # success must not, for the same reason it is not written to the ledger.
        if self.ledger and any(r.success and not r.is_mock for r in results):
            try:
                self.ledger.update_episode_status(series_id, episode_num, "published")
            except Exception as exc:
                logger.warning("Failed to transition episode status to 'published': %s", exc)

        return report
