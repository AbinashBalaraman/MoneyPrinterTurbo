"""Deprecated browser-automation YouTube adapter.

Superseded by :mod:`src.distribution.adapters.youtube_api`, which uses the
official YouTube Data API v3 and returns the real video id.

This class is kept so existing imports keep working, but it no longer pretends to
publish. The previous implementation filled the title, closed the browser without
completing the upload wizard, and returned ``success=True`` with a fabricated
``https://youtube.com/shorts/pending_upload`` URL — a video that never existed.

It also described itself as bypassing the Data API's daily quota. That is a
terms-of-service problem, and it concentrates risk on the same Google account
that drives Flow generation, so a ban would take out publishing *and* asset
generation together.
"""

from __future__ import annotations

import logging

from src.distribution.adapters.unverified import UnverifiedBrowserAdapter
from src.distribution.models import PlatformType

logger = logging.getLogger(__name__)

DEPRECATION_MESSAGE = (
    "YouTubeShortsAdapter is deprecated and no longer publishes. It used to return "
    "success=True without uploading anything. Use YouTubeApiAdapter "
    "(src.distribution.adapters.youtube_api), which uploads through the official "
    "YouTube Data API v3 and returns the real video URL."
)


class YouTubeShortsAdapter(UnverifiedBrowserAdapter):
    """Retained for import compatibility only. Always fails, and says why."""

    platform = PlatformType.YOUTUBE
    platform_label = "YouTube (browser automation)"

    requirement = (
        "use YouTubeApiAdapter with YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / "
        "YOUTUBE_REFRESH_TOKEN set"
    )

    def __init__(self, *args, **kwargs) -> None:
        logger.warning(DEPRECATION_MESSAGE)
        super().__init__(*args, **kwargs)

    def _explain(self) -> str:
        return DEPRECATION_MESSAGE
