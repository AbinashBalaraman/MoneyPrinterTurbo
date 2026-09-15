"""Structured log bus — bounded history plus live fan-out to dashboard clients.

Why this exists
---------------
The dashboard had no way to show what a run was doing. There was no log API and
no log stream, so the component named ``LogViewer`` rendered a table of
``/api/requests`` rows instead of log lines. This module is the missing
substrate: it turns ordinary ``logging`` calls into a queryable, streamable
event stream.

Design notes
------------
``seq`` is the contract
    Every record gets a monotonically increasing sequence number. A client that
    reconnects sends the last ``seq`` it saw and receives exactly the records it
    missed. This is what makes a dropped WebSocket survivable — previously
    anything emitted during a disconnect was gone forever.

Bounded history
    History is a fixed-size ring, so an unattended multi-hour run cannot grow
    memory without limit.

Drop the oldest, not the newest
    When a subscriber's queue is full we evict the oldest record rather than
    refusing the new one. A slow client should lose stale lines, not fall
    permanently further behind on the lines that matter.

``logging`` bridge
    ``LogBusHandler`` funnels the stdlib logging tree into the bus, so the
    hundreds of existing ``logger.info(...)`` calls become visible without
    editing a single call site.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import functools
import inspect
import itertools
import json
import logging
import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

DEFAULT_HISTORY = 5000
DEFAULT_QUEUE_SIZE = 1000
MAX_MESSAGE_CHARS = 8000
MAX_EXTRA_CHARS = 2000

LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# ``logging.LogRecord`` attributes that are structural rather than payload. Any
# attribute outside this set was passed by the caller as ``extra={...}`` and is
# therefore worth surfacing.
_RESERVED_RECORD_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

# ``log_stage`` tags output without forcing every function in the call chain to
# accept a ``stage`` parameter.
_stage_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "flowkit_log_stage", default=None
)

# Guards against a log call made from inside the bus (or from a library the bus
# touches) recursing forever.
_emitting = threading.local()


@contextlib.contextmanager
def log_stage(name: Optional[str]) -> Iterator[None]:
    """Tag every record emitted inside this block with ``stage``.

    >>> with log_stage("images"):
    ...     logger.info("rendering still 3 of 8")
    """
    token = _stage_var.set(name)
    try:
        yield
    finally:
        _stage_var.reset(token)


def current_stage() -> Optional[str]:
    """The stage currently in effect for this context, if any."""
    return _stage_var.get()


def staged(name: Optional[str]):
    """Decorator form of :func:`log_stage`, for sync and async functions alike.

    Useful where wrapping the body in a ``with`` block would mean re-indenting a
    long function and burying whatever it is actually doing::

        @staged("assemble")
        def merge_videos(...): ...

        @staged("voiceover")
        async def narrate_video(...): ...
    """
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args, **kwargs):
                with log_stage(name):
                    return await fn(*args, **kwargs)
            return async_wrapper

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            with log_stage(name):
                return fn(*args, **kwargs)
        return sync_wrapper
    return decorate


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    """Coerce ``value`` into something ``json.dumps`` can serialise.

    Unsupported types become their ``repr``, truncated, rather than raising and
    losing the log line.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, str) and len(value) > MAX_EXTRA_CHARS:
            return value[:MAX_EXTRA_CHARS] + "…"
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in list(value)[:50]]
    try:
        text = repr(value)
    except Exception:  # pragma: no cover - repr itself failing is pathological
        return "<unrepresentable>"
    return text[:MAX_EXTRA_CHARS] + ("…" if len(text) > MAX_EXTRA_CHARS else "")


@dataclass
class LogRecord:
    """A single structured log line."""

    seq: int
    ts: str
    level: str
    message: str
    stage: Optional[str] = None
    source: Optional[str] = None
    extra: Optional[dict] = None

    def to_dict(self) -> dict:
        data = {
            "seq": self.seq,
            "ts": self.ts,
            "level": self.level,
            "message": self.message,
            "stage": self.stage,
            "source": self.source,
        }
        if self.extra:
            data["extra"] = self.extra
        return data


@dataclass(eq=False)
class _Subscriber:
    """A live tail consumer, bound to the loop that created it.

    ``eq=False`` keeps identity semantics: subscribers live in a set and are
    distinguished by identity, not by the contents of their queue.
    """

    loop: asyncio.AbstractEventLoop
    queue: "asyncio.Queue[str]" = field(default_factory=lambda: asyncio.Queue(maxsize=DEFAULT_QUEUE_SIZE))


class LogBus:
    """Thread-safe, bounded log history with live fan-out.

    ``emit`` is safe to call from any thread, which matters because logging
    handlers can fire on worker threads.
    """

    def __init__(self, history_size: int = DEFAULT_HISTORY, queue_size: int = DEFAULT_QUEUE_SIZE):
        self._history: deque[LogRecord] = deque(maxlen=history_size)
        self._seq = itertools.count(1)
        self._issued = 0
        self._lock = threading.RLock()
        self._subscribers: set[_Subscriber] = set()
        self._queue_size = queue_size
        self._dropped = 0

    # ── introspection ────────────────────────────────────────────────

    @property
    def latest_seq(self) -> int:
        """Highest sequence number ever issued (0 before the first record).

        This is the cursor a client should resume from, so it tracks the
        counter rather than the retained history — clearing history must not
        make a client believe it has seen nothing.
        """
        with self._lock:
            return self._issued

    @property
    def count(self) -> int:
        """Number of records currently retained."""
        with self._lock:
            return len(self._history)

    @property
    def dropped(self) -> int:
        """Records evicted from a subscriber queue because it was full."""
        with self._lock:
            return self._dropped

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ── emission ─────────────────────────────────────────────────────

    def emit(
        self,
        level: str,
        message: str,
        *,
        stage: Optional[str] = None,
        source: Optional[str] = None,
        extra: Optional[dict] = None,
        exc_info: Any = None,
    ) -> Optional[LogRecord]:
        """Record a line and push it to every live subscriber.

        Returns the stored record, or ``None`` if this call was suppressed to
        break a recursion cycle.
        """
        if getattr(_emitting, "active", False):
            # A log call triggered by the bus itself. Storing it would recurse.
            return None
        _emitting.active = True
        try:
            level_name = (level or "INFO").upper()
            if level_name not in LEVELS:
                level_name = "INFO"

            text = message if isinstance(message, str) else str(message)
            if exc_info:
                text = f"{text}\n{''.join(traceback.format_exception(*exc_info)).rstrip()}"

            with self._lock:
                seq = next(self._seq)
                self._issued = seq
                record = LogRecord(
                    seq=seq,
                    ts=_utc_now(),
                    level=level_name,
                    message=text[:MAX_MESSAGE_CHARS],
                    stage=stage if stage is not None else _stage_var.get(),
                    source=source,
                    extra={k: _json_safe(v) for k, v in extra.items()} if extra else None,
                )
                self._history.append(record)
                subscribers = list(self._subscribers)

            if subscribers:
                payload = json.dumps(
                    {"type": "log", "data": record.to_dict(), "timestamp": record.ts}
                )
                for sub in subscribers:
                    self._deliver(sub, payload)

            return record
        finally:
            _emitting.active = False

    def _deliver(self, sub: _Subscriber, payload: str) -> None:
        """Hand ``payload`` to ``sub`` on its own event loop."""
        try:
            sub.loop.call_soon_threadsafe(self._offer, sub, payload)
        except RuntimeError:
            # Loop is closed; the subscriber is on its way out.
            with self._lock:
                self._subscribers.discard(sub)

    def _offer(self, sub: _Subscriber, payload: str) -> None:
        """Enqueue on the loop thread, evicting the oldest line if full."""
        queue = sub.queue
        try:
            queue.put_nowait(payload)
            return
        except asyncio.QueueFull:
            pass

        with self._lock:
            self._dropped += 1
        try:
            queue.get_nowait()  # discard the stalest line
        except asyncio.QueueEmpty:
            pass
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Another producer refilled it between the two calls.
            pass

    # ── subscription ─────────────────────────────────────────────────

    def subscribe(self) -> "asyncio.Queue[str]":
        """Register a live tail consumer. Call from within a running loop."""
        loop = asyncio.get_running_loop()
        sub = _Subscriber(loop=loop, queue=asyncio.Queue(maxsize=self._queue_size))
        with self._lock:
            self._subscribers.add(sub)
        return sub.queue

    def unsubscribe(self, queue: "asyncio.Queue[str]") -> None:
        with self._lock:
            for sub in list(self._subscribers):
                if sub.queue is queue:
                    self._subscribers.discard(sub)

    # ── query ────────────────────────────────────────────────────────

    def history(
        self,
        *,
        since: Optional[int] = None,
        limit: int = 500,
        level: Optional[str] = None,
        stage: Optional[str] = None,
        search: Optional[str] = None,
        ascending: bool = True,
    ) -> list[dict]:
        """Return retained records, oldest first.

        ``since`` is exclusive: pass the last ``seq`` you already have and you
        get exactly the records after it. This is the replay primitive.
        """
        with self._lock:
            records = list(self._history)

        if since is not None:
            records = [r for r in records if r.seq > since]

        if level:
            wanted = {lv.strip().upper() for lv in level.split(",") if lv.strip()}
            if wanted:
                records = [r for r in records if r.level in wanted]

        if stage:
            records = [r for r in records if (r.stage or "") == stage]

        if search:
            needle = search.lower()
            records = [
                r
                for r in records
                if needle in r.message.lower()
                or needle in (r.stage or "").lower()
                or needle in (r.source or "").lower()
            ]

        if limit is not None and limit >= 0:
            # Keep the newest ``limit`` matches, since that is what a tail wants.
            records = records[-limit:] if limit else []

        if not ascending:
            records = list(reversed(records))

        return [r.to_dict() for r in records]

    def stages(self) -> list[str]:
        """Distinct stage names seen so far, for building a filter UI."""
        with self._lock:
            seen = {r.stage for r in self._history if r.stage}
        return sorted(seen)

    def clear(self) -> None:
        """Drop all history. Sequence numbers keep advancing."""
        with self._lock:
            self._history.clear()


class LogBusHandler(logging.Handler):
    """Bridge the stdlib logging tree into a :class:`LogBus`.

    ``exclude`` names noisy loggers whose output would drown the pipeline lines
    a user actually wants (per-request HTTP access logs, file-watcher chatter).
    """

    def __init__(
        self,
        bus: LogBus,
        level: int = logging.INFO,
        exclude: tuple[str, ...] = (),
    ):
        super().__init__(level=level)
        self.bus = bus
        self.exclude = tuple(exclude)

    def emit(self, record: logging.LogRecord) -> None:  # noqa: A003 - stdlib name
        try:
            if self.exclude and record.name.startswith(self.exclude):
                return

            stage = getattr(record, "stage", None)
            extra = {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RESERVED_RECORD_KEYS
                and key != "stage"
                and not key.startswith("_")
            }
            self.bus.emit(
                record.levelname,
                record.getMessage(),
                stage=stage,
                source=record.name,
                extra=extra or None,
                exc_info=record.exc_info,
            )
        except Exception:  # pragma: no cover - never let logging break the app
            self.handleError(record)


log_bus = LogBus()
