"""Planner adapter: turn user text into a validated SceneScript.

The LLM (or human) owns the *world*; this module is the pluggable seam where a
world-builder lives. Per the locked decision, integration is
**bring-your-own adapter**:

- ``NoOpPlanner``      — default. The engine cannot invent worlds; the caller
                         supplies SceneScript JSON (author-time, or from any
                         external LLM) and we validate it.
- ``CallablePlanner``  — wrap any ``fn(text) -> scene dict`` (e.g. an OpenAI,
                         Anthropic, Gemini, or local-model call the caller wires).
- ``DeterministicPlanner`` — offline fallback that uses the keyword scene
                         planner (``src.scene.parse_script``) for simple prompts.

Everything a planner returns is passed through ``contract.validate_scene`` so a
hallucinated world is *rejected*, never silently rendered.
"""

import json
import re
from typing import Any, Callable, Dict, Optional, Protocol

from .contract import ContractError, capabilities, validate_scene


class PlanUnavailable(RuntimeError):
    """Raised when no planner backend can produce a scene for a prompt."""


class PlannerBackend(Protocol):
    """Anything that turns a prompt into a raw SceneScript dict."""

    def plan(self, prompt: str) -> Dict[str, Any]:  # pragma: no cover - protocol
        ...


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #
class NoOpPlanner:
    """Default backend: refuses to invent a world.

    Correct for the locked architecture — the engine must not hallucinate. The
    caller either passes an explicit scene dict to ``plan_scene`` or installs a
    real backend.
    """

    def plan(self, prompt: str) -> Dict[str, Any]:
        raise PlanUnavailable(
            "No planner backend is configured. Pass scene=... explicitly, or "
            "install a backend (CallablePlanner / cloud / local) via plan_scene()."
        )


class CallablePlanner:
    """Wrap any ``fn(prompt) -> scene dict | json str`` as a planner backend.

    This is the BYO seam: an OpenAI/Gemini/local-model call, or a human-supplied
    fixture, plugs in here. JSON is accepted as a string or a dict.
    """

    def __init__(self, fn: Callable[[str], Any]):
        self._fn = fn

    def plan(self, prompt: str) -> Dict[str, Any]:
        return _coerce_scene(self._fn(prompt))


class DeterministicPlanner:
    """Offline fallback: keyword scene planner for simple, well-covered prompts.

    Not open-vocabulary. It exists so the pipeline is usable with zero external
    dependencies; richer prompts should use a real LLM backend.
    """

    def plan(self, prompt: str) -> Dict[str, Any]:
        from .scene import parse_script
        script = parse_script(prompt)
        return _script_to_scene_dict(script)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _coerce_scene(raw: Any) -> Dict[str, Any]:
    """Accept a dict or a JSON string (optionally fenced) -> scene dict."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return parse_scene_json(raw)
    raise PlanUnavailable(f"Planner returned unsupported type {type(raw).__name__}.")


def parse_scene_json(text: str) -> Dict[str, Any]:
    """Extract the first JSON object from model output (handles ``` fences)."""
    if not isinstance(text, str):
        raise PlanUnavailable("Expected JSON text from planner.")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise PlanUnavailable("Planner output contained no JSON object.")
        candidate = text[start:end + 1]
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        raise PlanUnavailable(f"Planner JSON was malformed: {e}") from e
    if not isinstance(obj, dict):
        raise PlanUnavailable("Planner JSON must be an object.")
    return obj


def _script_to_scene_dict(script) -> Dict[str, Any]:
    """Adapt an in-repo SceneScript dataclass to the canonical scene dict."""
    return {
        "title": getattr(script, "title", "untitled"),
        "fps": getattr(script, "fps", 24),
        "characters": [
            {"id": c.id, "start_x": c.start_x} for c in getattr(script, "characters", [])
        ],
        "beats": [
            {
                "actor": b.actor,
                "action": b.action,
                "duration_s": b.duration_s,
                "direction": b.direction,
                "speed": b.speed,
                "amplitude": b.amplitude,
            }
            for b in getattr(script, "beats", [])
        ],
    }


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def plan_scene(
    prompt: str,
    backend: Optional[PlannerBackend] = None,
    scene: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Produce a **validated** scene dict for a prompt.

    Resolution order:
      1. ``scene`` given explicitly -> validate and return it (author-time path).
      2. ``backend`` given -> backend.plan(prompt) -> validate.
      3. otherwise -> :class:`PlanUnavailable`.

    Always raises :class:`ContractError` for a world the engine cannot render,
    and :class:`PlanUnavailable` when there is simply no planner.
    """
    if scene is not None:
        validated, _ = validate_scene(scene)
        return validated
    if backend is None:
        backend = NoOpPlanner()
    raw = backend.plan(prompt)
    validated, _ = validate_scene(raw)
    return validated


def llm_system_prompt() -> str:
    """Instruction text describing exactly what the LLM may express.

    Feed this to any external model as the system prompt; it targets the same
    registry ``validate_scene`` enforces, so valid output is guaranteed
    expressible and invalid output is caught.
    """
    caps = capabilities()
    actions = ", ".join(caps["actions"])
    objects = ", ".join(caps["objects"].keys())
    joints = ", ".join(caps["joints"].keys())
    themes = ", ".join(caps["themes"])
    scenery = ", ".join(caps["scenery_types"])
    camera = ", ".join(caps["camera_modes"])
    return (
        "You are a scene planner for a 2D stickman animation engine.\n"
        "Turn the user's request into ONE JSON SceneScript object. Output JSON only.\n\n"
        "Schema:\n"
        "{\n"
        '  "title": str,\n'
        '  "theme": "light"|"dark",\n'
        f'  "scenery": {{"type": one of [{scenery}]}},\n'
        '  "camera": {"mode": "' + "|".join(caps["camera_modes"]) + '", "zoom": float, "follow": bool},\n'
        '  "characters": [{"id": str, "start_x": float, "facing": 1|-1}],\n'
        '  "beats": [{"actor": id, "action": <action>, "duration_s": float, '
        '"direction": 1|-1, "speed": float, "amplitude": float}],\n'
        '  "objects": [{"id": str, "kind": <object>, "at": [x,y],\n'
        '               "attach": {"actor": id, "joint": "hand_r"},\n'
        '               "throw": {"frame": int, "vx": float, "vy": float}}]\n'
        "}\n\n"
        f"Allowed actions: {actions}\n"
        f"Allowed objects: {objects}\n"
        f"Allowed joints: {joints}\n"
        f"Themes: {themes}. Camera modes: {camera}.\n"
        "Rules: use only the names above; keep 1-2 characters; 5s is 120 frames "
        "at 24fps; every beat needs a valid actor id declared in characters."
    )
