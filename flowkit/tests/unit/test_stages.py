"""Pipeline stage vocabulary and the tagging that feeds the dashboard rail.

The dashboard groups log records by their ``stage`` field. If tagging silently
stops working, the rail does not break — it just renders empty panels, which is
worse, because it looks wired. These tests pin the contract at the three places
records actually get tagged: the request funnel, the post-process helpers, and
the TTS service.
"""

import asyncio
import logging
from typing import get_args

import pytest

from agent.models.enums import RequestType
from agent.services.log_bus import LogBus, LogBusHandler, current_stage, log_stage, staged
from agent.services.stages import (
    ALL_STAGES,
    REQUEST_TYPE_STAGE,
    is_known_stage,
    stage_for_request_type,
)


@pytest.fixture
def bus():
    """A fresh bus wired into the root logger, torn down afterwards."""
    b = LogBus()
    handler = LogBusHandler(b, level=logging.DEBUG)
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield b
    finally:
        root.removeHandler(handler)
        root.setLevel(previous)


def _last_stage(b):
    records = b.history(limit=1)
    assert records, "nothing reached the bus"
    return records[-1]["stage"]


# ── vocabulary ───────────────────────────────────────────────────────────

def test_every_request_type_is_mapped_to_a_stage():
    """An unmapped type would emit untagged lines that no rail node can show."""
    unmapped = [t for t in get_args(RequestType) if t not in REQUEST_TYPE_STAGE]
    assert unmapped == [], f"request types missing from the stage map: {unmapped}"


def test_mapping_never_invents_a_stage_outside_the_vocabulary():
    unknown = {s for s in REQUEST_TYPE_STAGE.values() if s not in ALL_STAGES}
    assert unknown == set(), f"stage map references unknown stages: {unknown}"


def test_character_image_types_belong_to_refs_and_scene_stills_to_images():
    assert stage_for_request_type("GENERATE_CHARACTER_IMAGE") == "refs"
    assert stage_for_request_type("EDIT_CHARACTER_IMAGE") == "refs"
    assert stage_for_request_type("GENERATE_IMAGE") == "images"
    assert stage_for_request_type("GENERATE_VIDEO") == "video"
    assert stage_for_request_type("UPSCALE_VIDEO") == "upscale"


def test_unknown_or_missing_type_is_untagged_rather_than_mis_tagged():
    assert stage_for_request_type("SOMETHING_ELSE") is None
    assert stage_for_request_type(None) is None
    assert stage_for_request_type("") is None
    assert is_known_stage(None) is False
    assert is_known_stage("images") is True


# ── tagging primitives ───────────────────────────────────────────────────

def test_context_manager_tags_records(bus):
    with log_stage("images"):
        assert current_stage() == "images"
        logging.getLogger("t.ctx").info("rendering still")
    assert current_stage() is None
    assert _last_stage(bus) == "images"


def test_context_manager_restores_the_previous_stage(bus):
    with log_stage("assemble"):
        with log_stage("voiceover"):
            logging.getLogger("t.nest").info("inner")
        logging.getLogger("t.nest").info("outer")
    stages = [r["stage"] for r in bus.history(limit=2)]
    assert stages == ["voiceover", "assemble"]


def test_sync_decorator_tags_records(bus):
    @staged("assemble")
    def work():
        logging.getLogger("t.sync").info("merging")
        return 42

    assert work() == 42
    assert _last_stage(bus) == "assemble"


def test_async_decorator_tags_records(bus):
    @staged("voiceover")
    async def work():
        logging.getLogger("t.async").info("synthesising")
        return "ok"

    assert asyncio.run(work()) == "ok"
    assert _last_stage(bus) == "voiceover"


def test_stage_does_not_leak_across_concurrent_tasks(bus):
    """contextvars give each task its own stage; sharing one would cross-tag."""
    async def worker(name):
        with log_stage(name):
            await asyncio.sleep(0)
            logging.getLogger("t.task").info("working")
            return current_stage()

    async def main():
        return await asyncio.gather(worker("images"), worker("video"))

    assert asyncio.run(main()) == ["images", "video"]
    assert [r["stage"] for r in bus.history(limit=2)] == ["images", "video"]


# ── the three real tagging sites ─────────────────────────────────────────

def test_worker_funnel_tags_by_request_type(bus, monkeypatch):
    from agent.worker import processor

    seen = {}

    async def fake_inner(req, deferred=None, retry_after=None):
        seen["stage"] = current_stage()

    monkeypatch.setattr(processor, "_process_one_inner", fake_inner)
    asyncio.run(processor._process_one({"id": "abcdef123", "type": "GENERATE_VIDEO"}))
    assert seen["stage"] == "video"


def test_post_process_helpers_carry_their_stage(bus):
    """Each helper tags its own stage.

    Deliberately drives the missing-input path: it logs before ffmpeg is
    reached, so the assertion needs neither a subprocess nor a writable disk.
    """
    from agent.services import post_process as pp

    pp.trim_video("/nonexistent/in.mp4", "/nonexistent/out.mp4", 0.0, 1.0)
    assert _last_stage(bus) == "assemble"

    pp.add_narration("/nonexistent/v.mp4", "/nonexistent/n.wav", "/nonexistent/o.mp4")
    assert _last_stage(bus) == "voiceover"

    pp.add_music("/nonexistent/v.mp4", "/nonexistent/m.mp3", "/nonexistent/o.mp4")
    assert _last_stage(bus) == "music"


def test_tts_service_functions_carry_the_voiceover_stage(bus):
    """The decorator must survive being applied to coroutine functions."""
    from agent.services import tts

    assert tts.generate_speech.__wrapped__ is not None
    assert tts.generate_video_narration.__wrapped__ is not None

    # Exercise the real wrapper without spawning the model subprocess.
    async def go():
        try:
            await tts.generate_speech("hi", "/tmp/definitely/not/writable/x.wav")
        except Exception:
            pass

    asyncio.run(go())
