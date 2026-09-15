"""YouTube Shorts publishing via the official YouTube Data API v3.

Why this replaces the Playwright adapter
----------------------------------------
``youtube.py`` drives studio.youtube.com through a saved browser session and, in
practice, fills the title, closes the browser, and returns ``success=True`` with a
fabricated ``https://youtube.com/shorts/pending_upload`` URL. Nothing is ever
published, and a caller has no way to tell. The docstring also states it exists to
bypass the API quota, which is a terms-of-service problem as well as a fragility
problem.

This adapter uses the supported route: an OAuth2 refresh token mints an access
token, then a resumable upload posts the file. It returns the **real** video id
and URL that YouTube assigned, or a failure carrying the API's own message. It
cannot report success for a video that does not exist.

Quota, stated honestly
----------------------
``videos.insert`` costs 1600 of the 10,000 daily units, so roughly **6 uploads
per day** on the default quota. That is a real ceiling, not a bug. Exhausting it
produces a clear ``quotaExceeded`` message rather than a silent failure. Request a
quota increase if the schedule needs more.

Shorts
------
No special API flag exists. YouTube classifies a video as a Short from its aspect
ratio and duration, so a vertical 9:16 clip under three minutes qualifies on its
own. The returned ``youtube.com/shorts/<id>`` URL is just the canonical form.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

import httpx

from src.distribution.adapters.base import BasePlatformAdapter
from src.distribution.credentials import (
    AccessTokenProvider,
    MissingCredentials,
    YouTubeCredentials,
    auth_headers,
    describe_error,
)
from src.distribution.models import PlatformType, PublishRequest, PublishResult

logger = logging.getLogger(__name__)

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
SHORTS_URL_TEMPLATE = "https://youtube.com/shorts/{video_id}"

# YouTube's own hard limits. Exceeding any of these fails the upload at the very
# last step, after the bytes have been sent, so they are enforced up front.
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_TOTAL_LENGTH = 500
DEFAULT_CATEGORY_ID = "24"  # Entertainment; YouTube requires a category.

# Uploads are slow and a short clip still takes tens of seconds. Status checks
# are cheap, so they get a much tighter budget.
UPLOAD_TIMEOUT = 900.0
STATUS_TIMEOUT = 30.0


class YouTubeApiAdapter(BasePlatformAdapter):
    """Publishes vertical clips through the YouTube Data API v3."""

    platform = PlatformType.YOUTUBE

    def __init__(
        self,
        credentials: Optional[YouTubeCredentials] = None,
        token_provider: Optional[AccessTokenProvider] = None,
        category_id: str = DEFAULT_CATEGORY_ID,
        made_for_kids: bool = False,
        notify_subscribers: bool = True,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._credentials = credentials
        self.category_id = category_id
        self.made_for_kids = made_for_kids
        self.notify_subscribers = notify_subscribers
        self._client = client
        self._tokens = token_provider

    # -- credential plumbing -------------------------------------------------

    def _token_provider(self) -> AccessTokenProvider:
        if self._tokens is None:
            creds = self._credentials or YouTubeCredentials.from_env()
            self._tokens = AccessTokenProvider(creds, client=self._client)
        return self._tokens

    def _http(self, timeout: float) -> tuple[httpx.AsyncClient, bool]:
        """Return (client, owns_client)."""
        if self._client is not None:
            return self._client, False
        return httpx.AsyncClient(timeout=timeout), True

    async def authenticate(self) -> bool:
        """True when a token can actually be minted.

        Checking the presence of a cookie file, as the browser adapter did, only
        proves a file exists — it says nothing about whether the credential still
        works. Minting a token is the real test.
        """
        try:
            await self._token_provider().access_token()
        except MissingCredentials as exc:
            logger.warning("YouTube authentication unavailable: %s", exc)
            return False
        return True

    # -- metadata ------------------------------------------------------------

    def _build_metadata(self, request: PublishRequest) -> tuple[dict[str, Any], list[str]]:
        """Assemble the snippet/status payload, enforcing YouTube's limits."""
        warnings: list[str] = []

        title = " ".join((request.title or "").split())
        if len(title) > MAX_TITLE_LENGTH:
            warnings.append(
                f"title truncated from {len(title)} to {MAX_TITLE_LENGTH} characters"
            )
            title = title[: MAX_TITLE_LENGTH - 1].rstrip() + "\u2026"
        if not title:
            title = "Untitled Short"
            warnings.append("empty title replaced with a placeholder")
        # Angle brackets are rejected outright by the API.
        title = title.replace("<", "(").replace(">", ")")

        description = (request.description or "").strip()[:MAX_DESCRIPTION_LENGTH]

        tags: list[str] = []
        used = 0
        for raw in request.tags or []:
            tag = " ".join(str(raw).split())
            if not tag:
                continue
            cost = len(tag) + 1
            if used + cost > MAX_TAGS_TOTAL_LENGTH:
                warnings.append(
                    f"dropped {len(request.tags) - len(tags)} tag(s); "
                    f"YouTube caps tags at {MAX_TAGS_TOTAL_LENGTH} characters total"
                )
                break
            tags.append(tag)
            used += cost

        snippet: dict[str, Any] = {
            "title": title,
            "description": description,
            "categoryId": self.category_id,
        }
        if tags:
            snippet["tags"] = tags

        status: dict[str, Any] = {
            "privacyStatus": request.privacy.value,
            # Required by the API. Omitting it fails the upload.
            "selfDeclaredMadeForKids": self.made_for_kids,
            "embeddable": True,
        }

        return {"snippet": snippet, "status": status}, warnings

    # -- publish -------------------------------------------------------------

    async def publish(self, request: PublishRequest) -> PublishResult:
        video_path = Path(request.video_path)
        if not video_path.is_file():
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"Video file not found: {request.video_path}",
            )

        size = video_path.stat().st_size
        if size == 0:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"Video file is empty: {request.video_path}",
            )

        try:
            token = await self._token_provider().access_token()
        except MissingCredentials as exc:
            return PublishResult(platform=self.platform, success=False, error=str(exc))

        metadata, warnings = self._build_metadata(request)
        for warning in warnings:
            logger.warning("YouTube metadata: %s", warning)

        client, owns_client = self._http(UPLOAD_TIMEOUT)
        try:
            session_uri = await self._initiate_upload(client, token, metadata, size, video_path)
            if isinstance(session_uri, PublishResult):
                return session_uri

            return await self._upload_bytes(client, session_uri, video_path, size)
        finally:
            if owns_client:
                await client.aclose()

    async def _initiate_upload(
        self,
        client: httpx.AsyncClient,
        token: str,
        metadata: dict[str, Any],
        size: int,
        video_path: Path,
    ) -> "str | PublishResult":
        """Open a resumable session and return its URI, or a failed result."""
        headers = {
            **auth_headers(token),
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(size),
        }
        params = {"uploadType": "resumable", "part": "snippet,status"}

        try:
            response = await client.post(
                UPLOAD_ENDPOINT, params=params, headers=headers, json=metadata
            )
        except httpx.HTTPError as exc:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"Could not reach the YouTube upload endpoint: {exc}",
            )

        if response.status_code >= 400:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"YouTube rejected the upload request — {describe_error(response)}",
            )

        session_uri = response.headers.get("location") or response.headers.get("Location")
        if not session_uri:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=(
                    "YouTube accepted the upload request but returned no session URI; "
                    f"headers were {dict(response.headers)}"
                ),
            )

        logger.info("YouTube resumable session opened for %s (%d bytes)", video_path.name, size)
        return session_uri

    async def _upload_bytes(
        self,
        client: httpx.AsyncClient,
        session_uri: str,
        video_path: Path,
        size: int,
    ) -> PublishResult:
        """PUT the file body and translate the response into a result.

        The file handle is streamed rather than read into memory, so a large clip
        cannot blow up the process.
        """
        headers = {
            "Content-Type": "video/*",
            "Content-Length": str(size),
        }
        try:
            with open(video_path, "rb") as handle:
                response = await client.put(session_uri, headers=headers, content=handle)
        except httpx.HTTPError as exc:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"Upload transfer failed for {video_path.name}: {exc}",
            )

        if response.status_code >= 400:
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"YouTube rejected the video — {describe_error(response)}",
            )

        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"YouTube returned a non-JSON upload response: {response.text[:300]}",
            )

        video_id = (body or {}).get("id")
        if not video_id:
            # Without an id there is no published video, whatever the status code
            # said. Reporting success here is exactly the bug being replaced.
            return PublishResult(
                platform=self.platform,
                success=False,
                error=f"YouTube returned no video id; response was {str(body)[:300]}",
            )

        url = SHORTS_URL_TEMPLATE.format(video_id=video_id)
        logger.info("published to YouTube: %s", url)
        return PublishResult(
            platform=self.platform,
            success=True,
            post_id=video_id,
            video_url=url,
            is_mock=False,
        )

    # -- status --------------------------------------------------------------

    async def check_status(self, post_id: str) -> str:
        """Query the video's real processing and visibility state.

        Returns one of ``PROCESSING``, ``LIVE``, ``PRIVATE``, ``REJECTED``,
        ``FAILED``, ``UNKNOWN``. ``UNKNOWN`` is reserved for "the API did not tell
        us", which is distinct from every one of the real states.
        """
        if not post_id:
            return "UNKNOWN"

        try:
            token = await self._token_provider().access_token()
        except MissingCredentials as exc:
            logger.warning("cannot check YouTube status: %s", exc)
            return "UNKNOWN"

        client, owns_client = self._http(STATUS_TIMEOUT)
        try:
            response = await client.get(
                VIDEOS_ENDPOINT,
                params={"part": "status,processingDetails", "id": post_id},
                headers=auth_headers(token),
            )
        except httpx.HTTPError as exc:
            logger.warning("YouTube status request failed for %s: %s", post_id, exc)
            return "UNKNOWN"
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            logger.warning("YouTube status check failed — %s", describe_error(response))
            return "UNKNOWN"

        try:
            items = (response.json() or {}).get("items") or []
        except Exception:  # noqa: BLE001
            return "UNKNOWN"

        if not items:
            # Deleted, or never visible to this account.
            logger.warning("YouTube reports no video for id %s", post_id)
            return "UNKNOWN"

        return self._interpret_status(items[0])

    @staticmethod
    def _interpret_status(video: dict[str, Any]) -> str:
        status = video.get("status") or {}
        processing = video.get("processingDetails") or {}

        upload_status = (status.get("uploadStatus") or "").lower()
        privacy = (status.get("privacyStatus") or "").lower()
        processing_status = (processing.get("processingStatus") or "").lower()
        failure = processing.get("processingFailureReason") or status.get("failureReason")

        if upload_status in {"rejected", "failed"} or failure:
            logger.warning("YouTube video not usable: uploadStatus=%s reason=%s", upload_status, failure)
            return "REJECTED"

        if processing_status in {"failed", "terminated"}:
            return "REJECTED"

        if upload_status == "processed":
            if privacy == "public":
                return "LIVE"
            if privacy == "private":
                return "PRIVATE"
            return "PROCESSING"  # unlisted: live, but not publicly listed

        if upload_status in {"uploaded", "processing"} or processing_status == "processing":
            return "PROCESSING"

        return "UNKNOWN"
