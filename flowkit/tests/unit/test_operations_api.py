"""Unit tests for /api/operations routes."""

from unittest.mock import AsyncMock, patch
from starlette.testclient import TestClient

from agent.main import app
from agent.operations import registry


def _client():
    return TestClient(app)


def test_get_operations_returns_catalog():
    client = _client()
    resp = client.get("/api/operations")
    assert resp.status_code == 200
    data = resp.json()
    assert "departments" in data
    assert "operations" in data
    assert "by_department" in data
    assert "capabilities" in data
    assert len(data["operations"]) >= 21
    # Check that known departments exist
    assert "ingest" in data["by_department"]
    assert "render" in data["by_department"]
    assert "director" in data["by_department"]
    assert "assembly" in data["by_department"]
    assert "post" in data["by_department"]
    assert "publish" in data["by_department"]


def test_run_operation_not_found():
    client = _client()
    resp = client.post("/api/operations/run", json={"name": "non_existent_op", "args": {}})
    assert resp.status_code == 404


def test_run_operation_read_success():
    client = _client()
    # Test validate_script with a valid sample manifest
    manifest = {
        "scenes": [
            {"duration": 8, "phase": "Hook", "image_prompt": "Prompt 1", "narrator_text": "Text 1"},
            {"duration": 8, "phase": "Rising", "image_prompt": "Prompt 2", "narrator_text": "Text 2"},
            {"duration": 8, "phase": "Complication", "image_prompt": "Prompt 3", "narrator_text": "Text 3"},
            {"duration": 8, "phase": "Climax", "image_prompt": "Prompt 4", "narrator_text": "Text 4"},
            {"duration": 8, "phase": "Loop", "image_prompt": "Prompt 5", "narrator_text": "Text 5"},
        ]
    }
    resp = client.post("/api/operations/run", json={"name": "validate_script", "args": {"manifest": manifest}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["operation"] == "validate_script"
    assert data["result"]["valid"] is True


def test_run_operation_spend_gated():
    client = _client()
    with patch("agent.config.AGENT_ALLOW_SPEND", False):
        resp = client.post("/api/operations/run", json={"name": "generate_episode", "args": {"manifest_path": "foo.json"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["refused"] is True
        assert "spends money" in data["error"]
