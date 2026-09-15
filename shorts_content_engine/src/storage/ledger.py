"""Episodic Continuity Ledger with SQLite WAL mode and atomic short-lived transactions."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional, Union

from src.models import (
    CharacterProfile,
    EntityType,
    EpisodeManifest,
    SeriesState,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


class EpisodicLedger:
    """SQLite WAL-mode continuity database tracking series, characters, episodes, and renders.
    
    Architectural Guarantees:
    - WAL Journal Mode: Concurrent non-blocking reads alongside single-writer writes.
    - Busy Timeout: 30,000ms (30s) to absorb concurrent connection lock contention.
    - Foreign Keys: Enabled (PRAGMA foreign_keys = ON) for relational integrity.
    - Atomic Transactions: Short-lived connections with auto-commit/rollback context managers.
      Locks are never held across external operations (e.g. FlowKit API calls or FFmpeg encoding).
    """

    def __init__(self, db_path: Union[str, Path] = "storage/ledger.db") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            parent_dir = os.path.dirname(os.path.abspath(self.db_path))
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Creates a configured SQLite connection with WAL mode and 30s busy timeout."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        if self.db_path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager providing an atomic, short-lived transactional connection."""
        conn = self.get_connection()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initializes database schema with required tables and indexes."""
        with self.transaction() as conn:
            # 1. Series Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    series_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    genre TEXT NOT NULL,
                    logline TEXT NOT NULL DEFAULT '',
                    target_duration REAL NOT NULL DEFAULT 45.0,
                    pacing_rhythm TEXT NOT NULL DEFAULT 'pulse_action',
                    current_season INTEGER NOT NULL DEFAULT 1,
                    current_episode INTEGER NOT NULL DEFAULT 0,
                    last_cliffhanger TEXT,
                    unresolved_threads TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
            """)

            # 2. Characters Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS characters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
                    character_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'character',
                    visual_summary TEXT NOT NULL,
                    personality TEXT NOT NULL DEFAULT '',
                    voice_profile TEXT NOT NULL DEFAULT 'en-US-ChristopherNeural',
                    seed INTEGER,
                    reference_image_url TEXT,
                    media_id TEXT,
                    relationships TEXT NOT NULL DEFAULT '{}',
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(series_id, character_id)
                );
            """)

            # 3. Episodes Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
                    episode_num INTEGER NOT NULL,
                    season_num INTEGER NOT NULL DEFAULT 1,
                    title TEXT NOT NULL,
                    premise TEXT NOT NULL DEFAULT '',
                    target_duration REAL NOT NULL,
                    actual_duration REAL NOT NULL DEFAULT 0.0,
                    total_word_count INTEGER NOT NULL DEFAULT 0,
                    overall_wpm REAL NOT NULL DEFAULT 0.0,
                    cliffhanger TEXT,
                    next_episode_hook TEXT,
                    micro_loop TEXT,
                    loop_phrase TEXT,
                    manifest_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'planned',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(series_id, episode_num, season_num)
                );
            """)

            # 4. Character State Deltas Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS character_state_deltas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
                    episode_num INTEGER NOT NULL,
                    character_name TEXT NOT NULL,
                    delta_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 5. Renders Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS renders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
                    episode_num INTEGER NOT NULL,
                    output_path TEXT NOT NULL,
                    duration REAL NOT NULL,
                    generation_mode TEXT NOT NULL DEFAULT 'mock',
                    status TEXT NOT NULL DEFAULT 'completed',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
            """)

            # 6. Publications Table (Multi-platform uploads)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
                    episode_num INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    post_id TEXT,
                    video_url TEXT,
                    status TEXT NOT NULL DEFAULT 'published',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    published_at TEXT NOT NULL
                );
            """)

            # Indexes for high-frequency queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_characters_series ON characters(series_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_series_ep ON episodes(series_id, episode_num);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_deltas_series_char ON character_state_deltas(series_id, character_name);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_renders_series_ep ON renders(series_id, episode_num);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_publications_series_ep ON publications(series_id, episode_num);")

    # -------------------------------------------------------------------------
    # Series Management
    # -------------------------------------------------------------------------

    def register_series(
        self,
        series_id: str,
        title: str,
        genre: str,
        logline: str = "",
        target_duration: float = 45.0,
        pacing_rhythm: str = "pulse_action",
    ) -> dict[str, Any]:
        """Registers a new series in the continuity ledger."""
        now = _utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO series (
                    series_id, title, genre, logline, target_duration, pacing_rhythm,
                    current_season, current_episode, last_cliffhanger, unresolved_threads,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, NULL, '[]', ?, ?)
                ON CONFLICT(series_id) DO UPDATE SET
                    title = excluded.title,
                    genre = excluded.genre,
                    logline = excluded.logline,
                    target_duration = excluded.target_duration,
                    pacing_rhythm = excluded.pacing_rhythm,
                    updated_at = excluded.updated_at;
                """,
                (series_id, title, genre, logline, target_duration, pacing_rhythm, now, now),
            )
        result = self.get_series(series_id)
        if result is None:
            raise RuntimeError(f"Failed to retrieve newly registered series '{series_id}'")
        return result

    def get_series(self, series_id: str) -> Optional[dict[str, Any]]:
        """Retrieves raw series record by ID."""
        with self.transaction() as conn:
            cursor = conn.execute("SELECT * FROM series WHERE series_id = ?;", (series_id,))
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["unresolved_threads"] = json.loads(data["unresolved_threads"])
            except Exception:
                data["unresolved_threads"] = []
            return data

    def update_series_state(
        self,
        series_id: str,
        current_season: int = 1,
        current_episode: int = 0,
        last_cliffhanger: Optional[str] = None,
        unresolved_threads: Optional[list[str]] = None,
    ) -> bool:
        """Updates progression state for an existing series."""
        now = _utc_now_iso()
        threads_json = json.dumps(unresolved_threads or [])
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE series SET
                    current_season = ?,
                    current_episode = ?,
                    last_cliffhanger = ?,
                    unresolved_threads = ?,
                    updated_at = ?
                WHERE series_id = ?;
                """,
                (current_season, current_episode, last_cliffhanger, threads_json, now, series_id),
            )
            return cursor.rowcount > 0

    def advance_episode(self, series_id: str) -> int:
        """Atomically increments current_episode and returns the new episode number."""
        now = _utc_now_iso()
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE series SET
                    current_episode = current_episode + 1,
                    updated_at = ?
                WHERE series_id = ?;
                """,
                (now, series_id),
            )
            cursor = conn.execute("SELECT current_episode FROM series WHERE series_id = ?;", (series_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Series '{series_id}' not found in ledger")
            return int(row["current_episode"])

    def get_series_state(self, series_id: str) -> Optional[SeriesState]:
        """Reconstructs the full SeriesState domain model including characters and episode history."""
        series = self.get_series(series_id)
        if not series:
            return None

        chars = self.get_characters(series_id)
        char_dict: dict[str, Any] = {c.name: c for c in chars}

        episodes = self.list_episodes(series_id)
        history = [
            {
                "episode_num": ep["episode_num"],
                "title": ep["title"],
                "duration": ep["actual_duration"],
                "word_count": ep["total_word_count"],
                "wpm": ep["overall_wpm"],
                "cliffhanger": ep["cliffhanger"] or "",
            }
            for ep in episodes
        ]

        return SeriesState(
            series_id=series["series_id"],
            title=series["title"],
            genre=series["genre"],
            premise=series["logline"],
            current_season=series["current_season"],
            current_episode=series["current_episode"],
            characters=char_dict,
            last_cliffhanger=series["last_cliffhanger"],
            unresolved_threads=series.get("unresolved_threads", []),
            episode_history=history,
        )

    # -------------------------------------------------------------------------
    # Character Persistence
    # -------------------------------------------------------------------------

    def save_character(self, series_id: str, character_profile: CharacterProfile) -> bool:
        """Saves or updates a persistent character profile bound to a series."""
        now = _utc_now_iso()
        rel_json = json.dumps(character_profile.relationships)
        tags_json = json.dumps(character_profile.tags)
        entity_type_str = character_profile.entity_type.value if hasattr(character_profile.entity_type, "value") else str(character_profile.entity_type)

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO characters (
                    series_id, character_id, name, entity_type, visual_summary,
                    personality, voice_profile, seed, reference_image_url, media_id,
                    relationships, tags, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, character_id) DO UPDATE SET
                    name = excluded.name,
                    entity_type = excluded.entity_type,
                    visual_summary = excluded.visual_summary,
                    personality = excluded.personality,
                    voice_profile = excluded.voice_profile,
                    seed = excluded.seed,
                    reference_image_url = excluded.reference_image_url,
                    media_id = excluded.media_id,
                    relationships = excluded.relationships,
                    tags = excluded.tags,
                    updated_at = excluded.updated_at;
                """,
                (
                    series_id,
                    character_profile.character_id,
                    character_profile.name,
                    entity_type_str,
                    character_profile.visual_summary,
                    character_profile.personality,
                    character_profile.voice_profile,
                    character_profile.seed,
                    character_profile.reference_image_url,
                    character_profile.media_id,
                    rel_json,
                    tags_json,
                    now,
                    now,
                ),
            )
            return True

    def get_characters(self, series_id: str) -> list[CharacterProfile]:
        """Retrieves all registered character profiles for a given series."""
        with self.transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM characters WHERE series_id = ? ORDER BY id ASC;",
                (series_id,),
            )
            rows = cursor.fetchall()
            profiles: list[CharacterProfile] = []
            for row in rows:
                try:
                    rel = json.loads(row["relationships"])
                except Exception:
                    rel = {}
                try:
                    tags = json.loads(row["tags"])
                except Exception:
                    tags = []

                profiles.append(
                    CharacterProfile(
                        character_id=row["character_id"],
                        name=row["name"],
                        entity_type=EntityType(row["entity_type"]),
                        visual_summary=row["visual_summary"],
                        personality=row["personality"] or "",
                        voice_profile=row["voice_profile"] or "en-US-ChristopherNeural",
                        seed=row["seed"],
                        reference_image_url=row["reference_image_url"],
                        media_id=row["media_id"],
                        relationships=rel,
                        tags=tags,
                    )
                )
            return profiles

    # -------------------------------------------------------------------------
    # Episode Manifest Persistence
    # -------------------------------------------------------------------------

    def save_episode_manifest(
        self,
        manifest: EpisodeManifest,
        status: str = "planned",
    ) -> bool:
        """Saves or updates an EpisodeManifest in the database."""
        now = _utc_now_iso()
        manifest_json = manifest.model_dump_json()

        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO episodes (
                    series_id, episode_num, season_num, title, premise, target_duration,
                    actual_duration, total_word_count, overall_wpm, cliffhanger,
                    next_episode_hook, micro_loop, loop_phrase, manifest_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(series_id, episode_num, season_num) DO UPDATE SET
                    title = excluded.title,
                    premise = excluded.premise,
                    target_duration = excluded.target_duration,
                    actual_duration = excluded.actual_duration,
                    total_word_count = excluded.total_word_count,
                    overall_wpm = excluded.overall_wpm,
                    cliffhanger = excluded.cliffhanger,
                    next_episode_hook = excluded.next_episode_hook,
                    micro_loop = excluded.micro_loop,
                    loop_phrase = excluded.loop_phrase,
                    manifest_json = excluded.manifest_json,
                    status = excluded.status,
                    updated_at = excluded.updated_at;
                """,
                (
                    manifest.series_id,
                    manifest.episode_num,
                    manifest.season_num,
                    manifest.title,
                    manifest.premise,
                    manifest.target_duration,
                    manifest.actual_duration,
                    manifest.total_word_count,
                    manifest.overall_wpm,
                    manifest.cliffhanger,
                    manifest.next_episode_hook,
                    manifest.micro_loop,
                    manifest.loop_phrase,
                    manifest_json,
                    status,
                    now,
                    now,
                ),
            )
            return True

    def get_episode_manifest(
        self,
        series_id: str,
        episode_num: int,
        season_num: int = 1,
    ) -> Optional[EpisodeManifest]:
        """Retrieves and deserializes an EpisodeManifest from the database."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT manifest_json FROM episodes
                WHERE series_id = ? AND episode_num = ? AND season_num = ?;
                """,
                (series_id, episode_num, season_num),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return EpisodeManifest.model_validate_json(row["manifest_json"])

    def get_episode(
        self,
        series_id: str,
        episode_num: int,
        season_num: int = 1,
    ) -> Optional[dict[str, Any]]:
        """Retrieves raw database record for a specific episode."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM episodes
                WHERE series_id = ? AND episode_num = ? AND season_num = ?;
                """,
                (series_id, episode_num, season_num),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def list_episodes(self, series_id: str) -> list[dict[str, Any]]:
        """Lists summary metadata for all episodes in a series ordered by episode_num."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT id, series_id, episode_num, season_num, title, premise,
                       target_duration, actual_duration, total_word_count, overall_wpm,
                       cliffhanger, next_episode_hook, status, created_at, updated_at
                FROM episodes
                WHERE series_id = ?
                ORDER BY season_num ASC, episode_num ASC;
                """,
                (series_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def update_episode_status(
        self,
        series_id: str,
        episode_num: int,
        status: str,
        season_num: int = 1,
    ) -> bool:
        """Updates the lifecycle status of an episode (e.g. directed, generating, completed, failed)."""
        now = _utc_now_iso()
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE episodes SET status = ?, updated_at = ?
                WHERE series_id = ? AND episode_num = ? AND season_num = ?;
                """,
                (status, now, series_id, episode_num, season_num),
            )
            return cursor.rowcount > 0

    # -------------------------------------------------------------------------
    # Render Output Tracking
    # -------------------------------------------------------------------------

    def record_render_output(
        self,
        series_id: str,
        episode_num: int,
        output_path: str,
        duration: float,
        generation_mode: str = "mock",
        metadata: Optional[dict[str, Any]] = None,
        status: str = "completed",
    ) -> int:
        """Records an assembled video render output artifact in the ledger."""
        now = _utc_now_iso()
        meta_json = json.dumps(metadata or {})
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO renders (
                    series_id, episode_num, output_path, duration,
                    generation_mode, status, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    series_id,
                    episode_num,
                    output_path,
                    duration,
                    generation_mode,
                    status,
                    meta_json,
                    now,
                ),
            )
            render_id = cursor.lastrowid or 0

            # Also update episode status to completed if successful
            if status == "completed":
                conn.execute(
                    """
                    UPDATE episodes SET status = 'completed', updated_at = ?
                    WHERE series_id = ? AND episode_num = ?;
                    """,
                    (now, series_id, episode_num),
                )

            return render_id

    def get_latest_render(self, series_id: str, episode_num: int) -> Optional[dict[str, Any]]:
        """Retrieves the latest render record for a given episode."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM renders
                WHERE series_id = ? AND episode_num = ?
                ORDER BY id DESC LIMIT 1;
                """,
                (series_id, episode_num),
            )
            row = cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["metadata"] = json.loads(data["metadata"])
            except Exception:
                data["metadata"] = {}
            return data

    def list_renders(self, series_id: str) -> list[dict[str, Any]]:
        """Lists all renders associated with a series ordered chronologically."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM renders
                WHERE series_id = ?
                ORDER BY id ASC;
                """,
                (series_id,),
            )
            renders = []
            for row in cursor.fetchall():
                data = dict(row)
                try:
                    data["metadata"] = json.loads(data["metadata"])
                except Exception:
                    data["metadata"] = {}
                renders.append(data)
            return renders

    # -------------------------------------------------------------------------
    # Character State Delta Tracking
    # -------------------------------------------------------------------------

    def record_character_delta(
        self,
        series_id: str,
        episode_num: int,
        character_name: str,
        delta_type: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        description: str = "",
    ) -> int:
        """Records a narrative or physical state delta for a character during an episode."""
        now = _utc_now_iso()
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO character_state_deltas (
                    series_id, episode_num, character_name, delta_type,
                    old_value, new_value, description, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    series_id,
                    episode_num,
                    character_name,
                    delta_type,
                    old_value,
                    new_value,
                    description,
                    now,
                ),
            )
            return cursor.lastrowid or 0

    def get_character_history(self, series_id: str, character_name: str) -> list[dict[str, Any]]:
        """Retrieves chronological history of state deltas for a given character."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM character_state_deltas
                WHERE series_id = ? AND character_name = ?
                ORDER BY episode_num ASC, id ASC;
                """,
                (series_id, character_name),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_all_deltas(self, series_id: str) -> list[dict[str, Any]]:
        """Retrieves all character state deltas for a series."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM character_state_deltas
                WHERE series_id = ?
                ORDER BY episode_num ASC, id ASC;
                """,
                (series_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # Publications Management (Multi-platform Social Media Distribution)
    # -------------------------------------------------------------------------

    def record_publication(
        self,
        series_id: str,
        episode_num: int,
        platform: str,
        post_id: Optional[str] = None,
        video_url: Optional[str] = None,
        status: str = "published",
        metadata: str = "{}",
    ) -> int:
        """Records a completed or pending social media upload in the ledger."""
        now = _utc_now_iso()
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO publications (
                    series_id, episode_num, platform, post_id, video_url, status, metadata, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    series_id,
                    episode_num,
                    platform.lower(),
                    post_id,
                    video_url,
                    status,
                    metadata,
                    now,
                ),
            )
            return cursor.lastrowid or 0

    def get_episode_publications(self, series_id: str, episode_num: int) -> list[dict[str, Any]]:
        """Retrieves all publications recorded for a given episode."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM publications
                WHERE series_id = ? AND episode_num = ?
                ORDER BY published_at DESC, id DESC;
                """,
                (series_id, episode_num),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_series_publications(self, series_id: str) -> list[dict[str, Any]]:
        """Retrieves all publications across all episodes for a series."""
        with self.transaction() as conn:
            cursor = conn.execute(
                """
                SELECT * FROM publications
                WHERE series_id = ?
                ORDER BY episode_num ASC, published_at DESC;
                """,
                (series_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

