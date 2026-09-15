"""S2P (Story-to-Prompt) Prompt Decoupling Compiler for FlowKit and Google Flow (Veo)."""

from __future__ import annotations

import re
from typing import Any, Optional

from src.models import CharacterProfile, DialogueLine


class DecouplingGuard:
    """Universal Dynamic N-Gram Attribute Quarantine Guard.
    
    Prevents semantic cross-attention collision in generative video models (Google Flow / Veo)
    by strictly separating intrinsic physical, biometric, and attire attributes (isolated in FlowKit
    reference entities) from extrinsic situational action, lighting, and camera directives.
    """

    FORBIDDEN_ANATOMICAL_CATEGORIES: dict[str, list[str]] = {
        "hair": [
            "hair", "cut", "bob", "curly", "straight", "blonde", "brunette", "braided",
            "bald", "ponytail", "silver-streaked", "dark hair", "blonde hair", "black hair",
            "brown hair", "grey hair", "gray hair", "asymmetrical dark bob", "asymmetrical bob",
        ],
        "eyes": [
            "eyes", "iris", "pupils", "hazel", "blue-eyed", "brown-eyed", "green-eyed",
            "grey eyes", "gray eyes", "blue eyes", "brown eyes", "green eyes",
            "contact lenses", "ar contact lenses", "wire-rimmed glasses",
        ],
        "facial": [
            "stubble", "beard", "mustache", "goatee", "wrinkles", "scar", "jaw",
            "cheekbones", "complexion", "freckles", "square jaw", "facial scar",
            "salt-and-pepper", "salt-and-pepper stubble",
        ],
        "attire": [
            "coat", "jacket", "fedora", "hat", "glasses", "vest", "suit", "hoodie",
            "boots", "shirt", "gloves", "armor", "trench coat", "leather jacket",
            "round glasses", "tailored suit", "velvet tailored suit", "signet ring",
            "tactical vest", "cyber-tactical vest", "graphite trench coat", "charcoal fedora",
        ],
        "build": [
            "tall", "slender", "muscular", "short", "heavy-set", "stocky", "frail", "rugged",
        ],
    }

    FORBIDDEN_GENERIC_TERMS: list[str] = [
        "facial features",
        "has blue eyes",
        "has brown eyes",
        "has green eyes",
        "with blonde hair",
        "with brown hair",
        "with black hair",
        "character design",
        "concept art",
        "character model",
    ]

    @classmethod
    def _extract_ngrams(cls, text: str, max_n: int = 3) -> list[str]:
        """Extracts 1-gram, 2-gram, and 3-gram candidate tokens from text."""
        cleaned = re.sub(r"[^\w\s-]", " ", text.lower())
        words = [w.strip("-") for w in cleaned.split() if len(w.strip("-")) >= 3]

        ngrams: list[str] = []
        # 1-grams
        for w in words:
            if len(w) >= 3:
                ngrams.append(w)
        # 2-grams
        for i in range(len(words) - 1):
            ngrams.append(f"{words[i]} {words[i+1]}")
        # 3-grams
        for i in range(len(words) - 2):
            ngrams.append(f"{words[i]} {words[i+1]} {words[i+2]}")

        return ngrams

    @classmethod
    def validate_prompt(
        cls, prompt: str, bound_profiles: list[CharacterProfile]
    ) -> tuple[bool, list[str]]:
        """Validates that a scene prompt does not leak permanent physical or attire traits."""
        warnings: list[str] = []
        lower_prompt = prompt.lower()

        # Check generic forbidden terms
        for term in cls.FORBIDDEN_GENERIC_TERMS:
            if term in lower_prompt:
                warnings.append(f"Prompt contains redundant physical description term '{term}'")

        # Aggregate category lookup sets
        all_category_terms: set[str] = set()
        for cat_list in cls.FORBIDDEN_ANATOMICAL_CATEGORIES.values():
            for t in cat_list:
                all_category_terms.add(t.lower())

        for profile in bound_profiles:
            profile_ngrams = cls._extract_ngrams(profile.visual_summary)

            candidate_traits: set[str] = set()
            for token in profile_ngrams:
                if token in all_category_terms:
                    candidate_traits.add(token)
                else:
                    # If any category word is in this n-gram, candidate trait
                    words_in_token = token.split()
                    for cat_term in all_category_terms:
                        if cat_term in words_in_token or cat_term == token:
                            candidate_traits.add(token)
                            candidate_traits.add(cat_term)

            detected_leaks: set[str] = set()
            # Check longest candidate traits first
            for trait in sorted(candidate_traits, key=len, reverse=True):
                # Avoid substring duplicates (e.g. if 'trench coat' is flagged, don't also flag 'coat')
                if any(trait in d for d in detected_leaks):
                    continue
                pattern = rf"\b{re.escape(trait)}\b"
                if re.search(pattern, lower_prompt):
                    detected_leaks.add(trait)
                    warnings.append(
                        f"CRITICAL PROMPT LEAK: Permanent trait '{trait}' from profile [{profile.name}] "
                        f"leaked into scene prompt! Physical traits must be quarantined in the reference profile."
                    )

        return len(warnings) == 0, warnings


class PromptCompiler:
    """Compiles narrative scene descriptions into decoupled visual and sub-clip timed prompts.
    
    Prevents semantic cross-attention collision by strictly separating intrinsic character
    attributes (delegated to FlowKit reference entities) from extrinsic situational actions,
    environment, lighting, and camera directives.
    """

    FORBIDDEN_LEAKAGE_TERMS = DecouplingGuard.FORBIDDEN_GENERIC_TERMS

    @classmethod
    def isolate_character_appearance(cls, profile: CharacterProfile) -> dict[str, Any]:
        """Extracts the intrinsic physical reference payload for FlowKit /characters registration."""
        return profile.to_flowkit_entity()

    @classmethod
    def bind_entity_tokens(cls, text: str, bound_characters: list[str]) -> str:
        """Ensures all bound character names are formatted as bound reference entity tokens e.g. [Detective Rex Vance]."""
        if not text or not bound_characters:
            return text or ""

        result = text
        # Sort descending by length so longer names match before substrings
        sorted_chars = sorted(bound_characters, key=len, reverse=True)
        for char_name in sorted_chars:
            if not char_name:
                continue
            # Split by existing bracketed tokens so we never match inside [...]
            parts = re.split(r"(\[[^\]]*\])", result)
            pattern = re.compile(rf"\b{re.escape(char_name)}\b", re.IGNORECASE)
            for i in range(0, len(parts), 2):  # even indices are outside brackets
                parts[i] = pattern.sub(f"[{char_name}]", parts[i])
            result = "".join(parts)

        return result

    @classmethod
    def generate_subclip_timeline(
        cls,
        time_start: float,
        time_end: float,
        action_beats: list[tuple[float, float, str]],
        bound_characters: list[str],
    ) -> str:
        """Generates sub-clip timed action prompt syntax e.g. '0-2s: [Rex] turns... 2-4s: [Rex] dashes...'."""
        duration = round(time_end - time_start, 2)
        if not action_beats:
            half = round(duration / 2.0, 1)
            token = f"[{bound_characters[0]}]" if bound_characters else "Subject"
            return f"0-{half}s: {token} initiates focused action; {half}-{duration}s: dynamic camera follows sudden movement"

        timeline_parts: list[str] = []
        for b_start, b_end, b_action in action_beats:
            bound_action = cls.bind_entity_tokens(b_action, bound_characters)
            timeline_parts.append(f"{b_start:.1f}-{b_end:.1f}s: {bound_action}")

        return "; ".join(timeline_parts)

    @classmethod
    def compile_scene_prompts(
        cls,
        situational_action: str,
        duration: float,
        bound_characters: list[str],
        camera_directive: Optional[str] = None,
        environment: Optional[str] = None,
        dialogue: Optional[DialogueLine] = None,
    ) -> tuple[str, str]:
        """Compiles decoupled (action_prompt, video_prompt) for a scene.
        
        Enforces strict bijectivity: every character in bound_characters must have an explicit
        action directive in situational_action. For pure environmental cutaways, bound_characters
        must be empty [].
        """
        bound_action = cls.bind_entity_tokens(situational_action, bound_characters)

        # Enforce strict bijectivity: every character in bound_characters must have an explicit action directive
        if bound_characters:
            missing_chars = [c for c in bound_characters if f"[{c}]" not in bound_action]
            if missing_chars:
                raise ValueError(
                    f"Directorial Staging Violation: Bound character(s) {missing_chars} have no explicit action "
                    f"directive in situational action: '{situational_action}'. Every bound character must actively "
                    f"perform or participate in the scene."
                )

        # Build Frame 0 Action Prompt
        elements: list[str] = [bound_action]
        if environment:
            elements.append(f"Environment: {environment}")
        if camera_directive:
            elements.append(f"Cinematography: {camera_directive}")
        elements.append("Lighting: High dynamic range, cinematic color grading, vertical 9:16 composition")

        action_prompt = ". ".join(elements) + "."

        # Build Sub-clip Video Prompt
        mid = round(duration / 2.0, 1)
        camera_part = camera_directive or "Dynamic tracking push-in shot"
        subclip_action1 = f"{bound_action}"

        if dialogue and dialogue.speaker:
            speaker_token = f"[{dialogue.speaker}]"
            emotion_lower = dialogue.emotion.lower()
            if "whisper" in emotion_lower:
                speech_verb = "whispers"
            elif "shout" in emotion_lower or "yell" in emotion_lower:
                speech_verb = "shouts"
            elif "snarl" in emotion_lower or "growl" in emotion_lower:
                speech_verb = "snarls"
            elif "cold" in emotion_lower:
                speech_verb = "says coldly"
            elif "urgent" in emotion_lower or "panick" in emotion_lower:
                speech_verb = "urgently says"
            else:
                speech_verb = "says"

            subclip_action2 = (
                f"{speaker_token} {speech_verb}: '{dialogue.text}'. "
                f"Camera executes {camera_part.lower()}, capturing heightened emotional reaction and continuous motion"
            )
        else:
            subclip_action2 = (
                f"Camera executes {camera_part.lower()}, "
                f"capturing heightened emotional reaction and continuous motion"
            )

        video_prompt = f"0-{mid}s: {subclip_action1}; {mid}-{duration:.1f}s: {subclip_action2}."

        return action_prompt, video_prompt

    @classmethod
    def validate_decoupled_prompt(
        cls, prompt: str, bound_profiles: list[CharacterProfile]
    ) -> tuple[bool, list[str]]:
        """Validates that a scene prompt does not leak permanent physical attributes that collide with reference entities."""
        return DecouplingGuard.validate_prompt(prompt, bound_profiles)
