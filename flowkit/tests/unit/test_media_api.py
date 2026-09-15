"""Unit tests for the media streaming and inspection API (/api/media)."""

import pytest
from pathlib import Path
from starlette.testclient import TestClient

from agent.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_list_artifacts(client):
    """Test listing media artifacts across workspace directories."""
    resp = client.get("/api/media/artifacts?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "artifacts" in data
    assert "total" in data
    assert isinstance(data["artifacts"], list)


def test_stream_media_file_not_found(client):
    """Test requesting a non-existent media file returns 404."""
    resp = client.get("/api/media/file?path=non_existent_video_12345.mp4")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


def test_stream_media_file_traversal_blocked(client):
    """Test path traversal attempts outside workspace are blocked with 403."""
    resp = client.get("/api/media/file?path=../../../../../../../../Windows/System32/cmd.exe")
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


def test_stream_and_inspect_valid_file(client, tmp_path):
    """Test inspecting and streaming a real media file created in the workspace."""
    from agent.api.media import WORKSPACE_ROOT
    
    # Create a dummy test image within workspace output directory
    test_dir = WORKSPACE_ROOT / "output"
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "test_preview_sample.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    try:
        # Inspect
        inspect_resp = client.get(f"/api/media/inspect?path=output/{test_file.name}")
        assert inspect_resp.status_code == 200
        inspect_data = inspect_resp.json()
        assert inspect_data["name"] == test_file.name
        assert inspect_data["type"] == "image"
        assert inspect_data["mime_type"] == "image/png"
        assert inspect_data["size_bytes"] > 0

        # Stream
        stream_resp = client.get(f"/api/media/file?path=output/{test_file.name}")
        assert stream_resp.status_code == 200
        assert stream_resp.headers["content-type"] == "image/png"
        assert len(stream_resp.content) == test_file.stat().st_size
    finally:
        if test_file.exists():
            test_file.unlink()
