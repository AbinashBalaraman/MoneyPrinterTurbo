"""Unit tests for the /api/characters route.

Regression guard: ``project_id`` used to be an undeclared query param, so FastAPI
silently ignored it and the endpoint answered with every character in the
database. Both the SCE client and scripts/generate_flowkit_stills.py pass it, so
the filter looked applied while doing nothing.
"""

from unittest.mock import AsyncMock, patch

from agent.api import characters as characters_api


def _client():
    """TestClient that never enters the lifespan.

    Entering it would run the app lifespan and start the worker against the real
    ``flow_agent.db``. Using it outside a context manager keeps this hermetic.
    """
    from starlette.testclient import TestClient

    from agent.main import app

    return TestClient(app)


class TestCharactersProjectFilter:
    def test_project_id_scopes_results_to_that_project(self):
        repo = AsyncMock()
        repo.get_project_characters = AsyncMock(
            return_value=[{"id": "c1", "name": "Arthur", "slug": "arthur", "media_id": None}]
        )

        with patch.object(characters_api, "_get_repo", return_value=repo):
            body = _client().get("/api/characters?project_id=proj-001").json()

        assert [c["id"] for c in body] == ["c1"]
        repo.get_project_characters.assert_awaited_once_with("proj-001")
        repo.list.assert_not_called()

    def test_no_project_id_returns_every_character(self):
        repo = AsyncMock()
        repo.list = AsyncMock(
            return_value=[
                {"id": "c1", "name": "Arthur", "slug": "arthur"},
                {"id": "c2", "name": "Rusty", "slug": "rusty"},
            ]
        )
        repo._row_to_character = lambda row: row

        with patch.object(characters_api, "_get_repo", return_value=repo):
            body = _client().get("/api/characters").json()

        assert sorted(c["id"] for c in body) == ["c1", "c2"]
        repo.get_project_characters.assert_not_called()
