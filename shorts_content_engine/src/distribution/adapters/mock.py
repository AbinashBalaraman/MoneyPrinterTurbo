"""Mock platform adapter for offline testing, CI/CD, and simulated publishing."""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Optional

from src.distribution.adapters.base import BasePlatformAdapter
from src.distribution.models import PlatformType, PublishRequest, PublishResult


class MockPlatformAdapter(BasePlatformAdapter):
    """Simulates social media uploads without contacting remote platform APIs."""

    def __init__(
        self,
        platform: PlatformType = PlatformType.YOUTUBE,
        simulate_delay: float = 0.05,
        fail_next: bool = False,
    ) -> None:
        self.platform = platform
        self.simulate_delay = simulate_delay
        self.fail_next = fail_next
        self.upload_history: list[PublishRequest] = []

    async def authenticate(self) -> bool:
        """Simulates successful authentication."""
        return True

    async def publish(self, request: PublishRequest) -> PublishResult:
        """Simulates video upload and produces mock platform URLs."""
        self.upload_history.append(request)

        if self.simulate_delay > 0:
            await asyncio.sleep(self.simulate_delay)

        if self.fail_next:
            self.fail_next = False
            return PublishResult(
                platform=self.platform,
                success=False,
                error="Simulated network timeout during upload",
                is_mock=True,
            )

        if not os.path.exists(request.video_path):
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"Video file not found: {request.video_path}",
                is_mock=True,
            )

        post_id = f"mock_{uuid.uuid4().hex[:10]}"
        if self.platform == PlatformType.YOUTUBE:
            url = f"https://youtube.com/shorts/{post_id}"
        elif self.platform == PlatformType.TIKTOK:
            url = f"https://www.tiktok.com/@shorts_creator/video/{post_id}"
        elif self.platform == PlatformType.INSTAGRAM:
            url = f"https://www.instagram.com/reel/{post_id}"
        else:
            url = f"https://social.example.com/{self.platform.value}/{post_id}"

        return PublishResult(
            platform=self.platform,
            success=True,
            post_id=post_id,
            video_url=url,
            is_mock=True,
        )

    async def check_status(self, post_id: str) -> str:
        """Returns ``MOCK``, never a real-looking state.

        This used to return ``LIVE``, which is the same class of lie as the
        browser adapters: anything that treats the string as fact would conclude a
        video was publicly available. ``MOCK`` is greppable and cannot be confused
        for a real status.
        """
        return "MOCK"
