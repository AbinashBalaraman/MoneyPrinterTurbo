"""AutoShorts automation package.

Adds a reactive, deduplicated, publish-capable layer on top of MoneyPrinterTurbo
without modifying any upstream module. See ``runner.py`` for the entry point.
"""

__all__ = ["ledger", "sources", "runner"]
