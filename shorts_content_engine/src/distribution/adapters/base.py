"""Base abstract class for social media platform publishing adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.distribution.models import PlatformType, PublishRequest, PublishResult


class BasePlatformAdapter(ABC):
    """Abstract publishing interface implemented by platform-specific uploaders."""

    platform: PlatformType

    @abstractmethod
    async def authenticate(self) -> bool:
        """Verifies session credentials, cookies, or API keys."""
        raise NotImplementedError

    @abstractmethod
    async def publish(self, request: PublishRequest) -> PublishResult:
        """Uploads and publishes a video clip to the destination platform."""
        raise NotImplementedError

    @abstractmethod
    async def check_status(self, post_id: str) -> str:
        """Queries the current status of a published video (e.g. PROCESSING, LIVE, REJECTED)."""
        raise NotImplementedError
