"""Read image prompts and exact per-still timing out of a storyboard manifest.

Two input shapes exist in ``shorts_content_engine``:

- ``output/storyboards/<ep>_storyboard.json`` — the richer one. Each scene carries
  ``stills[]``, and each still has a full ``image_prompt`` plus ``hold_seconds``.
  For episode 1 that is 17 stills whose holds sum to exactly 45.0s.
- ``output/manifests/<ep>.json`` — one prompt per scene (``action_prompt``), no
  per-still breakdown. Supported as a fallback: one still per scene, held for the
  scene's own duration.

Why the timing is carried through rather than collapsed
-------------------------------------------------------
AutoShorts' ``video_clip_duration`` is a single ``int`` applied to every material,
so the pipeline cannot express per-still holds on its own. The holds here are not
uniform (2.33s to 3.0s on episode 1). Rounding them all to 3s yields 51s of
material for a 45s narration, and ``combine_videos`` stops as soon as the required
duration is covered — so the final stills would silently never appear, and every
scene boundary would drift against the narration. Carrying the real durations
through lets the bridge pre-render each still at its exact length instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)


class StoryboardError(RuntimeError):
    """The manifest could not be read or contained no usable prompts."""


@dataclass(frozen=True)
class StoryboardStill:
    """One still to generate, with the timing the storyboard asked for."""

    label: str
    image_prompt: str
    hold_seconds: float
    shot_type: str = ""
    scene_index: int = 0
    transition: str = ""
    motion_hint: str = ""
    negative_prompt: str = ""

    def __post_init__(self) -> None:
        if not (self.image_prompt or "").strip():
            raise StoryboardError(f"still {self.label!r} has an empty image prompt")
        if self.hold_seconds <= 0:
            raise StoryboardError(f"still {self.label!r} has a non-positive hold: {self.hold_seconds}")


@dataclass
class Storyboard:
    """A parsed storyboard, ready to drive image generation."""

    title: str
    stills: list[StoryboardStill] = field(default_factory=list)
    series_id: str = ""
    episode_num: int = 0
    style: str = ""
    source_path: str = ""
    narration: list[str] = field(default_factory=list)
    """Per-scene narration, in scene order."""

    @property
    def script(self) -> str:
        """The full narration as one string, for ``VideoParams.video_script``.

        Supplying this matters: with an empty script AutoShorts generates its own
        from an LLM, and the wording then has nothing to do with the storyboard
        the stills were drawn from — the visuals and the voiceover drift apart.
        """
        return " ".join(part.strip() for part in self.narration if part and part.strip())

    @property
    def total_hold_seconds(self) -> float:
        return round(sum(s.hold_seconds for s in self.stills), 4)

    @property
    def has_uniform_holds(self) -> bool:
        """True when every still shares one hold, within a 10ms tolerance."""
        if not self.stills:
            return True
        first = self.stills[0].hold_seconds
        return all(abs(s.hold_seconds - first) < 0.01 for s in self.stills)

    def prompts(self) -> list[str]:
        return [s.image_prompt for s in self.stills]

    def holds(self) -> list[float]:
        return [s.hold_seconds for s in self.stills]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StoryboardError(f"storyboard not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StoryboardError(f"storyboard is not valid JSON: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise StoryboardError(f"storyboard root must be an object: {path}")
    return payload


def _stills_from_storyboard(payload: dict[str, Any]) -> list[StoryboardStill]:
    stills: list[StoryboardStill] = []
    for scene in payload.get("scenes") or []:
        scene_index = int(scene.get("scene_index", len(stills)))
        for still in scene.get("stills") or []:
            hold = still.get("hold_seconds")
            if hold is None:
                # Fall back to the slice of the scene this still covers.
                start = still.get("time_start")
                end = still.get("time_end")
                if start is not None and end is not None:
                    hold = float(end) - float(start)
            if hold is None:
                raise StoryboardError(
                    f"still {still.get('label')!r} has neither hold_seconds nor a time range"
                )
            stills.append(
                StoryboardStill(
                    label=str(still.get("label") or f"S{scene_index}-IMG{len(stills)}"),
                    image_prompt=str(still.get("image_prompt") or ""),
                    hold_seconds=float(hold),
                    shot_type=str(still.get("shot_type") or ""),
                    scene_index=scene_index,
                    transition=str(still.get("transition") or ""),
                    motion_hint=str(still.get("motion_hint") or ""),
                    negative_prompt=str(still.get("negative_prompt") or ""),
                )
            )
    return stills


def _stills_from_manifest(payload: dict[str, Any]) -> list[StoryboardStill]:
    """One still per scene, held for the scene's own duration."""
    stills: list[StoryboardStill] = []
    for index, scene in enumerate(payload.get("scenes") or []):
        prompt = scene.get("action_prompt") or scene.get("video_prompt") or ""
        start = scene.get("time_start")
        end = scene.get("time_end")
        hold = scene.get("duration")
        if hold is None and start is not None and end is not None:
            hold = float(end) - float(start)
        if hold is None:
            raise StoryboardError(f"scene {index} has no duration or time range")
        stills.append(
            StoryboardStill(
                label=f"S{scene.get('scene_index', index)}-IMG1",
                image_prompt=str(prompt),
                hold_seconds=float(hold),
                shot_type=str(scene.get("camera_directive") or ""),
                scene_index=int(scene.get("scene_index", index)),
            )
        )
    return stills


def load_storyboard(path: str | Path) -> Storyboard:
    """Parse either shape, preferring the per-still storyboard when present."""
    path = Path(path)
    payload = _read_json(path)

    scenes = payload.get("scenes") or []
    has_stills = any(scene.get("stills") for scene in scenes)

    stills = _stills_from_storyboard(payload) if has_stills else _stills_from_manifest(payload)
    if not stills:
        raise StoryboardError(f"no usable stills found in {path}")

    board = Storyboard(
        title=str(payload.get("title") or path.stem),
        stills=stills,
        series_id=str(payload.get("series_id") or ""),
        episode_num=int(payload.get("episode_num") or 0),
        style=str(payload.get("style") or ""),
        source_path=str(path),
        narration=[
            str(scene.get("narration") or "").strip()
            for scene in scenes
            if str(scene.get("narration") or "").strip()
        ],
    )
    logger.info(
        "loaded storyboard %r: %d stills, %.2fs total, holds %s, script %d chars",
        board.title,
        len(board.stills),
        board.total_hold_seconds,
        "uniform" if board.has_uniform_holds else "varying",
        len(board.script),
    )
    return board


def find_storyboards(root: str | Path) -> list[Path]:
    """Storyboard and manifest files under a project, storyboards first."""
    root = Path(root)
    found: list[Path] = []
    for sub in ("output/storyboards", "output/manifests"):
        directory = root / sub
        if directory.is_dir():
            found.extend(sorted(p for p in directory.glob("*.json") if not p.name.startswith("~$")))
    return found


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="inspect a storyboard manifest")
    parser.add_argument("path", help="storyboard or manifest JSON")
    parser.add_argument("--prompts-out", default=None, help="write one prompt per line here")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        board = load_storyboard(args.path)
    except StoryboardError as exc:
        print(f"FAILED: {exc}", file=__import__("sys").stderr)
        return 1

    print(f"title:   {board.title}")
    print(f"series:  {board.series_id} ep {board.episode_num} ({board.style})")
    print(f"stills:  {len(board.stills)}")
    print(f"total:   {board.total_hold_seconds}s")
    print(f"holds:   {'uniform' if board.has_uniform_holds else 'varying'}")
    print()
    for still in board.stills:
        print(f"  {still.label:<10} {still.hold_seconds:>5.2f}s  {still.shot_type:<26} {len(still.image_prompt):>5} chars")

    if args.prompts_out:
        Path(args.prompts_out).write_text("\n".join(board.prompts()) + "\n", encoding="utf-8")
        print(f"\nprompts written to {args.prompts_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
