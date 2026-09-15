"""Generates slideshow still-image prompts + storyboard PDF from an EpisodeManifest.

Example:
    python scripts/generate_storyboard_pdf.py
    python scripts/generate_storyboard_pdf.py --manifest output/manifests/farmer_and_rusty_ep01.json --style cinematic_photorealistic
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models import EpisodeManifest
from src.storyboard.generator import StoryboardGenerator
from src.storyboard.pdf import StoryboardPDFBuilder


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate slideshow storyboard PDF from episode script")
    p.add_argument("--manifest", default=str(ROOT / "output" / "manifests" / "farmer_and_rusty_ep01.json"), help="EpisodeManifest JSON path")
    p.add_argument("--characters-dir", default=str(ROOT / "Charectors"), help="Character photo folder")
    p.add_argument("--output-pdf", default=None, help="Output PDF path (default: output/storyboards/<series>_epXX_storyboard.pdf)")
    p.add_argument("--output-json", default=None, help="Output storyboard JSON path (default: alongside PDF)")
    p.add_argument("--style", default="cinematic_photorealistic", choices=["cinematic_photorealistic", "pixar_3d", "storybook"], help="Image prompt style")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"Error: manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    manifest = EpisodeManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8-sig")))

    generator = StoryboardGenerator(characters_dir=args.characters_dir, style=args.style)
    doc = generator.generate(manifest)

    if args.output_pdf:
        pdf_path = Path(args.output_pdf)
    else:
        pdf_path = ROOT / "output" / "storyboards" / f"{doc.series_id}_ep{doc.episode_num:02d}_storyboard.pdf"
    if args.output_json:
        json_path = Path(args.output_json)
    else:
        json_path = pdf_path.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)

    json_path.write_text(doc.model_dump_json(indent=2), encoding="utf-8")

    profiles_extra = {p.name: p.personality for p in manifest.character_profiles}
    builder = StoryboardPDFBuilder()
    built = builder.build(doc, pdf_path, profiles_extra=profiles_extra)

    print(f"Storyboard: {doc.title} (Ep {doc.episode_num})")
    print(f"  Scenes: {len(doc.scenes)}, stills: {doc.total_stills}")
    for s in doc.scenes:
        print(f"  Scene {s.scene_index + 1} [{s.phase}] {s.time_start:.1f}-{s.time_end:.1f}s -> {len(s.stills)} stills: {', '.join(x.label for x in s.stills)}")
    print(f"  Character photos:")
    for name, photos in doc.character_photos.items():
        print(f"    {name}: {len(photos)} photo(s)" + (f" e.g. {Path(photos[0]).name}" if photos else " (MISSING)"))
    missing = [n for n, ph in doc.character_photos.items() if not ph]
    if missing:
        print(f"  WARNING: no photos found for: {', '.join(missing)} (check Charectors/ subfolder names)")
    print(f"  JSON: {json_path.resolve()}")
    print(f"  PDF:  {built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
