"""Server-side tool loop — lets the in-app chat ACT instead of narrate.

Why this module exists
----------------------
The Agent Studio chat streamed straight to OpenCode and had no way to *do*
anything. Asked to check a log or run a test, it replied with a command for the
user to paste — the assistant narrated instead of acting. That is the defect
this closes.

Why a prompt-level protocol instead of native function calling
--------------------------------------------------------------
The free ``muse-spark-*`` models are the ones this account can actually use, and
their tool-calling support is not something we can rely on. So tools are
advertised in the system prompt and invoked with a literal marker the server
scrapes out of the reply::

    ⟦tool:web_search {"query": "veo api access"}⟧

The model stops there, the server runs the tool and appends the result as a
normal message, and the loop continues. This works on any model regardless of
provider, at the cost of being a convention rather than a guarantee.

Three syntaxes are *accepted* (``⟦…⟧``, ``[[…]]``, ``<<…>>``) but only the first
is advertised. A model that writes a different bracket still gets its tool run
instead of having raw markers dumped into the answer.

Streaming behaviour
-------------------
Text streams as it arrives, with one caveat: a tail the length of a partial
marker is held back, and once a real marker is seen the rest of that round is
buffered until it can be parsed. Without that, a tool call would flash on screen
as prose before being executed.

Security note
-------------
:func:`run_command` executes a shell command. The working directory is pinned
inside the workspace, output is capped, and catastrophic patterns are refused —
but this is a guardrail, **not a sandbox**. A command can still do anything the
user can. That is consistent with the terminal tab, which is a full PTY by
design.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from agent.operations.registry import DEPARTMENTS, OperationError, check_allowed, get as get_operation

logger = logging.getLogger(__name__)

# AutoShorts/  (…/flowkit/agent/services/chat_agent.py → parents[3])
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

#: Advertised marker. The others are tolerated so a bracket slip is not fatal.
TOOL_OPEN = "⟦tool:"
TOOL_CLOSE = "⟧"
_ALT_OPENERS = (TOOL_OPEN, "[[tool:", "<<tool:")
_ALT_CLOSERS = {TOOL_OPEN: TOOL_CLOSE, "[[tool:": "]]", "<<tool:": ">>"}

#: How many model↔tool exchanges before the loop gives up. Each round is a full
#: completion, so this is also the worst-case latency multiplier.
MAX_ROUNDS = 5

#: Pipeline order, used to group the tool list in the prompt. Imported rather
#: than restated so a new department cannot appear in one place and not the other.
_DEPARTMENT_ORDER = DEPARTMENTS

COMMAND_TIMEOUT_DEFAULT = 30.0
COMMAND_TIMEOUT_MAX = 120.0
COMMAND_OUTPUT_CAP = 12_000
#: Cap on a tool result fed back to the model, so one large search cannot eat
#: the whole context window.
MAX_RESULT_CHARS = 6_000
#: Long-term memory is meant to be short; only the tail is worth sending.
MEMORY_PROMPT_CHARS = 4_000

#: Refused outright. A guardrail against a catastrophic typo, not a security
#: boundary — see the module docstring.
_BLOCKED_COMMAND = (
    "rm -rf /", "mkfs", "dd if=", "shutdown", "vssadmin delete",
    "format c:", "format d:", "del /f /s /q c:", "rd /s /q c:",
)


# ─── Tool declarations ───────────────────────────────────────
#
# The list is no longer written here. It comes from the operations catalog
# (`agent.operations`), which is the single declaration of what this system can
# do — the same declarations the REST API is built from. Hand-maintaining a
# second list here is what let the two drift.


def _search_available() -> bool:
    try:
        from agent.services import web_search

        return web_search.configured()
    except Exception:  # pragma: no cover - config import edge case
        return False


def _availability(name: str) -> tuple[bool, str | None]:
    """Whether a tool can actually run right now, and why not if it cannot.

    Only web_search has a precondition today. The model is told plainly rather
    than discovering it as a confusing tool error mid-answer.
    """
    if name == "web_search" and not _search_available():
        return False, "TINYFISH_API_KEY is empty in AutoShorts/.env"
    return True, None


def tool_specs() -> list[dict[str, Any]]:
    """The tools advertised to the model, with availability resolved.

    Derived from the operations catalog, grouped by department so the model sees
    the pipeline's shape rather than a flat bag of functions.
    """
    from agent.operations import registry

    specs: list[dict[str, Any]] = []
    for op in sorted(registry.all_operations().values(), key=lambda o: (o.department, o.name)):
        available, hint = _availability(op.name)
        specs.append(
            {
                "name": op.name,
                "department": op.department,
                "risk": op.risk,
                "args": op.args_example(),
                "description": op.description,
                "available": available,
                "unavailable_hint": hint,
            }
        )
    return specs


def build_preamble() -> str:
    """The tool contract injected into the system prompt.

    Grouped by department so the model sees the pipeline's shape — that an
    episode is directed, then rendered, then assembled, then published — rather
    than a flat bag of functions it has to guess the order of.
    """
    specs = tool_specs()

    lines = [
        "",
        "",
        "## Tools you can actually run",
        "",
        "You have server-side tools. The user cannot run commands for you — if a",
        "task needs live data, files, or command output, use a tool. Never reply",
        "with a command for the user to paste instead of running it yourself.",
        "",
        "To call a tool, emit a marker on its own line and stop there:",
        "",
        f'{TOOL_OPEN}queue_status {{"project_id": "optional"}}{TOOL_CLOSE}',
        "",
        "The server executes it and sends the result back as a message. Then",
        "continue your answer using the real output. Never invent tool output.",
        "",
        "Available tools, grouped by the part of the pipeline that owns them:",
    ]

    for department in _DEPARTMENT_ORDER:
        group = [s for s in specs if s.get("department") == department]
        if not group:
            continue
        lines.append(f"\n[{department.upper()}]")
        for spec in group:
            if not spec["available"]:
                lines.append(f"- `{spec['name']}` — UNAVAILABLE ({spec['unavailable_hint']})")
                continue
            risk = spec.get("risk")
            suffix = ""
            if risk == "spend":
                suffix = "  ⚠ SPENDS MONEY — only if the user asked for it."
            elif risk == "destructive":
                suffix = "  ⚠ PUBLIC/IRREVERSIBLE — needs the user's explicit agreement."
            lines.append(
                f"- `{spec['name']}` {spec['args']} — {spec['description']}{suffix}"
            )

    lines += [
        "",
        "ROUTE MAP — the pipeline runs left to right; call the stage the request belongs to:",
        "topic idea -> INGEST list_topics | new episode script -> DIRECTOR direct_episode, then storyboard",
        "see projects or queue -> RENDER project_list, project_status, queue_status",
        "ONE standalone image -> RENDER generate_image (prompt only, no manifest needed)",
        "whole-episode stills and clips -> RENDER generate_episode (needs a manifest file)",
        "stills to finished mp4 -> ASSEMBLY assemble_episode | clean output -> POST scrub_video",
        "release -> PUBLISH publication_status first, publish_episode only on an explicit go",
        "logs and errors -> OPS read_logs | shell -> OPS run_command | memory and web -> ASSISTANT",
        "",
        "Rules:",
        f"- The marker must be exactly {TOOL_OPEN}name {{json}}{TOOL_CLOSE} — no other form works.",
        "- One or more markers may be emitted in a single reply, one per line.",
        "- Never explain the marker syntax to the user; they only see your prose.",
        "- If a tool is UNAVAILABLE, say so plainly instead of pretending.",
        "- Do not run a tool marked SPENDS MONEY or PUBLIC/IRREVERSIBLE unless the",
        "  user has clearly asked for that action. If it is refused, tell them why",
        "  and what to change — do not retry the same call.",
        "- After tool results arrive, answer the question. Do not call a tool again",
        "  unless the result genuinely leaves something unresolved.",
        "- If a tool errors twice in a row, do not call it again — work around it",
        "  or report the error to the user.",
    ]
    return "\n".join(lines)


def inject_preamble(system_prompt: str) -> str:
    """Append the tool contract to a system prompt (idempotent)."""
    system_prompt = system_prompt or ""
    if TOOL_OPEN in system_prompt:
        return system_prompt
    return f"{system_prompt}\n{build_preamble()}" if system_prompt else build_preamble().lstrip("\n")


def prepare_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Inject the tool contract into the system prompt (or add one)."""
    prepared = [dict(m) for m in messages]
    for msg in prepared:
        if msg.get("role") == "system":
            msg["content"] = inject_preamble(msg.get("content") or "")
            return prepared
    prepared.insert(0, {"role": "system", "content": inject_preamble("")})
    return prepared


# ─── Parsing ─────────────────────────────────────────────────


def _find_opener(text: str, start: int) -> tuple[int, str] | None:
    """Earliest accepted opener at or after ``start``."""
    best: tuple[int, str] | None = None
    for opener in _ALT_OPENERS:
        idx = text.find(opener, start)
        if idx != -1 and (best is None or idx < best[0]):
            best = (idx, opener)
    return best


def _scan_json_object(text: str, brace_at: int) -> int:
    """Index just past the ``}`` matching the ``{`` at ``brace_at``, or -1.

    Hand-rolled rather than a regex because tool arguments are nested objects —
    a non-greedy ``\\{.*?\\}`` stops at the first inner brace and mangles them.
    String literals and escapes are tracked so a brace inside a string does not
    close the object early.
    """
    if brace_at >= len(text) or text[brace_at] != "{":
        return -1
    depth = 0
    in_string = False
    escaped = False

    for i in range(brace_at, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def _parse_call(body: str) -> tuple[str | None, dict[str, Any], str | None]:
    """Split ``name {json}`` into ``(name, args, parse_error)``."""
    body = body.strip()
    if not body:
        return None, {}, "empty tool call"

    brace = body.find("{")
    if brace == -1:
        return body.strip(), {}, None

    name = body[:brace].strip()
    raw = body[brace:].strip()
    try:
        args = json.loads(raw)
    except json.JSONDecodeError as exc:
        return name, {}, f"arguments are not valid JSON ({exc.msg})"
    if not isinstance(args, dict):
        return name, {}, "arguments must be a JSON object"
    return name, args, None


def extract_tool_calls(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Pull tool calls out of a reply.

    Returns ``(prose, calls)`` with the markers removed from ``prose``. A marker
    whose JSON does not parse is kept as a call carrying ``parse_error`` — the
    model gets told, rather than the failure being swallowed into prose.
    """
    prose: list[str] = []
    calls: list[dict[str, Any]] = []
    cursor = 0

    while cursor < len(text):
        found = _find_opener(text, cursor)
        if found is None:
            prose.append(text[cursor:])
            break

        start, opener = found
        closer = _ALT_CLOSERS[opener]
        name_start = start + len(opener)
        brace = text.find("{", name_start)
        end = text.find(closer, name_start)

        # No argument object: the call is just a name, closed by the marker.
        if brace == -1 or (end != -1 and end < brace):
            if end == -1:
                prose.append(text[cursor:])
                break
            name = text[name_start:end].strip()
            prose.append(text[cursor:start])
            if name:
                calls.append({"name": name, "args": {}, "parse_error": None, "raw": ""})
            else:
                prose.append(text[start:end + len(closer)])
            cursor = end + len(closer)
            continue

        json_end = _scan_json_object(text, brace)
        closer_at = text.find(closer, name_start)

        # Prefer a balanced brace scan. Fall back to the closing marker when the
        # JSON is unbalanced: a marker with bad JSON means the model *meant* to
        # call a tool, so it is worth reporting so it can retry. Only a marker
        # with neither balance nor a closer is treated as prose.
        if json_end != -1 and (closer_at == -1 or json_end <= closer_at):
            after_call, raw = json_end, text[brace:json_end]
        elif closer_at != -1:
            after_call, raw = closer_at, text[brace:closer_at]
        else:
            prose.append(text[cursor:])
            break

        name = text[name_start:brace].strip()
        parsed_name, args, parse_error = _parse_call(f"{name} {raw}")

        prose.append(text[cursor:start])
        if parsed_name:
            calls.append({"name": parsed_name, "args": args, "parse_error": parse_error, "raw": raw})
        else:
            prose.append(text[start:after_call])

        # Step past the closing marker when the model supplied one.
        if text.startswith(closer, after_call):
            after_call += len(closer)
        cursor = after_call

    return "".join(prose), calls


def strip_tool_calls(text: str) -> str:
    """The reply with markers removed — what the user should read."""
    prose, _ = extract_tool_calls(text or "")
    return prose.strip()


def _safe_emit_len(text: str) -> int:
    """How much of ``text`` is safe to show as prose right now.

    Everything before the first marker, and never a tail that could be the
    beginning of a marker split across two stream chunks.
    """
    keep = max(len(o) for o in _ALT_OPENERS) - 1
    found = _find_opener(text, 0)
    if found is not None:
        return found[0]
    return max(0, len(text) - keep)


# ─── Tools ───────────────────────────────────────────────────
#
# Dispatch goes through the operations catalog. `TOOLS` is kept as a plain
# name→callable table because it is the injection point tests use to substitute
# a fake handler; the registry supplies the metadata (department, risk, args).


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[truncated, {len(text) - limit} more characters]"


def _allow_spend() -> bool:
    """Whether spending operations are permitted right now.

    Read from config at call time, not import time, so flipping the switch does
    not require restarting to take effect mid-session.
    """
    from agent import config

    return bool(getattr(config, "AGENT_ALLOW_SPEND", False))


def _build_tools() -> dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]]:
    """Adapt registry operations into the ``(args_dict) -> result`` callables
    the loop expects."""
    from agent.operations import registry

    table: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = {}
    for name, op in registry.all_operations().items():

        def make(handler):
            async def call(args: dict[str, Any]) -> dict[str, Any]:
                return await handler(**(args or {}))

            return call

        table[name] = make(op.handler)
    return table


#: name → callable. Populated from the catalog; the loop dispatches through it.
TOOLS: dict[str, Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]] = _build_tools()


def validate_script(manifest: dict) -> dict:
    """Check an episode manifest: 4-6 scenes, <=10s each, 30-50s total.

    Kept as a synchronous function on this module because the manifest is usually
    already in the conversation and validating it should not need a round trip.
    The implementation lives in the DIRECTOR department.
    """
    from agent.operations.director import validate_manifest

    return validate_manifest(manifest)


async def execute_tool(
    name: str,
    args: dict[str, Any],
    *,
    allow_spend: bool | None = None,
    confirm_token: str | None = None,
) -> dict[str, Any]:
    """Run one tool. Never raises — a failure is a result the model can read.

    The risk gate lives here, at the boundary where a tool is actually invoked,
    rather than in the loop: a caller cannot reach a `spend` or `destructive`
    operation by going around it.
    """
    impl = TOOLS.get(name)
    if impl is None:
        known = ", ".join(sorted(TOOLS))
        return {"ok": False, "error": f"Unknown tool {name!r}. Available: {known}."}

    op = get_operation(name)
    if op is not None:
        permitted = _allow_spend() if allow_spend is None else allow_spend
        # Destructive operations need an out-of-band confirm token (a dedicated
        # approve endpoint tied to the user session). The model's own
        # {"confirm": true} is deliberately NOT accepted — it is model-generated
        # JSON, so accepting it would let the model (or injected tool output)
        # self-authorize publishing. Via chat, destructive stays refused until
        # that endpoint exists; use the CLI for publishing.
        allowed, refusal = check_allowed(op, allow_spend=permitted, confirm_token=confirm_token)
        if not allowed:
            return {"ok": False, "error": refusal, "refused": True}

    try:
        return {"ok": True, "result": await impl(args or {})}
    except OperationError as exc:
        # An expected failure the model should read and act on.
        return {"ok": False, "error": str(exc)}
    except TypeError as exc:
        # Almost always the model passing the wrong argument names.
        return {"ok": False, "error": f"Bad arguments for {name}: {exc}"}
    except Exception as exc:  # noqa: BLE001 - the model must be told, not crashed
        logger.exception("chat_agent: tool %s failed", name)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ─── The loop ────────────────────────────────────────────────


#: Internal tool name → the name the dashboard renders. The UI has dedicated
#: cards for `memory` / `project_snapshot` / `queue_snapshot`; keeping that
#: mapping here means a rename on either side does not silently degrade the
#: card into a raw-JSON fallback.
_UI_TOOL = {
    "memory_read": "memory",
    "memory_append": "memory",
    "memory_write": "memory",
    "project_status": "project_snapshot",
    "queue_status": "queue_snapshot",
}


def _result_fields(name: str, result: Any) -> dict[str, Any]:
    """Tool-specific fields for the activity card. Unknown tools pass through."""
    if name == "web_search" and isinstance(result, dict):
        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "snippet": r.get("snippet"),
            }
            for r in (result.get("results") or [])
            if isinstance(r, dict)
        ]
        return {
            "query": result.get("query"),
            "results": results,
            "summary": f"{result.get('total_results', len(results))} results",
        }

    if name == "run_command" and isinstance(result, dict):
        return {
            "command": result.get("command"),
            "output": result.get("output"),
            "exit_code": result.get("exit_code"),
        }

    if name == "memory_read" and isinstance(result, dict):
        memory = result.get("memory") or ""
        return {"operation": "read", "detail": f"{len(memory)} chars" if memory else "empty"}

    if name == "memory_append" and isinstance(result, dict):
        return {
            "operation": "append",
            "detail": _truncate(str(result.get("saved") or ""), 120),
        }

    if name == "memory_write" and isinstance(result, dict):
        return {"operation": "write", "detail": f"{result.get('chars', 0)} chars"}

    if name == "validate_script" and isinstance(result, dict):
        errors = result.get("errors") or []
        return {
            "summary": "valid" if result.get("valid") else f"{len(errors)} issue(s)",
            "data": result,
        }

    if name == "project_list" and isinstance(result, dict):
        return {"summary": f"{len(result.get('projects') or [])} projects", "data": result}

    if name == "project_status" and isinstance(result, dict):
        counts = result.get("request_counts") or {}
        tally = ", ".join(f"{k} {v}" for k, v in counts.items()) or "no requests"
        return {"summary": f"{result.get('scene_count', 0)} scenes · {tally}", "data": result}

    if name == "queue_status" and isinstance(result, dict):
        return {
            "summary": (
                f"{result.get('total', 0)} requests · "
                f"outstanding {result.get('outstanding', 0)}"
            ),
            "data": result,
        }

    if name == "consistency_check" and isinstance(result, dict):
        unlinked = result.get("unlinked") or []
        unconditioned = result.get("unconditioned") or []
        unverified = result.get("unverified") or []
        if not (unlinked or unconditioned or unverified):
            summary = "all scenes reference-conditioned"
        else:
            parts = []
            if unconditioned:
                parts.append(f"{len(unconditioned)} proven un-conditioned")
            if unlinked:
                parts.append(f"{len(unlinked)} unlinked")
            if unverified:
                parts.append(f"{len(unverified)} unverified")
            summary = " · ".join(parts)
        return {"summary": summary, "data": result}

    # Detect media artifacts produced by tools
    media_path = None
    if isinstance(result, dict):
        for k in ("clean_path", "output_path", "out_path", "video_path", "image_path", "path", "file"):
            val = result.get(k)
            if isinstance(val, str) and val.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".png", ".jpg", ".jpeg", ".webp", ".mp3", ".wav", ".ogg")):
                media_path = val
                break

    base = {"data": result} if result is not None else {}
    if media_path:
        base["media_path"] = media_path
    return base


def _activity(
    name: str, args: dict[str, Any], status: str, output: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a ``tool`` frame for the dashboard.

    Shape is the dashboard's contract (see ``AgentToolEvent`` in
    ``dashboard/src/api/opencode.ts``): ``tool``/``status`` plus whichever
    tool-specific fields the card for that tool reads.

    ``risk`` is carried on every frame so the UI can mark an action that costs
    money or is irreversible *before* the user reads the result. A gate the user
    cannot see is indistinguishable from the assistant being broken.
    """
    args = args or {}
    event: dict[str, Any] = {
        "type": "tool",
        "tool": _UI_TOOL.get(name, name),
        "status": status,
        "args": args,
    }

    op = get_operation(name)
    if op is not None:
        event["risk"] = op.risk

    if status == "start":
        if name == "web_search":
            event["query"] = args.get("query")
        elif name == "run_command":
            event["command"] = args.get("command")
        elif name.startswith("memory_"):
            event["operation"] = name.split("_", 1)[1]
        return event

    if not output:
        return event

    if not output.get("ok"):
        event["status"] = "error"
        event["message"] = output.get("error") or "Tool failed."
        # A refusal is not a failure: nothing ran, and the reason is actionable.
        # The UI renders it differently so it does not read as a broken tool.
        if output.get("refused"):
            event["refused"] = True
        return event

    event.update(_result_fields(name, output.get("result")))
    return event


def _render_results(executed: list[dict[str, Any]]) -> str:
    """Format tool results as the message the model reads next."""
    blocks = ["Tool results:"]
    for item in executed:
        rendered = json.dumps(item["output"], ensure_ascii=False, default=str)
        blocks.append(f"\n[{item['name']}]\n{_truncate(rendered, MAX_RESULT_CHARS)}")
    return "\n".join(blocks)


async def run_agent(
    messages: list[dict[str, str]],
    model_call: Callable[[list[dict[str, str]]], AsyncIterator[dict[str, Any]]],
    *,
    max_rounds: int = MAX_ROUNDS,
) -> AsyncIterator[dict[str, Any]]:
    """Drive the model↔tool loop, yielding normalised events.

    ``model_call`` receives the conversation and yields deltas in the vocabulary
    the OpenCode router already speaks (``text`` / ``reasoning`` / ``usage``).
    Keeping HTTP out of here is what makes the loop testable with a scripted
    fake.

    Events: ``text``, ``reasoning``, ``usage``, ``tool``, ``error``.
    """
    convo = [dict(m) for m in messages]
    # Circuit breaker: a tool that keeps failing is not run again — the model
    # gets the verdict instead of burning rounds repeating the same call.
    strikes: dict[str, int] = {}
    dead_rounds = 0

    for round_no in range(1, max_rounds + 1):
        raw = ""
        emitted = 0

        try:
            async for delta in model_call(convo):
                kind = delta.get("type")
                if kind == "text":
                    raw += delta.get("text") or ""
                    target = _safe_emit_len(raw)
                    if target > emitted:
                        yield {"type": "text", "text": raw[emitted:target]}
                        emitted = target
                elif kind in ("reasoning", "usage"):
                    yield delta
        except Exception as exc:  # noqa: BLE001 - surface it, do not hang the stream
            logger.warning("chat_agent: model call failed on round %d: %s", round_no, exc)
            yield {"type": "error", "message": f"Model call failed: {exc}"}
            return

        prose, calls = extract_tool_calls(raw)

        # Flush whatever was held back, or sat after the last marker.
        tail = prose[max(0, emitted):]
        if tail:
            yield {"type": "text", "text": tail}

        if not calls:
            return

        malformed = [c for c in calls if c.get("parse_error")]
        runnable = [c for c in calls if not c.get("parse_error")]

        if not runnable:
            # Tell the model its syntax was wrong and let it retry. Silently
            # dropping these is how a model loops forever emitting the same
            # broken call.
            if round_no == max_rounds:
                yield {"type": "error", "message": "Tool calls were malformed and no rounds remain."}
                return
            for call in malformed:
                yield _activity(call["name"], call["args"], "error", {
                    "ok": False, "error": call["parse_error"],
                })
            convo.append({"role": "assistant", "content": raw})
            convo.append(
                {
                    "role": "user",
                    "content": (
                        "Those tool calls were malformed: "
                        + "; ".join(f"{c['name']}: {c['parse_error']}" for c in malformed)
                        + f'. Re-emit them as {TOOL_OPEN}name {{"arg": "value"}}{TOOL_CLOSE}.'
                    ),
                }
            )
            continue

        if round_no == max_rounds:
            yield {
                "type": "text",
                "text": f"\n\n_Stopped after {max_rounds} tool rounds without a final answer._",
            }
            return

        for call in malformed:
            yield _activity(call["name"], call["args"], "error", {
                "ok": False, "error": call["parse_error"],
            })

        executed: list[dict[str, Any]] = []
        for call in runnable:
            if strikes.get(call["name"], 0) >= 2:
                skipped = {
                    "ok": False,
                    "error": (
                        f"{call['name']} failed twice already; not run again. "
                        f"Work around it or report the error."
                    ),
                }
                executed.append({"name": call["name"], "output": skipped})
                yield _activity(call["name"], call["args"], "error", skipped)
                continue
            yield _activity(call["name"], call["args"], "start")
            output = await execute_tool(call["name"], call["args"])
            executed.append({"name": call["name"], "output": output})
            yield _activity(call["name"], call["args"], "done", output)
            if output.get("ok"):
                strikes[call["name"]] = 0
            else:
                strikes[call["name"]] = strikes.get(call["name"], 0) + 1

        if executed and all(not item["output"].get("ok") for item in executed):
            dead_rounds += 1
        else:
            dead_rounds = 0
        if dead_rounds >= 3:
            yield {
                "type": "text",
                "text": "\n\n_Three straight tool rounds failed, so I stopped retrying. Here's what broke above — tell me how to proceed._",
            }
            return

        convo.append({"role": "assistant", "content": raw})
        convo.append({"role": "user", "content": _render_results(executed)})

    return
