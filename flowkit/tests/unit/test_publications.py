"""Publish outcomes reported by shorts_content_engine.

The rule under test throughout: **a simulated upload is never a publication.**
The original defect was a dry run recorded as a real post, which made an empty
pipeline look like it had shipped. That is now enforced in three places — the
API model, the CRUD layer, and a CHECK constraint on the table — and each of
those is pinned here, because a rule with three enforcement points is a rule
with three places to regress.
"""

import asyncio
import sqlite3

import pytest

from agent.models.publication import (
    PublicationCreate,
    PublicationSummary,
)


# ---------------------------------------------------------------------------
# The summary rule
# ---------------------------------------------------------------------------

class TestSummary:
    def test_a_dry_run_never_counts_as_live(self):
        s = PublicationSummary.from_rows([{"status": "dry_run", "is_mock": 1}])
        assert s.live == 0
        assert s.dry_run == 1
        assert s.is_dry_run is True
        # `is_dry_run` is what the panel keys off to say "nothing was posted".
        # `is_unpublished` means "never attempted", and a dry run *was* an
        # attempt — conflating the two would make the panel claim the pipeline
        # had not run when it demonstrably had.
        assert s.is_unpublished is False

    def test_a_real_publication_counts_as_live(self):
        s = PublicationSummary.from_rows([{"status": "published", "is_mock": 0}])
        assert s.live == 1
        assert s.is_dry_run is False
        assert s.is_unpublished is False

    def test_mixed_dry_run_and_live_is_not_a_dry_run(self):
        s = PublicationSummary.from_rows([
            {"status": "published", "is_mock": 0},
            {"status": "dry_run", "is_mock": 1},
        ])
        assert (s.live, s.dry_run) == (1, 1)
        assert s.is_dry_run is False

    def test_a_published_row_flagged_mock_is_not_live(self):
        """Belt and braces: status alone must not be trusted if is_mock is set."""
        s = PublicationSummary.from_rows([{"status": "published", "is_mock": 1}])
        assert s.live == 0

    def test_failures_and_requests_are_counted_separately(self):
        s = PublicationSummary.from_rows([
            {"status": "failed", "is_mock": 0},
            {"status": "requested", "is_mock": 0},
        ])
        assert (s.failed, s.requested) == (1, 1)
        assert s.live == 0
        # A queued retry means it *has* been attempted, so not "unpublished".
        assert s.is_unpublished is False

    def test_no_rows_at_all_is_unpublished(self):
        s = PublicationSummary.from_rows([])
        assert s.total == 0
        assert s.is_unpublished is True
        assert s.is_dry_run is False


# ---------------------------------------------------------------------------
# Request validation (the API boundary)
# ---------------------------------------------------------------------------

class TestValidation:
    def test_simulated_upload_cannot_be_published(self):
        with pytest.raises(ValueError, match="dry_run"):
            PublicationCreate(platform="youtube", is_mock=True, status="published")

    def test_simulated_upload_cannot_carry_a_url(self):
        with pytest.raises(ValueError, match="url or post_id"):
            PublicationCreate(
                platform="youtube", is_mock=True, status="dry_run",
                video_url="https://youtu.be/fake",
            )

    def test_simulated_upload_cannot_carry_a_post_id(self):
        with pytest.raises(ValueError, match="url or post_id"):
            PublicationCreate(
                platform="youtube", is_mock=True, status="dry_run", post_id="abc123",
            )

    def test_a_clean_dry_run_is_accepted(self):
        p = PublicationCreate(platform="YouTube", is_mock=True, status="dry_run")
        assert p.platform == "youtube"  # normalised
        assert p.video_url is None

    def test_published_requires_a_platform_post_id(self):
        """A 200 with no id is a failure, not a publication."""
        with pytest.raises(ValueError, match="post_id"):
            PublicationCreate(platform="youtube", status="published")

    def test_failed_requires_an_error_message(self):
        with pytest.raises(ValueError, match="error_message"):
            PublicationCreate(platform="tiktok", status="failed")

    def test_blank_platform_is_rejected(self):
        with pytest.raises(ValueError, match="platform is required"):
            PublicationCreate(platform="   ")


# ---------------------------------------------------------------------------
# Storage — against a real database, so the CHECK constraint is exercised
# ---------------------------------------------------------------------------

@pytest.fixture
async def db(tmp_path, monkeypatch):
    """A real temp database with the real schema.

    Deliberately not stubbed: the honesty rule is enforced by a CHECK
    constraint, and a stubbed CRUD layer would not prove the constraint exists.
    """
    from agent.db import schema as schema_mod

    monkeypatch.setattr(schema_mod, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(schema_mod, "_db_connection", None)
    await schema_mod.init_db()
    try:
        yield schema_mod
    finally:
        await schema_mod.close_db()
        monkeypatch.setattr(schema_mod, "_db_connection", None)


async def _make_video():
    from agent.db import crud

    project = await crud.create_project(name="P")
    video = await crud.create_video(project["id"], title="V")
    return project, video


class TestStorage:
    async def test_a_dry_run_round_trips_without_a_url(self, db):
        from agent.db import crud

        _, video = await _make_video()
        row = await crud.record_publication(
            video_id=video["id"], platform="YouTube", status="dry_run",
            is_mock=True, metadata={"note": "simulated"},
        )
        assert row["platform"] == "youtube"
        assert row["is_mock"] == 1
        assert row["video_url"] is None
        assert row["post_id"] is None

    async def test_a_real_publication_stores_its_post_id_and_url(self, db):
        from agent.db import crud

        _, video = await _make_video()
        row = await crud.record_publication(
            video_id=video["id"], platform="youtube", status="published",
            post_id="dQw4w9WgXcQ", video_url="https://youtu.be/dQw4w9WgXcQ",
        )
        assert row["is_mock"] == 0
        assert row["post_id"] == "dQw4w9WgXcQ"

    async def test_crud_refuses_a_mock_recorded_as_published(self, db):
        from agent.db import crud

        _, video = await _make_video()
        with pytest.raises(ValueError, match="simulated upload"):
            await crud.record_publication(
                video_id=video["id"], platform="youtube",
                status="published", is_mock=True, post_id="x",
            )

    async def test_the_database_itself_rejects_a_mock_that_looks_published(self, db):
        """The CHECK constraint, bypassing the CRUD guards entirely."""
        _, video = await _make_video()
        conn = await db.get_db()
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                """INSERT INTO publication
                   (id,video_id,platform,status,post_id,video_url,is_mock,metadata,published_at,created_at,updated_at)
                   VALUES ('x','{}','youtube','published','p1','https://youtu.be/p1',1,'{{}}','now','now','now')""".format(video["id"])
            )

    async def test_listing_is_newest_first(self, db):
        from agent.db import crud

        _, video = await _make_video()
        await crud.record_publication(video_id=video["id"], platform="tiktok", status="dry_run", is_mock=True)
        await crud.record_publication(video_id=video["id"], platform="youtube", status="published", post_id="p1")
        rows = await crud.list_publications(video["id"])
        assert rows[0]["platform"] == "youtube"

    async def test_retry_is_idempotent_while_one_is_already_queued(self, db):
        from agent.db import crud

        _, video = await _make_video()
        first = await crud.request_publication_retry(video_id=video["id"], platform="youtube")
        second = await crud.request_publication_retry(video_id=video["id"], platform="youtube")
        assert first["id"] == second["id"]
        assert len(await crud.list_publications_by_status("requested")) == 1

    async def test_retry_after_a_failure_creates_a_new_row(self, db):
        from agent.db import crud

        _, video = await _make_video()
        await crud.record_publication(
            video_id=video["id"], platform="youtube", status="failed",
            error_message="quota exceeded",
        )
        row = await crud.request_publication_retry(video_id=video["id"], platform="youtube")
        assert row["status"] == "requested"
        assert len(await crud.list_publications(video["id"])) == 2


# ---------------------------------------------------------------------------
# HTTP contract
# ---------------------------------------------------------------------------

class TestEndpoints:
    """CRUD is stubbed here so the test needs no shared event loop.

    ``TestClient`` runs the app on its own loop, and the shared database
    connection is bound to whichever loop created it — the same reason the log
    bus tests stub rather than connect.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        from starlette.testclient import TestClient

        from agent.db import crud
        from agent.main import app

        async def _video(vid):
            return {"id": vid, "project_id": "p1", "title": "V"}

        async def _empty(video_id):
            return []

        monkeypatch.setattr(crud, "get_video", _video)
        monkeypatch.setattr(crud, "list_publications", _empty)

        return TestClient(app)

    def test_list_returns_empty_summary_for_a_fresh_video(self, client):
        r = client.get("/api/videos/v1/publications")
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["is_unpublished"] is True
        assert body["publications"] == []

    def test_unknown_video_is_a_404(self, client, monkeypatch):
        from agent.db import crud

        async def _none(vid):
            return None

        monkeypatch.setattr(crud, "get_video", _none)
        assert client.get("/api/videos/nope/publications").status_code == 404

    def test_a_mock_published_report_is_rejected_as_422(self, client):
        """422, not 500: the honesty rules must be a client error."""
        r = client.post("/api/videos/v1/publications", json={
            "platform": "youtube", "status": "published", "is_mock": True, "post_id": "x",
        })
        assert r.status_code == 422

    def test_published_without_a_post_id_is_rejected(self, client):
        r = client.post("/api/videos/v1/publications", json={
            "platform": "youtube", "status": "published",
        })
        assert r.status_code == 422

    def test_pending_lists_queued_retries(self, client, monkeypatch):
        from agent.db import crud

        async def _pending(status):
            assert status == "requested"
            return [{
                "id": "pub1", "video_id": "v1", "project_id": "p1",
                "platform": "youtube", "status": "requested", "is_mock": 0,
                "metadata": "{}",
            }]

        monkeypatch.setattr(crud, "list_publications_by_status", _pending)
        r = client.get("/api/publications/pending")
        assert r.status_code == 200
        assert r.json()[0]["platform"] == "youtube"

    def test_malformed_metadata_does_not_break_the_list(self, client, monkeypatch):
        from agent.db import crud

        async def _bad(video_id):
            return [{
                "id": "pub1", "video_id": "v1", "project_id": "p1",
                "platform": "youtube", "status": "dry_run", "is_mock": 1,
                "metadata": "{not json",
            }]

        monkeypatch.setattr(crud, "list_publications", _bad)
        r = client.get("/api/videos/v1/publications")
        assert r.status_code == 200
        assert "_unparsable" in r.json()["publications"][0]["metadata"]
