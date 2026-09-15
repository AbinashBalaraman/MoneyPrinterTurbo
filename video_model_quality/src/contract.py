"""Scene contract: the machine-readable capability registry + schema + validator.

This module is the *interface* between the world-builder (an LLM or a human
author) and the deterministic engine. The LLM describes a world as a
``SceneScript`` JSON document; this module declares exactly what that world can
express, and ``validate_scene`` normalises + rejects anything the engine cannot
truthfully render.

Division of labour
------------------
- **LLM / author** owns the *world*: who is present, what they do, which objects
  exist, where they are, how the camera frames them.
- **Engine** owns *execution*: rig, IK, ground contact, object simulation,
  camera, render. It never invents motion or semantics.

Nothing here imports the renderer or numpy, so it is cheap to expose as a tool
schema (MCP-like or otherwise) and safe to call from any layer.
"""

from typing import Any, Dict, List, Optional, Tuple

from .catalog import ACTION_METADATA

# --------------------------------------------------------------------------- #
# Rig capability: the joint names a prop may be anchored to.
# Joint i is the endpoint of bone i-1; joint 0 is the root.
# --------------------------------------------------------------------------- #
JOINT_INDEX: Dict[str, int] = {
    "root": 0,
    "spine": 1,
    "chest": 2,
    "neck": 3,
    "head": 4,
    "elbow_l": 5,
    "hand_l": 6,
    "elbow_r": 7,
    "hand_r": 8,
    "knee_l": 9,
    "ankle_l": 10,
    "foot_l": 11,
    "knee_r": 12,
    "ankle_r": 13,
    "foot_r": 14,
}

JOINT_ALIASES: Dict[str, str] = {
    "origin": "root", "hip": "root", "pelvis": "root",
    "torso": "spine", "waist": "spine",
    "shoulder": "chest", "shoulders": "chest", "upper_chest": "chest",
    "throat": "neck",
    "skull": "head",
    "left_elbow": "elbow_l",
    "left_hand": "hand_l", "lhand": "hand_l", "wrist_l": "hand_l",
    "right_elbow": "elbow_r",
    "right_hand": "hand_r", "rhand": "hand_r", "wrist_r": "hand_r",
    "hand": "hand_r", "wrist": "hand_r", "fist": "hand_r",
    "left_knee": "knee_l",
    "left_ankle": "ankle_l", "left_foot": "foot_l",
    "right_knee": "knee_r",
    "right_ankle": "ankle_r", "right_foot": "foot_r",
    "feet": "foot_r", "foot": "foot_r",
}


def resolve_joint(name: Any) -> Optional[int]:
    """Free-text joint name -> joint index, or None if unknown."""
    if isinstance(name, int):
        return name if 0 <= name < 15 else None
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace(" ", "_")
    if key in JOINT_INDEX:
        return JOINT_INDEX[key]
    if key in JOINT_ALIASES:
        return JOINT_INDEX[JOINT_ALIASES[key]]
    return None


# --------------------------------------------------------------------------- #
# Object capability registry.
#
# Capabilities mirror what the renderers truthfully implement:
#   place  -> can stand in the world at an (x, y)
#   attach -> can be locked to a puppet joint (hand-held)
#   throw  -> can be released on a ballistic arc
#   bounce -> should bounce/roll on landing (ball-like)
# --------------------------------------------------------------------------- #
OBJECT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "sword":   {"place": True,  "attach": True,  "throw": True,  "bounce": False,
                "aliases": ["blade", "katana", "rapier", "longsword", "saber", "sabre",
                            "broadsword", "claymore", "dagger", "knife", "cutlass", "scimitar", "greatsword"]},
    "staff":   {"place": True,  "attach": True,  "throw": True,  "bounce": False,
                "aliases": ["pole", "bo", "bo staff", "quarterstaff", "spear",
                            "stick", "rod", "cane", "walking stick", "baton", "wand"]},
    "shield":  {"place": True,  "attach": True,  "throw": True,  "bounce": False,
                "aliases": ["buckler", "guard_shield", "targe", "aegis", "riot shield", "pavise", "heater shield"]},
    "ball":    {"place": True,  "attach": True,  "throw": True,  "bounce": True,
                "aliases": ["sphere", "rock", "stone", "boulder", "ball_",
                            "orb", "globe", "basketball", "soccer ball", "football", "cannonball", "pellet"]},
    "chair":   {"place": True,  "attach": False, "throw": True,  "bounce": False,
                "aliases": ["stool", "seat", "bench", "throne", "armchair", "couch", "sofa", "recliner"]},
    "tree":    {"place": True,  "attach": False, "throw": False, "bounce": False,
                "aliases": ["plant", "bush", "sapling", "oak", "pine", "palm", "timber", "wood"]},
    "crowd":   {"place": True,  "attach": False, "throw": False, "bounce": False,
                "aliases": ["spectators", "audience", "onlookers", "bystanders",
                            "mob", "gathering", "fans", "masses", "cheerers"]},
    "box":     {"place": True,  "attach": False, "throw": True,  "bounce": False,
                "aliases": ["crate", "carton", "chest_box", "container",
                            "package", "parcel", "chest", "trunk", "cube"]},
    "speech_bubble": {"place": True, "attach": True, "throw": False, "bounce": False,
                "aliases": ["bubble", "dialogue", "speech", "thought",
                            "callout", "text bubble", "chat bubble", "speech balloon", "quote"]},
    "gavel":   {"place": True,  "attach": False, "throw": True,  "bounce": False,
                "aliases": ["hammer", "mallet", "judge_gavel", "club", "sledgehammer", "wooden hammer"]},
    "confetti": {"place": True, "attach": False, "throw": True,  "bounce": False,
                 "aliases": ["sparkles", "sparkle", "particles", "glitter", "streamers", "ribbons", "fireworks"]},
    "desk":    {"place": True,  "attach": False, "throw": False, "bounce": False,
                "aliases": ["table", "workstation", "counter", "office_desk", "bureau"]},
    "laptop":  {"place": True,  "attach": True,  "throw": True,  "bounce": False,
                "aliases": ["computer", "notebook", "pc", "terminal", "screen", "macbook"]},
}

# kind -> canonical, built from registry (longest alias wins via resolve_object).
_OBJECT_ALIASES: Dict[str, str] = {}
for _kind, _meta in OBJECT_REGISTRY.items():
    _OBJECT_ALIASES.setdefault(_kind, _kind)
    for _a in _meta.get("aliases", []):
        _OBJECT_ALIASES.setdefault(_a, _kind)


def resolve_object(name: Any) -> Optional[str]:
    """Free-text object noun -> canonical object kind, or None if unsupported."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower()
    if key in OBJECT_REGISTRY:
        return key
    if key in _OBJECT_ALIASES:
        return _OBJECT_ALIASES[key]
    return None


def object_supports(kind: str, capability: str) -> bool:
    meta = OBJECT_REGISTRY.get(kind)
    return bool(meta and meta.get(capability, False))


# --------------------------------------------------------------------------- #
# Stage capability.
# --------------------------------------------------------------------------- #
THEMES: Tuple[str, ...] = ("light", "dark")
SCENERY_TYPES: Tuple[str, ...] = ("plain", "perspective_hall", "spline_web", "split_screen_3")

CAMERA_MODES: Tuple[str, ...] = ("auto", "static", "follow", "close", "wide", "pan")

INTERACTIONS: Tuple[str, ...] = ("strike", "block", "dodge", "grab", "knockdown", "assist", "talk")

# 16-decal facial expressions on localized head UV space
EXPRESSIONS: Tuple[str, ...] = (
    "neutral", "happy", "sad", "angry", "effort", "shocked",
    "focused", "sleepy", "crying", "pensive", "manic", "ecstasy",
    "wink", "suspicious", "despair", "dead"
)

EXPRESSION_ALIASES: Dict[str, str] = {
    "normal": "neutral", "default": "neutral",
    "smile": "happy", "joy": "happy", "cheerful": "happy",
    "frown": "sad", "sorrow": "sad",
    "mad": "angry", "rage": "angry", "furious": "angry",
    "grimace": "effort", "strain": "effort", "struggle": "effort",
    "surprised": "shocked", "astonished": "shocked", "gasp": "shocked",
    "determined": "focused", "serious": "focused", "intense": "focused", "typing": "focused",
    "tired": "sleepy", "drowsy": "sleepy", "asleep": "sleepy",
    "tears": "crying", "weeping": "crying",
    "thinking": "pensive", "pondering": "pensive",
    "insane": "manic", "crazy": "manic", "unhinged": "manic",
    "bliss": "ecstasy", "delight": "ecstasy",
    "smirk": "wink", "flirt": "wink",
    "doubt": "suspicious", "skeptical": "suspicious",
    "distress": "despair", "anguish": "despair", "defeated": "despair",
    "dazed": "dead", "ko": "dead", "knocked_out": "dead", "x_eyes": "dead",
}


def resolve_expression(name: Any) -> Optional[str]:
    """Free-text expression name -> canonical expression name, or None if unknown."""
    if not isinstance(name, str):
        return None
    key = name.strip().lower().replace(" ", "_")
    if key in EXPRESSIONS:
        return key
    if key in EXPRESSION_ALIASES:
        return EXPRESSION_ALIASES[key]
    return None


# Action names (1P + 2P) come from the frozen catalog.
ACTION_NAMES: Tuple[str, ...] = tuple(ACTION_METADATA.keys())
ACTION_1P: Tuple[str, ...] = tuple(a for a, m in ACTION_METADATA.items() if m["n_person"] == 1)
ACTION_2P: Tuple[str, ...] = tuple(a for a, m in ACTION_METADATA.items() if m["n_person"] == 2)


# --------------------------------------------------------------------------- #
# Scene JSON schema (informal, for the planner prompt / tool description).
# --------------------------------------------------------------------------- #
SCENE_SCHEMA: Dict[str, Any] = {
    "title": "str",
    "fps": "int (default 24)",
    "theme": f"one of {list(THEMES)}",
    "scenery": {"type": f"one of {list(SCENERY_TYPES)}", "auto_camera": "bool"},
    "camera": {
        "mode": f"one of {list(CAMERA_MODES)}",
        "zoom": "float (default 1.0)",
        "focus": "actor id or 'mid'",
        "follow": "bool",
    },
    "characters": [
        {"id": "str", "start_x": "float", "facing": "1 (right) | -1 (left)",
         "color": "[r,g,b] optional", "role": "str optional",
         "expression": f"one of {list(EXPRESSIONS)} optional"}
    ],
    "beats": [
        {"actor": "character id", "action": f"one of {list(ACTION_NAMES)}",
         "duration_s": "float", "direction": "1|-1", "speed": "float",
         "amplitude": "float", "at_s": "float optional start time",
         "target": "actor id optional", "interaction": f"one of {list(INTERACTIONS)} optional",
         "expression": f"one of {list(EXPRESSIONS)} optional"}
    ],
    "objects": [
        {"id": "str", "kind": f"one of {list(OBJECT_REGISTRY)}",
         "at": "[x, y] optional",
         "spawn_frame": "int optional", "despawn_frame": "int optional",
         "attach": {"actor": "id", "joint": "name", "from_frame": "int", "to_frame": "int"},
         "throw": {"frame": "int", "vx": "float", "vy": "float", "gravity": "float"}}
    ],
    "shots": [
        {"id": "str optional", "duration_s": "float optional",
         "scenery": "dict optional", "camera": "dict optional",
         "characters": "list optional", "beats": "list optional",
         "objects": "list optional"}
    ],
}


def capabilities() -> Dict[str, Any]:
    """The full machine-readable capability registry for a planner/tool.

    An LLM (or any author) can read this to know precisely what worlds the
    engine can express before it emits a SceneScript.
    """
    return {
        "actions": list(ACTION_NAMES),
        "actions_1p": list(ACTION_1P),
        "actions_2p": list(ACTION_2P),
        "interactions": list(INTERACTIONS),
        "expressions": list(EXPRESSIONS),
        "expression_aliases": dict(EXPRESSION_ALIASES),
        "objects": {
            kind: {k: v for k, v in meta.items() if k != "aliases"}
            for kind, meta in OBJECT_REGISTRY.items()
        },
        "object_aliases": dict(_OBJECT_ALIASES),
        "joints": dict(JOINT_INDEX),
        "joint_aliases": dict(JOINT_ALIASES),
        "themes": list(THEMES),
        "scenery_types": list(SCENERY_TYPES),
        "camera_modes": list(CAMERA_MODES),
        "schema": SCENE_SCHEMA,
    }


# --------------------------------------------------------------------------- #
# Validation.
# --------------------------------------------------------------------------- #
class ContractError(ValueError):
    """Raised when a SceneScript describes something the engine cannot render."""


def _as_float(v: Any, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def validate_scene(scene: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, List[str]]]:
    """Normalise a raw SceneScript dict; reject unrenderable worlds.

    Returns ``(normalised_scene, report)`` where report has ``errors`` and
    ``warnings``. Raises :class:`ContractError` listing all errors when the
    scene cannot be truthfully compiled. Unknown-but-optional extras become
    warnings; unknown actions/objects/joints are hard errors (fail fast).
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(scene, dict):
        raise ContractError("SceneScript must be a JSON object.")

    out: Dict[str, Any] = {
        "title": str(scene.get("title", "untitled")),
        "fps": _as_int(scene.get("fps", 24), 24),
    }

    theme = str(scene.get("theme", "light")).strip().lower()
    if theme not in THEMES:
        warnings.append(f"Unknown theme '{theme}'; using 'light'. Valid: {list(THEMES)}")
        theme = "light"
    out["theme"] = theme

    scenery = scene.get("scenery") or {}
    if isinstance(scenery, dict):
        stype = str(scenery.get("type", "plain")).strip().lower()
        if stype not in SCENERY_TYPES:
            warnings.append(f"Unknown scenery type '{stype}'; using 'plain'. Valid: {list(SCENERY_TYPES)}")
            stype = "plain"
        out["scenery"] = {"type": stype, "auto_camera": bool(scenery.get("auto_camera", True))}
    else:
        out["scenery"] = {"type": "plain", "auto_camera": True}

    camera = scene.get("camera") or {}
    if isinstance(camera, dict) and camera:
        mode = str(camera.get("mode", "auto")).strip().lower()
        if mode not in CAMERA_MODES:
            warnings.append(f"Unknown camera mode '{mode}'; using 'auto'. Valid: {list(CAMERA_MODES)}")
            mode = "auto"
        out["camera"] = {
            "mode": mode,
            "zoom": max(0.25, min(4.0, _as_float(camera.get("zoom", 1.0), 1.0))),
            "focus": camera.get("focus", "mid"),
            "follow": bool(camera.get("follow", False)),
        }
    else:
        out["camera"] = {"mode": "auto", "zoom": 1.0, "focus": "mid", "follow": False}

    # Characters ---------------------------------------------------------- #
    chars = scene.get("characters") or []
    norm_chars: List[Dict[str, Any]] = []
    char_ids = set()
    if not isinstance(chars, list):
        errors.append("'characters' must be a list.")
        chars = []
    for i, c in enumerate(chars):
        if not isinstance(c, dict):
            errors.append(f"characters[{i}] must be an object.")
            continue
        cid = str(c.get("id", f"actor_{i}"))
        if cid in char_ids:
            errors.append(f"Duplicate character id '{cid}'.")
        char_ids.add(cid)
        cdict: Dict[str, Any] = {
            "id": cid,
            "start_x": _as_float(c.get("start_x", 0.0), 0.0),
            "facing": -1 if _as_int(c.get("facing", 1), 1) < 0 else 1,
            "color": c.get("color"),
        }
        if "role" in c and c["role"] is not None:
            cdict["role"] = str(c["role"]).strip()
        if "expression" in c and c["expression"] is not None:
            expr = resolve_expression(c["expression"])
            if expr:
                cdict["expression"] = expr
            else:
                warnings.append(f"characters[{i}]: unknown expression '{c['expression']}'; defaulting to 'neutral'.")
                cdict["expression"] = "neutral"
        norm_chars.append(cdict)
    out["characters"] = norm_chars

    # Beats --------------------------------------------------------------- #
    beats = scene.get("beats") or []
    norm_beats: List[Dict[str, Any]] = []
    if not isinstance(beats, list):
        errors.append("'beats' must be a list.")
        beats = []
    for i, b in enumerate(beats):
        if not isinstance(b, dict):
            errors.append(f"beats[{i}] must be an object.")
            continue
        action = str(b.get("action", "")).strip().lower()
        if action not in ACTION_METADATA:
            errors.append(
                f"beats[{i}]: unknown action '{b.get('action')}'. Valid: {list(ACTION_NAMES)}"
            )
            continue
        actor = str(b.get("actor", "a"))
        if actor not in char_ids:
            warnings.append(f"beats[{i}]: actor '{actor}' not declared in characters; adding it.")
            char_ids.add(actor)
            norm_chars.append({"id": actor, "start_x": 0.0, "facing": 1, "color": None})
        nb: Dict[str, Any] = {
            "actor": actor,
            "action": action,
            "duration_s": max(0.2, _as_float(b.get("duration_s", 2.0), 2.0)),
            "direction": -1 if _as_int(b.get("direction", 1), 1) < 0 else 1,
            "speed": max(0.1, _as_float(b.get("speed", 1.0), 1.0)),
            "amplitude": max(0.1, _as_float(b.get("amplitude", 1.0), 1.0)),
        }
        if "at_s" in b:
            nb["at_s"] = max(0.0, _as_float(b.get("at_s"), 0.0))
        if "target" in b and b["target"] is not None:
            target_id = str(b["target"]).strip()
            nb["target"] = target_id
            if char_ids and target_id not in char_ids:
                warnings.append(f"beats[{i}]: target '{target_id}' not declared in characters.")
        if "interaction" in b and b["interaction"] is not None:
            raw_inter = str(b["interaction"]).strip().lower()
            if raw_inter not in INTERACTIONS:
                errors.append(
                    f"beats[{i}]: unknown interaction '{b.get('interaction')}'. Valid: {list(INTERACTIONS)}"
                )
            else:
                nb["interaction"] = raw_inter
        if "expression" in b and b["expression"] is not None:
            b_expr = resolve_expression(b["expression"])
            if b_expr:
                nb["expression"] = b_expr
            else:
                warnings.append(f"beats[{i}]: unknown expression '{b['expression']}'.")
        norm_beats.append(nb)
    out["beats"] = norm_beats

    # Objects ------------------------------------------------------------- #
    objects = scene.get("objects") or []
    norm_objs: List[Dict[str, Any]] = []
    obj_ids = set()
    if not isinstance(objects, list):
        errors.append("'objects' must be a list.")
        objects = []
    for i, o in enumerate(objects):
        if not isinstance(o, dict):
            errors.append(f"objects[{i}] must be an object.")
            continue
        raw_kind = o.get("kind", o.get("type"))
        kind = resolve_object(raw_kind)
        if kind is None:
            errors.append(
                f"objects[{i}]: unknown object kind '{raw_kind}'. Valid: {list(OBJECT_REGISTRY)}"
            )
            continue
        oid = str(o.get("id", f"{kind}_{i}"))
        if oid in obj_ids:
            errors.append(f"Duplicate object id '{oid}'.")
        obj_ids.add(oid)
        meta = OBJECT_REGISTRY[kind]
        spec: Dict[str, Any] = {"id": oid, "kind": kind, "scale": max(0.1, _as_float(o.get("scale", 1.0), 1.0))}

        at = o.get("at")
        if isinstance(at, (list, tuple)) and len(at) == 2:
            spec["at"] = [_as_float(at[0], 0.0), _as_float(at[1], -0.42)]
        elif at is not None:
            warnings.append(f"objects[{i}]: 'at' must be [x, y]; ignoring.")
        spec["spawn_frame"] = max(0, _as_int(o.get("spawn_frame", 0), 0))
        if "despawn_frame" in o:
            spec["despawn_frame"] = max(0, _as_int(o.get("despawn_frame"), 0))

        # attach
        attach = o.get("attach")
        if attach:
            if not meta["attach"]:
                errors.append(f"objects[{i}] ('{kind}'): does not support attach.")
            elif not isinstance(attach, dict):
                errors.append(f"objects[{i}]: 'attach' must be an object.")
            else:
                actor = str(attach.get("actor", "a"))
                if char_ids and actor not in char_ids:
                    errors.append(f"objects[{i}]: attach.actor '{actor}' is not a declared character.")
                joint = resolve_joint(attach.get("joint", "hand_r"))
                if joint is None:
                    errors.append(f"objects[{i}]: unknown attach joint '{attach.get('joint')}'.")
                else:
                    spec["attach"] = {
                        "actor": actor,
                        "joint": joint,
                        "from_frame": max(0, _as_int(attach.get("from_frame", 0), 0)),
                        "to_frame": _as_int(attach.get("to_frame"), -1),
                    }

        # throw
        throw = o.get("throw")
        if throw:
            if not meta["throw"]:
                errors.append(f"objects[{i}] ('{kind}'): does not support throw.")
            elif not isinstance(throw, dict):
                errors.append(f"objects[{i}]: 'throw' must be an object.")
            else:
                spec["throw"] = {
                    "frame": max(0, _as_int(throw.get("frame", 0), 0)),
                    "vx": _as_float(throw.get("vx", 0.8), 0.8),
                    "vy": _as_float(throw.get("vy", 0.9), 0.9),
                    "gravity": _as_float(throw.get("gravity", 1.8), 1.8),
                }
        if "bounce" in o:
            spec["bounce"] = bool(o["bounce"]) and meta.get("bounce", False)
        elif meta.get("bounce"):
            spec["bounce"] = True

        # pickup / drop (ground <-> hand handoff)
        pickup = o.get("pickup")
        if pickup:
            if not meta["attach"]:
                errors.append(f"objects[{i}] ('{kind}'): does not support pickup.")
            elif not isinstance(pickup, dict):
                errors.append(f"objects[{i}]: 'pickup' must be an object.")
            else:
                actor = str(pickup.get("actor", "a"))
                if char_ids and actor not in char_ids:
                    errors.append(f"objects[{i}]: pickup.actor '{actor}' is not a declared character.")
                joint = resolve_joint(pickup.get("joint", "hand_r"))
                if joint is None:
                    errors.append(f"objects[{i}]: unknown pickup joint '{pickup.get('joint')}'.")
                else:
                    spec["pickup"] = {
                        "actor": actor,
                        "joint": joint,
                        "frame": max(0, _as_int(pickup.get("frame", 0), 0)),
                    }

        norm_objs.append(spec)
    out["objects"] = norm_objs

    # Shots (time / multi-shot editing) ----------------------------------- #
    shots = scene.get("shots")
    if shots is not None:
        if not isinstance(shots, list):
            errors.append("'shots' must be a list.")
        else:
            norm_shots: List[Dict[str, Any]] = []
            for si, s in enumerate(shots):
                if not isinstance(s, dict):
                    errors.append(f"shots[{si}] must be an object.")
                    continue
                nshot: Dict[str, Any] = {
                    "id": str(s.get("id", f"shot_{si}")),
                    "duration_s": max(0.2, _as_float(s.get("duration_s", 2.0), 2.0)),
                }
                for key in ("scenery", "camera", "characters", "beats", "objects"):
                    if key in s:
                        nshot[key] = s[key]
                norm_shots.append(nshot)
            out["shots"] = norm_shots

    if errors:
        raise ContractError("SceneScript failed validation:\n  - " + "\n  - ".join(errors))
    return out, {"errors": errors, "warnings": warnings}
