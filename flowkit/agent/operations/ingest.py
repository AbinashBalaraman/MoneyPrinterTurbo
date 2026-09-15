"""INGEST department — what to make next, once only.

Owns the topic backlog and the dedup ledger. The ledger is the gate, not the
source: a feed can return the same item every poll, and the ledger is what
decides it is genuinely new. That state is why this is a department rather than a
script.
"""

from __future__ import annotations

import logging
from pathlib import Path

from agent.operations.registry import RISK_READ, RISK_SPEND, OperationError, operation
from agent.operations.shell import WORKSPACE_ROOT, run_pipeline_cli

logger = logging.getLogger(__name__)

TOPICS_FILE = WORKSPACE_ROOT / "automation" / "topics.txt"


def _parse_topics(path: Path) -> list[dict]:
    """Parse ``topics.txt``: one topic per line, ``#`` comments, optional ``| url``."""
    if not path.exists():
        raise OperationError(f"Topic backlog not found at {path}.")
    topics: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        text, _, url = line.partition("|")
        topics.append({"topic": text.strip(), "url": url.strip() or None})
    return topics


def _ledger_state(keys: list[str]) -> dict[str, dict]:
    """Claim/done state per topic key, from the automation ledger.

    ``automation/ledger.py`` is stdlib-only, so it imports cleanly here. Reading
    it is what makes the list actionable: "what is new" is the question, not
    "what is in the file".
    """
    if not keys:
        return {}
    import sys

    root = str(WORKSPACE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        from automation.ledger import Ledger
    except Exception as exc:  # noqa: BLE001 - a missing ledger must not break listing
        logger.warning("ingest: ledger unavailable: %s", exc)
        return {}

    try:
        with Ledger() as ledger:
            state = {}
            for key in keys:
                row = ledger.get_topic(key)
                if row is None:
                    state[key] = {"state": "new"}
                else:
                    state[key] = {
                        "state": dict(row).get("status") or "unknown",
                        "attempts": dict(row).get("attempts"),
                        "error": dict(row).get("error"),
                    }
            return state
    except Exception as exc:  # noqa: BLE001
        logger.warning("ingest: could not read ledger: %s", exc)
        return {}


@operation(
    name="list_topics",
    department="ingest",
    risk=RISK_READ,
    description="The topic backlog with its ledger state — which topics are new, claimed, done or failed.",
    takes_args=False,
)
async def list_topics() -> dict:
    """Topics from the backlog, annotated with dedup state."""
    topics = _parse_topics(TOPICS_FILE)

    # The runner keys a topic by its text+url, so mirror that here rather than
    # inventing a different identity for the same row.
    keys = [f"{t['topic']}|{t['url'] or ''}" for t in topics]
    state = _ledger_state(keys)

    annotated = []
    for topic, key in zip(topics, keys):
        entry = state.get(key, {"state": "unknown"})
        annotated.append({**topic, **entry})

    counts: dict[str, int] = {}
    for entry in annotated:
        counts[entry["state"]] = counts.get(entry["state"], 0) + 1

    return {
        "backlog_file": str(TOPICS_FILE),
        "total": len(annotated),
        "counts": counts,
        "topics": annotated[:50],
        "note": (
            "State comes from the automation ledger: 'new' has never been made, "
            "'done' already exists, 'claimed' is in flight. Capped at 50."
        ),
    }


@operation(
    name="run_batch",
    department="ingest",
    risk=RISK_SPEND,
    description=(
        "Run N episodes through the whole pipeline (direct → generate → assemble). "
        "SPENDS MONEY and takes a long time."
    ),
    args={"series_id": "series identifier", "episodes": 1, "publish": False},
)
async def run_batch(
    series_id: str, episodes: int = 1, publish: bool = False
) -> dict:
    """Run the pipeline's own `batch` verb.

    `--live` is passed because the CLI's `--mock` defaults to true and a batch
    that silently simulated everything would be worse than a failure: it would
    report success and produce nothing.

    Publishing stays off unless asked for. It is the one step that is public and
    irreversible, so it does not ride along on a batch by default.
    """
    if not (series_id or "").strip():
        raise OperationError("run_batch needs a 'series_id'.")
    try:
        count = int(episodes)
    except (TypeError, ValueError):
        raise OperationError("'episodes' must be an integer.")
    if count < 1:
        raise OperationError("'episodes' must be at least 1.")

    argv = ["batch", "--series-id", series_id, "-n", str(count), "--live"]
    if publish:
        argv += ["--auto-publish", "--publish-live"]

    result = await run_pipeline_cli(argv, timeout=1800)
    if result.get("exit_code") != 0:
        raise OperationError(
            f"batch failed (exit {result.get('exit_code')}): "
            f"{(result.get('output') or '')[:800]}"
        )
    return result
