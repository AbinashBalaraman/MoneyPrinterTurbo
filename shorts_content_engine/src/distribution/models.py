"""Data models for multi-platform video publishing and distribution."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PlatformType(str, Enum):
    """Target social media platform for vertical video distribution."""
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"


class PrivacyStatus(str, Enum):
    """Publishing privacy visibility."""
    PUBLIC = "public"
    UNLISTED = "unlisted"
    PRIVATE = "private"


class PublishRequest(BaseModel):
    """Encapsulates video metadata and targets for publishing."""
    video_path: str
    title: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    privacy: PrivacyStatus = PrivacyStatus.PUBLIC
    series_id: Optional[str] = None
    episode_num: Optional[int] = None
    #: The FlowKit video this episode corresponds to, so publish outcomes can be
    #: reported back to FlowKit's dashboard. Optional: publishing works without
    #: it, the dashboard simply will not show the result.
    flowkit_video_id: Optional[str] = None
    schedule_time: Optional[datetime] = None
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class PublishResult(BaseModel):
    """Represents the outcome of a single platform upload operation."""
    platform: PlatformType
    success: bool
    post_id: Optional[str] = None
    video_url: Optional[str] = None
    error: Optional[str] = None
    published_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    is_mock: bool = False


class BatchPublishReport(BaseModel):
    """Aggregated report across multiple target platforms."""
    series_id: str
    episode_num: int
    results: list[PublishResult] = Field(default_factory=list)

    @property
    def all_successful(self) -> bool:
        """Returns True if all attempted platform uploads succeeded.

        Note this says nothing about whether anything was actually posted -- a
        dry run reports success. Use :attr:`live_publications` for that.
        """
        return bool(self.results and all(r.success for r in self.results))

    @property
    def confirmed_results(self) -> list[PublishResult]:
        """Results backed by a real platform acknowledgement (never mocks)."""
        return [r for r in self.results if r.success and not r.is_mock]

    @property
    def live_publications(self) -> int:
        """Count of uploads a real platform actually accepted."""
        return len(self.confirmed_results)

    @property
    def is_dry_run(self) -> bool:
        """True when every successful result was simulated, i.e. nothing posted."""
        successful = [r for r in self.results if r.success]
        return bool(successful) and all(r.is_mock for r in successful)

    @property
    def platform_urls(self) -> dict[str, str]:
        """Map of platform name to *live* video URL for confirmed posts.

        Mock results are excluded: their URLs are fabricated, and returning them
        here would present a URL that resolves nowhere as a published video.
        """
        return {
            r.platform.value: r.video_url
            for r in self.results
            if r.success and r.video_url and not r.is_mock
        }
