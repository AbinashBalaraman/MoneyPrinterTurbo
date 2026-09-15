"""Dedupe ledger for the AutoShorts automation pipeline.

The pipeline is *reactive* (a source keeps producing new items) and *publishes
automatically*. Without a record of what has already been handled, any retry or
overlapping run re-generates and re-uploads the same video -- which is exactly
what gets accounts flagged on TikTok / Instagram / YouTube.

This module is the single source of truth for "have we already done this?".
It is deliberately dependency-free (stdlib ``sqlite3`` only) and defaults to a
path under ``storage/``, which is gitignored.

Two properties matter and are both enforced here:

1. **Claim before work.** A topic is marked ``claimed`` *before* the batch is
   handed to the generator. If the process dies mid-run, the topic is not
   silently retried forever and cannot be picked up by a concurrent run.
2. **Idempotent recording.** Recording an outcome twice is a no-op, so a
   re-parsed CLI summary cannot double-count uploads.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

# Stored statuses. "new" is never stored -- a topic absent from the table is new.
STATUS_CLAIMED = "claimed"
STATUS_GENERATED = "generated"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

DEFAULT_MAX_ATTEMPTS = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    key           TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    title         TEXT NOT NULL,
    url           TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    status        TEXT NOT NULL,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    source      TEXT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    requested   INTEGER NOT NULL DEFAULT 0,
    generated   INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    dry_run     INTEGER NOT NULL DEFAULT 0,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS outputs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_key        TEXT NOT NULL REFERENCES topics(key),
    run_id           TEXT NOT NULL,
    task_id          TEXT,
    state            TEXT NOT NULL,
    video_paths      TEXT,
    cross_post_state TEXT,
    error            TEXT,
    recorded_at      TEXT NOT NULL
);

-- One row per (video file, platform). The UNIQUE constraint is the hard
-- guarantee against a duplicate upload: even if a run is retried, re-parsed, or
-- raced by a second process, the database refuses the second insert. Duplicate
-- posts are what get accounts flagged on these platforms, so this is enforced
-- by the schema rather than by application logic.
CREATE TABLE IF NOT EXISTS uploads (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_key         TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    video_path        TEXT NOT NULL,
    platform          TEXT NOT NULL,
    platform_video_id TEXT,
    url               TEXT,
    state             TEXT NOT NULL,
    error             TEXT,
    recorded_at       TEXT NOT NULL,
    UNIQUE(run_id, video_path, platform)
);

CREATE INDEX IF NOT EXISTS idx_outputs_topic ON outputs(topic_key);
CREATE INDEX IF NOT EXISTS idx_outputs_run ON outputs(run_id);
CREATE INDEX IF NOT EXISTS idx_topics_status ON topics(status);
CREATE INDEX IF NOT EXISTS idx_uploads_topic ON uploads(topic_key);
CREATE INDEX IF NOT EXISTS idx_uploads_video ON uploads(video_path);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_ledger_path() -> str:
    """Return ``<repo>/storage/automation/ledger.db``.

    ``storage/`` is gitignored, so the ledger never lands in the repository.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    return os.path.join(repo_root, "storage", "automation", "ledger.db")


class Ledger:
    """SQLite-backed record of which topics have been seen, run and published."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or default_ledger_path()
        parent = os.path.dirname(os.path.realpath(self.path))
        os.makedirs(parent, exist_ok=True)
        # The runner may be invoked from a scheduler while a previous run is
        # still finishing, so serialise writes across threads within a process.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    # ---------------------------------------------------------------- topics

    def get_topic(self, key: str) -> Optional[sqlite3.Row]:
        with self._lock:
            cur = self._conn.execute("SELECT * FROM topics WHERE key = ?", (key,))
            return cur.fetchone()

    def is_done(self, key: str) -> bool:
        """True when this topic has already been generated successfully."""
        row = self.get_topic(key)
        return bool(row) and row["status"] == STATUS_GENERATED

    def should_skip(self, key: str, max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> bool:
        """True when this topic must not be submitted again.

        Skips anything already generated, anything currently claimed by another
        run, and anything that has burned through its retry budget.
        """
        row = self.get_topic(key)
        if row is None:
            return False
        if row["status"] in (STATUS_GENERATED, STATUS_CLAIMED, STATUS_SKIPPED):
            return True
        return int(row["attempts"] or 0) >= max_attempts

    def claim(
        self,
        key: str,
        source: str,
        title: str,
        url: Optional[str] = None,
    ) -> bool:
        """Atomically claim a topic for this run.

        Returns True when the claim succeeded. Returns False when the topic is
        already known and not retryable, so a concurrent or repeated run cannot
        double-submit it.

        The claim is written *before* generation starts, which is what makes a
        mid-run crash safe: the topic stays ``claimed`` rather than reverting to
        new and being picked up again on the next tick.
        """
        now = _now()
        with self._tx() as conn:
            row = conn.execute(
                "SELECT status, attempts FROM topics WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                status = row["status"]
                attempts = int(row["attempts"] or 0)
                if status in (STATUS_GENERATED, STATUS_CLAIMED, STATUS_SKIPPED):
                    return False
                if attempts >= DEFAULT_MAX_ATTEMPTS:
                    return False
                conn.execute(
                    "UPDATE topics SET status = ?, attempts = ?, last_seen_at = ? "
                    "WHERE key = ?",
                    (STATUS_CLAIMED, attempts + 1, now, key),
                )
                return True

            conn.execute(
                "INSERT INTO topics "
                "(key, source, title, url, first_seen_at, last_seen_at, status, attempts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (key, source, title, url, now, now, STATUS_CLAIMED),
            )
            return True

    def mark_generated(self, key: str, error: Optional[str] = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE topics SET status = ?, last_seen_at = ?, last_error = NULL "
                "WHERE key = ?",
                (STATUS_GENERATED, _now(), key),
            )

    def mark_failed(self, key: str, error: Optional[str] = None) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE topics SET status = ?, last_seen_at = ?, last_error = ? "
                "WHERE key = ?",
                (STATUS_FAILED, _now(), error, key),
            )

    # ------------------------------------------------------------------ runs

    def start_run(self, run_id: str, source: str, requested: int, dry_run: bool) -> None:
        with self._tx() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs "
                "(run_id, source, started_at, requested, generated, failed, dry_run) "
                "VALUES (?, ?, ?, ?, 0, 0, ?)",
                (run_id, source, _now(), requested, 1 if dry_run else 0),
            )

    def finish_run(
        self,
        run_id: str,
        generated: int,
        failed: int,
        note: Optional[str] = None,
    ) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE runs SET finished_at = ?, generated = ?, failed = ?, note = ? "
                "WHERE run_id = ?",
                (_now(), generated, failed, note, run_id),
            )

    # --------------------------------------------------------------- outputs

    def record_output(
        self,
        topic_key: str,
        run_id: str,
        task_id: Optional[str],
        state: str,
        video_paths: Optional[Iterable[str]] = None,
        cross_post_state: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Record one task outcome. Recording the same (run_id, task_id) twice
        is a no-op so a re-parsed summary cannot inflate the upload count."""
        joined = ",".join(video_paths) if video_paths else None
        with self._tx() as conn:
            existing = conn.execute(
                "SELECT id FROM outputs WHERE run_id = ? AND task_id IS ? AND topic_key = ?",
                (run_id, task_id, topic_key),
            ).fetchone()
            if existing is not None:
                return
            conn.execute(
                "INSERT INTO outputs "
                "(topic_key, run_id, task_id, state, video_paths, cross_post_state, "
                "error, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    topic_key,
                    run_id,
                    task_id,
                    state,
                    joined,
                    cross_post_state,
                    error,
                    _now(),
                ),
            )

    # ------------------------------------------------------------------ stats

    def stats(self) -> dict:
        with self._lock:
            topics = {
                row["status"]: row["count"]
                for row in self._conn.execute(
                    "SELECT status, COUNT(*) AS count FROM topics GROUP BY status"
                )
            }
            published = self._conn.execute(
                "SELECT COUNT(*) AS c FROM outputs WHERE cross_post_state IN "
                "('complete', 'pending', 'processing')"
            ).fetchone()["c"]
            runs = self._conn.execute("SELECT COUNT(*) AS c FROM runs").fetchone()["c"]
        return {
            "ledger_path": self.path,
            "topics": topics,
            "uploads_recorded": published,
            "runs": runs,
        }
