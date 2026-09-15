"""Action Catalog definition and JSON schema validation for Puppet Engine.

Freezes all single-person (1P) and paired (2P) actions with their parameter schemas.
"""

from typing import Dict, Any, List, Optional
from .data_gen import ACTIONS_1P, ACTIONS_2P

ACTION_METADATA: Dict[str, Dict[str, Any]] = {
    # Single Person Actions (1P)
    "idle": {
        "description": "Standing rest pose with subtle breathing and arm sway.",
        "n_person": 1,
        "category": "locomotion_rest",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.1, "max": 2.5},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "walk": {
        "description": "Standard forward walking motion with natural arm swings.",
        "n_person": 1,
        "category": "locomotion",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.2, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "run": {
        "description": "High-cadence sprint with extended leg and arm stride.",
        "n_person": 1,
        "category": "locomotion",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.2, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "walkback": {
        "description": "Backpedaling motion with reversed root velocity.",
        "n_person": 1,
        "category": "locomotion",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.2, "max": 2.0},
            "direction": {"type": "int", "default": -1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "jump": {
        "description": "Vertical jump with knee tuck and airborne apex.",
        "n_person": 1,
        "category": "acrobatics",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.5},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "punch": {
        "description": "Forward fist strike with torso rotation and arm extension.",
        "n_person": 1,
        "category": "combat",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.5},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "kick": {
        "description": "Forward leg kick with hip drive and balance compensation.",
        "n_person": 1,
        "category": "combat",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.5},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "block": {
        "description": "Defensive guard posture with arms raised to absorb impact.",
        "n_person": 1,
        "category": "combat",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "wave": {
        "description": "Friendly greeting gesture with raised waving arm.",
        "n_person": 1,
        "category": "gesture",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.5},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "squat": {
        "description": "Deep knee flexion and hip drop towards ground plane.",
        "n_person": 1,
        "category": "exercise",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "knockdown": {
        "description": "Backward recoil and falling collapse to the ground.",
        "n_person": 1,
        "category": "combat_reaction",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "getup": {
        "description": "Rising from ground level back to standing rest pose.",
        "n_person": 1,
        "category": "combat_reaction",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },
    "celebrate": {
        "description": "Victory cheer with jumping hops and celebratory arm pumps.",
        "n_person": 1,
        "category": "gesture",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "speed": {"type": "float", "default": 1.0, "min": 0.2, "max": 3.0},
            "amplitude": {"type": "float", "default": 1.0, "min": 0.3, "max": 2.0},
            "direction": {"type": "int", "default": 1, "enum": [1, -1]},
            "seed": {"type": "int", "default": 0}
        }
    },

    # Paired Fight Actions (2P)
    "punch_block": {
        "description": "Person A delivers a punch while Person B blocks in reaction.",
        "n_person": 2,
        "category": "combat_pair",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "seed": {"type": "int", "default": 0}
        }
    },
    "kick_dodge": {
        "description": "Person A delivers a high kick while Person B ducks / squats.",
        "n_person": 2,
        "category": "combat_pair",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "seed": {"type": "int", "default": 0}
        }
    },
    "exchange": {
        "description": "Mutual martial arts strike and guard exchange between two actors.",
        "n_person": 2,
        "category": "combat_pair",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "seed": {"type": "int", "default": 0}
        }
    },
    "knockdown_getup": {
        "description": "Person A kicks Person B down, and Person B gradually gets back up.",
        "n_person": 2,
        "category": "combat_pair",
        "params": {
            "duration_seconds": {"type": "float", "default": 5.0, "min": 0.5, "max": 30.0},
            "seed": {"type": "int", "default": 0}
        }
    },
}


def get_action_catalog() -> Dict[str, Any]:
    """Returns the full frozen catalog schema for MCP and puppet engine discovery."""
    return {
        "actions": ACTION_METADATA,
        "actions_1p": ACTIONS_1P,
        "actions_2p": ACTIONS_2P,
        "categories": sorted(list({meta["category"] for meta in ACTION_METADATA.values()}))
    }


def validate_action_params(action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validates provided parameters against action schema and fills defaults."""
    if action not in ACTION_METADATA:
        raise ValueError(f"Unknown action '{action}'. Supported actions: {list(ACTION_METADATA.keys())}")
    
    schema = ACTION_METADATA[action]["params"]
    validated: Dict[str, Any] = {}
    params = params or {}

    for param_name, param_rule in schema.items():
        val = params.get(param_name, param_rule.get("default"))
        if "min" in param_rule and val < param_rule["min"]:
            val = param_rule["min"]
        if "max" in param_rule and val > param_rule["max"]:
            val = param_rule["max"]
        if "enum" in param_rule and val not in param_rule["enum"]:
            val = param_rule["default"]
        validated[param_name] = val

    return validated
