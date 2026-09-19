"""Unit tests for agent/worker/processor.py — heavy mocking of crud, flow_client, operations."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.worker.processor import (
    _is_already_completed,
    _mark_scene_failed,
    _handle_failure,
    _matches_name,
    _pending_reference_entities,
    _prerequisites_met,
    _reference_work_in_flight,
)
from agent.config import MAX_RETRIES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_req(
    req_type="GENERATE_IMAGE",
    scene_id="scene-001",
    orientation="VERTICAL",
    retry_count=0,
    rid="aaaaaaaa-bbbb-cccc-dddd-000000000001",
):
    return {
        "id": rid,
        "type": req_type,
        "scene_id": scene_id,
        "orientation": orientation,
        "retry_count": retry_count,
        "project_id": "proj-001",
        "video_id": "video-001",
    }


# ---------------------------------------------------------------------------
# _is_already_completed
# ---------------------------------------------------------------------------

class TestIsAlreadyCompleted:
    @pytest.mark.asyncio
    async def test_returns_true_when_vertical_image_completed(self, sample_scene_row):
        """Should return True when vertical_image_status is COMPLETED."""
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        # sample_scene_row has vertical_image_status = "COMPLETED"
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=sample_scene_row)
            result = await _is_already_completed(req, "VERTICAL")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_vertical_image_pending(self, sample_scene_row):
        """Should return False when vertical_image_status is PENDING."""
        pending_scene = {**sample_scene_row, "vertical_image_status": "PENDING"}
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=pending_scene)
            result = await _is_already_completed(req, "VERTICAL")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_for_generate_character_image(self, sample_scene_row):
        """GENERATE_CHARACTER_IMAGE has no scene — should always return False."""
        req = make_req(req_type="GENERATE_CHARACTER_IMAGE", scene_id="scene-001")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=sample_scene_row)
            result = await _is_already_completed(req, "VERTICAL")
        assert result is False
        mock_crud.get_scene.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_no_scene_id(self):
        """If scene_id is missing, should return False without querying DB."""
        req = make_req(req_type="GENERATE_IMAGE", scene_id=None)
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock()
            result = await _is_already_completed(req, "VERTICAL")
        assert result is False
        mock_crud.get_scene.assert_not_called()

    @pytest.mark.asyncio
    async def test_edit_image_never_skipped_even_when_image_completed(self, sample_scene_row):
        """EDIT_IMAGE should always run — it replaces the existing image."""
        req = make_req(req_type="EDIT_IMAGE", scene_id="scene-001")
        # sample_scene_row has vertical_image_status = "COMPLETED"
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=sample_scene_row)
            result = await _is_already_completed(req, "VERTICAL")
        assert result is False


# ---------------------------------------------------------------------------
# _mark_scene_failed
# ---------------------------------------------------------------------------

class TestMarkSceneFailed:
    @pytest.mark.asyncio
    async def test_sets_vertical_image_status_failed_for_generate_image(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001", orientation="VERTICAL")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_scene = AsyncMock()
            await _mark_scene_failed(req)
        mock_crud.update_scene.assert_awaited_once_with("scene-001", vertical_image_status="FAILED")

    @pytest.mark.asyncio
    async def test_sets_vertical_video_status_failed_for_generate_video(self):
        req = make_req(req_type="GENERATE_VIDEO", scene_id="scene-001", orientation="VERTICAL")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_scene = AsyncMock()
            await _mark_scene_failed(req)
        mock_crud.update_scene.assert_awaited_once_with("scene-001", vertical_video_status="FAILED")

    @pytest.mark.asyncio
    async def test_sets_vertical_upscale_status_failed_for_upscale_video(self):
        req = make_req(req_type="UPSCALE_VIDEO", scene_id="scene-001", orientation="VERTICAL")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_scene = AsyncMock()
            await _mark_scene_failed(req)
        mock_crud.update_scene.assert_awaited_once_with("scene-001", vertical_upscale_status="FAILED")

    @pytest.mark.asyncio
    async def test_no_update_when_no_scene_id(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id=None)
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_scene = AsyncMock()
            await _mark_scene_failed(req)
        mock_crud.update_scene.assert_not_called()


# ---------------------------------------------------------------------------
# _handle_failure
# ---------------------------------------------------------------------------

class TestHandleFailure:
    @pytest.mark.asyncio
    async def test_retries_when_under_max_retries(self):
        """When retry_count+1 < MAX_RETRIES, request should go back to PENDING."""
        req = make_req(retry_count=0)
        rid = req["id"]
        result = {"error": "timeout"}

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        mock_crud.update_request.assert_awaited_once()
        call_kwargs = mock_crud.update_request.call_args
        assert call_kwargs[0][0] == rid
        assert call_kwargs[1]["status"] == "PENDING"
        assert call_kwargs[1]["retry_count"] == 1

    @pytest.mark.asyncio
    async def test_marks_failed_when_at_max_retries(self):
        """When retry_count+1 >= MAX_RETRIES, request + scene should be marked FAILED."""
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001", retry_count=MAX_RETRIES - 1)
        rid = req["id"]
        result = {"error": "permanent failure"}

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        mock_crud.update_request.assert_awaited_once()
        call_kwargs = mock_crud.update_request.call_args
        assert call_kwargs[0][0] == rid
        assert call_kwargs[1]["status"] == "FAILED"
        # Scene should also be marked failed
        mock_crud.update_scene.assert_awaited_once_with("scene-001", vertical_image_status="FAILED")

    @pytest.mark.asyncio
    async def test_extracts_error_message_from_nested_data(self):
        """Error message extraction from data.error.message should work."""
        req = make_req(retry_count=MAX_RETRIES - 1)
        rid = req["id"]
        result = {
            "data": {
                "error": {
                    "code": 403,
                    "message": "caller does not have permission",
                }
            }
        }

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        call_kwargs = mock_crud.update_request.call_args
        assert "caller does not have permission" in call_kwargs[1]["error_message"]


# ---------------------------------------------------------------------------
# Reference-image prerequisites (scene stills are conditioned on these)
# ---------------------------------------------------------------------------

class TestMatchesName:
    def test_matches_by_slug(self):
        assert _matches_name({"name": "Arthur", "slug": "arthur"}, {"arthur"}) is True

    def test_matches_by_display_name(self):
        assert _matches_name({"name": "Arthur", "slug": "arthur"}, {"Arthur"}) is True

    def test_no_match(self):
        assert _matches_name({"name": "Arthur", "slug": "arthur"}, {"rusty"}) is False

    def test_handles_missing_fields(self):
        assert _matches_name({}, {"arthur"}) is False


class TestPendingReferenceEntities:
    @pytest.mark.asyncio
    async def test_returns_named_entity_lacking_media_id(self):
        scene = {"id": "scene-001", "character_names": '["Arthur", "Rusty"]'}
        chars = [
            {"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None},
            {"id": "c2", "name": "Rusty", "slug": "rusty", "media_id": "media-2"},
        ]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            out = await _pending_reference_entities(scene, "proj-001")
        assert [c["id"] for c in out] == ["c1"]

    @pytest.mark.asyncio
    async def test_accepts_list_valued_character_names(self):
        scene = {"id": "scene-001", "character_names": ["Arthur"]}
        chars = [{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            out = await _pending_reference_entities(scene, "proj-001")
        assert [c["id"] for c in out] == ["c1"]

    @pytest.mark.asyncio
    async def test_returns_empty_when_scene_names_nobody(self):
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock()
            out = await _pending_reference_entities({"id": "s1", "character_names": None}, "proj-001")
        assert out == []
        mock_crud.get_project_characters.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_named_entities_have_media(self):
        scene = {"character_names": '["Arthur"]'}
        chars = [{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": "media-1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            out = await _pending_reference_entities(scene, "proj-001")
        assert out == []

    @pytest.mark.asyncio
    async def test_malformed_json_is_treated_as_no_names(self):
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock()
            out = await _pending_reference_entities({"character_names": "not json"}, "proj-001")
        assert out == []

    @pytest.mark.asyncio
    async def test_returns_empty_without_project_id(self):
        scene = {"character_names": '["Arthur"]'}
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_project_characters = AsyncMock()
            out = await _pending_reference_entities(scene, None)
        assert out == []
        mock_crud.get_project_characters.assert_not_called()


class TestReferenceWorkInFlight:
    @pytest.mark.asyncio
    async def test_true_for_processing_reference_request(self):
        entities = [{"id": "c1"}]
        rows = [{"type": "GENERATE_CHARACTER_IMAGE", "status": "PROCESSING", "character_id": "c1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _reference_work_in_flight("proj-001", entities) is True

    @pytest.mark.asyncio
    async def test_true_for_pending_reference_request(self):
        entities = [{"id": "c1"}]
        rows = [{"type": "GENERATE_CHARACTER_IMAGE", "status": "PENDING", "character_id": "c1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _reference_work_in_flight("proj-001", entities) is True

    @pytest.mark.asyncio
    async def test_false_when_reference_request_already_failed(self):
        """A FAILED reference request is not in flight — nothing will arrive."""
        entities = [{"id": "c1"}]
        rows = [{"type": "GENERATE_CHARACTER_IMAGE", "status": "FAILED", "character_id": "c1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _reference_work_in_flight("proj-001", entities) is False

    @pytest.mark.asyncio
    async def test_false_for_other_entities(self):
        entities = [{"id": "c1"}]
        rows = [{"type": "GENERATE_CHARACTER_IMAGE", "status": "PROCESSING", "character_id": "other"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _reference_work_in_flight("proj-001", entities) is False

    @pytest.mark.asyncio
    async def test_false_for_unrelated_request_type(self):
        entities = [{"id": "c1"}]
        rows = [{"type": "GENERATE_IMAGE", "status": "PROCESSING", "character_id": "c1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _reference_work_in_flight("proj-001", entities) is False


class TestPrerequisitesMetReferenceImages:
    @pytest.mark.asyncio
    async def test_defers_while_reference_image_is_being_generated(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        scene = {"id": "scene-001", "character_names": '["Arthur"]'}
        chars = [{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None}]
        rows = [{"type": "GENERATE_CHARACTER_IMAGE", "status": "PROCESSING", "character_id": "c1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=scene)
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            mock_crud.list_requests = AsyncMock(return_value=rows)
            assert await _prerequisites_met(req, "VERTICAL") is False

    @pytest.mark.asyncio
    async def test_does_not_defer_when_no_reference_work_is_in_flight(self):
        """Nothing is coming, so let _dispatch surface the error and fail once."""
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        scene = {"id": "scene-001", "character_names": '["Arthur"]'}
        chars = [{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=scene)
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            mock_crud.list_requests = AsyncMock(return_value=[])
            assert await _prerequisites_met(req, "VERTICAL") is True

    @pytest.mark.asyncio
    async def test_proceeds_when_all_references_present(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        scene = {"id": "scene-001", "character_names": '["Arthur"]'}
        chars = [{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": "media-1"}]
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=scene)
            mock_crud.get_project_characters = AsyncMock(return_value=chars)
            mock_crud.list_requests = AsyncMock()
            assert await _prerequisites_met(req, "VERTICAL") is True
        mock_crud.list_requests.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_scene_does_not_block(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value=None)
            assert await _prerequisites_met(req, "VERTICAL") is True

    @pytest.mark.asyncio
    async def test_video_prerequisite_still_defers_without_scene_image(self):
        req = make_req(req_type="GENERATE_VIDEO", scene_id="scene-001")
        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.get_scene = AsyncMock(return_value={"id": "scene-001"})
            assert await _prerequisites_met(req, "VERTICAL") is False


# ---------------------------------------------------------------------------
# _handle_failure — reference images are a non-retryable ordering answer
# ---------------------------------------------------------------------------

class TestHandleFailureReferenceImages:
    @pytest.mark.asyncio
    async def test_fails_immediately_instead_of_retrying(self):
        """retry_count=0 would normally retry — a missing reference image must not."""
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001", retry_count=0)
        rid = req["id"]
        result = {"error": "Waiting for reference images: arthur, rusty"}

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        mock_crud.update_request.assert_awaited_once()
        call_kwargs = mock_crud.update_request.call_args
        assert call_kwargs[1]["status"] == "FAILED"
        assert "retry_count" not in call_kwargs[1]

    @pytest.mark.asyncio
    async def test_error_message_is_actionable(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001", retry_count=0)
        rid = req["id"]
        result = {"error": "Waiting for reference images: arthur, rusty"}

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        msg = mock_crud.update_request.call_args[1]["error_message"]
        assert "arthur, rusty" in msg
        assert "GENERATE_CHARACTER_IMAGE" in msg

    @pytest.mark.asyncio
    async def test_marks_scene_image_failed(self):
        req = make_req(req_type="GENERATE_IMAGE", scene_id="scene-001", orientation="VERTICAL")
        rid = req["id"]
        result = {"error": "Waiting for reference images: arthur"}

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(rid, req, result)

        mock_crud.update_scene.assert_awaited_once_with("scene-001", vertical_image_status="FAILED")


# ---------------------------------------------------------------------------
# _handle_failure — an authorisation refusal is not retryable
# ---------------------------------------------------------------------------

class TestHandleFailureAccessDenied:
    """Measured on this deployment: Stickman Legends' GENERATE_VIDEO requests
    failed with PUBLIC_ERROR_MODEL_ACCESS_DENIED, were retried four times each
    over five minutes, and were refused identically every time before being
    marked FAILED. The retry budget bought nothing, and the operator ends up
    with the same failure they could have had immediately.
    """

    @pytest.mark.asyncio
    async def test_fails_immediately_instead_of_retrying(self):
        req = make_req(req_type="GENERATE_VIDEO", scene_id="scene-001", retry_count=0)
        result = {
            "error": (
                "RpcError: eb1hJf failed: [7, None, "
                "[['type.googleapis.com/google.rpc.ErrorInfo', "
                "['PUBLIC_ERROR_MODEL_ACCESS_DENIED']]]]"
            )
        }

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(req["id"], req, result)

        mock_crud.update_request.assert_awaited_once()
        kwargs = mock_crud.update_request.call_args[1]
        assert kwargs["status"] == "FAILED"
        assert "retry_count" not in kwargs

    @pytest.mark.asyncio
    async def test_error_message_says_what_to_do(self):
        req = make_req(req_type="GENERATE_VIDEO", scene_id="scene-001", retry_count=0)

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(req["id"], req, {"error": "PUBLIC_ERROR_MODEL_ACCESS_DENIED"})

        msg = mock_crud.update_request.call_args[1]["error_message"]
        assert "does not have access" in msg
        assert "Retrying cannot change that" in msg

    @pytest.mark.asyncio
    async def test_a_transient_error_still_retries(self):
        """Guard against over-matching: an ordinary failure keeps its retries."""
        req = make_req(req_type="GENERATE_VIDEO", scene_id="scene-001", retry_count=0)

        with patch("agent.worker.processor.crud") as mock_crud:
            mock_crud.update_request = AsyncMock()
            mock_crud.update_scene = AsyncMock()
            await _handle_failure(req["id"], req, {"error": "connection reset by peer"})

        kwargs = mock_crud.update_request.call_args[1]
        assert kwargs["status"] == "PENDING"
        assert kwargs["retry_count"] == 1
