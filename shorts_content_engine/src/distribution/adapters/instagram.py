"""Instagram Reels publishing adapter.

Publishing Reels programmatically requires the Instagram Graph API, which needs a
Business or Creator account linked to a Facebook Page plus an approved app. There
is no supported unapproved route.

The previous implementation drove the Instagram web uploader through a saved
browser session, clicked "Share", slept for five seconds, and returned
``success=True`` with ``https://www.instagram.com/reels/pending`` — a URL that does
not exist. A five-second sleep is not evidence that a Reel was published.

Rather than ship browser automation that cannot be verified, this adapter fails
closed with an explanation. See :mod:`src.distribution.adapters.unverified` for
the reasoning.
"""

from __future__ import annotations

from src.distribution.adapters.unverified import UnverifiedBrowserAdapter
from src.distribution.models import PlatformType


class InstagramReelsAdapter(UnverifiedBrowserAdapter):
    """Fails closed until Instagram Graph API access is configured."""

    platform = PlatformType.INSTAGRAM
    platform_label = "Instagram Reels"

    requirement = (
        "convert the account to Business or Creator, link it to a Facebook Page, "
        "and supply an Instagram Graph API access token"
    )
