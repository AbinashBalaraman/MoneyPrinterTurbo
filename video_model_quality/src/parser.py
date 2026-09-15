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
        "punch and block", "punches and blocks", "punching and blocking", "punched and blocked",
        "punch block", "boxing defense", "strike and block", "strikes and blocks",
        "striking and blocking", "one punches other blocks", "one punches the other blocks",
        "jab and block", "jabs and blocks", "attack and defend", "attacks and defends",
        "attacking and defending", "strike and defend", "strikes and defends",
        "punch and guard", "punches and guards", "punching and guarding"
    ],
    "kick_dodge": [
        "kick and dodge", "kicks and dodges", "kicking and dodging", "kicked and dodged",
        "kick dodge", "kick and duck", "kicks and ducks", "kicking and ducking",
        "kicked and ducked", "sweep dodge", "sweep and dodge", "high kick duck",
        "kick and evade", "kicks and evades", "kicking and evading",
        "kick and weave", "kicks and weaves", "kick and sidestep", "kicks and sidesteps",
        "sweep and duck"
    ],
    "knockdown_getup": [
        "fighter kicks opponent down and opponent recovers",
        "kicks opponent down and opponent recovers", "kick opponent down and opponent recovers",
        "knockdown and getup", "knockdown getup", "knock down get up",
        "knock down and get up", "knocked down and gets up", "knockdown and rise",
        "knock down and rise", "kick down and rise", "kicks down and rises",
        "ko and get up", "beat down and recover", "beats down and recovers",
        "knock down and recover", "knockdown and recover", "fall down and get up",
        "falls down and gets up", "fell down and got up", "takedown and getup",
        "takedown and recover"
    ],
    "exchange": [
        "exchange blows", "exchanging blows", "sparring vigorously", "duel in martial arts",
        "fight each other", "fighting each other", "trade blows", "trades blows",
        "trading blows", "traded blows", "spar each other",
        "fight", "fights", "fighting", "fought",
        "spar", "spars", "sparring", "sparred",
        "exchange", "exchanges", "exchanging", "exchanged",
        "brawl", "brawls", "brawling", "brawled",
        "duel", "duels", "dueling", "duelling", "dueled",
        "martial arts", "combat", "melee", "skirmish", "skirmishing", "scuffle", "scuffling"
    ],

    # 1-Person Single Actions
    "walkback": [
        "walk back", "walks back", "walking back", "walked back",
        "walk backwards", "walks backwards", "walking backwards", "walked backwards",
        "walk backward", "walks backward", "walking backward", "walked backward",
        "walkback", "walkbacks", "backpedal", "backpedals", "backpedaling", "backpedaled",
        "retreat", "retreats", "retreating", "retreated",
        "backing up", "backs up", "backed up", "back up",
        "step back", "steps back", "stepping back", "stepped back",
        "step backwards", "steps backwards", "stepping backwards", "stepped backwards",
        "step backward", "steps backward", "stepping backward", "stepped backward",
        "reverse walk", "reverse walks", "reverse walking", "walk in reverse",
        "backing away", "back away", "backs away", "backed away",
        "withdraw", "withdraws", "withdrawing", "withdrew",
        "move back", "moves back", "moving back", "moved back"
    ],
    "walk": [
        "step forward", "steps forward", "stepping forward", "stepped forward",
        "walk", "walks", "walking", "walked",
        "stroll", "strolls", "strolling", "strolled",
        "march", "marches", "marching", "marched",
        "stride", "strides", "striding", "strode",
        "wander", "wanders", "wandering", "wandered",
        "pace", "paces", "pacing", "paced",
        "amble", "ambles", "ambling", "ambled",
        "saunter", "saunters", "sauntering", "sauntered",
        "promenade", "tread", "treads", "treading",
        "step", "steps", "stepping",
        "advance", "advances", "advancing", "advanced",
        "glide", "glides", "gliding"
    ],
    "run": [
        "run", "runs", "running", "ran",
        "sprint", "sprints", "sprinting", "sprinted",
        "dash", "dashes", "dashing", "dashed",
        "jog", "jogs", "jogging", "jogged",
        "hurry", "hurries", "hurrying", "hurried",
        "rush", "rushes", "rushing", "rushed",
        "charge", "charges", "charging", "charged",
        "bolt", "bolts", "bolting", "bolted",
        "dart", "darts", "darting", "darted",
        "race", "races", "racing", "raced",
        "gallop", "gallops", "galloping",
        "scurry", "scurries", "scurrying", "scurried",
        "scamper", "scampers", "scampering",
        "hustle", "hustles", "hustling"
    ],
    "jump": [
        "jump", "jumps", "jumping", "jumped",
        "leap", "leaps", "leaping", "leaped", "leapt",
        "hop", "hops", "hopping", "hopped",
        "bounce", "bounces", "bouncing", "bounced",
        "vault", "vaults", "vaulting", "vaulted",
        "cartwheel", "cartwheels", "cartwheeling", "cartwheeled",
        "flip", "flips", "flipping", "flipped",
        "backflip", "backflips", "frontflip", "frontflips",
        "somersault", "somersaults", "somersaulting",
        "bound", "bounds", "bounding", "bounded",
        "spring", "springs", "springing"
    ],
    "punch": [
        "throw a punch", "throws a punch", "throwing a punch", "threw a punch",
        "throw punch", "throws punch", "throwing punch",
        "fist strike", "fist strikes", "punch forward", "punches forward",
        "punch", "punches", "punching", "punched",
        "strike", "strikes", "striking", "struck",
        "fist", "fists",
        "jab", "jabs", "jabbing", "jabbed",
        "hook", "hooks", "hooking", "hooked",
        "hit", "hitting",
        "attack", "attacks", "attacking", "attacked",
        "cross", "crosses",
        "uppercut", "uppercuts", "uppercutting",
        "haymaker", "haymakers",
        "smack", "smacks", "smacking", "smacked",
        "sock", "socks", "socking", "socked",
        "swat", "swats", "swatting", "swatted"
    ],
    "kick": [
        "roundhouse kick", "roundhouse kicks", "side kick", "side kicks",
        "high kick", "high kicks", "low kick", "low kicks",
        "front kick", "front kicks", "back kick", "back kicks",
        "dropkick", "drop kick", "dropkicks", "dropkicking", "dropkicked",
        "flying kick", "flying kicks", "sweep kick", "leg sweep", "leg sweeps",
        "kicking high", "kick forward", "kicks forward",
        "kick", "kicks", "kicking", "kicked",
        "roundhouse",
        "punt", "punts", "punting", "punted",
        "boot", "boots", "booting", "booted"
    ],
    "block": [
        "ward off hit", "wards off hit", "warding off hit", "warded off hit",
        "defensive hits", "defensive hit",
        "block hit", "blocks hit", "blocking hit",
        "defend hit", "defends hit", "defending hit",
        "raise a shield", "raises a shield", "raise shield", "raises shield", "raising shield",
        "absorb blow", "absorb hit",
        "ward off", "wards off", "warding off", "warded off",
        "cover up", "covers up", "covering up", "covered up",
        "fend off", "fends off", "fending off",
        "block", "blocks", "blocking", "blocked",
        "guard", "guards", "guarding", "guarded",
        "defend", "defends", "defending", "defended",
        "defense", "defence", "defensive", "defensively",
        "shield", "shields", "shielding", "shielded",
        "parry", "parries", "parrying", "parried",
        "brace", "braces", "bracing", "braced"
    ],
    "wave": [
        "say goodbye", "says goodbye", "say hello", "says hello", "saying hello", "said hello",
        "hand wave", "hand waves", "wave hand", "waves hand", "waving hand",
        "wave", "waves", "waving", "waved",
        "greeting", "greet", "greets", "greeted",
        "hello", "hi", "handwave", "handwaves",
        "salute", "salutes", "saluting", "saluted",
        "beckon", "beckons", "beckoning", "beckoned",
        "gesture", "gestures", "gesturing", "gestured",
        "signal", "signals", "signaling", "signalling", "signaled", "signalled",
        "goodbye", "bye", "farewell"
    ],
    "squat": [
        "evade strike", "evades strike", "evaded strike", "evading strike",
        "dodge strike", "dodges strike", "dodged strike", "dodging strike",
        "duck strike", "ducks strike", "ducked strike", "ducking strike",
        "duck down", "ducks down", "ducking down",
        "crouch down", "crouches down", "crouching down",
        "drop down", "drops down", "dropping down",
        "squat", "squats", "squatting", "squatted",
        "crouch", "crouches", "crouching", "crouched",
        "duck", "ducks", "ducking", "ducked",
        "kneel", "kneels", "kneeling", "knelt",
        "sidestep", "sidesteps", "sidestepping", "sidestepped",
        "weave", "weaves", "weaving", "wove",
        "bob", "bobs", "bobbing", "bobbed",
        "evade", "evades", "evading", "evaded",
        "dodge", "dodges", "dodging", "dodged",
        "slip", "slips", "slipping", "slipped",
        "roll", "rolls", "rolling", "rolled",
        "tumble", "tumbles", "tumbling", "tumbled",
        "dip", "dips", "dipping", "dipped"
    ],
    "knockdown": [
        "fall to the floor", "falls to the floor", "fell to the floor",
        "collapse backwards", "collapses backwards",
        "drop to the ground", "drops to the ground", "dropped to the ground",
        "hit the deck", "hits the deck",
        "knocked down", "knocking down", "knocks down",
        "knock down", "knockdown",
        "falls down", "fall down", "falling down", "fell down", "fallen down",
        "falls", "fall", "falling", "fell",
        "collapse", "collapses", "collapsing", "collapsed",
        "KO", "knocked out", "faint", "faints", "fainting", "fainted",
        "wiped out", "wipe out", "wipeout",
        "topple", "topples", "toppling", "toppled",
        "get knocked down", "gets knocked down", "got knocked down"
    ],
    "getup": [
        "recover from fall", "recovers from fall", "recovering from fall", "recovered from fall",
        "rise from fall", "rises from fall", "rising from fall", "rose from fall",
        "stand back up", "stands back up", "standing back up", "stood back up",
        "rise from the floor", "rises from the floor", "rose from the floor",
        "get back up", "gets back up", "getting back up", "got back up",
        "rise up", "rises up", "rising up", "rose up",
        "pick oneself up", "picks oneself up", "picked oneself up",
        "get up", "gets up", "getup", "getting up", "got up",
        "stand up", "stands up", "standing up", "stood up",
        "rise", "rises", "rising", "rose",
        "recover", "recovers", "recovering", "recovered",
        "back on feet", "on feet",
        "climb up", "climbs up", "climbing up"
    ],
    "celebrate": [
        "cheering loudly", "cheer loudly", "fist pump", "fist pumps", "fist pumping", "fist pumped",
        "celebrate", "celebrates", "celebrating", "celebrated",
        "cheer", "cheers", "cheering", "cheered",
        "dance", "dances", "dancing", "danced",
        "victory", "win", "wins", "winning", "won",
        "applaud", "applauds", "applauding", "applauded", "applause",
        "clap", "claps", "clapping", "clapped",
        "rejoice", "rejoices", "rejoicing", "rejoiced",
        "triumph", "triumphs", "triumphing", "triumphed",
        "jubilant", "praise", "praises", "exult", "exults", "exulting"
    ],
    "idle": [
        "stand still", "stands still", "standing still", "stood still",
        "hold still", "holds still", "holding still", "held still",
        "remain still", "remains still", "remaining still", "remained still",
        "stay still", "stays still", "staying still", "stayed still",
        "stay put", "stays put", "staying put",
        "be still",
        "idle", "idles", "idling", "idled",
        "stand", "stands", "standing", "stood",
        "rest", "rests", "resting", "rested",
        "breathe", "breathes", "breathing", "breathed",
        "wait", "waits", "waiting", "waited",
        "pause", "pauses", "pausing", "paused",
        "relax", "relaxes", "relaxing", "relaxed",
        "stationary",
        "chill", "chills", "chilling", "chilled",
        "freeze", "freezes", "freezing", "frozen",
        "still"
    ]
}


def match_actions(text: str) -> list:
    """Return ordered ``(position, action, matched_term)`` hits in ``text``.

    Single source of truth for lexicon matching, shared by the single-action
    parser and the scene planner. Matches are found positionally, then greedily
    de-duplicated longest-term-first so an overlap like "punch and block"
    resolves to the single paired action ``punch_block`` rather than also
    emitting ``punch`` and ``block``.
    """
    text = (text or "").lower()
    hits = []
    for action, terms in SYNONYMS.items():
        for term in terms:
            start = 0
            while True:
                i = text.find(term, start)
                if i < 0:
                    break
                before = text[i - 1] if i > 0 else " "
                after = text[i + len(term)] if i + len(term) < len(text) else " "
                if not before.isalnum() and not after.isalnum():
                    hits.append((i, action, term))
                start = i + len(term)
    hits.sort(key=lambda h: (h[0], -len(h[2])))

    kept = []
    last_end = -1
    for pos, action, term in hits:
        if pos < last_end:
            continue
        kept.append((pos, action, term))
        last_end = pos + len(term)
    return kept


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

    # 1. Match Action(s). Positional, longest-first, non-overlapping: a pair
    #    phrase like "punch and block" matches the single 2P action punch_block,
    #    while "walk, then punch" yields two distinct actions. The single-action
    #    parser FAILS FAST on multi-action scripts instead of silently picking
    #    one (the F-P0-1 defect); those belong to the scene planner.
    hits = match_actions(text)
    distinct = sorted({action for _, action, _ in hits})

    if not distinct:
        raise ValueError(
            f"Unsupported prompt: Could not match action in '{prompt}'. "
            f"Supported actions: {list(ACTION_METADATA.keys())}. "
            "Note: V1 engine supports constrained procedural actions; free-form open-vocabulary generation is not supported."
        )
    if len(distinct) > 1:
        raise ValueError(
            f"Ambiguous multi-action prompt: '{prompt}' mentions multiple actions "
            f"{distinct}. Use the scene planner "
            "(src.scene.parse_script / compile_scene) for ordered multi-action scripts "
            "instead of the single-action parser."
        )
    detected_action = distinct[0]

    # 2. Match Direction (default 1 = right, -1 = left)
    # Word-boundary regex to avoid substring false positives (e.g. 'hi' in 'high').
    def _has_word(words):
        return any(re.search(r'\b' + re.escape(w) + r'\b', text) for w in words)

    direction = 1
    if _has_word(["left", "backward", "backwards", "reverse", "retreat",
                  "leftward", "leftwards", "to the left", "rearward", "rearwards"]):
        direction = -1
    elif _has_word(["right", "forward", "ahead",
                    "rightward", "rightwards", "to the right", "frontward", "frontwards", "onward", "onwards"]):
        direction = 1

    # 3. Match Speed (default 1.0)
    speed = 1.0
    if _has_word(["fast", "quickly", "speedy", "rapid", "rapidly", "sprint", "swift", "swiftly",
                  "brisk", "briskly", "hurriedly", "hastily", "furiously", "wildly", "furious",
                  "wild", "frantic", "frantically", "energetic", "energetically"]):
        speed = 1.5
    elif _has_word(["slow", "slowly", "leisurely", "gently", "cautiously", "cautious",
                    "calm", "calmly", "gradual", "gradually", "sluggish", "sluggishly",
                    "deliberate", "deliberately", "unhurried", "unhurriedly", "hesitant", "hesitantly"]):
        speed = 0.6

    # 4. Match Amplitude (default 1.0)
    amplitude = 1.0
    if _has_word(["high", "huge", "big", "hard", "powerful", "powerfully", "strong", "strongly",
                  "intense", "intensely", "furiously", "wildly", "furious", "wild", "deep", "deeply",
                  "great", "greatly", "maximum", "max", "massive", "forceful", "forcefully",
                  "heavy", "heavily", "vigorous", "vigorously", "explosive", "explosively", "fierce", "fiercely"]):
        amplitude = 1.4
    elif _has_word(["small", "soft", "softly", "light", "lightly", "tiny", "subtle", "subtly",
                    "gentle", "gently", "slight", "slightly", "shallow", "mild", "mildly",
                    "cautious", "cautiously", "faint", "faintly", "low", "minimal", "delicate", "delicately"]):
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
