"""Emit the assembly settings surface as JSON, straight from ``VideoParams``.

Why this exists
---------------
The agent runs in the flowkit venv, which does not have the assembly engine's
dependencies (``app.models.schema`` imports ``app.config``, which needs ``toml``).
So it cannot import ``VideoParams`` and discover the ~39 settings it may pass to
``build_batch_task``.

The alternative -- hand-writing the field list on the agent side -- is exactly the
duplication that has already bitten this project twice (the dashboard's private
model list, and ``_char_matches`` vs ``_matches``). So the agent shells out to
this script in the assembly venv and reads the schema back.

``VideoParams`` stays the single declaration. Add a field there and the agent
sees it; there is no second list to update.

Output: a JSON array on stdout, one object per field::

    [{"name": "video_aspect", "type": "str", "default": "9:16",
      "allowed": ["9:16", "16:9", "1:1"]}, ...]

``--json-schema`` emits the raw pydantic schema instead, for debugging.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from typing import Any, Literal, get_args, get_origin

# Importing app.config logs at INFO, and the caller merges stderr into stdout, so
# the JSON would arrive wrapped in log lines. Silence the chatter before the
# import; genuine errors still surface.
try:
    from loguru import logger as _loguru

    _loguru.remove()
    _loguru.add(sys.stderr, level="ERROR")
except Exception:  # pragma: no cover - logging is not worth failing over
    pass

from pydantic_core import PydanticUndefined  # noqa: E402

from app.models.schema import VideoParams  # noqa: E402


def _type_name(annotation: Any) -> str:
    """A short, readable type label for a pydantic annotation."""
    origin = get_origin(annotation)
    if origin is Literal:
        return "literal"
    if origin is None:
        return annotation.__name__ if isinstance(annotation, type) else str(annotation)

    args = [a for a in get_args(annotation) if a is not type(None)]
    inner = ", ".join(_type_name(a) for a in args) or "any"
    if origin in (list, set, tuple):
        return f"list[{inner}]"
    if origin is dict:
        return f"dict[{inner}]"
    if origin is Literal:
        return "literal"
    return inner


def _allowed_values(annotation: Any) -> list[Any]:
    """Enum member values or Literal options carried by an annotation."""
    found: list[Any] = []

    def walk(node: Any) -> None:
        origin = get_origin(node)
        if origin is Literal:
            found.extend(a for a in get_args(node) if a is not None)
            return
        if origin is not None:
            for arg in get_args(node):
                walk(arg)
            return
        if isinstance(node, type) and issubclass(node, Enum):
            found.extend(member.value for member in node)

    walk(annotation)
    return found


def _default_of(field: Any) -> Any:
    """The declared default, JSON-safe, or None when there is nothing to show."""
    if field.default is PydanticUndefined:
        if field.default_factory is None:
            return None
        try:
            default = field.default_factory()
        except Exception:
            return None
    else:
        default = field.default
    if isinstance(default, Enum):
        return default.value
    if isinstance(default, (str, int, float, bool, list, dict)) or default is None:
        return default
    return str(default)


def describe() -> list[dict[str, Any]]:
    described: list[dict[str, Any]] = []
    for name, field in VideoParams.model_fields.items():
        annotation = field.annotation
        entry: dict[str, Any] = {"name": name, "type": _type_name(annotation)}
        if field.is_required():
            entry["required"] = True
        else:
            default = _default_of(field)
            if default is not None:
                entry["default"] = default
        allowed = _allowed_values(annotation)
        if allowed:
            entry["allowed"] = allowed
        description = (field.description or "").strip()
        if description:
            entry["description"] = description
        described.append(entry)
    return described


def main() -> int:
    if "--json-schema" in sys.argv:
        json.dump(VideoParams.model_json_schema(), sys.stdout, ensure_ascii=False)
    else:
        json.dump(describe(), sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
