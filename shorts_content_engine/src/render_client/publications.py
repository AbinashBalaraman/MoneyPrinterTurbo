"""Report publish outcomes back to FlowKit so the dashboard can display them.

FlowKit's dashboard cannot publish — uploading belongs here, in the directing
engine, which is headless by design. So after each platform attempt we POST the
outcome to FlowKit and the dashboard renders it from there. That keeps one UI,
one WebSocket and one log bus instead of a second backend for the browser.

Two rules this module exists to hold:

1. **A simulated upload is never reported as a publication.** ``is_mock`` is
   forwarded verbatim and the fabricated URL a mock carries is *dropped* — the
   whole point is that a dry run must not look like a post.

2. **Reporting never breaks publishing.** The video is already uploaded by the
   time we report; if FlowKit is down, the upload still succeeded. Failures are
   logged and swallowed, never raised into the publish path.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from src.distribution.models import PublishResult

logger = logging.getLogger(__name__)

DEFAULT_FLOWKIT_URL = "http://127.0.0.1:8100/api"


def to_flowkit_payload(result: PublishResult) -> dict:
    """Translate a :class:`PublishResult` into FlowKit's publication payload.

    Kept as a standalone function so the honesty rules are testable without a
    network or a running FlowKit.
    """
    if result.is_mock:
        # A mock's url and post_id are fabricated. Forwarding either would put a
        # URL that does not exist in front of a user.
        status = "dry_run" if result.success else "failed"
        payload: dict = {
            "platform": result.platform.value,
            "status": status,
            "is_mock": result.success,  # a failed mock never reached the platform
        }
        if not result.success:
            payload["error_message"] = result.error or "simulated upload failed"
        return payload

    if result.success:
        return {
            "platform": result.platform.value,
            "status": "published",
            "post_id": result.post_id,
            "video_url": result.video_url,
            "is_mock": False,
        }

    return {
        "platform": result.platform.value,
        "status": "failed",
        "error_message": result.error or "upload failed with no error reported",
        "is_mock": False,
    }


class FlowKitPublicationReporter:
    """Posts publish outcomes to FlowKit's ``/videos/{id}/publications``."""

    def __init__(
        self,
        base_url: str = DEFAULT_FLOWKIT_URL,
        timeout: float = 10.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._external_client = client is not None
        # trust_env=False: FlowKit runs on localhost, so it must never be routed
        # through an ambient HTTP_PROXY. When one is configured, httpx sends the
        # absolute URL in the request line and the server 404s on the mangled
        # path — an obscure failure caused by an unrelated environment variable.
        self.client = client or httpx.AsyncClient(timeout=timeout, trust_env=False)

    async def aclose(self) -> None:
        if not self._external_client and not self.client.is_closed:
            await self.client.aclose()

    async def report(self, video_id: Optional[str], result: PublishResult) -> bool:
        """Report one outcome. Returns whether FlowKit accepted it.

        Never raises: a reporting failure must not fail the upload that already
        succeeded.
        """
        if not video_id:
            logger.warning(
                "No FlowKit video id for %s outcome; dashboard will not show it",
                result.platform.value,
            )
            return False

        try:
            response = await self.client.post(
                f"{self.base_url}/videos/{video_id}/publications",
                json=to_flowkit_payload(result),
            )
        except Exception as e:  # network, DNS, timeout — all non-fatal here
            logger.warning("Could not report %s outcome to FlowKit: %s", result.platform.value, e)
            return False

        if response.status_code >= 400:
            logger.warning(
                "FlowKit rejected the %s outcome (%s): %s",
                result.platform.value, response.status_code, response.text[:200],
            )
            return False

        if result.is_mock:
            logger.info("Reported dry-run outcome for %s (nothing was posted)", result.platform.value)
        else:
            logger.info("Reported %s outcome for %s to FlowKit", result.platform.value, video_id[:8])
        return True
