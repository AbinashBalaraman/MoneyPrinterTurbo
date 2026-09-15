"""Tests for the AutoShorts runner's pure helpers.

Focus is on the parts where a mistake would be silent and expensive: the
environment defaults that decide what gets generated, the summary parser that
decides what gets recorded as published, and the params template that decides
what reaches the pipeline.
"""

import json

import pytest

from automation import runner


# ------------------------------------------------------- environment defaults


def test_parser_defaults_come_from_environment(monkeypatch):
    """Regression: .env must reach the CLI defaults.

    The parser is built before app.config is imported, so unless .env is loaded
    early these values are invisible and the runner silently uses its built-in
    defaults instead.
    """
    monkeypatch.setenv("AUTOSHORTS_SOURCE_TYPE", "rss")
    monkeypatch.setenv("AUTOSHORTS_SOURCE_URL", "https://example.com/feed.xml")
    monkeypatch.setenv("AUTOSHORTS_LIMIT", "4")
    monkeypatch.setenv("AUTOSHORTS_STOP_AT", "script")
    monkeypatch.setenv("AUTOSHORTS_DRY_RUN", "true")

    args = runner._build_parser().parse_args([])

    assert args.source_type == "rss"
    assert args.source_url == "https://example.com/feed.xml"
    assert args.limit == 4
    assert args.stop_at == "script"
    assert args.dry_run is True


def test_explicit_flags_beat_environment(monkeypatch):
    monkeypatch.setenv("AUTOSHORTS_LIMIT", "9")
    monkeypatch.setenv("AUTOSHORTS_DRY_RUN", "true")

    args = runner._build_parser().parse_args(["--limit", "2"])

    assert args.limit == 2
    # A safe-by-default env var must remain escapable from the command line.
    assert args.dry_run is True
    assert runner._build_parser().parse_args(["--no-dry-run"]).dry_run is False


def test_dry_run_defaults_to_false_when_unset(monkeypatch):
    monkeypatch.delenv("AUTOSHORTS_DRY_RUN", raising=False)
    args = runner._build_parser().parse_args([])
    assert args.dry_run is False


# ------------------------------------------------------------ summary parsing


def _summary(**overrides):
    payload = {"total": 1, "succeeded": 1, "failed": 0, "tasks": [{"index": 1}]}
    payload.update(overrides)
    return json.dumps(payload)


def test_parse_summary_accepts_clean_json():
    parsed = runner._parse_summary(_summary())
    assert parsed is not None
    assert len(parsed["tasks"]) == 1


def test_parse_summary_tolerates_leading_output():
    stdout = "some incidental banner\n" + _summary()
    parsed = runner._parse_summary(stdout)
    assert parsed is not None
    assert parsed["total"] == 1


def test_parse_summary_returns_none_on_junk():
    assert runner._parse_summary("") is None
    assert runner._parse_summary("not json at all") is None
    # Valid JSON, but not a batch summary.
    assert runner._parse_summary('{"unrelated": true}') is None


# ---------------------------------------------------------- params templates


def test_params_template_rejects_video_subject(tmp_path):
    """video_subject comes from the topic; letting a template set it would
    silently make every generated video identical."""
    path = tmp_path / "params.json"
    path.write_text(json.dumps({"video_subject": "hijacked"}), encoding="utf-8")

    with pytest.raises(ValueError, match="must not set video_subject"):
        runner._load_params_template(str(path))


def test_params_template_rejects_non_object(tmp_path):
    path = tmp_path / "params.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        runner._load_params_template(str(path))


def test_params_template_missing_file_raises():
    with pytest.raises(ValueError, match="not found"):
        runner._load_params_template("does/not/exist.json")


def test_params_template_absent_returns_empty():
    assert runner._load_params_template(None) == {}


def test_params_template_rejects_unknown_fields(tmp_path):
    """Unknown keys must fail here, not on task 1 of N after the ledger has
    already claimed every topic in the batch."""
    path = tmp_path / "params.json"
    path.write_text(json.dumps({"_comment": "x", "video_aspect": "9:16"}), encoding="utf-8")

    with pytest.raises(ValueError, match="not VideoParams fields"):
        runner._load_params_template(str(path))


def test_shipped_free_profile_is_valid():
    """Guards the free-only profile against typos in future edits."""
    import os

    path = os.path.join(runner.REPO_ROOT, "automation", "free.params.json")
    payload = runner._load_params_template(path)

    # The whole point of this profile is that it cannot bill.
    assert payload["video_source"] == "pexels"
    assert payload["video_source"] not in {
        "volcengine_seedance",
        "ofox",
        "metaso_minimax",
    }


def test_shipped_smoke_profile_is_valid():
    import os

    path = os.path.join(runner.REPO_ROOT, "automation", "smoke.params.json")
    payload = runner._load_params_template(path)
    # A fixed script is what makes the smoke test free.
    assert payload.get("video_script")


# ------------------------------------------------------------- source resolve


def test_resolve_source_requires_a_location():
    args = runner._build_parser().parse_args(["--source", "rss"])
    with pytest.raises(ValueError, match="requires 'url'"):
        runner._resolve_source(args)


def test_resolve_source_builds_topics_file(tmp_path):
    path = tmp_path / "topics.txt"
    path.write_text("A topic\n", encoding="utf-8")

    args = runner._build_parser().parse_args(
        ["--source", "topics_file", "--path", str(path)]
    )
    source = runner._resolve_source(args)
    assert len(list(source.fetch(limit=1))) == 1
