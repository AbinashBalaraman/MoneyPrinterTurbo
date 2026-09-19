"""create_series operation: create a series in the continuity ledger.

Its absence was a real, reproducible failure. Asked to "create new series
'interesting facts' create first video", the assistant called `direct_episode`,
was correctly told to run `init-series` first, and had no tool that could — so
it spent its remaining rounds on `dir` and on probing for modules that do not
exist (`python -m automation.director`, `python -m pipeline`,
`python -m ledger`), then answered with nothing at all.

The capability was never missing from the project: `init-series` has been in
`shorts_content_engine/src/cli.py` the whole time. It was missing from the
catalogue. A tool the model cannot see is a tool it does not have.

monkeypatch throughout — no DB, no network, no repo writes.
"""

import pytest

from agent.operations import registry

registry.all_operations()  # force the full catalog load before direct module import

from agent.operations import director as director_ops
from agent.operations.registry import OperationError, get


class _FakeCli:
    """Stand-in for run_pipeline_cli: records argv, returns a scripted result."""

    def __init__(self, exit_code=0, output="Series Registered Successfully"):
        self.exit_code = exit_code
        self.output = output
        self.calls: list[list[str]] = []

    async def __call__(self, args, *, timeout=300):
        self.calls.append(list(args))
        return {"exit_code": self.exit_code, "output": self.output}


def _op():
    return get("create_series")


async def _run(**kwargs):
    return await _op().handler(**kwargs)


@pytest.mark.asyncio
async def test_registered_as_a_director_write():
    op = _op()
    assert op.department == "director"
    assert op.risk == "write"


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["series_id", "title", "genre"])
async def test_requires_the_identifying_arguments(missing):
    args = {
        "series_id": "interesting_facts",
        "title": "Interesting Facts",
        "genre": "Trivia",
    }
    args[missing] = "   "
    with pytest.raises(OperationError, match=f"needs a '{missing}'"):
        await _run(**args)


@pytest.mark.asyncio
async def test_builds_the_init_series_argv(monkeypatch):
    cli = _FakeCli()
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    await _run(series_id="interesting_facts", title="Interesting Facts", genre="Trivia")
    argv = cli.calls[0]
    assert argv[0] == "init-series"
    assert argv[argv.index("--series-id") + 1] == "interesting_facts"
    assert argv[argv.index("--title") + 1] == "Interesting Facts"
    assert argv[argv.index("--genre") + 1] == "Trivia"


@pytest.mark.asyncio
async def test_optional_arguments_are_only_sent_when_given(monkeypatch):
    """Unset flags must be absent, not sent empty — argparse owns the defaults."""
    cli = _FakeCli()
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    await _run(series_id="s", title="T", genre="G")
    argv = cli.calls[0]
    assert "--logline" not in argv
    assert "--target-duration" not in argv
    assert "--no-seed-characters" not in argv


@pytest.mark.asyncio
async def test_optional_arguments_are_forwarded(monkeypatch):
    cli = _FakeCli()
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    await _run(
        series_id="s",
        title="T",
        genre="G",
        logline="bite-sized facts",
        target_duration=30,
        pacing_rhythm="noir_suspense",
        seed_characters=False,
    )
    argv = cli.calls[0]
    assert argv[argv.index("--logline") + 1] == "bite-sized facts"
    assert argv[argv.index("--target-duration") + 1] == "30.0"
    assert argv[argv.index("--pacing-rhythm") + 1] == "noir_suspense"
    assert "--no-seed-characters" in argv


@pytest.mark.asyncio
async def test_a_failing_cli_is_loud(monkeypatch):
    """A duplicate id must not read as success."""
    cli = _FakeCli(exit_code=1, output="Series 's' already exists")
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    with pytest.raises(OperationError, match="init-series failed"):
        await _run(series_id="s", title="T", genre="G")


@pytest.mark.asyncio
async def test_passes_the_ledger_the_dashboard_actually_reads(monkeypatch):
    """Regression: the CLI's ``--db-path`` defaults to ``storage/ledger.db``,
    *relative to its cwd*, which resolves to a different file than the one
    ``continuity_status`` reads. The series data was split across two ledgers,
    so a series created here was invisible to the status tool.
    """
    from agent.services.ledger import ledger_path

    cli = _FakeCli()
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    await _run(series_id="s", title="T", genre="G")
    argv = cli.calls[0]
    assert argv[argv.index("--db-path") + 1] == ledger_path()
    assert argv[argv.index("--db-path") + 1].endswith("continuity_ledger.db")


@pytest.mark.asyncio
async def test_direct_episode_writes_to_the_same_ledger(monkeypatch):
    """Same ledger for the reader and the writer, or the split comes back."""
    from agent.services.ledger import ledger_path

    cli = _FakeCli()
    monkeypatch.setattr(director_ops, "run_pipeline_cli", cli)
    await director_ops.direct_episode("farmer_and_rusty")
    argv = cli.calls[0]
    assert argv[argv.index("--db-path") + 1] == ledger_path()


class TestContinuityStatusSeriesFilter:
    """`continuity_status(series_id=...)` used to fail for every series.

    It filtered on ``s.get("id")``, but the ledger's series records key on
    ``series_id`` — so ``id`` was always None, nothing ever matched, and asking
    for a series that existed still answered "No series ... in the continuity
    ledger". The tool was unusable with an argument.
    """

    @staticmethod
    def _patch(monkeypatch, state):
        from unittest.mock import AsyncMock

        from agent.api import continuity as continuity_api

        monkeypatch.setattr(
            continuity_api, "get_ledger_state", AsyncMock(return_value=state)
        )

    @pytest.mark.asyncio
    async def test_matches_on_series_id(self, monkeypatch):
        self._patch(monkeypatch, {"series": [{"series_id": "interesting_facts"}]})
        out = await director_ops.continuity_status("interesting_facts")
        assert [s["series_id"] for s in out["series"]] == ["interesting_facts"]

    @pytest.mark.asyncio
    async def test_a_genuinely_missing_series_still_raises(self, monkeypatch):
        self._patch(monkeypatch, {"series": [{"series_id": "a"}]})
        with pytest.raises(OperationError, match="No series"):
            await director_ops.continuity_status("nope")

    @pytest.mark.asyncio
    async def test_no_filter_returns_every_series(self, monkeypatch):
        self._patch(monkeypatch, {"series": [{"series_id": "a"}, {"series_id": "b"}]})
        out = await director_ops.continuity_status()
        assert len(out["series"]) == 2
