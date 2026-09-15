"""Mathematical Pacing Budgeter and timing validator for 30-60s vertical shorts."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from src.models import EngagementPhase, SceneBeat, _count_words


class PacingRhythm(str, Enum):
    """Directorial pacing rhythms dictating tension, cut frequency, and shot durations."""
    PULSE_ACTION = "pulse_action"         # Accelerating cuts, staccato tension buildup
    NOIR_SUSPENSE = "noir_suspense"       # Deliberate atmospheric holds punctuated by sudden shock
    VIRAL_REVELATION = "viral_revelation" # Rapid hook, gradual tension, explosive twist
    COMEDIC_SNAPPY = "comedic_snappy"     # Staccato banter, rhythmic comedic syncopation


class PacingBudgeter:
    """Calculates strict word budgets, validates 140-160 WPM verbal pacing, and allocates scene cut timestamps."""

    MIN_WPM: float = 140.0
    TARGET_WPM: float = 150.0
    MAX_WPM: float = 160.0

    # Tolerance bounds for validation edge cases
    TOLERANCE_MIN_WPM: float = 135.0
    TOLERANCE_MAX_WPM: float = 165.0

    MIN_DURATION: float = 30.0
    MAX_DURATION: float = 60.0

    # Non-linear phase weight ratios by rhythm
    RHYTHM_PHASE_WEIGHTS: dict[PacingRhythm, dict[EngagementPhase, float]] = {
        PacingRhythm.PULSE_ACTION: {
            EngagementPhase.RISING_TENSION: 0.24,
            EngagementPhase.COMPLICATION: 0.42,
            EngagementPhase.CLIMAX_TWIST: 0.19,
            EngagementPhase.CLIFFHANGER_LOOP: 0.15,
        },
        PacingRhythm.NOIR_SUSPENSE: {
            EngagementPhase.RISING_TENSION: 0.27,
            EngagementPhase.COMPLICATION: 0.38,
            EngagementPhase.CLIMAX_TWIST: 0.20,
            EngagementPhase.CLIFFHANGER_LOOP: 0.15,
        },
        PacingRhythm.VIRAL_REVELATION: {
            EngagementPhase.RISING_TENSION: 0.22,
            EngagementPhase.COMPLICATION: 0.38,
            EngagementPhase.CLIMAX_TWIST: 0.25,
            EngagementPhase.CLIFFHANGER_LOOP: 0.15,
        },
        PacingRhythm.COMEDIC_SNAPPY: {
            EngagementPhase.RISING_TENSION: 0.25,
            EngagementPhase.COMPLICATION: 0.35,
            EngagementPhase.CLIMAX_TWIST: 0.25,
            EngagementPhase.CLIFFHANGER_LOOP: 0.15,
        },
    }

    @classmethod
    def count_words(cls, text: str) -> int:
        """Accurately counts words in verbal script text."""
        return _count_words(text)

    @classmethod
    def calculate_word_budget(cls, duration_seconds: float) -> tuple[int, int, int]:
        """Returns (min_words, target_words, max_words) for a given duration in seconds."""
        if not (cls.MIN_DURATION <= duration_seconds <= cls.MAX_DURATION):
            raise ValueError(f"Duration {duration_seconds}s must be within [{cls.MIN_DURATION}, {cls.MAX_DURATION}]s")

        min_words = int(round((cls.MIN_WPM / 60.0) * duration_seconds))
        target_words = int(round((cls.TARGET_WPM / 60.0) * duration_seconds))
        max_words = int(round((cls.MAX_WPM / 60.0) * duration_seconds))
        return min_words, target_words, max_words

    @classmethod
    def validate_narration_pacing(
        cls, text: str, duration_seconds: float, strict: bool = True
    ) -> tuple[bool, float, str]:
        """Validates if narration text satisfies WPM bounds for the given duration."""
        if duration_seconds <= 0:
            return False, 0.0, "Duration must be greater than zero"

        words = cls.count_words(text)
        wpm = round((words / duration_seconds) * 60.0, 1)

        low = cls.MIN_WPM if strict else cls.TOLERANCE_MIN_WPM
        high = cls.MAX_WPM if strict else cls.TOLERANCE_MAX_WPM

        if wpm < low:
            return (
                False,
                wpm,
                f"Narration pacing too sluggish ({wpm} WPM < {low} WPM). Word count: {words} words for {duration_seconds:.1f}s.",
            )
        if wpm > high:
            return (
                False,
                wpm,
                f"Narration pacing too hurried ({wpm} WPM > {high} WPM). Word count: {words} words for {duration_seconds:.1f}s.",
            )

        return True, wpm, f"Optimal pacing ({wpm} WPM) within [{low}, {high}]."

    @classmethod
    def calculate_phase_allocations(
        cls,
        target_duration: float,
        rhythm: PacingRhythm = PacingRhythm.PULSE_ACTION,
    ) -> dict[EngagementPhase, dict[str, float]]:
        """Allocates time windows for the 5-phase retention arc across target_duration (30-60s)."""
        if not (cls.MIN_DURATION <= target_duration <= cls.MAX_DURATION):
            raise ValueError(f"target_duration {target_duration}s must be in [{cls.MIN_DURATION}, {cls.MAX_DURATION}]s")

        # Phase 1: Hook is strictly 0.0s to 3.0s (3.0s duration)
        hook_dur = 3.0
        remaining = target_duration - hook_dur

        # Use rhythm-specific weighting ratios
        weights = cls.RHYTHM_PHASE_WEIGHTS.get(rhythm, cls.RHYTHM_PHASE_WEIGHTS[PacingRhythm.PULSE_ACTION])
        rising_dur = round(remaining * weights[EngagementPhase.RISING_TENSION], 1)
        complication_dur = round(remaining * weights[EngagementPhase.COMPLICATION], 1)
        climax_dur = round(remaining * weights[EngagementPhase.CLIMAX_TWIST], 1)
        cliffhanger_dur = round(target_duration - (hook_dur + rising_dur + complication_dur + climax_dur), 1)

        t0 = 0.0
        t1 = hook_dur
        t2 = round(t1 + rising_dur, 1)
        t3 = round(t2 + complication_dur, 1)
        t4 = round(t3 + climax_dur, 1)
        t5 = round(target_duration, 1)

        return {
            EngagementPhase.HOOK: {"start": t0, "end": t1, "duration": round(t1 - t0, 1)},
            EngagementPhase.RISING_TENSION: {"start": t1, "end": t2, "duration": round(t2 - t1, 1)},
            EngagementPhase.COMPLICATION: {"start": t2, "end": t3, "duration": round(t3 - t2, 1)},
            EngagementPhase.CLIMAX_TWIST: {"start": t3, "end": t4, "duration": round(t4 - t3, 1)},
            EngagementPhase.CLIFFHANGER_LOOP: {"start": t4, "end": t5, "duration": round(t5 - t4, 1)},
        }

    @classmethod
    def _get_subscene_weights(cls, n_scenes: int, rhythm: PacingRhythm) -> list[float]:
        """Calculates non-linear duration curves across sub-scenes in a phase."""
        if n_scenes <= 1:
            return [1.0]

        if rhythm == PacingRhythm.PULSE_ACTION:
            # Accelerating cuts from setup to staccato climax
            if n_scenes == 2:
                return [1.15, 0.85]
            elif n_scenes == 3:
                return [1.25, 1.0, 0.75]
            elif n_scenes == 4:
                return [1.3, 1.1, 0.9, 0.7]
            else:
                step = 0.6 / (n_scenes - 1)
                return [1.3 - (i * step) for i in range(n_scenes)]

        elif rhythm == PacingRhythm.NOIR_SUSPENSE:
            # Atmospheric holds punctuated by sudden shock
            if n_scenes == 2:
                return [0.9, 1.1]
            elif n_scenes == 3:
                return [1.15, 1.1, 0.75]
            elif n_scenes == 4:
                return [1.1, 1.2, 1.0, 0.7]
            else:
                return [1.0] * n_scenes

        elif rhythm == PacingRhythm.VIRAL_REVELATION:
            # Rapid hook, build, sudden drop
            if n_scenes == 2:
                return [0.85, 1.15]
            elif n_scenes == 3:
                return [0.85, 1.25, 0.9]
            else:
                return [1.0] * n_scenes

        else:  # COMEDIC_SNAPPY
            if n_scenes == 2:
                return [1.0, 1.0]
            elif n_scenes == 3:
                return [1.05, 0.95, 1.0]
            else:
                return [1.0] * n_scenes

    @classmethod
    def generate_scene_timeline(
        cls,
        target_duration: float,
        scene_counts: Optional[dict[EngagementPhase, int]] = None,
        rhythm: PacingRhythm = PacingRhythm.PULSE_ACTION,
    ) -> list[dict[str, Any]]:
        """Generates explicit scene cut timestamps with non-linear duration curves."""
        phase_allocs = cls.calculate_phase_allocations(target_duration, rhythm=rhythm)

        default_counts: dict[EngagementPhase, int]
        if target_duration <= 35.0:
            default_counts = {
                EngagementPhase.HOOK: 1,
                EngagementPhase.RISING_TENSION: 1,
                EngagementPhase.COMPLICATION: 2,
                EngagementPhase.CLIMAX_TWIST: 1,
                EngagementPhase.CLIFFHANGER_LOOP: 1,
            }
        elif target_duration <= 50.0:
            default_counts = {
                EngagementPhase.HOOK: 1,
                EngagementPhase.RISING_TENSION: 2,
                EngagementPhase.COMPLICATION: 3,
                EngagementPhase.CLIMAX_TWIST: 2,
                EngagementPhase.CLIFFHANGER_LOOP: 1,
            }
        else:
            default_counts = {
                EngagementPhase.HOOK: 1,
                EngagementPhase.RISING_TENSION: 3,
                EngagementPhase.COMPLICATION: 4,
                EngagementPhase.CLIMAX_TWIST: 3,
                EngagementPhase.CLIFFHANGER_LOOP: 2,
            }

        counts = scene_counts or default_counts

        scenes: list[dict[str, Any]] = []
        global_scene_idx = 0

        for phase in [
            EngagementPhase.HOOK,
            EngagementPhase.RISING_TENSION,
            EngagementPhase.COMPLICATION,
            EngagementPhase.CLIMAX_TWIST,
            EngagementPhase.CLIFFHANGER_LOOP,
        ]:
            alloc = phase_allocs[phase]
            p_start = alloc["start"]
            p_end = alloc["end"]
            p_dur = alloc["duration"]
            n_scenes = max(1, counts.get(phase, 1))

            raw_weights = cls._get_subscene_weights(n_scenes, rhythm)
            weight_sum = sum(raw_weights)
            sub_durs = [round(p_dur * (w / weight_sum), 2) for w in raw_weights]
            # Absorb minor rounding discrepancy into the last subscene of the phase
            discrepancy = round(p_dur - sum(sub_durs), 2)
            sub_durs[-1] = round(sub_durs[-1] + discrepancy, 2)

            curr_t = p_start
            for s_idx in range(n_scenes):
                dur = sub_durs[s_idx]
                s_start = round(curr_t, 2)
                s_end = round(curr_t + dur, 2) if s_idx < n_scenes - 1 else round(p_end, 2)
                dur = round(s_end - s_start, 2)
                curr_t = s_end

                target_words = max(1, int(round((cls.TARGET_WPM / 60.0) * dur)))
                min_words = max(1, int(round((cls.MIN_WPM / 60.0) * dur)))
                max_words = max(target_words, int(round((cls.MAX_WPM / 60.0) * dur)))

                scenes.append({
                    "scene_index": global_scene_idx,
                    "phase": phase,
                    "time_start": s_start,
                    "time_end": s_end,
                    "duration": dur,
                    "target_words": target_words,
                    "min_words": min_words,
                    "max_words": max_words,
                })
                global_scene_idx += 1

        return scenes

    @classmethod
    def adjust_narration_syntactically(
        cls, text: str, duration: float, target_wpm: float = 150.0
    ) -> str:
        """Calibrates verbal text to satisfy pacing limits without dumb truncation or canned fillers.
        
        Applies grammatical pruning of non-essential adverbs if hurried,
        and avoids spammy filler phrases or amputated ellipsis mid-thought.
        """
        words = text.strip().split()
        if not words:
            return "The silence carries a heavy, unspoken truth."

        current_count = cls.count_words(text)
        current_wpm = (current_count / duration) * 60.0 if duration > 0 else 0.0

        # If within natural speech tolerance bounds [135.0, 165.0], preserve authentic prose
        if cls.TOLERANCE_MIN_WPM <= current_wpm <= cls.TOLERANCE_MAX_WPM:
            return text

        # If too hurried (> 165 WPM), perform intelligent syntactic compression
        if current_wpm > cls.TOLERANCE_MAX_WPM:
            prunable_adverbs = [
                r"\b(very|actually|simply|completely|furiously|cautiously|slowly|desperately|intently|gradually|ominously|just|really)\b\s*",
                r"\b(suddenly|quickly|quietly|carefully)\b\s*",
            ]
            compressed = text
            for pat in prunable_adverbs:
                compressed = re.sub(pat, "", compressed, flags=re.IGNORECASE).strip()
                compressed = re.sub(r"\s+", " ", compressed)
                comp_wpm = (cls.count_words(compressed) / duration) * 60.0
                if comp_wpm <= cls.TOLERANCE_MAX_WPM:
                    return compressed

            # If still slightly hurried, verify clean ending punctuation, NEVER ellipsis
            if not compressed.endswith((".", "!", "?")):
                compressed += "."
            return compressed

        # If below tolerance (< 135 WPM), preserve prose genuinely without spammy canned fillers
        return text

    @classmethod
    def validate_episode_pacing(cls, scenes: list[SceneBeat], target_duration: float) -> tuple[bool, list[str]]:
        """Validates all scenes in an episode for timestamp continuity, total duration, and overall WPM."""
        errors: list[str] = []
        if not scenes:
            return False, ["Episode has no scenes"]

        # Check timestamp continuity
        if scenes[0].time_start != 0.0:
            errors.append(f"First scene must start at 0.0s, got {scenes[0].time_start}s")

        for i in range(len(scenes) - 1):
            curr_s = scenes[i]
            next_s = scenes[i + 1]
            if abs(curr_s.time_end - next_s.time_start) > 0.05:
                errors.append(
                    f"Timestamp discontinuity between scene {curr_s.scene_index} (end {curr_s.time_end}s) and scene {next_s.scene_index} (start {next_s.time_start}s)"
                )

        total_duration = scenes[-1].time_end
        if abs(total_duration - target_duration) > 1.5:
            errors.append(f"Total duration {total_duration:.2f}s diverges from target {target_duration:.2f}s by >1.5s")

        total_words = sum(s.word_count for s in scenes)
        overall_wpm = round((total_words / total_duration) * 60.0, 1) if total_duration > 0 else 0.0

        if not (cls.TOLERANCE_MIN_WPM <= overall_wpm <= cls.TOLERANCE_MAX_WPM):
            errors.append(
                f"Overall episode WPM {overall_wpm} outside tolerance [{cls.TOLERANCE_MIN_WPM}, {cls.TOLERANCE_MAX_WPM}]. Total words: {total_words} over {total_duration:.1f}s."
            )

        return len(errors) == 0, errors
