"""The operations catalog — one implementation, two front doors.

Why this exists
---------------
An operation like "get project status" used to be implemented twice: once as a
FastAPI route, once as a hand-written chatbot tool. They drifted — twice, in one
week:

* the `tool` SSE frame shape the dashboard expected vs what the backend emitted;
* `operations.py::_char_matches` vs `consistency.py::_matches`.

Both were the same failure: two copies of one truth. Here an operation is
declared **once**, and both front doors are derived from it.

    @operation(name="queue_status", department="render", risk="read")
    async def queue_status(project_id: str | None = None) -> dict: ...

The declaration carries its own metadata — which department owns it, what it
costs, what arguments it takes — so the chatbot tool spec, the risk gate and the
dashboard's tool-card name all come from one place instead of three.

Risk
----
`risk` is not decoration. `spend` operations cost real money and `destructive`
ones publish or delete, and this pipeline is designed to run unattended. The gate
in :func:`check_allowed` is the difference between "the model decided to
generate 40 images" and "the model asked to".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

#: What an operation costs. Ordered least to most dangerous.
RISK_READ = "read"
RISK_WRITE = "write"
RISK_SPEND = "spend"
RISK_DESTRUCTIVE = "destructive"

VALID_RISKS = (RISK_READ, RISK_WRITE, RISK_SPEND, RISK_DESTRUCTIVE)

#: Departments, in pipeline order. Used for grouping and for the docs.
DEPARTMENTS = (
    "ingest",
    "director",
    "render",
    "assembly",
    "post",
    "publish",
    "assistant",
    "ops",
)


class OperationError(Exception):
    """A failure the model should *read*, not a crash.

    Operations raise this for expected problems — a missing key, an unknown id, a
    refused command. The tool layer turns it into an error result the model can
    act on. Anything else escaping an operation is a genuine bug and is reported
    as one, because hiding it behind a friendly message is how a broken pipeline
    looks healthy.
    """


@dataclass(frozen=True)
class Operation:
    """One thing the system can do, declared once."""

    name: str
    department: str
    handler: Callable[..., Awaitable[dict]]
    risk: str = RISK_READ
    description: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    #: True when the operation needs no arguments at all, so the prompt can show
    #: `{}` rather than an example the model might copy literally.
    takes_args: bool = True

    def args_example(self) -> str:
        """The JSON snippet shown to the model in the tool preamble."""
        if not self.takes_args:
            return "{}"
        import json

        return json.dumps(self.args, ensure_ascii=False)

    def to_tool_spec(self) -> dict[str, Any]:
        """The shape the chatbot's prompt builder consumes."""
        return {
            "name": self.name,
            "department": self.department,
            "risk": self.risk,
            "description": self.description,
            "args": self.args_example(),
        }


_REGISTRY: dict[str, Operation] = {}


def operation(
    *,
    name: str,
    department: str,
    risk: str = RISK_READ,
    description: str = "",
    args: Optional[dict] = None,
    takes_args: bool = True,
) -> Callable:
    """Register a function as an operation. Declared once, used everywhere."""
    if department not in DEPARTMENTS:
        raise ValueError(
            f"{name}: unknown department {department!r}. "
            f"Known departments: {', '.join(DEPARTMENTS)}."
        )
    if risk not in VALID_RISKS:
        raise ValueError(
            f"{name}: unknown risk {risk!r}. Known risks: {', '.join(VALID_RISKS)}."
        )

    def decorator(fn: Callable[..., Awaitable[dict]]) -> Callable[..., Awaitable[dict]]:
        if name in _REGISTRY:
            # A duplicate name means one of the two would silently shadow the
            # other — exactly the drift this module exists to prevent.
            raise ValueError(f"Duplicate operation name: {name!r}")
        _REGISTRY[name] = Operation(
            name=name,
            department=department,
            handler=fn,
            risk=risk,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            args=args or {},
            takes_args=takes_args,
        )
        return fn

    return decorator


def all_operations() -> dict[str, Operation]:
    """Every registered operation, keyed by name."""
    _ensure_loaded()
    return dict(_REGISTRY)


def get(name: str) -> Optional[Operation]:
    _ensure_loaded()
    return _REGISTRY.get(name)


def by_department() -> dict[str, list[Operation]]:
    """Operations grouped by department, in pipeline order."""
    grouped: dict[str, list[Operation]] = {d: [] for d in DEPARTMENTS}
    for op in all_operations().values():
        grouped.setdefault(op.department, []).append(op)
    for ops in grouped.values():
        ops.sort(key=lambda o: o.name)
    return {d: ops for d, ops in grouped.items() if ops}


def tool_specs(*, include_risks: Optional[set[str]] = None) -> list[dict[str, Any]]:
    """Tool specs for the chatbot, optionally filtered by risk."""
    specs = []
    for op in sorted(all_operations().values(), key=lambda o: (o.department, o.name)):
        if include_risks is not None and op.risk not in include_risks:
            continue
        specs.append(op.to_tool_spec())
    return specs


def check_allowed(
    op: Operation,
    *,
    allow_spend: bool,
    confirm_token: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Whether an operation may run right now.

    Returns ``(allowed, refusal_reason)``. A refusal is a *result the model can
    read*, not an exception — the model should be told why so it can explain it
    to the user instead of silently failing.

    `spend` is opt-in because this pipeline is built to run unattended: the
    failure mode is not "a wasted click", it is a queue of paid generations
    nobody asked for. `destructive` additionally needs a token, so a confirmation
    cannot be skipped by the model simply calling it again.
    """
    if op.risk == RISK_READ:
        return True, None

    if op.risk == RISK_WRITE:
        return True, None

    if op.risk == RISK_SPEND:
        if not allow_spend:
            return False, (
                f"Refused: {op.name!r} spends money and spending is currently "
                f"disabled. Set AGENT_ALLOW_SPEND=1 in AutoShorts/.env and restart "
                f"the agent, or run it from the CLI."
            )
        return True, None

    if op.risk == RISK_DESTRUCTIVE:
        if not allow_spend:
            return False, (
                f"Refused: {op.name!r} is destructive and destructive operations "
                f"are disabled. Set AGENT_ALLOW_SPEND=1 in AutoShorts/.env and "
                f"restart the agent."
            )
        if not confirm_token:
            return False, (
                f"Refused: {op.name!r} is destructive and needs explicit "
                f"confirmation. Ask the user to confirm, then re-issue the call "
                f"with a \"confirm\" argument."
            )
        return True, None

    return False, f"Refused: {op.name!r} has an unrecognised risk level {op.risk!r}."


def _ensure_loaded() -> None:
    """Import the department modules so their decorators run.

    Deferred rather than done at import time so this module stays import-pure and
    a partial import cannot leave the registry half-populated.
    """
    if _REGISTRY:
        return
    from agent.operations import (  # noqa: F401
        assembly,
        assistant,
        director,
        ingest,
        ops,
        post,
        publish,
        render,
    )
