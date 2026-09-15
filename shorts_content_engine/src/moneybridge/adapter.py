"""Converts EpisodeManifest / StoryboardDocument into MoneyPrinterTurbo tasks.

Money's ``VideoParams`` (app/models/schema.py) needs ``video_subject`` or
``video_script`` plus a ``video_source``. Two slideshow-friendly modes:

- ``local``: you generate the 17 stills yourself (any image model, using our
  PDF prompts + Charectors/ ref photos for likeness), then Money does free
  Edge-TTS narration + subtitles + BGM + 9:16 concat. Zero image cost.
- ``openai_image``: Money calls an OpenAI-compatible ``/images/generations``
  endpoint once per ``video_terms`` entry and renders each image into a
  zoom-effect clip. Set Money's ``openai_image_prompt_template = "{term}"``
  so our full cinematic prompts pass through untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.models import EpisodeManifest
from src.storyboard.models import StoryboardDocument

MoneySource = Literal["local", "openai_image"]


class MoneyTask(BaseModel):
    """Single Money VideoParams-compatible task dict wrapper."""

    video_subject: str
    video_script: str
    video_terms: list[str] | None = None
    video_source: str = "local"
    video_materials: list[dict[str, Any]] | None = None
    video_aspect: str = "9:16"
    video_concat_mode: str = "sequential"
    video_transition_mode: str | None = "FadeIn"
    video_clip_duration: int = 3
    video_fit_mode: str = "cover"
    match_materials_to_script: bool = True
    voice_name: str = "en-US-ChristopherNeural"
    voice_volume: float = 1.0
    subtitle_enabled: bool = True
    bgm_type: str = "random"
    bgm_volume: float = 0.2

    def to_params(self) -> dict[str, Any]:
        d = self.model_dump(exclude_none=True)
        # Money CLI rejects explicit null for aspect/concat; ensure present.
        d.setdefault("video_aspect", "9:16")
        d.setdefault("video_concat_mode", "sequential")
        return d


class MoneyBridgeAdapter:
    """Builds Money tasks from our directing + storyboard outputs."""

    ALLOWED_SOURCES = (
        "pexels", "pixabay", "coverr", "volcengine_seedance", "ofox",
        "metaso_minimax", "openai_image", "cf_worker", "local",
    )

    def __init__(self, stills_dir: str | Path = "output/stills", voice: str = "en-US-ChristopherNeural") -> None:
        self.stills_dir = Path(stills_dir)
        self.voice = voice

    # -- public ------------------------------------------------------

    def episode_script_text(self, manifest: EpisodeManifest) -> str:
        """Concatenates scene narrations + dialogue into Money's video_script."""
        lines: list[str] = []
        for s in manifest.scenes:
            if s.narration:
                lines.append(s.narration.strip())
            if s.dialogue:
                lines.append(f'{s.dialogue.speaker} says: "{s.dialogue.text.strip()}"')
        return " ".join(lines)

    def storyboard_terms(self, doc: StoryboardDocument) -> list[str]:
        """Full copy-paste image prompts, one per still, in story order."""
        terms: list[str] = []
        for scene in sorted(doc.scenes, key=lambda s: s.scene_index):
            for still in sorted(scene.stills, key=lambda st: st.image_index):
                terms.append(still.image_prompt)
        return terms

    def expected_still_paths(self, doc: StoryboardDocument) -> list[Path]:
        """Where the 17 still PNGs should live for ``local`` mode."""
        base = self.stills_dir / f"{doc.series_id}_ep{doc.episode_num:02d}"
        paths: list[Path] = []
        for scene in sorted(doc.scenes, key=lambda s: s.scene_index):
            for still in sorted(scene.stills, key=lambda st: st.image_index):
                paths.append(base / f"{still.label}.png")
        return paths

    def to_task(
        self,
        manifest: EpisodeManifest,
        doc: StoryboardDocument,
        source: MoneySource = "local",
    ) -> MoneyTask:
        if source not in ("local", "openai_image"):
            raise ValueError(f"source must be 'local' or 'openai_image', got {source!r}")
        subject = f"{manifest.series_id} Ep{manifest.episode_num}: {manifest.title}"
        script = self.episode_script_text(manifest)
        if not subject.strip() and not script.strip():
            raise ValueError("Money task needs video_subject or video_script")
        terms = self.storyboard_terms(doc)
        # Mean hold ~ total/17 ≈ 2.6s -> clip 3s lets Money trim to narration.
        clip_dur = 3
        if source == "local":
            materials = [
                {"provider": "local", "url": str(p), "duration": 0}
                for p in self.expected_still_paths(doc)
            ]
            return MoneyTask(
                video_subject=subject, video_script=script, video_terms=None,
                video_source="local", video_materials=materials,
                video_clip_duration=clip_dur, voice_name=self.voice,
            )
        return MoneyTask(
            video_subject=subject, video_script=script, video_terms=terms,
            video_source="openai_image", video_materials=None,
            video_clip_duration=clip_dur, voice_name=self.voice,
        )

    def to_batch_file(
        self,
        manifest: EpisodeManifest,
        doc: StoryboardDocument,
        out_path: str | Path,
        source: MoneySource = "local",
    ) -> str:
        task = self.to_task(manifest, doc, source=source)
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([task.to_params()], indent=2), encoding="utf-8")
        return str(out.resolve())

    # -- dry-run validation (mirrors Money cli.py rules, no heavy deps) --

    @classmethod
    def validate_task(cls, params: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if not str(params.get("video_subject", "")).strip() and not str(params.get("video_script", "")).strip():
            errors.append("one of video_subject or video_script is required")
        src = params.get("video_source", "pexels")
        if src not in cls.ALLOWED_SOURCES:
            errors.append(f"video_source must be one of: {', '.join(cls.ALLOWED_SOURCES)}")
        mats = params.get("video_materials")
        if src == "local":
            if not mats:
                errors.append("video_materials is required with video_source=local")
            else:
                for i, m in enumerate(mats, 1):
                    if not isinstance(m, dict) or not str(m.get("url", "")).strip():
                        errors.append(f"material {i} needs a url")
        elif mats:
            errors.append("video_materials can only be used with video_source=local")
        terms = params.get("video_terms")
        if src == "openai_image" and not terms:
            errors.append("video_terms (our 17 prompts) required with video_source=openai_image")
        if params.get("video_aspect") not in ("9:16", "16:9", "1:1"):
            errors.append("video_aspect must be 9:16, 16:9 or 1:1")
        return errors
