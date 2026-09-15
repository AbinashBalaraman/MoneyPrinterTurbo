"""Unit tests for the slideshow storyboard subsystem."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import EpisodeManifest
from src.storyboard.characters import CharacterPhotoResolver
from src.storyboard.generator import StoryboardGenerator, still_count_for_duration
from src.storyboard.pdf import StoryboardPDFBuilder

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = ROOT / "output" / "manifests" / "farmer_and_rusty_ep01.json"
CHAR_DIR = ROOT / "Charectors"


def _load_manifest() -> EpisodeManifest:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    return EpisodeManifest.model_validate(raw)


def test_still_count_auto_rule():
    assert still_count_for_duration(6.0) == 2
    assert still_count_for_duration(7.0) == 3
    assert still_count_for_duration(8.0) == 3
    assert still_count_for_duration(2.0) == 2  # floor
    assert still_count_for_duration(20.0) == 3  # cap


def test_character_resolver_finds_arthur_rusty():
    resolver = CharacterPhotoResolver(CHAR_DIR)
    arthur = resolver.resolve("Arthur")
    rusty = resolver.resolve("rusty")  # case-insensitive
    assert len(arthur) == 2, f"expected 2 Arthur photos, got {arthur}"
    assert len(rusty) == 2, f"expected 2 Rusty photos, got {rusty}"
    assert resolver.resolve("Nobody") == []


def test_generator_produces_auto_stills_with_prompts():
    manifest = _load_manifest()
    gen = StoryboardGenerator(characters_dir=CHAR_DIR, style="cinematic_photorealistic")
    doc = gen.generate(manifest)
    assert doc.series_id == "farmer_and_rusty"
    assert len(doc.scenes) == 6
    # 6s->2, rest 7-8s->3 each = 17
    assert doc.total_stills == 17
    for scene, sb in zip(manifest.scenes, doc.scenes):
        assert len(sb.stills) >= 2
        for still in sb.stills:
            assert still.image_prompt, "image prompt must not be empty"
            assert "9:16" in still.image_prompt
            assert "cinematic photorealistic" in still.image_prompt.lower()
            # character likeness must be embedded (not decoupled)
            for cname in sb.bound_characters:
                if cname in ("Arthur", "Rusty"):
                    assert cname in still.image_prompt
            assert still.hold_seconds > 0
    # photos wired
    assert len(doc.character_photos["Arthur"]) == 2
    assert len(doc.character_photos["Rusty"]) == 2


def test_pdf_builds_with_embedded_photos(tmp_path):
    manifest = _load_manifest()
    gen = StoryboardGenerator(characters_dir=CHAR_DIR)
    doc = gen.generate(manifest)
    out_pdf = tmp_path / "storyboard_test.pdf"
    profiles_extra = {p.name: p.personality for p in manifest.character_profiles}
    built = StoryboardPDFBuilder().build(doc, out_pdf, profiles_extra=profiles_extra)
    assert Path(built).exists()
    assert Path(built).stat().st_size > 50_000, "PDF suspiciously small, photos may be missing"
    # verify images embedded
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(built))
        assert len(reader.pages) >= 7  # cover + chars + 6 scenes
        n_images = sum(len(list(p.images)) for p in reader.pages)
        assert n_images >= 10, f"expected embedded character photos, got {n_images}"
    except ImportError:
        pytest.skip("pypdf not installed")
