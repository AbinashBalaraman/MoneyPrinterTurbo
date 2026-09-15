"""Deterministic keyword & synonym parser for natural language stickman prompts.

Maps text prompt -> structured controls {action, direction, speed, duration_seconds, amplitude, seed, n_person}.
Complies with AGENTS.md: No LLM inside the runtime engine; returns explicit limitations for unsupported prompts.
"""

import re
from typing import Dict, Any, Optional
from .catalog import ACTION_METADATA, validate_action_params

# Action keyword and synonym dictionary
SYNONYMS: Dict[str, list] = {
    # 2-Person Paired Actions (higher priority matching)
    "punch_block": [
        "punch and block", "punch block", "punching and blocking", "boxing defense",
        "strike and block", "one punches other blocks"
    ],
    "kick_dodge": [
        "kick and dodge", "kick dodge", "kick and duck", "kicking and dodging",
        "sweep dodge", "high kick duck"
    ],
    "knockdown_getup": [
        "knockdown and getup", "knockdown getup", "knock down get up", "kick down and rise",
        "ko and get up", "beat down and recover"
    ],
    "exchange": [
        "fight", "spar", "sparring", "exchange", "brawl", "duel", "martial arts",
        "combat", "exchange blows", "fight each other"
    ],

    # 1-Person Single Actions
    "walkback": [
        "walk back", "walk backwards", "walkback", "backpedal", "retreat", "backing up",
        "step back", "reverse walk"
    ],
    "walk": [
        "walk", "walks", "walking", "stroll", "strolls", "step forward", "march", "strolling"
    ],
    "run": [
        "run", "runs", "running", "sprint", "sprinting", "dash", "jog", "jogging", "hurry", "rush"
    ],
    "jump": [
        "jump", "jumps", "jumping", "leap", "leaping", "hop", "hopping", "bounce", "vault"
    ],
    "punch": [
        "punch", "punches", "punching", "strike", "fist", "jab", "hook", "hit", "attack"
    ],
    "kick": [
        "kick", "kicks", "kicking", "high kick", "side kick", "roundhouse"
    ],
    "block": [
        "block", "blocks", "blocking", "guard", "guarding", "defend", "shield"
    ],
    "wave": [
        "wave", "waves", "waving", "greeting", "say hello", "hello", "hi", "hand wave"
    ],
    "squat": [
        "squat", "squats", "squatting", "crouch", "crouching", "duck", "ducking", "kneel"
    ],
    "knockdown": [
        "knockdown", "knocked down", "knock down", "falls down", "fall down", "falls", "fall", "collapse", "collapses", "KO", "faint"
    ],
    "getup": [
        "get up", "gets up", "getup", "getting up", "stand up", "stands up", "standing up", "rise", "rises", "rising"
    ],
    "celebrate": [
        "celebrate", "celebrates", "celebrating", "cheer", "cheers", "cheering", "dance", "dances", "dancing", "victory", "win", "wins"
    ],
    "idle": [
        "idle", "stand", "stands", "standing", "rest", "rests", "breathe", "stay still", "wait", "waits", "still"
    ]
}


def parse_prompt(prompt: str, default_duration: float = 5.0, seed: int = 0) -> Dict[str, Any]:
    """Parse text prompt into structured Puppet Engine controls.
    
    Returns dict:
    {
        "action": str,
        "n_person": int,
        "direction": int,
        "speed": float,
        "amplitude": float,
        "duration_seconds": float,
        "seed": int,
        "supported": bool,
        "raw_prompt": str
    }
    Raises ValueError with actionable message if the action is completely unsupported.
    """
    text = prompt.strip().lower()

    # 1. Match Action
    detected_action: Optional[str] = None
    
    # Check paired actions first (e.g. "punch and block" before "punch")
    for action, terms in SYNONYMS.items():
        for term in terms:
            # Word boundary matching where applicable
            pattern = r'\b' + re.escape(term) + r'\b'
            if re.search(pattern, text):
                detected_action = action
                break
        if detected_action:
            break

    if not detected_action:
        raise ValueError(
            f"Unsupported prompt: Could not match action in '{prompt}'. "
            f"Supported actions: {list(ACTION_METADATA.keys())}. "
            "Note: V1 engine supports constrained procedural actions; free-form open-vocabulary generation is not supported."
        )

    # 2. Match Direction (default 1 = right, -1 = left)
    # Word-boundary regex to avoid substring false positives (e.g. 'hi' in 'high').
    def _has_word(words):
        return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)

    direction = 1
    if _has_word(["left", "backward", "backwards", "reverse", "retreat"]):
        direction = -1
    elif _has_word(["right", "forward", "ahead"]):
        direction = 1

    # 3. Match Speed (default 1.0)
    speed = 1.0
    if _has_word(["fast", "quickly", "speedy", "rapid", "sprint"]):
        speed = 1.5
    elif _has_word(["slow", "slowly", "leisurely", "gently"]):
        speed = 0.6

    # 4. Match Amplitude (default 1.0)
    amplitude = 1.0
    if _has_word(["high", "huge", "big", "hard", "powerful", "strong", "intense"]):
        amplitude = 1.4
    elif _has_word(["small", "soft", "light", "tiny", "subtle", "gentle", "gently", "slight", "slightly"]):
        amplitude = 0.6

    # 5. Match Duration (e.g., "3s", "3 seconds", "5 sec")
    duration = default_duration
    dur_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)\b', text)
    if dur_match:
        try:
            val = float(dur_match.group(1))
            if 0.5 <= val <= 30.0:
                duration = val
        except ValueError:
            pass

    meta = ACTION_METADATA[detected_action]
    n_person = meta["n_person"]

    validated_params = validate_action_params(detected_action, {
        "duration_seconds": duration,
        "speed": speed,
        "amplitude": amplitude,
        "direction": direction,
        "seed": seed
    })

    return {
        "action": detected_action,
        "n_person": n_person,
        "direction": validated_params.get("direction", direction),
        "speed": validated_params.get("speed", speed),
        "amplitude": validated_params.get("amplitude", amplitude),
        "duration_seconds": validated_params.get("duration_seconds", duration),
        "seed": seed,
        "supported": True,
        "raw_prompt": prompt
    }
