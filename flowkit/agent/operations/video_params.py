"""The assembly settings surface, read from ``VideoParams`` instead of restated.

Why this module exists
----------------------
``build_batch_task`` takes a ``settings`` object of MoneyPrinterTurbo
``VideoParams`` fields. It used to pass any key straight through, which meant:

* the model had to *guess* the ~39 field names, and a guess like ``voice``
  instead of ``voice_name`` landed in the manifest and failed deep inside the
  assembly run — the expensive end of the pipeline;
* nothing rejected ``video_aspect: "vertical"`` when the only accepted values are
  ``9:16`` / ``16:9`` / ``1:1``.

The fix is not to hand-write a field list here. That is the duplication that has
already bitten this project twice (the dashboard's private model list, and
``_char_matches`` vs ``_matches``). Instead ``VideoParams`` stays the single
declaration, and this module asks the assembly venv to describe it
(``automation/emit_video_params_schema.py``).

Add a field to ``VideoParams`` and the agent sees it. Delete one and the agent
stops accepting it. There is no second list to update.

Layering: this sits beside the department operations rather than under
``agent/services`` so it can use the subprocess plumbing in
``agent.operations.shell`` without inverting the dependency direction.
"""

from __future__ import annotations

import difflib
import json
import logging
from typing import Any

from agent.operations.registry import OperationError
from agent.operations.shell import run_assembly_module

logger = logging.getLogger(__name__)

EMITTER_MODULE = "automation.emit_video_params_schema"

#: The field list is a property of the checked-out code, not of a request, so one
#: read per process is enough. ``refresh=True`` re-reads after a code change.
_schema: list[dict[str, Any]] | None = None


class SettingsSchemaError(OperationError):
    """The settings surface could not be read from the assembly engine."""


async def load_schema(*, refresh: bool = False) -> list[dict[str, Any]]:
    """Return ``VideoParams`` described as a list of field objects.

    Raises :class:`SettingsSchemaError` rather than returning an empty list: a
    schema that silently came back empty would make every settings key look
    invalid, which is a worse failure than saying so plainly.
    """
    global _schema
    if _schema is not None and not refresh:
        return _schema

    result = await run_assembly_module(EMITTER_MODULE, [], timeout=180.0)
    if result.get("exit_code") != 0:
        raise SettingsSchemaError(
            "Could not read the assembly settings surface: "
            f"{EMITTER_MODULE} exited {result.get('exit_code')}. "
            f"{(result.get('output') or '')[-600:]}"
        )
    parsed = _parse_json_output(result.get("output") or "")
    if not isinstance(parsed, list) or not parsed:
        raise SettingsSchemaError(
            f"{EMITTER_MODULE} returned no fields; refusing to validate against "
            f"an empty surface. Got: {(result.get('output') or '')[:300]!r}"
        )
    _schema = parsed
    return parsed


def _parse_json_output(text: str) -> Any:
    """Parse the emitter's stdout, tolerating log lines around the payload.

    The subprocess runner merges stderr into stdout, so any log line the emitter
    does not silence lands in front of the JSON. The emitter silences its own
    logging; this is the second line of defence, so a stray warning downgrades to
    a slower parse rather than to a hard failure.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        candidate = line.strip()
        if not candidate or candidate[0] not in "[{":
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise SettingsSchemaError(
        f"{EMITTER_MODULE} did not return JSON. Got: {text[:300]!r}"
    )


def field_names(schema: list[dict[str, Any]]) -> list[str]:
    return [str(field.get("name")) for field in schema if field.get("name")]


def _render(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def validate_settings(settings: dict[str, Any], schema: list[dict[str, Any]]) -> None:
    """Raise :class:`OperationError` describing every problem found.

    All problems are reported at once rather than one per call: the caller is
    usually a model, and making it re-try once per bad key wastes a round trip
    each time.
    """
    by_name = {str(f.get("name")): f for f in schema if f.get("name")}
    known = sorted(by_name)
    problems: list[str] = []

    for key, value in settings.items():
        field = by_name.get(key)
        if field is None:
            close = difflib.get_close_matches(key, known, n=3, cutoff=0.6)
            hint = f" Did you mean {', '.join(repr(c) for c in close)}?" if close else ""
            problems.append(f"unknown setting {key!r}.{hint}")
            continue

        allowed = field.get("allowed")
        if allowed and value not in allowed:
            problems.append(
                f"{key}={_render(value)} is not valid; "
                f"allowed: {', '.join(_render(a) for a in allowed)}"
            )
            continue

        declared = str(field.get("type") or "")
        if declared and not _type_ok(declared, value):
            problems.append(
                f"{key}={_render(value)} is a {type(value).__name__}, "
                f"expected {declared}"
            )

    if not problems:
        return

    preview = ", ".join(known[:12])
    more = "" if len(known) <= 12 else f" … and {len(known) - 12} more"
    raise OperationError(
        "Invalid assembly settings: "
        + "; ".join(problems)
        + f". Valid settings: {preview}{more}. "
        + "Call assembly_settings_schema for the full list, defaults and allowed "
        + "values."
    )


def _type_ok(declared: str, value: Any) -> bool:
    """A deliberately loose type check — enough to catch the common mistakes.

    ``list[...]`` and dict-like fields are not type-checked element-wise; the
    engine's own pydantic validation is authoritative for structure. This is a
    cheap early net, not a second validator.
    """
    if declared.startswith("list["):
        return isinstance(value, list)
    if declared.startswith("dict["):
        return isinstance(value, dict)
    if declared == "bool":
        return isinstance(value, bool)
    if declared == "int":
        # bool is an int subclass; a bool where an int is expected is a mistake.
        return isinstance(value, int) and not isinstance(value, bool)
    if declared == "float":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if declared in ("str", "literal") or declared[0].isupper():
        # Enum-typed fields (VideoAspect, VideoConcatMode, …) accept their value
        # form, which is a plain string.
        return isinstance(value, str)
    return True


def summarise(schema: list[dict[str, Any]]) -> dict[str, Any]:
    """A compact, prompt-friendly view of the surface."""
    return {
        "field_count": len(schema),
        "required": field_names([f for f in schema if f.get("required")]),
        "fields_with_allowed_values": {
            str(f["name"]): f["allowed"] for f in schema if f.get("allowed")
        },
        "fields": schema,
    }
