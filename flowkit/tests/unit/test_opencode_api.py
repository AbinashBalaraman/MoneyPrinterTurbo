"""OpenCode routing: the agent, not the browser, decides how to talk to a model.

What this pins down
-------------------
The dashboard used to hold its own model list *and* its own guess at each
model's protocol::

    endpoint: isResponses ? 'responses' : 'chat/completions'

Two things followed. A live API key shipped inside the JS bundle, and a model
whose real endpoint was ``responses`` but whose id did not contain
``muse-spark`` was sent to ``chat/completions`` -- failing in a way that looked
like a broken model rather than a routing bug.

So the tests below are mostly about *refusal to guess*: an unknown model is
rejected rather than quietly swapped, an unsupported reasoning tier is rejected
rather than silently dropped, and the protocol comes from the catalogue entry
even when the model id gives no hint.
"""

import json

import httpx
import pytest

from agent.services.opencode_models import (
    CANONICAL_FREE_MODELS,
    ENDPOINT_CHAT_COMPLETIONS,
    ENDPOINT_RESPONSES,
    ModelInfo,
    build_request_payload,
    endpoint_path,
    parse_chat_response,
    resolve_endpoint_type,
    resolve_model_reasoning,
)

API_KEY = "sk-test-not-a-real-key"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text if text is not None else json.dumps(self._payload)

    def json(self):
        return self._payload


class _FakeStreamResponse:
    """A streaming response, as httpx exposes one."""

    def __init__(self, status_code=200, lines=None, body=b""):
        self.status_code = status_code
        self._lines = list(lines or [])
        self._body = body

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _AsyncCtx:
    """Minimal async context manager wrapping a value."""

    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, *exc):
        return False


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient and records what was sent."""

    calls: list = []
    response: _FakeResponse = _FakeResponse()
    stream_response: _FakeStreamResponse = _FakeStreamResponse()

    def __init__(self, *args, **kwargs):
        _FakeAsyncClient.calls.append(("init", args, kwargs))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None):
        _FakeAsyncClient.calls.append(("get", url, headers))
        return _FakeAsyncClient.response

    async def post(self, url, headers=None, json=None, data=None):
        _FakeAsyncClient.calls.append(("post", url, headers, json))
        return _FakeAsyncClient.response

    def stream(self, method, url, headers=None, json=None, data=None):
        _FakeAsyncClient.calls.append(("stream", method, url, headers, json))
        return _AsyncCtx(_FakeAsyncClient.stream_response)

    @classmethod
    def last_post(cls):
        for entry in reversed(cls.calls):
            if entry[0] == "post":
                return entry
        return None

    @classmethod
    def last_stream(cls):
        for entry in reversed(cls.calls):
            if entry[0] == "stream":
                return entry
        return None

    @classmethod
    def reset(cls, response=None, stream_response=None):
        cls.calls = []
        cls.response = response or _FakeResponse()
        cls.stream_response = stream_response or _FakeStreamResponse()


class _StubCatalogue:
    """A catalogue whose contents the test dictates."""

    def __init__(self, models, source="api", error=None):
        self._models = models
        self.last_source = source
        self.last_error = error

    async def get(self, api_key=None, base_url=None):
        return self._models

    @property
    def cached_count(self):
        return len(self._models)

    @property
    def builtin_count(self):
        return len(CANONICAL_FREE_MODELS)

    def invalidate(self):
        pass


@pytest.fixture(autouse=True)
def _fake_http(monkeypatch):
    """Route every outbound httpx call through the fake."""
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.reset()
    yield
    _FakeAsyncClient.reset()


@pytest.fixture(autouse=True)
def _fresh_catalogue(monkeypatch):
    """The catalogue is a module-level singleton; drop it between tests."""
    from agent.services import opencode_models

    monkeypatch.setattr(opencode_models, "_catalogue", None)
    yield


@pytest.fixture(autouse=True)
def _no_key_by_default(monkeypatch):
    """Keep the provider-key state hermetic.

    `agent.config` reads the shared repository `.env`, so on a real developer
    machine these are usually populated. The "not configured" cases below must
    not depend on that ambient state, so pin them empty here and let the
    `with_key` fixture opt in explicitly.

    All three are pinned, not just OpenCode. `_is_configured` in
    `agent/api/opencode.py` accepts GEMINI_API_KEY or NVIDIA_API_KEY as
    fallbacks, because the assistant routes to those providers when OpenCode is
    unavailable. Pinning only OPENCODE_API_KEY leaves the endpoint configured,
    so these tests failed on every machine holding a Gemini or NVIDIA key.
    """
    from agent import config

    for name in ("OPENCODE_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.setattr(config, name, "")
    yield


@pytest.fixture
def client():
    """TestClient that does NOT run the lifespan (which would start the worker)."""
    from starlette.testclient import TestClient

    from agent.main import app

    return TestClient(app)


@pytest.fixture
def with_key(monkeypatch):
    from agent import config

    monkeypatch.setattr(config, "OPENCODE_API_KEY", API_KEY)
    return API_KEY


# ---------------------------------------------------------------------------
# Protocol resolution
# ---------------------------------------------------------------------------

class TestEndpointResolution:
    def test_names_map_to_paths(self):
        assert endpoint_path(ENDPOINT_RESPONSES) == "/responses"
        # The name has a hyphen; the URL path has a slash. That mismatch is
        # precisely what drifted between the two projects before.
        assert endpoint_path(ENDPOINT_CHAT_COMPLETIONS) == "/chat/completions"

    def test_unknown_endpoint_type_is_an_error_not_a_default(self):
        with pytest.raises(ValueError):
            endpoint_path("chat/completions")

    def test_muse_spark_speaks_the_responses_protocol(self):
        assert resolve_endpoint_type("muse-spark-1.3-contributor-free") == ENDPOINT_RESPONSES

    def test_everything_else_speaks_chat_completions(self):
        for model_id in (
            "deepseek-v4-flash-free",
            "mimo-v2.5-free",
            "nemotron-3-ultra-free",
            "some-model-nobody-has-heard-of",
        ):
            assert resolve_endpoint_type(model_id) == ENDPOINT_CHAT_COMPLETIONS

    def test_reasoning_tiers_follow_the_family(self):
        assert resolve_model_reasoning("muse-spark-1.3-contributor-free")[0][0] == "xhigh"
        assert resolve_model_reasoning("deepseek-v4-flash-free") == (["high", "medium", "off"], "high")
        assert resolve_model_reasoning("nemotron-3-ultra-free") == (["off"], "off")

    def test_the_canonical_list_is_usable_with_no_network(self):
        assert CANONICAL_FREE_MODELS
        for model in CANONICAL_FREE_MODELS:
            assert model.endpoint_type in (ENDPOINT_RESPONSES, ENDPOINT_CHAT_COMPLETIONS)
            assert model.default_reasoning in model.supported_reasoning

    def test_to_dict_uses_the_canonical_field_name(self):
        payload = CANONICAL_FREE_MODELS[0].to_dict()
        assert "endpoint_type" in payload
        assert "endpoint" not in payload


class TestPayloadBuilding:
    def test_responses_protocol_uses_input_and_reasoning_effort(self):
        payload = build_request_payload(
            model_id="muse-spark-1.3-contributor-free",
            endpoint_type=ENDPOINT_RESPONSES,
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="xhigh",
        )
        assert payload["input"] == [{"role": "user", "content": "hi"}]
        assert payload["reasoning"] == {"effort": "xhigh"}
        assert "messages" not in payload

    def test_chat_protocol_uses_messages_and_reasoning_effort(self):
        payload = build_request_payload(
            model_id="deepseek-v4-flash-free",
            endpoint_type=ENDPOINT_CHAT_COMPLETIONS,
            messages=[{"role": "user", "content": "hi"}],
            reasoning_effort="high",
        )
        assert payload["messages"] == [{"role": "user", "content": "hi"}]
        assert payload["reasoningEffort"] == "high"
        assert "input" not in payload

    def test_reasoning_off_is_omitted_entirely(self):
        """`off` means "do not ask for reasoning", not `effort: "off"`."""
        for endpoint_type, key in (
            (ENDPOINT_RESPONSES, "reasoning"),
            (ENDPOINT_CHAT_COMPLETIONS, "reasoningEffort"),
        ):
            payload = build_request_payload("m", endpoint_type, [], reasoning_effort="off")
            assert key not in payload

    def test_unknown_endpoint_type_raises(self):
        with pytest.raises(ValueError):
            build_request_payload("m", "nonsense", [])


class TestResponseParsing:
    def test_responses_protocol_is_normalised(self):
        parsed = parse_chat_response(ENDPOINT_RESPONSES, {
            "output": [
                {"type": "reasoning", "summary": ["step one", "step two"]},
                {"type": "message", "content": [{"type": "output_text", "text": "hello"}]},
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "total_tokens": 30,
                "output_tokens_details": {"reasoning_tokens": 7},
            },
        })
        assert parsed["text"] == "hello"
        assert parsed["thought_trace"] == "step one\nstep two"
        assert parsed["reasoning_tokens"] == 7
        assert parsed["input_tokens"] == 10

    def test_chat_protocol_is_normalised_to_the_same_shape(self):
        parsed = parse_chat_response(ENDPOINT_CHAT_COMPLETIONS, {
            "choices": [{"message": {"content": "hello", "reasoning_content": "thinking"}}],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 7},
            },
        })
        assert parsed["text"] == "hello"
        assert parsed["thought_trace"] == "thinking"
        assert parsed["reasoning_tokens"] == 7
        assert parsed["input_tokens"] == 10

    def test_a_response_with_no_usage_does_not_invent_numbers(self):
        parsed = parse_chat_response(ENDPOINT_CHAT_COMPLETIONS, {"choices": [{"message": {"content": "x"}}]})
        assert parsed["reasoning_tokens"] == 0
        assert parsed["input_tokens"] == 0
        assert parsed["total_tokens"] == 0


# ---------------------------------------------------------------------------
# /api/opencode/status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_reports_not_configured_without_a_key(self, client):
        body = client.get("/api/opencode/status").json()
        assert body["configured"] is False
        assert body["models_builtin"] == len(CANONICAL_FREE_MODELS)

    def test_never_returns_the_key(self, client, with_key):
        body = client.get("/api/opencode/status").json()
        assert body["configured"] is True
        assert with_key not in json.dumps(body)

    def test_counts_are_zero_before_the_catalogue_is_fetched(self, client):
        body = client.get("/api/opencode/status").json()
        assert body["models_cached"] == 0
        # The built-in count is what the UI falls back to, so it is always real.
        assert body["models_builtin"] > 0


# ---------------------------------------------------------------------------
# /api/opencode/models
# ---------------------------------------------------------------------------

class TestModels:
    def test_without_a_key_the_builtins_stand_and_are_labelled_as_such(self, client):
        body = client.get("/api/opencode/models").json()
        assert body["source"] == "builtin"
        assert body["key_configured"] is False
        assert {m["id"] for m in body["models"]} >= {m.id for m in CANONICAL_FREE_MODELS}
        # Nothing may claim to be live when no call was made.
        assert all(m["source"] == "builtin" for m in body["models"])

    def test_a_failed_live_fetch_degrades_instead_of_erroring(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(500, text="upstream exploded")

        body = client.get("/api/opencode/models").json()

        assert body["source"] == "builtin"
        assert body["models"]
        # The reason is reported rather than swallowed.
        assert body["error"]

    def test_a_live_fetch_merges_and_is_labelled_api(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {
            "data": [{"id": "some-new-model", "name": "Some New Model"}]
        })

        body = client.get("/api/opencode/models").json()

        ids = {m["id"] for m in body["models"]}
        assert "some-new-model" in ids
        # The canonical entries are still there, so the UI never ends up empty.
        assert {m.id for m in CANONICAL_FREE_MODELS} <= ids
        assert body["source"] == "api"
        assert body["error"] is None

    def test_the_live_list_is_fetched_from_the_models_path(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {"data": []})
        client.get("/api/opencode/models")

        gets = [c for c in _FakeAsyncClient.calls if c[0] == "get"]
        assert gets, "expected the catalogue to make a GET"
        assert gets[-1][1].endswith("/models")


# ---------------------------------------------------------------------------
# /api/opencode/chat
# ---------------------------------------------------------------------------

def _chat(client, **body):
    payload = {"model": "deepseek-v4-flash-free", "messages": [{"role": "user", "content": "hi"}]}
    payload.update(body)
    return client.post("/api/opencode/chat", json=payload)


class TestChatRefusals:
    def test_without_a_key_it_is_503_not_a_silent_failure(self, client):
        res = _chat(client)
        assert res.status_code == 503
        assert "OPENCODE_API_KEY" in res.json()["detail"]

    def test_empty_messages_are_rejected(self, client, with_key):
        res = _chat(client, messages=[])
        assert res.status_code == 422

    def test_an_unknown_model_is_rejected_rather_than_substituted(self, client, with_key):
        """A silent fallback to a different model is the 'models mismatch' bug."""
        res = _chat(client, model="gpt-9-imaginary")
        assert res.status_code == 400
        assert "gpt-9-imaginary" in res.json()["detail"]
        # Nothing must have been sent upstream.
        assert _FakeAsyncClient.last_post() is None

    def test_an_unsupported_reasoning_tier_is_rejected(self, client, with_key):
        res = _chat(client, model="nemotron-3-ultra-free", reasoning_effort="xhigh")
        assert res.status_code == 422
        assert "xhigh" in res.json()["detail"]

    def test_an_upstream_error_is_surfaced_with_its_status(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(429, text="rate limited")
        res = _chat(client)
        assert res.status_code == 429
        assert "rate limited" in res.json()["detail"]


class TestChatSuccess:
    def test_chat_completions_is_parsed_and_reported(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {
            "choices": [{"message": {"content": "directed", "reasoning_content": "trace"}}],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 6,
                "total_tokens": 11,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        })

        body = _chat(client).json()

        assert body["text"] == "directed"
        assert body["thought_trace"] == "trace"
        assert body["reasoning_tokens"] == 3
        assert body["model"] == "deepseek-v4-flash-free"
        # The protocol actually used is reported, so a routing bug is visible
        # rather than showing up as an inexplicable model failure.
        assert body["endpoint_type"] == ENDPOINT_CHAT_COMPLETIONS
        assert body["latency_ms"] >= 0

    def test_responses_protocol_is_used_for_muse_spark(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
            "usage": {"output_tokens_details": {"reasoning_tokens": 12}},
        })

        body = _chat(client, model="muse-spark-1.3-contributor-free", reasoning_effort="xhigh").json()

        assert body["text"] == "ok"
        assert body["endpoint_type"] == ENDPOINT_RESPONSES
        _, url, _, sent = _FakeAsyncClient.last_post()
        assert url.endswith("/responses")
        assert sent["input"] == [{"role": "user", "content": "hi"}]
        assert sent["reasoning"] == {"effort": "xhigh"}

    def test_the_protocol_comes_from_the_catalogue_not_the_model_id(self, client, with_key, monkeypatch):
        """The regression that started this.

        A model whose id gives no hint must still be routed by what the
        catalogue says it speaks -- here, `responses` for an id with no
        'muse-spark' in it.
        """
        from agent.api import opencode as opencode_api

        exotic = ModelInfo(
            id="totally-unrelated-name",
            name="Exotic",
            endpoint_type=ENDPOINT_RESPONSES,
            supported_reasoning=["high", "off"],
            default_reasoning="high",
        )
        monkeypatch.setattr(
            opencode_api, "get_catalogue", lambda: _StubCatalogue([exotic])
        )
        _FakeAsyncClient.response = _FakeResponse(200, {"output": [], "usage": {}})

        body = _chat(client, model="totally-unrelated-name").json()

        assert body["endpoint_type"] == ENDPOINT_RESPONSES
        _, url, _, _ = _FakeAsyncClient.last_post()
        assert url.endswith("/responses"), "an id-based guess would have used /chat/completions"

    def test_the_default_reasoning_tier_is_applied_when_none_is_given(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})

        body = _chat(client).json()

        # deepseek's default is 'high' per the catalogue.
        assert body["reasoning_effort"] == "high"
        _, _, _, sent = _FakeAsyncClient.last_post()
        assert sent["reasoningEffort"] == "high"

    def test_the_key_is_injected_server_side(self, client, with_key):
        _FakeAsyncClient.response = _FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})

        _chat(client)

        _, _, headers, _ = _FakeAsyncClient.last_post()
        assert headers["Authorization"] == f"Bearer {with_key}"

    def test_environment_proxies_are_ignored(self, client, with_key):
        """A localhost HTTP_PROXY would otherwise mangle the upstream URL."""
        _FakeAsyncClient.response = _FakeResponse(200, {"choices": [{"message": {"content": "x"}}]})

        _chat(client)

        inits = [c for c in _FakeAsyncClient.calls if c[0] == "init"]
        assert inits, "expected an httpx client to be constructed"
        assert inits[-1][2].get("trust_env") is False


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def _sse_lines(*payloads) -> list:
    """Build raw SSE lines the way the upstream would send them."""
    lines = [f"data: {json.dumps(p)}" for p in payloads]
    lines.append("data: [DONE]")
    return lines


def _stream(client, **body):
    payload = {"model": "deepseek-v4-flash-free", "messages": [{"role": "user", "content": "hi"}]}
    payload.update(body)
    return client.post("/api/opencode/chat/stream", json=payload)


def _frames(res) -> list:
    """Decode an SSE body into the list of frames it carried."""
    out = []
    for line in res.text.splitlines():
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


class TestStreamEventParsing:
    """The protocols stream in different shapes; both must read the same here."""

    def test_responses_text_delta(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_RESPONSES, {
            "type": "response.output_text.delta", "delta": "hello"
        }) == {"type": "text", "text": "hello"}

    def test_responses_reasoning_delta(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_RESPONSES, {
            "type": "response.reasoning_summary_text.delta", "delta": "because"
        }) == {"type": "reasoning", "text": "because"}

    def test_responses_completed_carries_usage(self):
        from agent.services.opencode_models import parse_stream_event

        got = parse_stream_event(ENDPOINT_RESPONSES, {
            "type": "response.completed",
            "response": {"usage": {
                "input_tokens": 5, "output_tokens": 6, "total_tokens": 11,
                "output_tokens_details": {"reasoning_tokens": 3},
            }},
        })
        assert got["type"] == "usage"
        assert got["reasoning_tokens"] == 3
        assert got["input_tokens"] == 5

    def test_responses_ignores_events_with_nothing_to_show(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_RESPONSES, {"type": "response.created"}) is None

    def test_chat_content_delta(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_CHAT_COMPLETIONS, {
            "choices": [{"delta": {"content": "hi"}}]
        }) == {"type": "text", "text": "hi"}

    def test_chat_reasoning_delta(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_CHAT_COMPLETIONS, {
            "choices": [{"delta": {"reasoning_content": "thinking"}}]
        }) == {"type": "reasoning", "text": "thinking"}

    def test_chat_usage_only_chunk(self):
        from agent.services.opencode_models import parse_stream_event

        got = parse_stream_event(ENDPOINT_CHAT_COMPLETIONS, {
            "choices": [],
            "usage": {"prompt_tokens": 5, "completion_tokens": 6, "total_tokens": 11,
                      "completion_tokens_details": {"reasoning_tokens": 3}},
        })
        assert got["type"] == "usage"
        assert got["reasoning_tokens"] == 3

    def test_chat_empty_delta_is_not_an_event(self):
        from agent.services.opencode_models import parse_stream_event

        assert parse_stream_event(ENDPOINT_CHAT_COMPLETIONS, {"choices": [{"delta": {}}]}) is None


class TestStreamPayload:
    def test_chat_completions_asks_for_usage_in_the_final_chunk(self):
        from agent.services.opencode_models import build_stream_payload

        p = build_stream_payload("deepseek-v4-flash-free", ENDPOINT_CHAT_COMPLETIONS, [], "high")
        assert p["stream"] is True
        # Without this the final chunk omits usage, so the token counts shown in
        # the UI would be permanently zero.
        assert p["stream_options"] == {"include_usage": True}

    def test_responses_does_not_send_stream_options(self):
        from agent.services.opencode_models import build_stream_payload

        p = build_stream_payload("muse-spark-1.3-contributor-free", ENDPOINT_RESPONSES, [], "xhigh")
        assert p["stream"] is True
        assert "stream_options" not in p

    def test_unknown_endpoint_type_raises(self):
        from agent.services.opencode_models import build_stream_payload

        with pytest.raises(ValueError):
            build_stream_payload("m", "nonsense", [])


class TestStreamEndpoint:
    def test_streams_text_then_done(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"choices": [{"delta": {"content": "Di"}}]},
            {"choices": [{"delta": {"content": "rected"}}]},
        ))

        frames = _frames(_stream(client))

        assert [f["type"] for f in frames] == ["text", "text", "done"]
        assert "".join(f["text"] for f in frames if f["type"] == "text") == "Directed"
        assert frames[-1]["model"] == "deepseek-v4-flash-free"
        assert frames[-1]["endpoint_type"] == ENDPOINT_CHAT_COMPLETIONS

    def test_reasoning_deltas_are_separated_from_text(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"choices": [{"delta": {"reasoning_content": "weighing"}}]},
            {"choices": [{"delta": {"content": "answer"}}]},
        ))

        frames = _frames(_stream(client))

        assert [f["type"] for f in frames] == ["reasoning", "text", "done"]
        assert frames[0]["text"] == "weighing"

    def test_usage_frame_reaches_the_client(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"choices": [{"delta": {"content": "x"}}]},
            {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 6,
                                      "total_tokens": 11,
                                      "completion_tokens_details": {"reasoning_tokens": 3}}},
        ))

        frames = _frames(_stream(client))

        usage = [f for f in frames if f["type"] == "usage"]
        assert len(usage) == 1
        assert usage[0]["reasoning_tokens"] == 3

    def test_responses_protocol_streams_from_the_responses_path(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"type": "response.output_text.delta", "delta": "ok"},
        ))

        frames = _frames(_stream(client, model="muse-spark-1.3-contributor-free",
                                 reasoning_effort="xhigh"))

        assert frames[0] == {"type": "text", "text": "ok"}
        _, method, url, _, sent = _FakeAsyncClient.last_stream()
        assert method == "POST"
        assert url.endswith("/responses")
        assert sent["stream"] is True
        assert sent["input"] == [{"role": "user", "content": "hi"}]

    def test_a_malformed_frame_does_not_kill_the_stream(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, [
            "data: {not json",
            f"data: {json.dumps({'choices': [{'delta': {'content': 'survived'}}]})}",
            "data: [DONE]",
        ])

        frames = _frames(_stream(client))

        assert [f["type"] for f in frames] == ["text", "done"]
        assert frames[0]["text"] == "survived"

    def test_upstream_error_becomes_an_error_frame(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(429, body=b"rate limited")

        frames = _frames(_stream(client))

        assert frames[0]["type"] == "error"
        assert "rate limited" in frames[0]["message"]
        # No `done` frame: the stream did not complete, and saying otherwise
        # would make a failed generation look finished.
        assert all(f["type"] != "done" for f in frames)

    def test_response_is_event_stream(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"choices": [{"delta": {"content": "x"}}]},
        ))

        assert _stream(client).headers["content-type"].startswith("text/event-stream")

    def test_validation_is_shared_with_the_buffered_endpoint(self, client, with_key):
        """A rule must not hold for /chat and quietly not hold for /chat/stream."""
        assert _stream(client, model="gpt-9-imaginary").status_code == 400
        assert _stream(client, model="nemotron-3-ultra-free",
                       reasoning_effort="xhigh").status_code == 422
        assert _stream(client, messages=[]).status_code == 422
        # None of them reached upstream.
        assert _FakeAsyncClient.last_stream() is None

    def test_without_a_key_it_is_503(self, client):
        assert _stream(client).status_code == 503

    def test_environment_proxies_are_ignored(self, client, with_key):
        _FakeAsyncClient.stream_response = _FakeStreamResponse(200, _sse_lines(
            {"choices": [{"delta": {"content": "x"}}]},
        ))

        _stream(client)

        inits = [c for c in _FakeAsyncClient.calls if c[0] == "init"]
        assert inits[-1][2].get("trust_env") is False
