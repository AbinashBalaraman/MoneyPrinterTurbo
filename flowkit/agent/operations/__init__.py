"""The operations catalog.

One implementation per operation, declared once with its department and risk.
Both front doors — the REST API and the chatbot's tool surface — are derived from
this, so they cannot drift apart.

See :mod:`agent.operations.registry` for why, and ``docs/ARCHITECTURE.md`` §
"Control" for where it sits in the system.
"""

from agent.operations.registry import (
    DEPARTMENTS,
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_SPEND,
    RISK_WRITE,
    Operation,
    OperationError,
    all_operations,
    by_department,
    check_allowed,
    get,
    operation,
    tool_specs,
)

__all__ = [
    "DEPARTMENTS",
    "RISK_DESTRUCTIVE",
    "RISK_READ",
    "RISK_SPEND",
    "RISK_WRITE",
    "Operation",
    "OperationError",
    "all_operations",
    "by_department",
    "check_allowed",
    "get",
    "operation",
    "tool_specs",
]
