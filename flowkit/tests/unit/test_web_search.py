"""Unit tests for the TinyFish web search service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.services import web_search


class _FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _client_factory(resp):
    """Patch target for httpx.AsyncClient used via `async with`."""
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=cm), client


# ---------------------------------------------------------------------------
# normalise
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_trims_to_max_results(self):
        payload = {"query": "q", "total_results": 10,
                   "results": [{"position": i, "title": f"t{i}", "url": f"u{i}"} for i in range(1, 11)]}
        out = web_search.normalise(payload, 3)
        assert len(out["results"]) == 3
        assert out["total_results"] == 10

    def test_fills_missing_fields_with_empty_strings(self):
        out = web_search.normalise({"results": [{"url": "https://x"}]}, 5)
        res = out["results"][0]
        assert res["title"] == ""
        assert res["snippet"] == ""
        assert res["site_name"] == ""

    def test_skips_non_dict_items(self):
        out = web_search.normalise({"results": ["junk", {"url": "https://ok"}]}, 5)
        assert [r["url"] for r in out["results"]] == ["https://ok"]

    def test_handles_missing_results_key(self):
        assert web_search.normalise({}, 5)["results"] == []


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_reports_missing_key_instead_of_calling_api(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "")
        out = await web_search.search("hello")
        assert "TINYFISH_API_KEY" in out["error"]

    @pytest.mark.asyncio
    async def test_rejects_blank_query(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "key")
        out = await web_search.search("   ")
        assert "Empty" in out["error"]

    @pytest.mark.asyncio
    async def test_sends_api_key_header_and_query(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "secret-key")
        factory, client = _client_factory(_FakeResp(payload={
            "query": "veo", "total_results": 1,
            "results": [{"position": 1, "title": "T", "url": "https://t", "snippet": "S"}],
        }))

        with patch("agent.services.web_search.httpx.AsyncClient", factory):
            out = await web_search.search("veo", max_results=5)

        kwargs = client.get.call_args.kwargs
        assert kwargs["headers"]["X-API-Key"] == "secret-key"
        assert kwargs["params"]["query"] == "veo"
        assert out["results"][0]["title"] == "T"

    @pytest.mark.asyncio
    async def test_optional_params_are_only_sent_when_provided(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "key")
        factory, client = _client_factory(_FakeResp(payload={"results": []}))

        with patch("agent.services.web_search.httpx.AsyncClient", factory):
            await web_search.search("q", purpose="find a library", recency_minutes=60,
                                    location="IN", language="en", domain_type="news")

        params = client.get.call_args.kwargs["params"]
        assert params["purpose"] == "find a library"
        assert params["recency_minutes"] == 60
        assert params["location"] == "IN"
        assert params["language"] == "en"
        assert params["domain_type"] == "news"

    @pytest.mark.asyncio
    async def test_purpose_is_trimmed_to_upstream_limit(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "key")
        factory, client = _client_factory(_FakeResp(payload={"results": []}))

        with patch("agent.services.web_search.httpx.AsyncClient", factory):
            await web_search.search("q", purpose="x" * 5000)

        assert len(client.get.call_args.kwargs["params"]["purpose"]) == 2000

    @pytest.mark.asyncio
    async def test_http_error_returns_error_dict_not_exception(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "key")
        factory, _ = _client_factory(_FakeResp(status=403, text="forbidden"))

        with patch("agent.services.web_search.httpx.AsyncClient", factory):
            out = await web_search.search("q")

        assert "403" in out["error"]

    @pytest.mark.asyncio
    async def test_non_json_response_is_handled(self, monkeypatch):
        monkeypatch.setattr(web_search, "TINYFISH_API_KEY", "key")
        factory, _ = _client_factory(_FakeResp(status=200, payload=None))

        with patch("agent.services.web_search.httpx.AsyncClient", factory):
            out = await web_search.search("q")

        assert "non-JSON" in out["error"]
