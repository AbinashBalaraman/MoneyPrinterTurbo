"""Unit tests for EpisodicLedger with SQLite WAL mode and atomic short-lived transactions."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
import pytest

from src.director.character import build_default_characters
from src.director.director import StoryDirector
from src.models import (
    CharacterProfile,
    EntityType,
    EpisodeManifest,
    SeriesState,
)
from src.storage.ledger import EpisodicLedger


@pytest.fixture
def temp_ledger(tmp_path: Path) -> EpisodicLedger:
    """Fixture providing an EpisodicLedger backed by a temporary file."""
    db_file = tmp_path / "test_ledger.db"
    return EpisodicLedger(db_path=db_file)


class TestEpisodicLedgerConfiguration:
    """Tests SQLite connection configuration, WAL mode, foreign keys, and pragmas."""

    def test_wal_mode_and_pragmas(self, temp_ledger: EpisodicLedger):
        conn = temp_ledger.get_connection()
        try:
            # WAL mode check
            cur = conn.execute("PRAGMA journal_mode;")
            mode = cur.fetchone()[0].upper()
            assert mode == "WAL"

            # Busy timeout check
            cur = conn.execute("PRAGMA busy_timeout;")
            timeout = cur.fetchone()[0]
            assert timeout == 30000

            # Foreign keys check
            cur = conn.execute("PRAGMA foreign_keys;")
            fk = cur.fetchone()[0]
            assert fk == 1
        finally:
            conn.close()

    def test_foreign_key_enforcement(self, temp_ledger: EpisodicLedger):
        """Inserting a character with an invalid series_id must fail via foreign key check."""
        profile = CharacterProfile(
            character_id="char_orphan",
            name="Orphan Ghost",
            visual_summary="A spectral figure in a neon trench coat",
        )
        with pytest.raises(sqlite3.IntegrityError):
            temp_ledger.save_character("non_existent_series", profile)


class TestSeriesCRUD:
    """Tests series registration, retrieval, updating, and state reconstruction."""

    def test_register_and_get_series(self, temp_ledger: EpisodicLedger):
        series = temp_ledger.register_series(
            series_id="noir_01",
            title="Neon Shadows",
            genre="Cyberpunk Noir",
            logline="A detective hunts a rogue temporal chronometer.",
            target_duration=45.0,
            pacing_rhythm="pulse_action",
        )
        assert series["series_id"] == "noir_01"
        assert series["title"] == "Neon Shadows"
        assert series["current_episode"] == 0
        assert series["current_season"] == 1
        assert series["unresolved_threads"] == []

        fetched = temp_ledger.get_series("noir_01")
        assert fetched is not None
        assert fetched["title"] == "Neon Shadows"
        assert fetched["target_duration"] == 45.0

    def test_get_nonexistent_series(self, temp_ledger: EpisodicLedger):
        assert temp_ledger.get_series("ghost_series") is None
        assert temp_ledger.get_series_state("ghost_series") is None

    def test_update_series_state(self, temp_ledger: EpisodicLedger):
        temp_ledger.register_series(
            series_id="noir_02",
            title="Neon Shadows 2",
            genre="Cyberpunk Noir",
        )
        updated = temp_ledger.update_series_state(
            series_id="noir_02",
            current_season=1,
            current_episode=2,
            last_cliffhanger="The vault door seals shut.",
            unresolved_threads=["Who forged the chronometer signature?"],
        )
        assert updated is True

        series = temp_ledger.get_series("noir_02")
        assert series is not None
        assert series["current_episode"] == 2
        assert series["last_cliffhanger"] == "The vault door seals shut."
        assert series["unresolved_threads"] == ["Who forged the chronometer signature?"]

    def test_advance_episode(self, temp_ledger: EpisodicLedger):
        temp_ledger.register_series(
            series_id="noir_03",
            title="Neon Shadows 3",
            genre="Cyberpunk Noir",
        )
        ep1 = temp_ledger.advance_episode("noir_03")
        assert ep1 == 1
        ep2 = temp_ledger.advance_episode("noir_03")
        assert ep2 == 2

        series = temp_ledger.get_series("noir_03")
        assert series["current_episode"] == 2


class TestCharacterPersistence:
    """Tests saving, updating, and querying character profiles."""

    def test_save_and_retrieve_characters(self, temp_ledger: EpisodicLedger):
        temp_ledger.register_series("cyber_01", "Cyber Test", "Sci-Fi")
        chars = build_default_characters()

        for c in chars:
            saved = temp_ledger.save_character("cyber_01", c)
            assert saved is True

        retrieved = temp_ledger.get_characters("cyber_01")
        assert len(retrieved) == len(chars)

        names = {c.name for c in retrieved}
        assert "Detective Rex Vance" in names
        assert "Dr. Aris Thorne" in names
        assert "Maya Lin" in names

    def test_character_upsert(self, temp_ledger: EpisodicLedger):
        temp_ledger.register_series("cyber_02", "Cyber Test 2", "Sci-Fi")
        c = CharacterProfile(
            character_id="char_rex",
            name="Rex Vance",
            visual_summary="Cybernetic eye, weathered trench coat",
            personality="Cynical",
        )
        temp_ledger.save_character("cyber_02", c)

        # Update Rex
        c_updated = CharacterProfile(
            character_id="char_rex",
            name="Rex Vance",
            visual_summary="Cybernetic eye, burned trench coat with scar",
            personality="Enraged",
        )
        temp_ledger.save_character("cyber_02", c_updated)

        chars = temp_ledger.get_characters("cyber_02")
        assert len(chars) == 1
        assert chars[0].visual_summary == "Cybernetic eye, burned trench coat with scar"
        assert chars[0].personality == "Enraged"


class TestEpisodeManifestStorage:
    """Tests saving and retrieving full EpisodeManifest structures with Pydantic fidelity."""

    def test_manifest_roundtrip(self, temp_ledger: EpisodicLedger):
        series_id = "series_manifest_test"
        temp_ledger.register_series(
            series_id=series_id,
            title="Manifest Journey",
            genre="Thriller",
        )

        state = SeriesState(
            series_id=series_id,
            title="Manifest Journey",
            genre="Thriller",
            current_season=1,
            current_episode=0,
        )
        for c in build_default_characters():
            temp_ledger.save_character(series_id, c)
            state.characters[c.name] = c

        director = StoryDirector()
        manifest = director.direct_episode(state, episode_num=1, target_duration=45.0)

        # Save to ledger
        saved = temp_ledger.save_episode_manifest(manifest, status="directed")
        assert saved is True

        # Retrieve and verify roundtrip fidelity
        fetched = temp_ledger.get_episode_manifest(series_id, episode_num=1)
        assert fetched is not None
        assert fetched.series_id == series_id
        assert fetched.episode_num == 1
        assert fetched.title == manifest.title
        assert fetched.target_duration == manifest.target_duration
        assert len(fetched.scenes) == len(manifest.scenes)
        assert fetched.cliffhanger == manifest.cliffhanger
        assert fetched.micro_loop == manifest.micro_loop

        # Verify scenes integrity
        for orig_s, fetched_s in zip(manifest.scenes, fetched.scenes):
            assert orig_s.scene_index == fetched_s.scene_index
            assert orig_s.time_start == fetched_s.time_start
            assert orig_s.time_end == fetched_s.time_end
            assert orig_s.narration == fetched_s.narration
            assert orig_s.action_prompt == fetched_s.action_prompt
            assert orig_s.bound_characters == fetched_s.bound_characters

    def test_list_episodes_and_status(self, temp_ledger: EpisodicLedger):
        series_id = "series_list_test"
        temp_ledger.register_series(series_id, "Listing Test", "Sci-Fi")

        state = SeriesState(series_id=series_id, title="Listing Test", genre="Sci-Fi")
        director = StoryDirector()

        for ep_num in [1, 2]:
            m = director.direct_episode(state, episode_num=ep_num, target_duration=45.0)
            temp_ledger.save_episode_manifest(m, status="directed")

        episodes = temp_ledger.list_episodes(series_id)
        assert len(episodes) == 2
        assert episodes[0]["episode_num"] == 1
        assert episodes[1]["episode_num"] == 2
        assert episodes[0]["status"] == "directed"

        # Update status
        temp_ledger.update_episode_status(series_id, 1, "completed")
        episodes_after = temp_ledger.list_episodes(series_id)
        assert episodes_after[0]["status"] == "completed"


class TestCharacterDeltasAndRenders:
    """Tests character state deltas tracking and render outputs recording."""

    def test_record_and_get_character_history(self, temp_ledger: EpisodicLedger):
        series_id = "delta_series"
        temp_ledger.register_series(series_id, "Delta Series", "Drama")

        temp_ledger.record_character_delta(
            series_id=series_id,
            episode_num=1,
            character_name="Rex Vance",
            delta_type="injury",
            old_value="Healthy",
            new_value="Burned left shoulder from laser grazing",
            description="Suffered blast damage during vault escape",
        )

        temp_ledger.record_character_delta(
            series_id=series_id,
            episode_num=2,
            character_name="Rex Vance",
            delta_type="inventory",
            old_value="Unarmed",
            new_value="Acquired plasma cutter",
            description="Recovered tool from Dr. Thorne's abandoned bench",
        )

        history = temp_ledger.get_character_history(series_id, "Rex Vance")
        assert len(history) == 2
        assert history[0]["episode_num"] == 1
        assert history[0]["delta_type"] == "injury"
        assert history[1]["episode_num"] == 2
        assert history[1]["delta_type"] == "inventory"

    def test_record_render_output(self, temp_ledger: EpisodicLedger):
        series_id = "render_series"
        temp_ledger.register_series(series_id, "Render Series", "Action")

        # Save an episode first
        state = SeriesState(series_id=series_id, title="Render Series", genre="Action")
        director = StoryDirector()
        m = director.direct_episode(state, episode_num=1, target_duration=45.0)
        temp_ledger.save_episode_manifest(m, status="directed")

        render_id = temp_ledger.record_render_output(
            series_id=series_id,
            episode_num=1,
            output_path="output/episode_01.mp4",
            duration=45.2,
            generation_mode="mock",
            metadata={"project_id": "proj_123", "scenes_rendered": 5},
            status="completed",
        )
        assert render_id > 0

        latest = temp_ledger.get_latest_render(series_id, episode_num=1)
        assert latest is not None
        assert latest["output_path"] == "output/episode_01.mp4"
        assert latest["duration"] == 45.2
        assert latest["metadata"]["project_id"] == "proj_123"

        # Verify episode status updated to completed automatically
        episodes = temp_ledger.list_episodes(series_id)
        assert episodes[0]["status"] == "completed"


class TestSeriesStateReconstruction:
    """Tests reconstructing SeriesState domain model from ledger data."""

    def test_get_series_state_complete(self, temp_ledger: EpisodicLedger):
        series_id = "state_series"
        temp_ledger.register_series(
            series_id=series_id,
            title="State Reconstruction",
            genre="Noir",
            logline="Testing full state reconstruction",
        )
        chars = build_default_characters()
        for c in chars:
            temp_ledger.save_character(series_id, c)

        state = temp_ledger.get_series_state(series_id)
        assert state is not None
        assert state.series_id == series_id
        assert state.title == "State Reconstruction"
        assert len(state.characters) == len(chars)
        assert "Detective Rex Vance" in state.characters


class TestConcurrencyAndRollback:
    """Tests multi-threaded concurrent access in WAL mode and transaction rollback integrity."""

    def test_concurrent_reads_and_writes(self, temp_ledger: EpisodicLedger):
        series_id = "concurrency_series"
        temp_ledger.register_series(series_id, "Concurrency Series", "Tech")

        errors: list[Exception] = []

        def worker(thread_id: int):
            try:
                for i in range(10):
                    # Record a delta
                    temp_ledger.record_character_delta(
                        series_id=series_id,
                        episode_num=1,
                        character_name="Rex Vance",
                        delta_type="heartbeat",
                        description=f"Thread {thread_id} beat {i}",
                    )
                    # Read series
                    series = temp_ledger.get_series(series_id)
                    assert series is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrency errors occurred: {errors}"
        deltas = temp_ledger.get_character_history(series_id, "Rex Vance")
        assert len(deltas) == 40

    def test_transaction_rollback_integrity(self, temp_ledger: EpisodicLedger):
        series_id = "rollback_series"
        temp_ledger.register_series(series_id, "Rollback Series", "Test")

        # Attempt transaction that executes valid insert then fails
        try:
            with temp_ledger.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO character_state_deltas (
                        series_id, episode_num, character_name, delta_type,
                        description, created_at
                    ) VALUES (?, 1, 'Rex Vance', 'test_delta', 'valid insert', '2026-09-12T00:00:00Z');
                    """,
                    (series_id,),
                )
                # Intentional error: violates foreign key with non-existent series
                conn.execute(
                    """
                    INSERT INTO character_state_deltas (
                        series_id, episode_num, character_name, delta_type,
                        description, created_at
                    ) VALUES ('non_existent_series_fk', 1, 'Rex Vance', 'bad_delta', 'invalid', '2026-09-12T00:00:00Z');
                    """
                )
        except sqlite3.IntegrityError:
            pass

        # Verify that the first insert was rolled back!
        deltas = temp_ledger.get_character_history(series_id, "Rex Vance")
        assert len(deltas) == 0

    def test_cascade_delete_series(self, temp_ledger: EpisodicLedger):
        series_id = "cascade_series"
        temp_ledger.register_series(series_id, "Cascade Series", "Mystery")
        c = CharacterProfile(
            character_id="char_c",
            name="Cascade Char",
            visual_summary="Visual summary test",
        )
        temp_ledger.save_character(series_id, c)
        temp_ledger.record_character_delta(
            series_id=series_id,
            episode_num=1,
            character_name="Cascade Char",
            delta_type="status",
            description="Active",
        )

        # Delete series directly with foreign keys enabled
        with temp_ledger.transaction() as conn:
            conn.execute("DELETE FROM series WHERE series_id = ?;", (series_id,))

        # Verify characters and deltas were cascade-deleted
        assert len(temp_ledger.get_characters(series_id)) == 0
        assert len(temp_ledger.get_character_history(series_id, "Cascade Char")) == 0
