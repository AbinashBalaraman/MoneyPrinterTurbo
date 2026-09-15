"""Exports a MoneyPrinterTurbo batch manifest from our episode + storyboard.

Example:
    python scripts/export_to_money.py --source local
    python scripts/export_to_money.py --source openai_image --voice en-US-ChristopherNeural
    python scripts/export_to_money.py --source local --stills-dir output/stills

Then in the Money repo:
    uv run python cli.py --batch-file <generated tasks.json> --video-aspect 9:16
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
from src.moneybridge.adapter import MoneyBridgeAdapter
from src.storyboard.models import StoryboardDocument


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export MoneyPrinterTurbo batch tasks from storyboard")
    p.add_argument("--manifest", default=str(ROOT / "output" / "manifests" / "farmer_and_rusty_ep01.json"))
    p.add_argument("--storyboard", default=str(ROOT / "output" / "storyboards" / "farmer_and_rusty_ep01_storyboard.json"))
    p.add_argument("--source", default="local", choices=["local", "openai_image"])
    p.add_argument("--stills-dir", default=str(ROOT / "output" / "stills"))
    p.add_argument("--voice", default="en-US-ChristopherNeural")
    p.add_argument("--out", default=None)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    manifest = EpisodeManifest.model_validate(json.loads(Path(args.manifest).read_text(encoding="utf-8-sig")))
    doc = StoryboardDocument.model_validate(json.loads(Path(args.storyboard).read_text(encoding="utf-8")))
    stills_dir = str(Path(args.stills_dir).resolve()) if not Path(args.stills_dir).is_absolute() else args.stills_dir
    adapter = MoneyBridgeAdapter(stills_dir=stills_dir, voice=args.voice)
    out = Path(args.out) if args.out else (ROOT / "output" / "money_tasks" / f"{doc.series_id}_ep{doc.episode_num:02d}_{args.source}_tasks.json")
    built = adapter.to_batch_file(manifest, doc, out, source=args.source)
    params = json.loads(Path(built).read_text(encoding="utf-8"))[0]
    errors = MoneyBridgeAdapter.validate_task(params)
    print(f"Storyboard -> Money ({args.source}): {doc.title} | {doc.total_stills} stills")
    print(f"  script chars: {len(params['video_script'])} | terms: {len(params.get('video_terms') or [])} | materials: {len(params.get('video_materials') or [])}")
    if errors:
        print("  VALIDATION ERRORS:")
        for e in errors:
            print(f"    - {e}")
        return 1
    print("  Money VideoParams dry-run validation: PASS")
    if args.source == "local":
        missing = [m["url"] for m in params["video_materials"] if not Path(m["url"]).exists()]
        print(f"  stills dir: {args.stills_dir}/{doc.series_id}_ep{doc.episode_num:02d}/")
        print(f"  still files present: {len(params['video_materials']) - len(missing)}/{len(params['video_materials'])} (generate missing PNGs from the PDF prompts first)")
        if missing:
            print(f"  e.g. missing: {Path(missing[0]).name} ...")
    else:
        print('  Money config needed: video_source="openai_image", openai_image_base_url+model set, openai_image_prompt_template="{term}"')
    print(f"  batch file: {built}")
    print("  run in Money repo: uv run python cli.py --batch-file \"<above>\" --video-aspect 9:16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
