"""OAuth2 credentials for the YouTube Data API.

Uses the standard installed-app refresh-token flow, which is the right shape for
an unattended pipeline: the channel owner authorises once, and every later run
mints a short-lived access token from the stored refresh token. No browser, no
interactive consent, nothing to click at 3am.

Configuration is environment-only so secrets never land in the repo:

    YOUTUBE_CLIENT_ID
    YOUTUBE_CLIENT_SECRET
    YOUTUBE_REFRESH_TOKEN

There is deliberately no fallback to a placeholder token. A missing credential
raises, because a pipeline that silently publishes nothing is worse than one that
stops and says why.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

# Refresh a little before real expiry so an upload in flight cannot be cut off
# mid-transfer by a token that expired while the request was queued.
EXPIRY_SAFETY_SECONDS = 120
DEFAULT_TOKEN_TIMEOUT = 30.0

ENV_CLIENT_ID = "YOUTUBE_CLIENT_ID"
ENV_CLIENT_SECRET = "YOUTUBE_CLIENT_SECRET"
ENV_REFRESH_TOKEN = "YOUTUBE_REFRESH_TOKEN"


class MissingCredentials(RuntimeError):
    """Raised when the environment does not carry usable YouTube credentials."""


@dataclass(frozen=True)
class YouTubeCredentials:
    """The three values needed to mint access tokens."""

    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls, env: Optional[dict[str, str]] = None) -> "YouTubeCredentials":
        source = env if env is not None else os.environ
        missing = [
            name
            for name in (ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_REFRESH_TOKEN)
            if not (source.get(name) or "").strip()
        ]
        if missing:
            raise MissingCredentials(
                "YouTube Data API credentials are not configured. Missing: "
                + ", ".join(missing)
                + ". Create an OAuth client (Desktop app) in Google Cloud Console, "
                "authorise the channel once with scope "
                "https://www.googleapis.com/auth/youtube.upload, and set "
                "YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN."
            )
        return cls(
            client_id=source[ENV_CLIENT_ID].strip(),
            client_secret=source[ENV_CLIENT_SECRET].strip(),
            refresh_token=source[ENV_REFRESH_TOKEN].strip(),
        )

    @classmethod
    def is_configured(cls, env: Optional[dict[str, str]] = None) -> bool:
        try:
            cls.from_env(env)
        except MissingCredentials:
            return False
        return True


class AccessTokenProvider:
    """Mints and caches a YouTube access token from a refresh token.

    Google returns an access token valid for about an hour. Caching it matters:
    the token endpoint is rate limited, and a batch publishing several episodes
    would otherwise re-mint for every call.
    """

    def __init__(
        self,
        credentials: YouTubeCredentials,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = DEFAULT_TOKEN_TIMEOUT,
    ) -> None:
        self.credentials = credentials
        self._client = client
        self.timeout = timeout
        self._token: Optional[str] = None
        self._expires_at: float = 0.0

    @property
    def cached(self) -> bool:
        return self._token is not None and time.monotonic() < self._expires_at

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    async def access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self.cached:
            return self._token  # type: ignore[return-value]

        payload = {
            "client_id": self.credentials.client_id,
            "client_secret": self.credentials.client_secret,
            "refresh_token": self.credentials.refresh_token,
            "grant_type": "refresh_token",
        }

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self.timeout)
        try:
            response = await client.post(TOKEN_ENDPOINT, data=payload)
        finally:
            if owns_client:
                await client.aclose()

        if response.status_code >= 400:
            raise MissingCredentials(
                "YouTube token refresh failed with HTTP "
                f"{response.status_code}: {response.text[:300]}. "
                "The refresh token may have been revoked or the client secret rotated."
            )

        body = response.json()
        token = body.get("access_token")
        if not token:
            raise MissingCredentials(f"YouTube token response carried no access_token: {body}")

        expires_in = float(body.get("expires_in") or 3600)
        self._token = token
        self._expires_at = time.monotonic() + max(60.0, expires_in - EXPIRY_SAFETY_SECONDS)
        logger.debug("minted YouTube access token, valid for %.0fs", expires_in)
        return token


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def describe_error(response: httpx.Response) -> str:
    """Turn a Google API error body into something a human can act on."""
    try:
        body: Any = response.json()
    except Exception:  # noqa: BLE001 - error path must never raise
        return f"HTTP {response.status_code}: {response.text[:300]}"

    error = (body or {}).get("error") or {}
    if isinstance(error, str):
        return f"HTTP {response.status_code}: {error}"

    message = error.get("message") or response.text[:300]
    reasons = [
        item.get("reason")
        for item in (error.get("errors") or [])
        if isinstance(item, dict) and item.get("reason")
    ]

    if "quotaExceeded" in reasons or "uploadLimitExceeded" in reasons:
        return (
            f"HTTP {response.status_code}: YouTube quota exhausted ({message}). "
            "The Data API allows ~6 uploads/day (1600 of 10,000 daily units per upload). "
            "Wait for the quota to reset at midnight Pacific, or request a quota increase."
        )
    if "youtubeSignupRequired" in reasons:
        return (
            f"HTTP {response.status_code}: this Google account has no YouTube channel. "
            "Create a channel before uploading."
        )

    suffix = f" [{', '.join(reasons)}]" if reasons else ""
    return f"HTTP {response.status_code}: {message}{suffix}"
