"""Where the continuity ledger lives — one answer, not two.

The pipeline CLI defaults ``--db-path`` to ``storage/ledger.db``, which is
*relative to its working directory*. The operations run it with
``cwd=shorts_content_engine``, so that resolves to
``shorts_content_engine/storage/ledger.db``. The dashboard's continuity panel,
and therefore ``continuity_status``, reads
``shorts_content_engine/continuity_ledger.db`` instead.

Those are different files, so the agent's series handling was split across two
ledgers. Measured 2026-09-19 — both existed, each holding a different series:

* ``continuity_ledger.db`` → ``farmer_and_rusty``
* ``storage/ledger.db``    → ``interesting_facts`` (just created through the agent)

Consequences: a series created through the agent was invisible to
``continuity_status``, and ``farmer_and_rusty`` was invisible to
``direct_episode``, which would fail with "not found in ledger".

This module is the single definition, in a layer both the API and the
operations may import. Operations pass it to the CLI explicitly with
``--db-path`` so the CLI's own default never decides where data lands.
"""

from __future__ import annotations

from pathlib import Path

#: ``flowkit/agent/services/ledger.py`` → the repository root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

ENGINE_DIR = REPO_ROOT / "shorts_content_engine"

#: The ledger the dashboard reads, and therefore the only one worth writing to.
LEDGER_PATH = ENGINE_DIR / "continuity_ledger.db"


def ledger_path() -> str:
    """Absolute path to the continuity ledger, for ``--db-path``."""
    return str(LEDGER_PATH)
