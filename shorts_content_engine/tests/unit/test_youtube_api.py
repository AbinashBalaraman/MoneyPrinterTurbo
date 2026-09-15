"""Unit tests for the YouTube Data API v3 adapter and its credentials.

No network: httpx is replaced with a fake client. The most important test here is
``test_publish_fails_when_api_returns_no_video_id`` — the whole point of this
adapter is that it can never report success for a video that does not exist.
"""

import json

import pytest

from src.distribution.adapters.youtube_api import (
    MAX_TAGS_TOTAL_LENGTH,
    MAX_TITLE_LENGTH,
    YouTubeApiAdapter,
)
from src.distribution.credentials import (
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_REFRESH_TOKEN,
    AccessTokenProvider,
    MissingCredentials,
    YouTubeCredentials,
    describe_error,
)
from src.distribution.models import PlatformType, PrivacyStatus, PublishRequest

GOOD_ENV = {
    ENV_CLIENT_ID: "client-abc",
    ENV_CLIENT_SECRET: "secret-xyz",
    ENV_REFRESH_TOKEN: "refresh-123",
}


class FakeResponse:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeAsyncClient:
    """Records calls and replays canned responses."""

    def __init__(self, post=None, put=None, get=None):
        self._post = post
        self._put = put
        self._get = get
        self.calls = []

    async def post(self, url, params=None, headers=None, json=None, data=None, content=None):
        # httpx accepts either a JSON body or a form-encoded ``data`` payload;
        # the OAuth token exchange uses ``data`` while the resumable-upload
        # initiation uses ``json``. Record whichever was supplied so tests can
        # assert on the real request shape instead of a lossy normalisation.
        body = json if json is not None else data
        self.calls.append(("post", url, params, body))
        return self._post

    async def put(self, url, headers=None, content=None):
        body = content.read() if hasattr(content, "read") else content
        self.calls.append(("put", url, headers, body))
        return self._put

    async def get(self, url, params=None, headers=None):
        self.calls.append(("get", url, params))
        return self._get

    async def aclose(self):
        pass


class StubTokenProvider:
    def __init__(self, token="stub-token"):
        self.token = token
        self.calls = 0

    async def access_token(self, force_refresh=False):
        self.calls += 1
        return self.token


def make_video(tmp_path, name="clip.mp4", data=b"VIDEOBYTES"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def adapter_with(tmp_path, post=None, put=None, get=None, token_provider=None):
    client = FakeAsyncClient(post=post, put=put, get=get)
    adapter = YouTubeApiAdapter(
        token_provider=token_provider or StubTokenProvider(),
        client=client,
    )
    return adapter, client


# --- credentials -----------------------------------------------------------


def test_from_env_raises_and_names_every_missing_variable():
    with pytest.raises(MissingCredentials) as exc:
        YouTubeCredentials.from_env({})
    message = str(exc.value)
    assert ENV_CLIENT_ID in message
    assert ENV_CLIENT_SECRET in message
    assert ENV_REFRESH_TOKEN in message


def test_from_env_reads_values():
    creds = YouTubeCredentials.from_env(GOOD_ENV)
    assert creds.client_id == "client-abc"
    assert creds.refresh_token == "refresh-123"


def test_from_env_treats_blank_as_missing():
    env = dict(GOOD_ENV, **{ENV_REFRESH_TOKEN: "   "})
    with pytest.raises(MissingCredentials, match=ENV_REFRESH_TOKEN):
        YouTubeCredentials.from_env(env)


def test_is_configured_reflects_environment():
    assert YouTubeCredentials.is_configured(GOOD_ENV) is True
    assert YouTubeCredentials.is_configured({}) is False


@pytest.mark.asyncio
async def test_token_provider_mints_then_caches():
    response = FakeResponse(json_data={"access_token": "tok-1", "expires_in": 3600})
    client = FakeAsyncClient(post=response)
    provider = AccessTokenProvider(YouTubeCredentials.from_env(GOOD_ENV), client=client)

    assert await provider.access_token() == "tok-1"
    assert await provider.access_token() == "tok-1"
    # The token endpoint is rate limited, so a second call must not re-mint.
    assert len([c for c in client.calls if c[0] == "post"]) == 1


@pytest.mark.asyncio
async def test_token_provider_force_refresh_bypasses_cache():
    response = FakeResponse(json_data={"access_token": "tok-2", "expires_in": 3600})
    client = FakeAsyncClient(post=response)
    provider = AccessTokenProvider(YouTubeCredentials.from_env(GOOD_ENV), client=client)

    await provider.access_token()
    await provider.access_token(force_refresh=True)
    assert len([c for c in client.calls if c[0] == "post"]) == 2


@pytest.mark.asyncio
async def test_token_provider_surfaces_refresh_failure():
    client = FakeAsyncClient(post=FakeResponse(status_code=400, text="invalid_grant"))
    provider = AccessTokenProvider(YouTubeCredentials.from_env(GOOD_ENV), client=client)

    with pytest.raises(MissingCredentials, match="revoked or the client secret rotated"):
        await provider.access_token()


@pytest.mark.asyncio
async def test_token_provider_rejects_response_without_token():
    client = FakeAsyncClient(post=FakeResponse(json_data={"expires_in": 3600}))
    provider = AccessTokenProvider(YouTubeCredentials.from_env(GOOD_ENV), client=client)
    with pytest.raises(MissingCredentials, match="no access_token"):
        await provider.access_token()


# --- error translation -----------------------------------------------------


def test_describe_error_explains_quota_exhaustion():
    body = {
        "error": {
            "message": "The request cannot be completed because you have exceeded your quota.",
            "errors": [{"reason": "quotaExceeded"}],
        }
    }
    text = describe_error(FakeResponse(status_code=403, json_data=body))
    assert "quota" in text.lower()
    assert "1600" in text  # the per-upload unit cost, so the ceiling is actionable


def test_describe_error_handles_non_json_body():
    text = describe_error(FakeResponse(status_code=500, text="<html>oops</html>"))
    assert "HTTP 500" in text


# --- metadata limits -------------------------------------------------------


def test_title_is_truncated_to_youtube_limit(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    request = PublishRequest(video_path="x.mp4", title="A" * 250)
    metadata, warnings = adapter._build_metadata(request)

    assert len(metadata["snippet"]["title"]) == MAX_TITLE_LENGTH
    assert any("truncated" in w for w in warnings)


def test_angle_brackets_are_replaced(tmp_path):
    """The API rejects < and > outright, so an upload would fail at the last step."""
    adapter, _ = adapter_with(tmp_path)
    metadata, _ = adapter._build_metadata(
        PublishRequest(video_path="x.mp4", title="Episode <1> of 5")
    )
    assert "<" not in metadata["snippet"]["title"]
    assert ">" not in metadata["snippet"]["title"]


def test_empty_title_is_replaced_and_reported(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    metadata, warnings = adapter._build_metadata(PublishRequest(video_path="x.mp4", title="   "))
    assert metadata["snippet"]["title"] == "Untitled Short"
    assert any("placeholder" in w for w in warnings)


def test_tag_budget_is_enforced(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    tags = ["x" * 60 for _ in range(20)]
    metadata, warnings = adapter._build_metadata(
        PublishRequest(video_path="x.mp4", title="t", tags=tags)
    )
    kept = metadata["snippet"]["tags"]
    assert sum(len(t) + 1 for t in kept) <= MAX_TAGS_TOTAL_LENGTH
    assert len(kept) < len(tags)
    assert any("dropped" in w for w in warnings)


def test_status_always_declares_made_for_kids(tmp_path):
    """Omitting selfDeclaredMadeForKids fails the upload."""
    adapter, _ = adapter_with(tmp_path)
    metadata, _ = adapter._build_metadata(PublishRequest(video_path="x.mp4", title="t"))
    assert metadata["status"]["selfDeclaredMadeForKids"] is False
    assert metadata["status"]["privacyStatus"] == "public"


def test_privacy_is_carried_through(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    metadata, _ = adapter._build_metadata(
        PublishRequest(video_path="x.mp4", title="t", privacy=PrivacyStatus.PRIVATE)
    )
    assert metadata["status"]["privacyStatus"] == "private"


# --- publish ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_rejects_missing_file(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    result = await adapter.publish(PublishRequest(video_path=str(tmp_path / "nope.mp4"), title="t"))
    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_publish_rejects_empty_file(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    empty = make_video(tmp_path, data=b"")
    result = await adapter.publish(PublishRequest(video_path=str(empty), title="t"))
    assert result.success is False
    assert "empty" in result.error.lower()


@pytest.mark.asyncio
async def test_publish_success_returns_real_video_id_and_url(tmp_path):
    video = make_video(tmp_path)
    session = FakeResponse(status_code=200, headers={"location": "https://upload/session-1"})
    done = FakeResponse(status_code=200, json_data={"id": "dQw4w9WgXcQ"})
    adapter, client = adapter_with(tmp_path, post=session, put=done)

    result = await adapter.publish(PublishRequest(video_path=str(video), title="Episode 1"))

    assert result.success is True
    assert result.post_id == "dQw4w9WgXcQ"
    assert result.video_url == "https://youtube.com/shorts/dQw4w9WgXcQ"
    assert result.is_mock is False
    # The file body must actually be sent.
    put_call = [c for c in client.calls if c[0] == "put"][0]
    assert put_call[3] == b"VIDEOBYTES"


@pytest.mark.asyncio
async def test_publish_fails_when_api_returns_no_video_id(tmp_path):
    """The regression this adapter exists to prevent.

    The old adapter returned success=True with a hand-written 'pending_upload'
    URL. A 200 with no id means no video, so this must be a failure.
    """
    video = make_video(tmp_path)
    session = FakeResponse(status_code=200, headers={"location": "https://upload/session-1"})
    done = FakeResponse(status_code=200, json_data={"kind": "youtube#video"})
    adapter, _ = adapter_with(tmp_path, post=session, put=done)

    result = await adapter.publish(PublishRequest(video_path=str(video), title="t"))

    assert result.success is False
    assert result.video_url is None
    assert "no video id" in result.error


@pytest.mark.asyncio
async def test_publish_surfaces_quota_exhaustion(tmp_path):
    video = make_video(tmp_path)
    body = {"error": {"message": "quota exceeded", "errors": [{"reason": "quotaExceeded"}]}}
    adapter, _ = adapter_with(tmp_path, post=FakeResponse(status_code=403, json_data=body))

    result = await adapter.publish(PublishRequest(video_path=str(video), title="t"))

    assert result.success is False
    assert result.video_url is None
    assert "quota" in result.error.lower()


@pytest.mark.asyncio
async def test_publish_fails_when_session_uri_is_missing(tmp_path):
    video = make_video(tmp_path)
    adapter, _ = adapter_with(tmp_path, post=FakeResponse(status_code=200, headers={}))

    result = await adapter.publish(PublishRequest(video_path=str(video), title="t"))

    assert result.success is False
    assert "session uri" in result.error.lower()


@pytest.mark.asyncio
async def test_publish_reports_credential_problem_without_raising(tmp_path):
    video = make_video(tmp_path)

    class FailingTokens:
        async def access_token(self, force_refresh=False):
            raise MissingCredentials("no credentials configured")

    adapter, _ = adapter_with(tmp_path, token_provider=FailingTokens())
    result = await adapter.publish(PublishRequest(video_path=str(video), title="t"))

    assert result.success is False
    assert "no credentials configured" in result.error


# --- check_status ----------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_mints_a_token_rather_than_checking_a_file(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    assert await adapter.authenticate() is True


@pytest.mark.asyncio
async def test_authenticate_false_when_credentials_missing(tmp_path):
    class FailingTokens:
        async def access_token(self, force_refresh=False):
            raise MissingCredentials("nope")

    adapter, _ = adapter_with(tmp_path, token_provider=FailingTokens())
    assert await adapter.authenticate() is False


@pytest.mark.parametrize(
    "video,expected",
    [
        ({"status": {"uploadStatus": "processed", "privacyStatus": "public"}}, "LIVE"),
        ({"status": {"uploadStatus": "processed", "privacyStatus": "private"}}, "PRIVATE"),
        ({"status": {"uploadStatus": "processed", "privacyStatus": "unlisted"}}, "PROCESSING"),
        ({"status": {"uploadStatus": "uploaded"}}, "PROCESSING"),
        ({"status": {"uploadStatus": "processing"}}, "PROCESSING"),
        ({"status": {"uploadStatus": "rejected"}}, "REJECTED"),
        ({"status": {"uploadStatus": "failed"}}, "REJECTED"),
        (
            {"status": {"uploadStatus": "processed"}, "processingDetails": {"processingStatus": "terminated"}},
            "REJECTED",
        ),
        ({"status": {"uploadStatus": "somethingNew"}}, "UNKNOWN"),
    ],
)
def test_status_mapping(video, expected):
    assert YouTubeApiAdapter._interpret_status(video) == expected


@pytest.mark.asyncio
async def test_check_status_queries_the_api(tmp_path):
    payload = {"items": [{"status": {"uploadStatus": "processed", "privacyStatus": "public"}}]}
    adapter, client = adapter_with(tmp_path, get=FakeResponse(json_data=payload))

    assert await adapter.check_status("abc123") == "LIVE"
    call = [c for c in client.calls if c[0] == "get"][0]
    assert call[2]["id"] == "abc123"
    assert "status" in call[2]["part"]


@pytest.mark.asyncio
async def test_check_status_unknown_when_video_absent(tmp_path):
    adapter, _ = adapter_with(tmp_path, get=FakeResponse(json_data={"items": []}))
    assert await adapter.check_status("gone") == "UNKNOWN"


@pytest.mark.asyncio
async def test_check_status_unknown_on_api_error(tmp_path):
    adapter, _ = adapter_with(tmp_path, get=FakeResponse(status_code=403, text="forbidden"))
    assert await adapter.check_status("abc") == "UNKNOWN"


@pytest.mark.asyncio
async def test_check_status_unknown_for_blank_id(tmp_path):
    adapter, _ = adapter_with(tmp_path)
    assert await adapter.check_status("") == "UNKNOWN"
