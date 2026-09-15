"""Unit tests for agent/services/log_bus.py.

The log bus exists because the dashboard had no way to see what a run was
doing. These tests pin the two properties that make it useful: a record is
never silently lost while a client is away, and history stays bounded.
"""

import asyncio
import json
import logging
import threading

import pytest

from agent.services.log_bus import (
    LogBus,
    LogBusHandler,
    current_stage,
    log_bus,
    log_stage,
)


async def _next(queue, timeout: float = 1.0) -> str:
    """Await one item, yielding to the loop so call_soon_threadsafe lands."""
    return await asyncio.wait_for(queue.get(), timeout)


# ---------------------------------------------------------------------------
# Emission and sequencing
# ---------------------------------------------------------------------------

class TestEmit:
    def test_seq_starts_at_one_and_increments(self):
        bus = LogBus()
        a = bus.emit("INFO", "first")
        b = bus.emit("INFO", "second")
        assert (a.seq, b.seq) == (1, 2)

    def test_record_carries_fields(self):
        bus = LogBus()
        rec = bus.emit("WARNING", "disk low", stage="images", source="agent.worker")
        assert rec.level == "WARNING"
        assert rec.stage == "images"
        assert rec.source == "agent.worker"
        assert rec.ts.endswith("+00:00")

    def test_unknown_level_falls_back_to_info(self):
        bus = LogBus()
        assert bus.emit("NOPE", "x").level == "INFO"

    def test_level_is_upper_cased(self):
        bus = LogBus()
        assert bus.emit("error", "x").level == "ERROR"

    def test_latest_seq_and_count_track_emissions(self):
        bus = LogBus()
        assert bus.latest_seq == 0
        assert bus.count == 0
        bus.emit("INFO", "a")
        bus.emit("INFO", "b")
        assert bus.latest_seq == 2
        assert bus.count == 2

    def test_clear_empties_history_but_not_the_cursor(self):
        bus = LogBus()
        bus.emit("INFO", "a")
        bus.clear()
        assert bus.count == 0
        # latest_seq is a cursor, not a history length: a client that had seen
        # seq 1 must still be able to resume from 1 after a clear.
        assert bus.latest_seq == 1
        # Sequence numbers keep advancing so a stale cursor cannot match a
        # post-clear record and silently skip it.
        assert bus.emit("INFO", "b").seq == 2

    def test_extra_values_are_json_safe(self):
        bus = LogBus()
        rec = bus.emit("INFO", "x", extra={"obj": object(), "n": 3})
        assert rec.extra["n"] == 3
        assert isinstance(rec.extra["obj"], str)
        json.dumps(rec.to_dict())  # must not raise

    def test_exception_is_formatted_into_the_message(self):
        bus = LogBus()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            rec = bus.emit("ERROR", "failed", exc_info=sys.exc_info())
        assert "ValueError: boom" in rec.message
        assert "Traceback" in rec.message

    def test_long_message_is_truncated(self):
        bus = LogBus()
        rec = bus.emit("INFO", "x" * 20000)
        assert len(rec.message) == 8000

    def test_emit_is_safe_from_another_thread(self):
        bus = LogBus()
        threads = [threading.Thread(target=bus.emit, args=("INFO", f"t{i}")) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert bus.count == 20
        # Sequence numbers must be unique even under concurrent emission.
        seqs = [r["seq"] for r in bus.history(limit=100)]
        assert len(set(seqs)) == 20


# ---------------------------------------------------------------------------
# Bounded history
# ---------------------------------------------------------------------------

class TestHistoryBound:
    def test_history_is_capped(self):
        bus = LogBus(history_size=10)
        for i in range(50):
            bus.emit("INFO", f"line {i}")
        assert bus.count == 10

    def test_cap_keeps_the_newest_records(self):
        bus = LogBus(history_size=3)
        for i in range(10):
            bus.emit("INFO", f"line {i}")
        messages = [r["message"] for r in bus.history()]
        assert messages == ["line 7", "line 8", "line 9"]


# ---------------------------------------------------------------------------
# Query — the replay primitive
# ---------------------------------------------------------------------------

class TestQuery:
    def _bus(self):
        bus = LogBus()
        bus.emit("INFO", "boot", stage="script")
        bus.emit("WARNING", "slow", stage="images")
        bus.emit("ERROR", "boom", stage="images", source="agent.worker")
        bus.emit("INFO", "done", stage="publish")
        return bus

    def test_since_is_exclusive(self):
        bus = self._bus()
        got = bus.history(since=1)
        assert [r["seq"] for r in got] == [2, 3, 4]

    def test_since_beyond_head_returns_empty(self):
        assert self._bus().history(since=99) == []

    def test_since_none_returns_everything(self):
        assert len(self._bus().history()) == 4

    def test_level_filter_accepts_a_list(self):
        got = self._bus().history(level="WARNING,ERROR")
        assert {r["level"] for r in got} == {"WARNING", "ERROR"}

    def test_stage_filter_is_exact(self):
        got = self._bus().history(stage="images")
        assert [r["seq"] for r in got] == [2, 3]

    def test_search_matches_message_stage_and_source(self):
        bus = self._bus()
        assert len(bus.history(search="boom")) == 1
        assert len(bus.history(search="images")) == 2
        assert len(bus.history(search="agent.worker")) == 1

    def test_search_is_case_insensitive(self):
        assert len(self._bus().history(search="BOOM")) == 1

    def test_limit_keeps_the_newest(self):
        got = self._bus().history(limit=2)
        assert [r["seq"] for r in got] == [3, 4]

    def test_limit_zero_returns_nothing(self):
        assert self._bus().history(limit=0) == []

    def test_descending_order(self):
        got = self._bus().history(ascending=False)
        assert [r["seq"] for r in got] == [4, 3, 2, 1]

    def test_stages_lists_distinct_names(self):
        assert self._bus().stages() == ["images", "publish", "script"]


# ---------------------------------------------------------------------------
# Live fan-out
# ---------------------------------------------------------------------------

class TestFanOut:
    async def test_subscriber_receives_a_typed_event(self):
        bus = LogBus()
        q = bus.subscribe()
        bus.emit("INFO", "hello", stage="images")

        payload = json.loads(await _next(q))
        assert payload["type"] == "log"
        assert payload["data"]["message"] == "hello"
        assert payload["data"]["stage"] == "images"
        assert payload["timestamp"] == payload["data"]["ts"]

    async def test_multiple_subscribers_all_receive(self):
        bus = LogBus()
        a, b = bus.subscribe(), bus.subscribe()
        bus.emit("INFO", "broadcast")
        assert json.loads(await _next(a))["data"]["message"] == "broadcast"
        assert json.loads(await _next(b))["data"]["message"] == "broadcast"

    async def test_unsubscribe_stops_delivery(self):
        bus = LogBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit("INFO", "after")
        assert q.empty()
        assert bus.subscriber_count == 0

    async def test_full_queue_drops_the_oldest_line(self):
        """A slow client should lose stale lines, not the newest ones."""
        bus = LogBus(queue_size=2)
        q = bus.subscribe()
        for i in range(5):
            bus.emit("INFO", f"line {i}")
            await asyncio.sleep(0)

        seen = [json.loads(q.get_nowait())["data"]["message"] for _ in range(2)]
        assert seen == ["line 3", "line 4"]
        assert bus.dropped == 3


# ---------------------------------------------------------------------------
# stdlib logging bridge
# ---------------------------------------------------------------------------

class TestLogBusHandler:
    @pytest.fixture
    def bridged(self):
        """A bus plus a private logger wired to it, torn down afterwards."""
        bus = LogBus()
        logger = logging.getLogger("flowkit_test_bridge")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = LogBusHandler(bus)
        logger.addHandler(handler)
        yield bus, logger
        logger.removeHandler(handler)

    def test_logger_call_reaches_the_bus(self, bridged):
        bus, logger = bridged
        logger.info("bridged line")
        records = bus.history()
        assert len(records) == 1
        assert records[0]["message"] == "bridged line"
        assert records[0]["level"] == "INFO"
        assert records[0]["source"] == "flowkit_test_bridge"

    def test_extra_fields_are_captured(self, bridged):
        bus, logger = bridged
        logger.info("scene done", extra={"scene_id": "s-1", "index": 3})
        rec = bus.history()[0]
        assert rec["extra"]["scene_id"] == "s-1"
        assert rec["extra"]["index"] == 3

    def test_explicit_stage_extra_is_used(self, bridged):
        bus, logger = bridged
        logger.info("tagged", extra={"stage": "publish"})
        assert bus.history()[0]["stage"] == "publish"

    def test_level_threshold_is_respected(self, bridged):
        bus, logger = bridged
        logger.debug("below threshold")
        assert bus.count == 0

    def test_excluded_logger_is_ignored(self):
        bus = LogBus()
        noisy = logging.getLogger("uvicorn.access")
        noisy.propagate = False
        handler = LogBusHandler(bus, exclude=("uvicorn.access",))
        noisy.addHandler(handler)
        try:
            noisy.info("GET /health 200")
            assert bus.count == 0
        finally:
            noisy.removeHandler(handler)

    def test_exception_in_logging_does_not_escape(self, bridged):
        bus, logger = bridged
        # A message that cannot be formatted still must not raise.
        logger.info("bad %s", object())
        assert bus.count == 1


# ---------------------------------------------------------------------------
# Stage context and recursion safety
# ---------------------------------------------------------------------------

class TestStageContext:
    def test_log_stage_tags_emissions(self):
        bus = LogBus()
        with log_stage("watermark"):
            assert current_stage() == "watermark"
            rec = bus.emit("INFO", "scrubbing")
        assert rec.stage == "watermark"

    def test_stage_is_restored_after_the_block(self):
        with log_stage("images"):
            pass
        assert current_stage() is None

    def test_explicit_stage_wins_over_context(self):
        bus = LogBus()
        with log_stage("images"):
            rec = bus.emit("INFO", "x", stage="publish")
        assert rec.stage == "publish"

    def test_stage_is_isolated_per_async_task(self):
        """A stage set in one task must not leak into a sibling task."""
        bus = LogBus()

        async def worker(name):
            with log_stage(name):
                await asyncio.sleep(0)
                return bus.emit("INFO", "x").stage

        async def run():
            return await asyncio.gather(worker("a"), worker("b"))

        assert asyncio.run(run()) == ["a", "b"]


class TestRecursionGuard:
    def test_a_log_call_during_emit_is_suppressed(self):
        """The guard covers the window while a record is being stored.

        A library that logs from inside that window (here, from a ``__repr__``
        reached while serialising ``extra``) would otherwise recurse until the
        stack blew. The outer line must still be recorded.
        """
        bus = LogBus()
        logger = logging.getLogger("flowkit_test_recursion")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        handler = LogBusHandler(bus)
        logger.addHandler(handler)

        class LogsWhileBeingRepred:
            def __repr__(self):
                logger.warning("inner line emitted mid-serialisation")
                return "evil"

        try:
            bus.emit("INFO", "outer line", extra={"payload": LogsWhileBeingRepred()})
        finally:
            logger.removeHandler(handler)

        assert bus.count == 1
        assert bus.history()[0]["message"] == "outer line"

    def test_guard_is_released_after_emit(self):
        """A suppressed call must not wedge the bus shut for later records."""
        bus = LogBus()

        class LogsWhileBeingRepred:
            def __repr__(self):
                bus.emit("DEBUG", "inner")
                return "evil"

        bus.emit("INFO", "first", extra={"payload": LogsWhileBeingRepred()})
        bus.emit("INFO", "second")
        messages = [r["message"] for r in bus.history()]
        assert messages == ["first", "second"]


# ---------------------------------------------------------------------------
# HTTP + WebSocket wiring
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_db(monkeypatch):
    """Stub the request query the dashboard socket performs on connect.

    ``TestClient`` is deliberately NOT used as a context manager here: entering
    it would run the app lifespan, which starts the worker against the real
    ``flow_agent.db``. Stubbing the one DB call keeps this test hermetic.
    """
    from agent.db import crud

    async def _no_requests(status=None):
        return []

    monkeypatch.setattr(crud, "list_requests", _no_requests)


class TestLogsEndpoint:
    @pytest.fixture(autouse=True)
    def _clean(self):
        log_bus.clear()
        yield
        log_bus.clear()

    def test_endpoint_returns_records_and_cursor(self):
        from starlette.testclient import TestClient

        from agent.main import app

        base = log_bus.latest_seq
        log_bus.emit("INFO", "alpha", stage="script")
        log_bus.emit("ERROR", "beta", stage="images")

        body = TestClient(app).get("/api/logs").json()

        assert [r["message"] for r in body["records"]] == ["alpha", "beta"]
        assert body["latest_seq"] == base + 2
        assert body["retained"] == 2
        assert body["stages"] == ["images", "script"]

    def test_since_returns_only_the_gap(self):
        from starlette.testclient import TestClient

        from agent.main import app

        # Sequence numbers are process-wide and keep advancing across clear(),
        # so the cursor must be read rather than assumed.
        base = log_bus.latest_seq
        log_bus.emit("INFO", "one")
        log_bus.emit("INFO", "two")
        log_bus.emit("INFO", "three")

        body = TestClient(app).get(f"/api/logs?since={base + 1}").json()
        assert [r["message"] for r in body["records"]] == ["two", "three"]

    def test_level_filter_over_http(self):
        from starlette.testclient import TestClient

        from agent.main import app

        log_bus.emit("INFO", "quiet")
        log_bus.emit("ERROR", "loud")

        body = TestClient(app).get("/api/logs?level=ERROR").json()
        assert [r["message"] for r in body["records"]] == ["loud"]

    def test_stages_endpoint(self):
        from starlette.testclient import TestClient

        from agent.main import app

        log_bus.emit("INFO", "x", stage="publish")
        body = TestClient(app).get("/api/logs/stages").json()
        assert body["stages"] == ["publish"]


class TestDashboardWebSocket:
    @pytest.fixture(autouse=True)
    def _clean(self):
        log_bus.clear()
        yield
        log_bus.clear()

    def test_replay_delivers_missed_logs_then_streams_live(self, isolated_db):
        """The whole point: a client that was away gets the gap, then the tail."""
        from starlette.testclient import TestClient

        from agent.main import app

        base = log_bus.latest_seq
        log_bus.emit("INFO", "while away")
        client = TestClient(app)

        with client.websocket_connect(f"/ws/dashboard?since={base}") as ws:
            assert ws.receive_json()["type"] == "snapshot"

            replay = ws.receive_json()
            assert replay["type"] == "log_replay"
            assert [r["message"] for r in replay["data"]["records"]] == ["while away"]
            assert replay["data"]["latest_seq"] == base + 1

            log_bus.emit("INFO", "live line")
            live = ws.receive_json()
            assert live["type"] == "log"
            assert live["data"]["message"] == "live line"
            assert live["data"]["seq"] == base + 2

    def test_replay_is_skipped_when_there_is_no_gap(self, isolated_db):
        from starlette.testclient import TestClient

        from agent.main import app

        log_bus.emit("INFO", "already seen")
        client = TestClient(app)

        with client.websocket_connect(f"/ws/dashboard?since={log_bus.latest_seq}") as ws:
            assert ws.receive_json()["type"] == "snapshot"

            log_bus.emit("INFO", "fresh")
            assert ws.receive_json()["data"]["message"] == "fresh"


class TestHandlerWiring:
    """The stdlib-logging bridge must be attached to the root logger once.

    ``python -m agent.main`` executes the module under the name ``__main__``,
    then ``uvicorn.run("agent.main:app")`` imports it again under its real
    name, re-running all module-level code. A bare ``addHandler`` therefore ran
    twice and every log line reached the dashboard twice -- each copy carrying
    its own ``seq``, so the client's de-duplication could not catch it. These
    tests pin the guard that prevents that.
    """

    def test_attaching_repeatedly_keeps_a_single_handler(self):
        from agent.main import _attach_log_bus_handler

        root = logging.getLogger()
        _attach_log_bus_handler()
        _attach_log_bus_handler()

        attached = [h for h in root.handlers if isinstance(h, LogBusHandler)]
        assert len(attached) == 1

    def test_reimporting_the_module_does_not_add_a_second_handler(self):
        """Reloading re-runs module-level code, which is what uvicorn does."""
        import importlib

        import agent.main as main_module

        root = logging.getLogger()

        def attached() -> int:
            return len([h for h in root.handlers if isinstance(h, LogBusHandler)])

        assert attached() == 1
        importlib.reload(main_module)
        assert attached() == 1, "reloading agent.main attached a duplicate handler"
        importlib.reload(main_module)
        assert attached() == 1, "a second reload attached yet another handler"

    def test_one_log_call_produces_exactly_one_record(self):
        """The end-to-end property: one call in, one record out."""
        bus = LogBus()
        handler = LogBusHandler(bus, level=logging.INFO)
        root = logging.getLogger()
        # The root logger defaults to WARNING, which would filter an INFO call
        # before any handler sees it. Raise the level for the duration.
        previous_level = root.level
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        try:
            root.info("a single line")
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        messages = [record["message"] for record in bus.history()]
        assert messages.count("a single line") == 1
