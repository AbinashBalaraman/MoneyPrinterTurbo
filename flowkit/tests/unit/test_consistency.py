"""The conditioning report: what was *actually* conditioned, not what is linked.

Why the distinction matters
---------------------------
The obvious implementation checks whether a scene's declared characters are
currently linked to the project. That answers a different question and lies in
the case that matters most: an image generated while the characters were
unlinked is un-conditioned **forever** — linking afterwards does not
retroactively condition it. So the truth is recorded at generation time in
``scene.conditioned_with`` and read back here.

These tests pin all three states, and the negative cases that must stay clean.
A report that cries wolf is worse than no report.
"""

import json

import pytest

from agent.services import consistency


class _FakeCrud:
    def __init__(self, projects, linked, videos, scenes_by_video):
        self._projects = projects
        self._linked = linked
        self._videos = videos
        self._scenes = scenes_by_video

    async def list_projects(self):
        return self._projects

    async def get_project(self, pid):
        return next((p for p in self._projects if p["id"] == pid), None)

    async def get_project_characters(self, pid):
        return self._linked.get(pid, [])

    async def list_videos(self, project_id):
        return self._videos.get(project_id, [])

    async def list_scenes(self, video_id):
        return self._scenes.get(video_id, [])


def install(monkeypatch, fake):
    import agent.db.crud as real_crud

    for name in (
        "list_projects",
        "get_project",
        "get_project_characters",
        "list_videos",
        "list_scenes",
    ):
        monkeypatch.setattr(real_crud, name, getattr(fake, name))


def scene(sid, order, names, conditioned, status="COMPLETED"):
    """``conditioned=None`` writes a NULL column, i.e. unknown."""
    return {
        "id": sid,
        "display_order": order,
        "character_names": json.dumps(names) if names is not None else None,
        "conditioned_with": None if conditioned is None else json.dumps(conditioned),
        "vertical_image_status": status,
    }


PROJECT = {"id": "p1", "name": "farmer_and_rusty"}
VIDEOS = {"p1": [{"id": "v1", "title": "Ep 1"}]}
ARTHUR = {"id": "c1", "slug": "arthur", "name": "Arthur", "media_id": "m1"}


def run(monkeypatch, scenes, linked=None):
    fake = _FakeCrud(
        projects=[PROJECT],
        linked={"p1": linked if linked is not None else [ARTHUR]},
        videos=VIDEOS,
        scenes_by_video={"v1": scenes},
    )
    install(monkeypatch, fake)
    return consistency.unconditioned_scenes()


class TestConditionedIsFine:
    @pytest.mark.asyncio
    async def test_a_conditioned_scene_is_clean(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], ["arthur"])])
        assert out["clean"] is True
        assert out["scenes_checked"] == 1

    @pytest.mark.asyncio
    async def test_a_scene_naming_nobody_is_skipped(self, monkeypatch):
        """No declared characters means no reference image was ever needed."""
        out = await run(monkeypatch, [scene("s1", 0, [], [])])
        assert out["clean"] is True
        assert out["scenes_checked"] == 0

    @pytest.mark.asyncio
    async def test_a_scene_with_no_image_yet_is_not_flagged(self, monkeypatch):
        """Nothing generated means nothing can be wrong about the image."""
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], None, status="PENDING")])
        assert out["clean"] is True


class TestProvenUnconditioned:
    @pytest.mark.asyncio
    async def test_an_empty_record_is_proven_unconditioned(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], [])])
        assert out["clean"] is False
        assert len(out["unconditioned"]) == 1
        assert out["unconditioned"][0]["declared_names"] == ["arthur"]

    @pytest.mark.asyncio
    async def test_linking_afterwards_does_not_clear_a_proven_bad_image(self, monkeypatch):
        """The whole reason this report does not just read the project links."""
        # Arthur IS linked now, and has a reference image...
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], [])], linked=[ARTHUR])
        # ...but the recorded conditioning says the image got none of it.
        assert out["unlinked"] == []
        assert len(out["unconditioned"]) == 1
        assert out["clean"] is False


class TestUnverified:
    @pytest.mark.asyncio
    async def test_a_null_record_is_unverified_not_guessed(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], None)])
        assert len(out["unverified"]) == 1
        # Must not be asserted as either good or bad.
        assert out["unconditioned"] == []

    @pytest.mark.asyncio
    async def test_unverified_alone_does_not_make_a_project_unclean(self, monkeypatch):
        """A gap in evidence is not a known problem.

        Images generated before the conditioning column existed can be neither
        confirmed nor denied. Flagging every one of them red would make every
        older project look broken, and a report that cries wolf gets ignored.
        """
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], None)])
        assert out["unverified"]
        assert out["clean"] is True

    @pytest.mark.asyncio
    async def test_an_unparseable_record_is_unverified(self, monkeypatch):
        bad = scene("s1", 0, ["arthur"], None)
        bad["conditioned_with"] = "{not json"
        out = await run(monkeypatch, [bad])
        assert len(out["unverified"]) == 1
        assert out["clean"] is True


class TestUnlinked:
    @pytest.mark.asyncio
    async def test_a_declared_name_with_no_entity_is_unlinked(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["rusty"], ["arthur"])])
        assert len(out["unlinked"]) == 1
        assert out["unlinked"][0]["unlinked_names"] == ["rusty"]
        assert out["clean"] is False

    @pytest.mark.asyncio
    async def test_partially_linked_flags_only_the_missing_name(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["arthur", "rusty"], ["arthur"])])
        assert out["unlinked"][0]["unlinked_names"] == ["rusty"]

    @pytest.mark.asyncio
    async def test_matching_by_display_name_is_not_unlinked(self, monkeypatch):
        """The scene may name 'Arthur' while the entity slug is 'arthur'."""
        out = await run(monkeypatch, [scene("s1", 0, ["Arthur"], ["arthur"])])
        assert out["unlinked"] == []

    @pytest.mark.asyncio
    async def test_a_linked_entity_without_a_reference_image_still_links(self, monkeypatch):
        """No media_id means generation will block on a reference image, which is
        the pipeline's problem to report — not a silent inconsistency."""
        no_media = {"id": "c2", "slug": "rusty", "name": "Rusty", "media_id": None}
        out = await run(monkeypatch, [scene("s1", 0, ["rusty"], ["rusty"])], linked=[no_media])
        assert out["unlinked"] == []
        assert out["clean"] is True


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_malformed_character_names_does_not_raise(self, monkeypatch):
        bad = scene("s1", 0, None, None)
        bad["character_names"] = "{not json"
        out = await run(monkeypatch, [bad])
        assert out["clean"] is True

    @pytest.mark.asyncio
    async def test_no_projects_reports_clean_not_an_error(self, monkeypatch):
        fake = _FakeCrud(projects=[], linked={}, videos={}, scenes_by_video={})
        install(monkeypatch, fake)
        out = await consistency.unconditioned_scenes()
        assert out["clean"] is True
        assert out["project"] is None

    @pytest.mark.asyncio
    async def test_an_explicit_project_id_is_used(self, monkeypatch):
        fake = _FakeCrud(
            projects=[PROJECT, {"id": "p2", "name": "stickman_legends"}],
            linked={"p1": [ARTHUR], "p2": []},
            videos={"p1": [], "p2": [{"id": "v2", "title": "Ep 1"}]},
            scenes_by_video={"v2": [scene("s2", 0, ["red_blade"], [])]},
        )
        install(monkeypatch, fake)
        out = await consistency.unconditioned_scenes("p2")
        assert out["project"]["name"] == "stickman_legends"
        assert out["unlinked"][0]["unlinked_names"] == ["red_blade"]

    @pytest.mark.asyncio
    async def test_an_unknown_project_id_falls_back_to_the_newest(self, monkeypatch):
        out = await run(monkeypatch, [scene("s1", 0, ["arthur"], ["arthur"])])
        assert out["project"]["id"] == "p1"


class TestConditioningRecord:
    """The write path — this is what makes the report a fact instead of a guess.

    ``test_result_handler.py`` cannot run here (it needs the ``mocker`` fixture,
    and ``pytest-mock`` is not installed), so this covers the function those
    tests would have reached indirectly.
    """

    async def _record(self, monkeypatch, scene, linked, videos=None):
        import agent.db.crud as crud
        from agent.sdk.services import result_handler

        async def get_project_characters(pid):
            return linked

        async def get_video(vid):
            return (videos or {}).get(vid)

        monkeypatch.setattr(crud, "get_project_characters", get_project_characters)
        monkeypatch.setattr(crud, "get_video", get_video)
        return await result_handler._conditioning_record(scene)

    @pytest.mark.asyncio
    async def test_records_only_entities_with_a_reference_image(self, monkeypatch):
        scene = {"id": "s1", "_project_id": "p1", "character_names": json.dumps(["arthur", "rusty"])}
        linked = [
            {"id": "c1", "slug": "arthur", "name": "Arthur", "media_id": "m1"},
            {"id": "c2", "slug": "rusty", "name": "Rusty", "media_id": None},
        ]
        out = await self._record(monkeypatch, scene, linked)
        assert json.loads(out) == ["arthur"]

    @pytest.mark.asyncio
    async def test_unlinked_names_record_as_an_empty_list(self, monkeypatch):
        """The Stickman Legends case: names declared, nothing linked.

        An empty list is the honest record — it is what makes the scene report
        as proven un-conditioned later rather than silently fine.
        """
        scene = {"id": "s1", "_project_id": "p1", "character_names": json.dumps(["red_blade"])}
        out = await self._record(monkeypatch, scene, [])
        assert json.loads(out) == []

    @pytest.mark.asyncio
    async def test_a_scene_naming_nobody_records_empty(self, monkeypatch):
        scene = {"id": "s1", "_project_id": "p1", "character_names": json.dumps([])}
        out = await self._record(monkeypatch, scene, [])
        assert json.loads(out) == []

    @pytest.mark.asyncio
    async def test_the_project_is_resolved_through_the_video_when_absent(self, monkeypatch):
        scene = {"id": "s1", "video_id": "v1", "character_names": json.dumps(["arthur"])}
        linked = [{"id": "c1", "slug": "arthur", "name": "Arthur", "media_id": "m1"}]
        out = await self._record(monkeypatch, scene, linked, videos={"v1": {"project_id": "p1"}})
        assert json.loads(out) == ["arthur"]

    @pytest.mark.asyncio
    async def test_no_project_at_all_records_empty_rather_than_raising(self, monkeypatch):
        scene = {"id": "s1", "character_names": json.dumps(["arthur"])}
        out = await self._record(monkeypatch, scene, [])
        assert json.loads(out) == []
