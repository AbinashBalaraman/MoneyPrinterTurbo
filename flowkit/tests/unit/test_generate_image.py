"""generate_image operation: single standalone Flow still, spend-gated.

Uses monkeypatched crud throughout — never touches the shared SQLite file,
which can block on the agent's lock.
"""

import pytest

from agent.operations import registry

registry.all_operations()  # force the full catalog load before direct module import

from agent.operations import render as render_ops
from agent.operations.registry import OperationError, get


def _async(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _patch_crud(monkeypatch, project=None, videos=(), scenes=()):
    from agent.db import crud

    monkeypatch.setattr(
        crud, "get_project", _async(project if project is not None else {"id": "p1", "name": "Demo"})
    )
    monkeypatch.setattr(crud, "list_projects", _async([{"id": "p1", "name": "Demo"}]))
    monkeypatch.setattr(crud, "list_videos", _async(list(videos)))
    created = {}

    async def _create_video(**kw):
        video = {"id": "v-new", **kw}
        created["video"] = video
        return video

    async def _create_scene(**kw):
        scene = {"id": "s-new", **kw}
        created["scene"] = scene
        return scene

    async def _create_request(req_type, **kw):
        req = {"id": "r-new", "type": req_type, "status": "PENDING", **kw}
        created["request"] = req
        return req

    monkeypatch.setattr(crud, "create_video", _create_video)
    monkeypatch.setattr(crud, "list_scenes", _async(list(scenes)))
    monkeypatch.setattr(crud, "create_scene", _create_scene)
    monkeypatch.setattr(crud, "create_request", _create_request)
    return created


def test_registered_as_spend():
    assert get("generate_image").risk == "spend"
    assert get("generate_image").department == "render"


@pytest.mark.asyncio
async def test_rejects_empty_prompt(monkeypatch):
    _patch_crud(monkeypatch)
    with pytest.raises(OperationError):
        await render_ops.generate_image("   ")


@pytest.mark.asyncio
async def test_rejects_bad_orientation(monkeypatch):
    _patch_crud(monkeypatch)
    with pytest.raises(OperationError):
        await render_ops.generate_image("a cat", orientation="SQUARE")


@pytest.mark.asyncio
async def test_creates_oneoff_video_scene_and_request(monkeypatch):
    created = _patch_crud(monkeypatch)
    out = await render_ops.generate_image("a tabby cat in a barn doorway")
    assert out["request_id"] == "r-new"
    assert out["status"] == "PENDING"
    assert out["orientation"] == "VERTICAL"
    assert created["video"]["title"] == "One-off images"
    assert created["scene"]["image_prompt"] == "a tabby cat in a barn doorway"
    assert created["request"]["type"] == "GENERATE_IMAGE"
    assert created["request"]["scene_id"] == "s-new"


@pytest.mark.asyncio
async def test_reuses_existing_oneoff_video(monkeypatch):
    existing = {"id": "v-old", "title": "One-off images"}
    created = _patch_crud(
        monkeypatch, videos=[existing, {"id": "v-ep", "title": "Episode 1"}], scenes=[{"id": "s0"}]
    )
    out = await render_ops.generate_image("a cat", project_id="p1")
    assert out["video_id"] == "v-old"
    assert "video" not in created  # no new video minted
    assert created["scene"]["display_order"] == 1


@pytest.mark.asyncio
async def test_refused_without_spend_enabled(monkeypatch):
    from agent import config
    from agent.services import chat_agent

    monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", False)
    out = await chat_agent.execute_tool("generate_image", {"prompt": "a cat"})
    assert out["ok"] is False
    assert out.get("refused") is True
