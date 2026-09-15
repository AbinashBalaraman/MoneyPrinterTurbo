"""Reporting publish outcomes back to FlowKit.

The dashboard renders whatever is reported here, so this translation is where
the honesty guarantee is either kept or lost. Two failure modes matter:

* a simulated upload reported as a publication — the original defect, which
  made an empty pipeline look like it had shipped;
* a fabricated URL from a mock reaching the dashboard.

Reporting must also never break publishing: by the time we report, the video is
already uploaded, so a FlowKit outage cannot be allowed to fail the publish.
"""

import asyncio

import pytest

from src.distribution.models import PlatformType, PublishResult
from src.render_client.publications import FlowKitPublicationReporter, to_flowkit_payload


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class FakeAsyncClient:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []
        self.is_closed = False

    async def post(self, url, json=None, **kwargs):
        self.calls.append((url, json))
        if self._raises:
            raise self._raises
        return self._response

    async def aclose(self):
        self.is_closed = True


def _result(platform=PlatformType.YOUTUBE, success=True, is_mock=False,
            post_id=None, video_url=None, error=None):
    return PublishResult(
        platform=platform, success=success, post_id=post_id,
        video_url=video_url, error=error, is_mock=is_mock,
    )


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

class TestToFlowKitPayload:
    def test_a_simulated_success_is_a_dry_run_and_carries_no_url(self):
        """The core guarantee: a mock never looks like a post."""
        payload = to_flowkit_payload(_result(
            success=True, is_mock=True,
            post_id="fabricated", video_url="https://youtu.be/fabricated",
        ))
        assert payload["status"] == "dry_run"
        assert payload["is_mock"] is True
        # Both of these are invented by the mock and must be dropped.
        assert "video_url" not in payload
        assert "post_id" not in payload

    def test_a_real_success_reports_its_post_id_and_url(self):
        payload = to_flowkit_payload(_result(
            success=True, post_id="dQw4w9WgXcQ", video_url="https://youtu.be/dQw4w9WgXcQ",
        ))
        assert payload["status"] == "published"
        assert payload["is_mock"] is False
        assert payload["post_id"] == "dQw4w9WgXcQ"
        assert payload["video_url"] == "https://youtu.be/dQw4w9WgXcQ"

    def test_a_real_failure_reports_the_error(self):
        payload = to_flowkit_payload(_result(success=False, error="quotaExceeded"))
        assert payload["status"] == "failed"
        assert payload["error_message"] == "quotaExceeded"
        assert payload["is_mock"] is False

    def test_a_real_failure_without_an_error_still_supplies_one(self):
        """FlowKit rejects status='failed' with no message, so never send one."""
        payload = to_flowkit_payload(_result(success=False, error=None))
        assert payload["status"] == "failed"
        assert payload["error_message"]

    def test_a_failed_mock_is_a_failure_not_a_dry_run(self):
        payload = to_flowkit_payload(_result(success=False, is_mock=True, error="boom"))
        assert payload["status"] == "failed"
        assert payload["is_mock"] is False  # nothing was simulated successfully
        assert payload["error_message"] == "boom"

    def test_platform_name_is_the_lowercase_enum_value(self):
        payload = to_flowkit_payload(_result(platform=PlatformType.TIKTOK))
        assert payload["platform"] == "tiktok"


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

class TestReporter:
    def test_it_posts_to_the_video_scoped_endpoint(self):
        client = FakeAsyncClient(response=FakeResponse(201))
        reporter = FlowKitPublicationReporter(client=client)
        ok = asyncio.run(reporter.report("vid-123", _result(success=True, post_id="p1")))

        assert ok is True
        url, body = client.calls[0]
        assert url.endswith("/videos/vid-123/publications")
        assert body["status"] == "published"

    def test_a_missing_video_id_is_reported_as_not_reported(self):
        """Without a FlowKit id there is nowhere to post; say so, do not raise."""
        client = FakeAsyncClient(response=FakeResponse(201))
        reporter = FlowKitPublicationReporter(client=client)
        assert asyncio.run(reporter.report(None, _result())) is False
        assert client.calls == []

    def test_a_network_error_does_not_propagate(self):
        """The upload already succeeded; a reporting failure must not undo it."""
        client = FakeAsyncClient(raises=ConnectionError("flowkit is down"))
        reporter = FlowKitPublicationReporter(client=client)
        assert asyncio.run(reporter.report("vid-1", _result())) is False

    def test_a_rejected_report_returns_false_rather_than_raising(self):
        client = FakeAsyncClient(response=FakeResponse(422, text="bad payload"))
        reporter = FlowKitPublicationReporter(client=client)
        assert asyncio.run(reporter.report("vid-1", _result())) is False


# ---------------------------------------------------------------------------
# The manager forwards every outcome, not just the good ones
# ---------------------------------------------------------------------------

class RecordingReporter:
    def __init__(self):
        self.seen = []

    async def report(self, video_id, result):
        self.seen.append((video_id, result.platform.value, result.success, result.is_mock))
        return True


@pytest.fixture
def video_file(tmp_path):
    """The mock adapter checks the file exists, so give it a real one."""
    path = tmp_path / "episode.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    return str(path)


class TestManagerForwardsOutcomes:
    def test_dry_runs_are_reported(self, video_file):
        """Reporting only successes would show a rosier picture than reality."""
        from src.distribution.adapters.mock import MockPlatformAdapter
        from src.distribution.manager import DistributionManager
        from src.distribution.models import PublishRequest

        reporter = RecordingReporter()
        manager = DistributionManager(use_mock=True, delay_between_platforms=0.0, reporter=reporter)
        manager.register_adapter(PlatformType.YOUTUBE, MockPlatformAdapter(PlatformType.YOUTUBE))

        request = PublishRequest(
            video_path=video_file, title="T", series_id="s", episode_num=1,
            flowkit_video_id="vid-9",
        )
        asyncio.run(manager.publish_episode(request, platforms=[PlatformType.YOUTUBE]))

        assert len(reporter.seen) == 1
        video_id, platform, success, is_mock = reporter.seen[0]
        assert video_id == "vid-9"
        assert platform == "youtube"
        assert success is True
        assert is_mock is True  # the mock adapter simulates, so this is a dry run

    def test_a_failing_reporter_does_not_fail_the_publish(self, video_file):
        from src.distribution.adapters.mock import MockPlatformAdapter
        from src.distribution.manager import DistributionManager
        from src.distribution.models import PublishRequest

        class Exploding:
            async def report(self, video_id, result):
                raise RuntimeError("boom")

        manager = DistributionManager(use_mock=True, delay_between_platforms=0.0, reporter=Exploding())
        manager.register_adapter(PlatformType.YOUTUBE, MockPlatformAdapter(PlatformType.YOUTUBE))

        request = PublishRequest(
            video_path=video_file, title="T", series_id="s", episode_num=1,
            flowkit_video_id="vid-9",
        )
        report = asyncio.run(manager.publish_episode(request, platforms=[PlatformType.YOUTUBE]))
        assert report.all_successful is True
