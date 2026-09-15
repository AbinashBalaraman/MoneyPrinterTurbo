"""Makes labeled placeholder stills (1080x1920) for pipeline smoke tests.

Real stills come from an image model using the storyboard PDF prompts.
Placeholders only prove Money assembly (TTS + subtitles + concat) end to end.

Example:
    python scripts/make_placeholder_stills.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

PALETTE = [
    (120, 84, 40), (96, 64, 32), (46, 90, 60),
    (60, 70, 50), (30, 110, 70), (25, 40, 90),
]


def main() -> int:
    sb_path = ROOT / "output" / "storyboards" / "farmer_and_rusty_ep01_storyboard.json"
    doc = json.loads(sb_path.read_text(encoding="utf-8"))
    base = ROOT / "output" / "stills_demo" / f"{doc['series_id']}_ep{doc['episode_num']:02d}"
    base.mkdir(parents=True, exist_ok=True)
    n = 0
    for scene in sorted(doc["scenes"], key=lambda s: s["scene_index"]):
        color = PALETTE[scene["scene_index"] % len(PALETTE)]
        for still in sorted(scene["stills"], key=lambda s: s["image_index"]):
            img = Image.new("RGB", (1080, 1920), color)
            d = ImageDraw.Draw(img)
            d.rectangle([60, 700, 1020, 1220], fill=(0, 0, 0))
            d.text((110, 760), still["label"], fill=(255, 220, 130))
            d.text((110, 820), f"{scene['phase']}", fill=(255, 255, 255))
            d.text((110, 880), f"{still['shot_type']}", fill=(220, 220, 220))
            d.text((110, 940), f"{still['time_start']:.1f}-{still['time_end']:.1f}s", fill=(220, 220, 220))
            narration = scene.get("narration", "")[:90]
            d.text((110, 1000), narration, fill=(200, 200, 200))
            d.text((110, 1120), "PLACEHOLDER - replace with", fill=(255, 150, 150))
            d.text((110, 1160), "AI still from PDF prompt", fill=(255, 150, 150))
            img.save(base / f"{still['label']}.png")
            n += 1
    print(f"wrote {n} placeholder stills to {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
