"""TikTok publishing adapter.

Publishing to TikTok programmatically requires the TikTok Content Posting API,
which needs an approved developer app. There is no supported way to post from an
unapproved client.

The previous implementation drove the TikTok Creator Center through a saved
browser session, clicked "Post", closed the browser immediately, and returned
``success=True`` with ``https://www.tiktok.com/@creator/video/pending`` — a URL
that does not exist. It never waited for the upload to finish and never confirmed
the post.

Rather than ship browser automation that cannot be verified, this adapter fails
closed with an explanation. See :mod:`src.distribution.adapters.unverified` for
the reasoning.
"""

from __future__ import annotations

from src.distribution.adapters.unverified import UnverifiedBrowserAdapter
from src.distribution.models import PlatformType


class TikTokAdapter(UnverifiedBrowserAdapter):
    """Fails closed until TikTok API access is configured."""

    platform = PlatformType.TIKTOK
    platform_label = "TikTok"

    requirement = (
        "register an app with the TikTok for Developers Content Posting API, "
        "complete the audit, and supply the resulting access token"
    )
