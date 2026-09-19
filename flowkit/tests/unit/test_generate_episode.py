"""generate_episode: render an episode from the manifest in the ledger.

This operation had never worked once. It took a ``manifest_path`` and ran
``generate --manifest <path>``, but the pipeline CLI has never accepted
``--manifest`` and *requires* ``--series-id`` — so every call died with

    shorts_engine generate: error: the following arguments are required: --series-id

and nothing downstream of ``direct_episode`` could ever run. Found while
following up on "create new series … create first video", where the assistant
had no working way to actually render the episode.

The manifest comes from the ledger, not a file: ``generate`` resolves it with
``ledger.get_episode_manifest(series_id, episode_num)``.

monkeypatch throughout — no DB, no network, no spend.
"""

import pytest

from agent.operations import registry

registry.all_operations()  # force the full catalog load before direct module import

from agent.operations import shell as shell_ops
from agent.operations.registry import OperationError, get


class _FakeCli:
    """Stand-in for run_pipeline_cli: records argv, returns a scripted result."""

    def __init__(self, exit_code=0, output="Generated"):
        self.exit_code = exit_code
        self.output = output
        self.calls: list[list[str]] = []

    async def __call__(self, args, *, timeout=1800):
        self.calls.append(list(args))
        return {"exit_code": self.exit_code, "output": self.output}


def _op():
    return get("generate_episode")


async def _run(**kwargs):
    return await _op().handler(**kwargs)


@pytest.mark.asyncio
async def test_registered_as_a_render_spend():
    op = _op()
    assert op.department == "render"
    assert op.risk == "spend"


@pytest.mark.asyncio
async def test_requires_a_series_id():
    with pytest.raises(OperationError, match="needs a 'series_id'"):
        await _run(series_id="   ")


@pytest.mark.asyncio
async def test_passes_the_required_series_id(monkeypatch):
    """The regression: without --series-id argparse refuses the whole call."""
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="interesting_facts")
    argv = cli.calls[0]
    assert argv[0] == "generate"
    assert argv[argv.index("--series-id") + 1] == "interesting_facts"


@pytest.mark.asyncio
async def test_never_passes_manifest(monkeypatch):
    """`generate` reads the manifest from the ledger; --manifest is not an option."""
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s")
    assert "--manifest" not in cli.calls[0]


@pytest.mark.asyncio
async def test_runs_live_by_default(monkeypatch):
    """The CLI defaults to --mock. A spend-gated op that silently simulates
    instead of generating is a quiet no-op, so live is the default here."""
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s")
    argv = cli.calls[0]
    assert "--live" in argv
    assert "--mock" not in argv


@pytest.mark.asyncio
async def test_a_dry_run_can_be_requested(monkeypatch):
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s", live=False)
    argv = cli.calls[0]
    assert "--mock" in argv
    assert "--live" not in argv


@pytest.mark.asyncio
async def test_episode_is_forwarded_when_given(monkeypatch):
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s", episode=3)
    argv = cli.calls[0]
    assert argv[argv.index("--episode") + 1] == "3"


@pytest.mark.asyncio
async def test_episode_is_omitted_by_default(monkeypatch):
    """Omitted means "the latest directed episode" — the CLI's own default."""
    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s")
    assert "--episode" not in cli.calls[0]


@pytest.mark.asyncio
async def test_uses_the_shared_ledger(monkeypatch):
    from agent.services.ledger import ledger_path

    cli = _FakeCli()
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    await _run(series_id="s")
    assert cli.calls[0][cli.calls[0].index("--db-path") + 1] == ledger_path()


@pytest.mark.asyncio
async def test_a_failing_cli_is_loud(monkeypatch):
    cli = _FakeCli(exit_code=1, output="Series 's' not found in ledger.")
    monkeypatch.setattr(shell_ops, "run_pipeline_cli", cli)
    with pytest.raises(OperationError, match="generate failed"):
        await _run(series_id="s")
