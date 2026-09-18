# -*- coding: utf-8 -*-
"""FlowKit material source (``video_source = "flowkit"``).

Unlike the paid per-clip generators, this source creates nothing during the run:
it takes the completed media of an existing FlowKit project, removes the
watermark and stages it locally. So the contract worth pinning down is:

* the project reference is required, and its absence is a clear error rather
  than an empty material list;
* a missing scrubber is **fatal**, because the alternative is silently shipping
  watermarked media into a published video;
* a project shorter than the narration is **reported**, because the assembly
  engine will otherwise loop clips and the repeat is visible in the output.

Network, ffmpeg and the watermark engine are all patched out.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from loguru import logger as loguru_logger

from app.config import config
from app.services import material

BRIDGE = "automation.flowkit_bridge"


@contextmanager
def captured_logs(level="INFO"):
    """Collect loguru records.

    ``unittest.assertLogs`` hooks the stdlib logging module, which loguru does not
    route through, so it sees nothing from this codebase. Add a sink instead.
    """
    messages: list[str] = []
    sink_id = loguru_logger.add(lambda message: messages.append(str(message)), level=level)
    try:
        yield messages
    finally:
        loguru_logger.remove(sink_id)


def _staged(*names):
    """Stand-ins for the bridge's StagedImage/StagedVideo (only the path is read)."""
    return [SimpleNamespace(absolute_path=name) for name in names]


class _FakeScrubber:
    def __init__(self, available=True):
        self._available = available

    def available(self):
        return self._available

    def scrub(self, path):  # pragma: no cover - the bridge owns scrubbing
        pass

    def scrub_video(self, path):  # pragma: no cover
        pass


class TestFlowkitMaterialSource(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        # A developer's local config.toml must not change what these assert.
        for key in ("flowkit_project", "flowkit_media"):
            config.app.pop(key, None)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def _call(self, **overrides):
        kwargs = dict(
            task_id="task-1",
            search_terms=["Scene one", "Scene two"],
            video_aspect=material.VideoAspect.portrait,
            audio_duration=30.0,
            max_clip_duration=5,
            material_directory="",
        )
        kwargs.update(overrides)
        return material._download_videos_flowkit_on_demand(**kwargs)

    def test_requires_a_flowkit_project(self):
        """Without a project there is nothing to stage, so say so plainly."""
        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()):
            with self.assertRaises(Exception) as caught:
                self._call()
        self.assertIn("flowkit_project", str(caught.exception))

    def test_refuses_to_stage_without_a_scrubber(self):
        """A missing ffmpeg must fail, not ship watermarked material."""
        config.app["flowkit_project"] = "farmer_and_rusty"
        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber(available=False)):
            with self.assertRaises(Exception) as caught:
                self._call()
        self.assertIn("ffmpeg", str(caught.exception))

    def test_returns_staged_paths_and_asks_for_auto_media(self):
        config.app["flowkit_project"] = "farmer_and_rusty"
        captured = {}

        def fake_stage(project_ref, task_id, **kwargs):
            captured["project_ref"] = project_ref
            captured["kwargs"] = kwargs
            return _staged("/tmp/a.mp4", "/tmp/b.png"), "narration"

        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()), patch(
            f"{BRIDGE}.stage_flowkit_project", fake_stage
        ), patch.object(material, "_staged_material_seconds", lambda p: 20.0):
            paths = self._call()

        self.assertEqual(paths, ["/tmp/a.mp4", "/tmp/b.png"])
        self.assertEqual(captured["project_ref"], "farmer_and_rusty")
        # Default media mode is auto: completed video preferred, still fallback.
        self.assertEqual(captured["kwargs"]["media"], "auto")
        self.assertIsNotNone(captured["kwargs"]["scrubber"])

    def test_media_mode_is_configurable(self):
        config.app["flowkit_project"] = "farmer_and_rusty"
        config.app["flowkit_media"] = "still"
        captured = {}

        def fake_stage(project_ref, task_id, **kwargs):
            captured.update(kwargs)
            return _staged("/tmp/a.png"), ""

        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()), patch(
            f"{BRIDGE}.stage_flowkit_project", fake_stage
        ), patch.object(material, "_staged_material_seconds", lambda p: 40.0):
            self._call()

        self.assertEqual(captured["media"], "still")

    def test_reports_a_shortfall_instead_of_looping_silently(self):
        """The looped-footage defect: 33s of media against 39s of narration."""
        config.app["flowkit_project"] = "farmer_and_rusty"

        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()), patch(
            f"{BRIDGE}.stage_flowkit_project",
            lambda *a, **k: (_staged("/tmp/a.mp4"), ""),
        ), patch.object(material, "_staged_material_seconds", lambda p: 33.0):
            with captured_logs("WARNING") as logs:
                self._call(audio_duration=39.0)

        joined = "\n".join(logs)
        self.assertIn("33.0", joined)
        self.assertIn("39.0", joined)
        self.assertIn("loop", joined.lower())

    def test_no_warning_when_materials_cover_the_narration(self):
        config.app["flowkit_project"] = "farmer_and_rusty"

        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()), patch(
            f"{BRIDGE}.stage_flowkit_project",
            lambda *a, **k: (_staged("/tmp/a.mp4"), ""),
        ), patch.object(material, "_staged_material_seconds", lambda p: 45.0):
            with captured_logs("WARNING") as logs:
                self._call(audio_duration=39.0)

        self.assertFalse(
            any("loop" in line.lower() for line in logs),
            "must not warn when the media covers the narration",
        )

    def test_unmeasurable_material_does_not_crash_the_run(self):
        """A material ffmpeg cannot read must not take the whole task down."""
        config.app["flowkit_project"] = "farmer_and_rusty"

        with patch(f"{BRIDGE}.ProjectScrubber", lambda: _FakeScrubber()), patch(
            f"{BRIDGE}.stage_flowkit_project",
            lambda *a, **k: (_staged("/tmp/a.mp4"), ""),
        ), patch.object(material, "_staged_material_seconds", lambda p: 0.0):
            paths = self._call()

        self.assertEqual(paths, ["/tmp/a.mp4"])


class TestFlowkitDispatch(unittest.TestCase):
    """`download_videos` must route the new source to the new implementation."""

    def setUp(self):
        self.original_app_config = dict(config.app)

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)

    def test_dispatch_routes_flowkit(self):
        called = {}

        def fake(**kwargs):
            called.update(kwargs)
            return ["/tmp/staged.mp4"]

        with patch.object(material, "_download_videos_flowkit_on_demand", fake):
            result = material.download_videos(
                task_id="task-1",
                search_terms=["one"],
                source="flowkit",
                video_aspect=material.VideoAspect.portrait,
                video_concat_mode=material.VideoConcatMode.random,
                audio_duration=12.0,
                max_clip_duration=5,
            )

        self.assertEqual(result, ["/tmp/staged.mp4"])
        self.assertEqual(called["task_id"], "task-1")
        self.assertEqual(called["audio_duration"], 12.0)
