"""Generates slideshow still-image ideas from an EpisodeManifest.

Strategy (chosen by user):
- Auto by duration: 1 still per ~3s -> n = ceil(duration / 3), clamped to 2..3.
- Style: cinematic photorealistic.
- Unlike the S2P video compiler (which quarantines appearance traits),
  image prompts DELIBERATELY embed full character visual summaries so a
  still-image model reproduces likeness without reference-entity binding.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

from src.models import EpisodeManifest
from src.storyboard.characters import CharacterPhotoResolver
from src.storyboard.models import StillImageIdea, StoryboardScene, StoryboardDocument


STYLE_SUFFIXES: dict[str, str] = {
    "cinematic_photorealistic": (
        "cinematic photorealistic film still, natural skin texture, "
        "high dynamic range, 8k detail, vertical 9:16 composition"
    ),
    "pixar_3d": (
        "3D Pixar-style animation still, soft subsurface scattering, "
        "expressive characters, vibrant clean shapes, vertical 9:16 composition"
    ),
    "storybook": (
        "warm storybook illustration, soft watercolor texture, cozy lighting, "
        "vertical 9:16 composition"
    ),
}

NEGATIVE_PROMPT_DEFAULT = (
    "cartoon, anime, blurry, distorted face, extra limbs, deformed hands, "
    "text, watermark, logo, oversaturated, low-res"
)

PHASE_MOOD: dict[str, str] = {
    "hook": "urgent, drought-stricken tension, immediate curiosity",
    "rising_tension": "mounting urgency, restless energy",
    "complication": "awe mixed with dread, stakes escalating",
    "climax_twist": "peak wonder and explosive energy",
    "cliffhanger_loop": "ominous dread, unresolved peril",
}

PHASE_LIGHTING: dict[str, str] = {
    "hook": "harsh blazing golden-hour sunlight, deep cracked-earth shadows",
    "rising_tension": "bright dusty daylight with flying dust motes",
    "complication": "soft emerald glow mixing with warm sunlight on faces",
    "climax_twist": "radiant golden-green magical bloom light bursting overhead",
    "cliffhanger_loop": "eerie blue subterranean glow cutting through dust",
}

SHOT_PROGRESSION: dict[int, list[tuple[str, str]]] = {
    # n -> [(shot_type, focus_hint)]
    2: [
        ("Wide establishing", "opening composition, where everyone is"),
        ("Close emotional beat", "reaction detail, payoff into next scene"),
    ],
    3: [
        ("Wide establishing", "opening composition, spatial context"),
        ("Medium action", "core physical action peak"),
        ("Macro close-up / reaction", "emotional payoff detail, eyes/hands/light"),
    ],
}


def still_count_for_duration(duration: float) -> int:
    """Auto rule: 1 still per ~3s, clamped to 2..3 per scene."""
    n = int(math.ceil(max(0.1, duration) / 3.0))
    return max(2, min(3, n))


class StoryboardGenerator:
    """Builds a StoryboardDocument from an EpisodeManifest + character photos."""

    def __init__(
        self,
        characters_dir: str | Path | None = None,
        style: str = "cinematic_photorealistic",
    ) -> None:
        self.style = style if style in STYLE_SUFFIXES else "cinematic_photorealistic"
        self.resolver: Optional[CharacterPhotoResolver] = None
        if characters_dir is not None:
            self.resolver = CharacterPhotoResolver(characters_dir)

    def generate(self, manifest: EpisodeManifest) -> StoryboardDocument:
        visuals = {p.name: p.visual_summary for p in manifest.character_profiles}
        # Location summary used as shared environment grounding
        location_summary = next(
            (
                p.visual_summary
                for p in manifest.character_profiles
                if p.entity_type.value == "location"
            ),
            "",
        )
        char_names = sorted({c for s in manifest.scenes for c in s.bound_characters})
        photos: dict[str, list[str]] = {}
        if self.resolver is not None:
            photos = self.resolver.resolve_all(char_names)
        else:
            photos = {n: [] for n in char_names}

        sb_scenes: list[StoryboardScene] = []
        for scene in manifest.scenes:
            n = still_count_for_duration(scene.duration)
            progression = SHOT_PROGRESSION[n]
            seg = scene.duration / n
            stills: list[StillImageIdea] = []
            for k in range(n):
                t0 = round(scene.time_start + k * seg, 2)
                t1 = round(scene.time_start + (k + 1) * seg, 2)
                shot_type, focus_hint = progression[k]
                focus = self._focus_for_keyframe(scene, k, n, focus_hint)
                prompt = self._compose_prompt(
                    scene_index=scene.scene_index,
                    shot_type=shot_type,
                    focus=focus,
                    scene=scene,
                    visuals=visuals,
                    location_summary=location_summary,
                )
                hold = round(t1 - t0, 2)
                stills.append(
                    StillImageIdea(
                        image_index=k,
                        label=f"S{scene.scene_index + 1}-IMG{k + 1}",
                        time_start=t0,
                        time_end=t1,
                        shot_type=shot_type,
                        focus=focus,
                        image_prompt=prompt,
                        negative_prompt=NEGATIVE_PROMPT_DEFAULT,
                        hold_seconds=hold,
                        transition="cross-dissolve",
                        motion_hint=self._motion_hint(shot_type),
                    )
                )
            sb_scenes.append(
                StoryboardScene(
                    scene_index=scene.scene_index,
                    time_start=scene.time_start,
                    time_end=scene.time_end,
                    duration=round(scene.duration, 2),
                    phase=scene.phase.value if hasattr(scene.phase, "value") else str(scene.phase),
                    narration=scene.narration or "",
                    dialogue_speaker=scene.dialogue.speaker if scene.dialogue else None,
                    dialogue_text=scene.dialogue.text if scene.dialogue else None,
                    dialogue_emotion=scene.dialogue.emotion if scene.dialogue else None,
                    action_prompt=scene.action_prompt,
                    video_prompt=scene.video_prompt,
                    camera_directive=scene.camera_directive,
                    bound_characters=list(scene.bound_characters),
                    stills=stills,
                )
            )

        return StoryboardDocument(
            series_id=manifest.series_id,
            episode_num=manifest.episode_num,
            title=manifest.title,
            target_duration=manifest.target_duration,
            actual_duration=manifest.actual_duration,
            style=self.style,
            cliffhanger=manifest.cliffhanger,
            next_episode_hook=manifest.next_episode_hook,
            character_visuals=visuals,
            character_photos=photos,
            scenes=sb_scenes,
        )

    # -- internals ------------------------------------------------------

    def _focus_for_keyframe(self, scene, k: int, n: int, hint: str) -> str:
        base = scene.action_prompt.strip().rstrip(".")
        if n == 2:
            if k == 0:
                return f"Opening: {base}. ({hint})"
            return f"Payoff: {base} — faces/hands reacting, leading into next cut. ({hint})"
        # n == 3
        if k == 0:
            return f"Opening: {base}. ({hint})"
        if k == 1:
            return f"Peak action: {scene.video_prompt.strip()} ({hint})"
        last = f"Detail payoff: {base} — tight on eyes, hands, or glowing object. ({hint})"
        if scene.dialogue:
            last += f" {scene.dialogue.speaker} says: '{scene.dialogue.text}' ({scene.dialogue.emotion})."
        return last

    def _motion_hint(self, shot_type: str) -> str:
        st = shot_type.lower()
        if "wide" in st:
            return "Slow push-in (100% -> 108%) over hold duration"
        if "medium" in st:
            return "Subtle left-to-right pan + 105% zoom (Ken Burns)"
        return "Static hold with 103% micro-zoom into eyes/object"

    def _compose_prompt(
        self,
        scene_index: int,
        shot_type: str,
        focus: str,
        scene,
        visuals: dict[str, str],
        location_summary: str,
    ) -> str:
        phase_key = scene.phase.value if hasattr(scene.phase, "value") else str(scene.phase)
        char_block = self._character_block(scene.bound_characters, visuals)
        mood = PHASE_MOOD.get(phase_key, "emotional pastoral drama")
        lighting = PHASE_LIGHTING.get(phase_key, "warm natural daylight, soft shadows")
        camera = (scene.camera_directive or "ground-level cinematic framing").strip().rstrip(".")
        style_suffix = STYLE_SUFFIXES[self.style]
        env = location_summary.strip().rstrip(".") if location_summary else "dry pastoral farm at golden hour"

        parts = [
            f"{style_suffix}",
            f"{shot_type} shot, Scene {scene_index + 1}",
            f"Action: {focus}",
            f"Characters: {char_block}" if char_block else "",
            f"Setting: {env}",
            f"Lighting: {lighting}",
            f"Camera: {camera}, shallow depth of field on subjects",
            f"Mood: {mood}",
            "Consistent character likeness, no text, no watermark, no logo",
        ]
        return ". ".join(p for p in parts if p) + "."

    def _character_block(self, bound: list[str], visuals: dict[str, str]) -> str:
        chunks: list[str] = []
        for name in bound:
            summary = visuals.get(name, "").strip().rstrip(".")
            if summary:
                chunks.append(f"{name} ({summary})")
            else:
                chunks.append(name)
        if not chunks:
            return ""
        if len(chunks) == 1:
            return chunks[0]
        return " and ".join([", ".join(chunks[:-1]), chunks[-1]])
