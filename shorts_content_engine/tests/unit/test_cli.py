"""Unit tests for the CLI runner and batch automation subsystem."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from src.cli import build_parser, main
from src.storage.ledger import EpisodicLedger


@pytest.fixture
def cli_db(tmp_path: Path) -> Path:
    """Fixture returning path to a temporary SQLite ledger database."""
    return tmp_path / "cli_test_ledger.db"


@pytest.fixture
def output_dir(tmp_path: Path) -> Path:
    """Fixture returning path to a temporary output folder."""
    out = tmp_path / "renders"
    out.mkdir(parents=True, exist_ok=True)
    return out


class TestCLIParser:
    """Tests argument parser configuration and subcommand routing."""

    def test_parser_init_series(self):
        parser = build_parser()
        args = parser.parse_args([
            "init-series",
            "--series-id", "s1",
            "--title", "Series One",
            "--genre", "Noir",
            "--target-duration", "50.0",
        ])
        assert args.command == "init-series"
        assert args.series_id == "s1"
        assert args.title == "Series One"
        assert args.genre == "Noir"
        assert args.target_duration == 50.0
        assert args.seed_characters is True

    def test_parser_direct(self):
        parser = build_parser()
        args = parser.parse_args([
            "direct",
            "--series-id", "s1",
            "--episode", "2",
            "--duration", "40.0",
            "--rhythm", "noir_suspense",
        ])
        assert args.command == "direct"
        assert args.series_id == "s1"
        assert args.episode == 2
        assert args.duration == 40.0
        assert args.rhythm == "noir_suspense"

    def test_parser_generate_mock_and_live(self):
        parser = build_parser()
        args_mock = parser.parse_args(["generate", "--series-id", "s1", "--mock"])
        assert args_mock.mock is True

        args_live = parser.parse_args(["generate", "--series-id", "s1", "--live"])
        assert args_live.mock is False

    def test_parser_batch(self):
        parser = build_parser()
        args = parser.parse_args([
            "batch",
            "--series-id", "s1",
            "-n", "5",
            "--start-episode", "1",
        ])
        assert args.command == "batch"
        assert args.series_id == "s1"
        assert args.episodes == 5
        assert args.start_episode == 1


class TestCLIInitSeries:
    """Tests init-series subcommand execution."""

    def test_init_series_with_seeded_characters(self, cli_db: Path):
        code = main([
            "init-series",
            "--series-id", "neon_pulse",
            "--title", "Neon Pulse",
            "--genre", "Cyberpunk Noir",
            "--logline", "A detective hunts a rogue temporal relay.",
            "--target-duration", "45.0",
            "--db-path", str(cli_db),
        ])
        assert code == 0

        ledger = EpisodicLedger(db_path=cli_db)
        series = ledger.get_series("neon_pulse")
        assert series is not None
        assert series["title"] == "Neon Pulse"
        assert series["target_duration"] == 45.0

        # Verify seeded characters
        chars = ledger.get_characters("neon_pulse")
        assert len(chars) >= 3
        names = {c.name for c in chars}
        assert "Detective Rex Vance" in names

    def test_init_series_no_seed_characters(self, cli_db: Path):
        code = main([
            "init-series",
            "--series-id", "empty_series",
            "--title", "Empty Series",
            "--genre", "Mystery",
            "--no-seed-characters",
            "--db-path", str(cli_db),
        ])
        assert code == 0

        ledger = EpisodicLedger(db_path=cli_db)
        chars = ledger.get_characters("empty_series")
        assert len(chars) == 0


class TestCLIDirect:
    """Tests direct subcommand execution and manifest generation."""

    def test_direct_missing_series_fails(self, cli_db: Path):
        code = main(["direct", "--series-id", "nonexistent", "--db-path", str(cli_db)])
        assert code == 1

    def test_direct_single_episode_advances_state(self, cli_db: Path, tmp_path: Path):
        # Init series first
        main([
            "init-series",
            "--series-id", "direct_test",
            "--title", "Directing Test",
            "--genre", "Thriller",
            "--db-path", str(cli_db),
        ])

        manifest_file = tmp_path / "ep1_manifest.json"
        code = main([
            "direct",
            "--series-id", "direct_test",
            "--episode", "1",
            "--duration", "45.0",
            "--output-manifest", str(manifest_file),
            "--db-path", str(cli_db),
        ])
        assert code == 0

        # Check ledger
        ledger = EpisodicLedger(db_path=cli_db)
        series = ledger.get_series("direct_test")
        assert series["current_episode"] == 1
        assert series["last_cliffhanger"] is not None

        manifest = ledger.get_episode_manifest("direct_test", episode_num=1)
        assert manifest is not None
        assert manifest.episode_num == 1
        assert len(manifest.scenes) >= 5

        # Check JSON file written
        assert manifest_file.exists()
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        assert data["episode_num"] == 1


class TestCLIGenerate:
    """Tests generate subcommand execution with mock FlowKit orchestration."""

    def test_generate_mock_episode(self, cli_db: Path, output_dir: Path):
        # Init & direct
        main([
            "init-series",
            "--series-id", "gen_test",
            "--title", "Generation Test",
            "--genre", "Action",
            "--db-path", str(cli_db),
        ])
        main([
            "direct",
            "--series-id", "gen_test",
            "--episode", "1",
            "--db-path", str(cli_db),
        ])

        # Generate in mock mode
        code = main([
            "generate",
            "--series-id", "gen_test",
            "--episode", "1",
            "--mock",
            "--output-dir", str(output_dir),
            "--db-path", str(cli_db),
        ])
        assert code == 0

        # Check ledger render record
        ledger = EpisodicLedger(db_path=cli_db)
        render = ledger.get_latest_render("gen_test", episode_num=1)
        assert render is not None
        assert render["generation_mode"] == "mock"
        assert render["status"] == "completed"
        assert os.path.exists(render["output_path"])


class TestCLIBatch:
    """Tests daily batch automation runner executing N sequential episodes."""

    def test_batch_automation_3_episodes(self, cli_db: Path, output_dir: Path):
        # Init series
        main([
            "init-series",
            "--series-id", "batch_series",
            "--title", "The Chronos Cycle",
            "--genre", "Cyberpunk Noir",
            "--target-duration", "45.0",
            "--db-path", str(cli_db),
        ])

        # Run 3-episode batch
        code = main([
            "batch",
            "--series-id", "batch_series",
            "-n", "3",
            "--mock",
            "--output-dir", str(output_dir),
            "--db-path", str(cli_db),
        ])
        assert code == 0

        # Verify ledger state across all 3 episodes
        ledger = EpisodicLedger(db_path=cli_db)
        series = ledger.get_series("batch_series")
        assert series["current_episode"] == 3
        assert len(series["unresolved_threads"]) >= 2

        episodes = ledger.list_episodes("batch_series")
        assert len(episodes) == 3
        assert [e["episode_num"] for e in episodes] == [1, 2, 3]
        for ep in episodes:
            assert ep["status"] == "completed"
            assert 140.0 <= ep["overall_wpm"] <= 165.0

        # Verify renders created and recorded
        renders = ledger.list_renders("batch_series")
        assert len(renders) == 3
        for r in renders:
            assert os.path.exists(r["output_path"])
            assert r["status"] == "completed"

        # Verify character deltas tracked
        deltas = ledger.list_all_deltas("batch_series")
        assert len(deltas) >= 3


class TestCLIStatusAndValidate:
    """Tests status and validate subcommands."""

    def test_status_command(self, cli_db: Path, output_dir: Path, capsys):
        # Init and direct
        main([
            "init-series",
            "--series-id", "stat_test",
            "--title", "Status Test",
            "--genre", "Sci-Fi",
            "--db-path", str(cli_db),
        ])
        main([
            "direct",
            "--series-id", "stat_test",
            "--episode", "1",
            "--db-path", str(cli_db),
        ])

        code = main(["status", "--series-id", "stat_test", "--db-path", str(cli_db)])
        assert code == 0

        captured = capsys.readouterr()
        assert "Status Test" in captured.out
        assert "Detective Rex Vance" in captured.out
        assert "Ep 1" in captured.out

    def test_status_all_series(self, cli_db: Path, capsys):
        main([
            "init-series",
            "--series-id", "s_alpha",
            "--title", "Series Alpha",
            "--genre", "Noir",
            "--db-path", str(cli_db),
        ])
        main([
            "init-series",
            "--series-id", "s_beta",
            "--title", "Series Beta",
            "--genre", "Sci-Fi",
            "--db-path", str(cli_db),
        ])

        code = main(["status", "--db-path", str(cli_db)])
        assert code == 0
        captured = capsys.readouterr()
        assert "Series Alpha" in captured.out
        assert "Series Beta" in captured.out

    def test_validate_command_synthetic(self, cli_db: Path):
        code = main(["validate", "--db-path", str(cli_db)])
        assert code == 0

    def test_validate_command_existing_manifest(self, cli_db: Path):
        main([
            "init-series",
            "--series-id", "val_test",
            "--title", "Validation Series",
            "--genre", "Noir",
            "--db-path", str(cli_db),
        ])
        main([
            "direct",
            "--series-id", "val_test",
            "--episode", "1",
            "--db-path", str(cli_db),
        ])

        code = main([
            "validate",
            "--series-id", "val_test",
            "--episode", "1",
            "--db-path", str(cli_db),
        ])
        assert code == 0


class TestCLISubprocess:
    """Tests real subprocess execution of python -m src.cli."""

    def test_subprocess_cli_help(self):
        cmd = [sys.executable, "-m", "src.cli", "--help"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        assert res.returncode == 0
        assert "shorts_engine" in res.stdout
        assert "init-series" in res.stdout
        assert "batch" in res.stdout
