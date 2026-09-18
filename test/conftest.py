"""Shared test isolation for the MoneyPrinterTurbo suite.

Why this exists
---------------
``app.config`` keeps its settings in module-level dicts (``config.app``,
``config.ui``, ``config.proxy``, …) and tests mutate them directly — a search
turns up sixteen files doing ``config.app["api_key"] = ...`` and similar. Most
of them restore what they changed, but the restore lives in each file's own
``tearDown``, so a test that fails during ``setUp``, or a file that simply
forgets, leaks its value into everything that runs afterwards.

The symptom is unpleasant to read: a full-suite run fails a test that passes on
its own, and *which* test fails moves between runs because it depends on
ordering. That is exactly what
``test_asgi_static_files.py::test_configured_key_protects_task_file`` did — it
passed alone and as a whole file, and failed only in the full run.

One autouse fixture beats auditing sixteen files: it makes the leak impossible
rather than relying on every file remembering.
"""

import pytest

from app.config import config


def _shared_config_dicts() -> dict[str, dict]:
    """Every module-level dict on ``config``.

    Discovered rather than listed. A hard-coded list would go stale the moment
    someone adds a section to ``config.toml``, and the leak would come back with
    no signal — which is the failure mode this file exists to remove.
    """
    found: dict[str, dict] = {}
    for name in dir(config):
        if name.startswith("_"):
            continue
        value = getattr(config, name)
        if isinstance(value, dict):
            found[name] = value
    return found


@pytest.fixture(autouse=True)
def isolate_shared_config():
    """Snapshot the shared config dicts before each test and restore them after.

    Restores *in place* rather than rebinding, because the objects are handed
    around by reference — ``from app.config import config`` then ``config.app``
    is the same dict everywhere, so replacing the attribute would leave every
    existing holder pointing at the mutated one.
    """
    snapshots = {name: dict(value) for name, value in _shared_config_dicts().items()}
    try:
        yield
    finally:
        for name, original in snapshots.items():
            current = getattr(config, name, None)
            if isinstance(current, dict):
                current.clear()
                current.update(original)
