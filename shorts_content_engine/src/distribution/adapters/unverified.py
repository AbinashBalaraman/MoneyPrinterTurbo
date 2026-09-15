"""Shared behaviour for platform adapters that cannot confirm publication.

The three original browser adapters shared a specific defect: each drove a
platform's web UI just far enough to look plausible, closed the browser, and
returned ``success=True`` with a hand-written URL such as
``https://youtube.com/shorts/pending_upload`` or
``https://www.tiktok.com/@creator/video/pending``. None of them ever confirmed
that a video existed, and none of them could: the upload had not finished, and the
code read the video link *before* waiting for it.

That is worse than failing. A caller records the episode as published, never
retries it, and finds out weeks later that the channel is empty.

This module gives those adapters one honest behaviour instead:

- ``authenticate()`` returns False. A saved cookie file proves a file exists; it
  does not prove a session is still valid.
- ``publish()`` returns ``success=False`` with an explanation of what is actually
  required, and never invents a URL.
- ``check_status()`` returns ``UNKNOWN``, which the interface already documents as
  "we do not know" — distinct from ``LIVE``.

Adapters that *can* confirm a publication (see ``youtube_api.py``, which reads the
video id out of the API response) implement the real thing instead of inheriting
this.
"""

from __future__ import annotations

import logging
from typing import Optional

from src.distribution.adapters.base import BasePlatformAdapter
from src.distribution.models import PlatformType, PublishRequest, PublishResult

logger = logging.getLogger(__name__)


class UnverifiedBrowserAdapter(BasePlatformAdapter):
    """Fails closed, and says exactly why, when publication cannot be verified."""

    platform: PlatformType

    #: Human-readable platform name, used in messages.
    platform_label: str = "this platform"

    #: What the operator must actually do to publish here for real.
    requirement: str = "configure API credentials for this platform"

    def __init__(
        self,
        session_path: Optional[str] = None,
        headless: bool = True,
    ) -> None:
        self.session_path = session_path
        self.headless = headless

    def _explain(self) -> str:
        return (
            f"{self.platform_label} publishing is not available: the browser-automation "
            f"path cannot confirm that a video was actually published, so it refuses to "
            f"report success. To publish to {self.platform_label}, {self.requirement}. "
            "YouTube is supported today through YouTubeApiAdapter, which returns the "
            "real video id from the API response."
        )

    async def authenticate(self) -> bool:
        """Always False — a stored cookie is not evidence of a live session."""
        return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        logger.warning("%s publish refused: %s", self.platform_label, self._explain())
        return PublishResult(
            platform=self.platform,
            success=False,
            error=self._explain(),
            is_mock=False,
        )

    async def check_status(self, post_id: str) -> str:
        return "UNKNOWN"
