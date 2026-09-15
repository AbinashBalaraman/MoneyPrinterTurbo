"""Tests for agent.sdk.services.result_handler."""

import pytest
from unittest.mock import AsyncMock, patch

from agent.sdk.services.result_handler import parse_result, apply_scene_result, apply_character_result
from agent.sdk.models.media import GenerationResult


# ---------------------------------------------------------------------------
# parse_result tests
# ---------------------------------------------------------------------------


def test_parse_result_image_success_extracts_media_id_and_url(sample_image_success, sample_uuid):
    result = parse_result(sample_image_success, "GENERATE_IMAGE")

    assert result.success is True
    assert result.media_id == sample_uuid
    assert sample_uuid in result.url
    assert result.error is None


def test_parse_result_video_success_extracts_media_id_and_url(sample_video_success, sample_uuid):
    result = parse_result(sample_video_success, "GENERATE_VIDEO")

    assert result.success is True
    assert result.media_id == sample_uuid
    assert result.url is not None
    assert result.error is None


def test_parse_result_top_level_error_returns_failure(sample_error_response):
    result = parse_result(sample_error_response, "GENERATE_IMAGE")

    assert result.success is False
    assert result.error == "Internal error encountered"
    assert result.media_id is None


def test_parse_result_nested_error_returns_failure(sample_nested_error):
    result = parse_result(sample_nested_error, "GENERATE_IMAGE")

    assert result.success is False
    assert "permission" in result.error
    assert result.media_id is None


def test_parse_result_raw_is_attached(sample_image_success):
    result = parse_result(sample_image_success, "GENERATE_IMAGE")

    assert result.raw is sample_image_success


# ---------------------------------------------------------------------------
# apply_scene_result tests
#
# These used `mocker` (pytest-mock), which is not installed in this venv — so the
# whole block errored at setup and had never actually run. Rewritten with
# `monkeypatch`, which needs no dependency.
#
# They must patch the *reads* as well as the write: since the conditioning work,
# `apply_scene_result` also calls `crud.get_scene` (twice) and the project's
# linked characters. An unpatched read would hit the real SQLite file, which can
# block on the agent's lock and present as a hang.
# ---------------------------------------------------------------------------


@pytest.fixture
def crud_spy(monkeypatch):
    """Patch every crud call result_handler makes, and record the writes."""
    from agent.db import crud

    calls = {"scene": [], "character": []}
    scene_row = {
        "id": "scene-001",
        "video_id": "vid-001",
        "parent_scene_id": None,
        "character_names": None,
    }
    calls["scene_row"] = scene_row

    async def update_scene(scene_id, **kwargs):
        calls["scene"].append({"scene_id": scene_id, **kwargs})

    async def update_character(char_id, **kwargs):
        calls["character"].append({"character_id": char_id, **kwargs})

    async def get_scene(scene_id):
        return dict(scene_row)

    async def get_video(vid):
        return {"id": vid, "project_id": "proj-001"}

    async def get_project_characters(pid):
        return []

    monkeypatch.setattr(crud, "update_scene", update_scene)
    monkeypatch.setattr(crud, "update_character", update_character)
    monkeypatch.setattr(crud, "get_scene", get_scene)
    monkeypatch.setattr(crud, "get_video", get_video)
    monkeypatch.setattr(crud, "get_project_characters", get_project_characters)
    return calls


@pytest.mark.asyncio
async def test_apply_scene_result_generate_image_sets_fields_and_cascades(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")

    await apply_scene_result("scene-001", "GENERATE_IMAGE", "VERTICAL", result)

    assert len(crud_spy["scene"]) == 1
    kwargs = crud_spy["scene"][0]
    assert kwargs["vertical_image_media_id"] == sample_uuid
    assert kwargs["vertical_image_status"] == "COMPLETED"
    # Cascade: video and upscale reset to PENDING
    assert kwargs["vertical_video_status"] == "PENDING"
    assert kwargs["vertical_video_media_id"] is None
    assert kwargs["vertical_upscale_status"] == "PENDING"
    assert kwargs["vertical_upscale_media_id"] is None


@pytest.mark.asyncio
async def test_apply_scene_result_edit_image_same_cascade_as_generate(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")

    await apply_scene_result("scene-001", "EDIT_IMAGE", "VERTICAL", result)

    assert len(crud_spy["scene"]) == 1
    kwargs = crud_spy["scene"][0]
    assert kwargs["vertical_image_status"] == "COMPLETED"
    assert kwargs["vertical_video_status"] == "PENDING"
    assert kwargs["vertical_upscale_status"] == "PENDING"


@pytest.mark.asyncio
async def test_apply_scene_result_generate_video_sets_fields_and_cascades_upscale(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://storage.googleapis.com/vid.mp4")

    await apply_scene_result("scene-001", "GENERATE_VIDEO", "VERTICAL", result)

    assert len(crud_spy["scene"]) == 1
    kwargs = crud_spy["scene"][0]
    assert kwargs["vertical_video_media_id"] == sample_uuid
    assert kwargs["vertical_video_status"] == "COMPLETED"
    # Cascade: upscale reset to PENDING
    assert kwargs["vertical_upscale_status"] == "PENDING"
    assert kwargs["vertical_upscale_media_id"] is None
    # No image keys touched
    assert "vertical_image_status" not in kwargs


@pytest.mark.asyncio
async def test_apply_scene_result_upscale_video_sets_fields_no_cascade(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://storage.googleapis.com/upscale.mp4")

    await apply_scene_result("scene-001", "UPSCALE_VIDEO", "VERTICAL", result)

    assert len(crud_spy["scene"]) == 1
    kwargs = crud_spy["scene"][0]
    assert kwargs["vertical_upscale_media_id"] == sample_uuid
    assert kwargs["vertical_upscale_status"] == "COMPLETED"
    # No image or video keys touched
    assert "vertical_image_status" not in kwargs
    assert "vertical_video_status" not in kwargs


@pytest.mark.asyncio
async def test_apply_scene_result_skips_when_scene_id_is_none(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")

    await apply_scene_result(None, "GENERATE_IMAGE", "VERTICAL", result)

    assert crud_spy["scene"] == []


@pytest.mark.asyncio
async def test_apply_scene_result_skips_when_result_failed(crud_spy):
    result = GenerationResult(success=False, error="API error")

    await apply_scene_result("scene-001", "GENERATE_IMAGE", "VERTICAL", result)

    assert crud_spy["scene"] == []


@pytest.mark.asyncio
async def test_apply_scene_result_horizontal_orientation_uses_correct_prefix(sample_uuid, crud_spy):
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")

    await apply_scene_result("scene-001", "GENERATE_IMAGE", "HORIZONTAL", result)

    assert len(crud_spy["scene"]) == 1
    kwargs = crud_spy["scene"][0]
    assert kwargs["horizontal_image_media_id"] == sample_uuid
    assert kwargs["horizontal_image_status"] == "COMPLETED"
    assert "vertical_image_status" not in kwargs


# ---------------------------------------------------------------------------
# The conditioning record — written at generation time
#
# This is the write path that makes `services/consistency.py` a fact rather than
# a guess: an image generated while the characters were unlinked is
# un-conditioned *forever*, so linking them afterwards must not make the report
# go green. See docs/ARCHITECTURE.md.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_records_the_references_actually_conditioned(sample_uuid, crud_spy, monkeypatch):
    import json

    from agent.db import crud

    crud_spy["scene_row"]["character_names"] = json.dumps(["arthur"])

    async def linked(pid):
        return [{"id": "c1", "slug": "arthur", "name": "Arthur", "media_id": "m1"}]

    monkeypatch.setattr(crud, "get_project_characters", linked)

    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")
    await apply_scene_result("scene-001", "GENERATE_IMAGE", "VERTICAL", result)

    assert json.loads(crud_spy["scene"][0]["conditioned_with"]) == ["arthur"]


@pytest.mark.asyncio
async def test_records_empty_when_nothing_is_linked(sample_uuid, crud_spy, monkeypatch):
    """The Stickman Legends case: names declared, nothing linked.

    An empty record is the honest answer — it is what later reports as *proven*
    un-conditioned rather than silently fine.
    """
    import json

    from agent.db import crud

    crud_spy["scene_row"]["character_names"] = json.dumps(["red_blade"])

    async def none_linked(pid):
        return []

    monkeypatch.setattr(crud, "get_project_characters", none_linked)

    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")
    await apply_scene_result("scene-001", "GENERATE_IMAGE", "VERTICAL", result)

    assert json.loads(crud_spy["scene"][0]["conditioned_with"]) == []


@pytest.mark.asyncio
async def test_a_scene_naming_nobody_records_empty(sample_uuid, crud_spy):
    """No declared characters means no reference image was ever needed."""
    import json

    result = GenerationResult(success=True, media_id=sample_uuid, url="https://example.com/img.jpg")
    await apply_scene_result("scene-001", "GENERATE_IMAGE", "VERTICAL", result)

    assert json.loads(crud_spy["scene"][0]["conditioned_with"]) == []


@pytest.mark.asyncio
async def test_video_results_do_not_touch_the_conditioning_record(sample_uuid, crud_spy):
    """Conditioning is a property of the still, not of the clip."""
    result = GenerationResult(success=True, media_id=sample_uuid, url="https://storage.googleapis.com/vid.mp4")
    await apply_scene_result("scene-001", "GENERATE_VIDEO", "VERTICAL", result)

    assert "conditioned_with" not in crud_spy["scene"][0]


# ---------------------------------------------------------------------------
# apply_character_result tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_character_result_sets_media_id_and_url(sample_uuid, crud_spy):
    result = GenerationResult(
        success=True,
        media_id=sample_uuid,
        url=f"https://example.com/ref/{sample_uuid}",
    )

    await apply_character_result("char-001", result)

    assert crud_spy["character"] == [
        {"character_id": "char-001", "media_id": sample_uuid, "reference_image_url": result.url}
    ]


@pytest.mark.asyncio
async def test_apply_character_result_skips_when_result_failed(crud_spy):
    result = GenerationResult(success=False, error="generation failed")

    await apply_character_result("char-001", result)

    assert crud_spy["character"] == []
