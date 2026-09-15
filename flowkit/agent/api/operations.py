"""Operations catalog API — direct HTTP execution for the operations catalog.

Provides:
- GET /api/operations : full catalog of all 21+ operations grouped by department
- POST /api/operations/run : execute any operation with typed args and safety gates
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent import config
from agent.operations import registry
from agent.operations.registry import (
    OperationError,
    check_allowed,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/operations", tags=["operations"])


class RunOperationRequest(BaseModel):
    name: str = Field(..., description="Name of the operation to execute")
    args: dict[str, Any] = Field(default_factory=dict, description="Arguments for the operation")
    confirm: bool = Field(default=False, description="Confirmation token for destructive operations")


@router.get("")
async def get_operations():
    """Returns the operations catalog grouped by department with parameter specifications and risk ratings."""
    ops = registry.all_operations()
    departments_map = registry.by_department()
    
    allow_spend = bool(getattr(config, "AGENT_ALLOW_SPEND", False))
    
    serialized_ops = []
    for op in sorted(ops.values(), key=lambda o: (registry.DEPARTMENTS.index(o.department) if o.department in registry.DEPARTMENTS else 99, o.name)):
        serialized_ops.append({
            "name": op.name,
            "department": op.department,
            "risk": op.risk,
            "description": op.description,
            "args": op.args,
            "takes_args": op.takes_args,
        })

    return {
        "departments": list(registry.DEPARTMENTS),
        "operations": serialized_ops,
        "by_department": {
            dept: [
                {
                    "name": op.name,
                    "department": op.department,
                    "risk": op.risk,
                    "description": op.description,
                    "args": op.args,
                    "takes_args": op.takes_args,
                }
                for op in dept_ops
            ]
            for dept, dept_ops in departments_map.items()
        },
        "capabilities": {
            "allow_spend": allow_spend,
            "total": len(ops),
        },
    }


@router.post("/run")
async def run_operation(body: RunOperationRequest):
    """Execute any registered operation from the catalog.
    
    Enforces risk checking (spend, destructive confirm token), executes the handler,
    and returns a clean structured result.
    """
    op = registry.get(body.name)
    if op is None:
        raise HTTPException(status_code=404, detail=f"Operation '{body.name}' not found in catalog.")
    
    allow_spend = bool(getattr(config, "AGENT_ALLOW_SPEND", False))
    confirm_token = "user_confirmed" if body.confirm else None
    
    allowed, refusal_reason = check_allowed(op, allow_spend=allow_spend, confirm_token=confirm_token)
    if not allowed:
        return {
            "success": False,
            "operation": op.name,
            "department": op.department,
            "risk": op.risk,
            "refused": True,
            "error": refusal_reason,
        }
    
    try:
        # If the operation takes arguments, pass them as keyword arguments;
        # otherwise call without arguments
        if op.takes_args:
            result = await op.handler(**body.args)
        else:
            result = await op.handler()
            
        return {
            "success": True,
            "operation": op.name,
            "department": op.department,
            "risk": op.risk,
            "refused": False,
            "result": result,
        }
    except TypeError as te:
        logger.warning("Parameter mismatch calling operation %s: %s", op.name, te)
        return {
            "success": False,
            "operation": op.name,
            "department": op.department,
            "risk": op.risk,
            "refused": False,
            "error": f"Invalid arguments for {op.name}: {te}",
        }
    except OperationError as oe:
        logger.info("Operation %s reported expected failure: %s", op.name, oe)
        return {
            "success": False,
            "operation": op.name,
            "department": op.department,
            "risk": op.risk,
            "refused": False,
            "error": str(oe),
        }
    except Exception as exc:
        logger.exception("Unexpected error executing operation %s: %s", op.name, exc)
        return {
            "success": False,
            "operation": op.name,
            "department": op.department,
            "risk": op.risk,
            "refused": False,
            "error": f"Internal execution error in {op.name}: {exc}",
        }
