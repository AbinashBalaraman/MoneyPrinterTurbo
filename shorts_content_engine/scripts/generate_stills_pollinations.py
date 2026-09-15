"""Generates real AI stills for every storyboard keyframe via Pollinations (free, no key).

Reads the storyboard JSON (full cinematic prompts with embedded character
likeness), downloads one portrait image per still, converts to PNG.

Example:
    python scripts/generate_stills_pollinations.py
    python scripts/generate_stills_pollinations.py --only-missing --model flux
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.storyboard.models import StoryboardDocument

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate AI stills via Pollinations")
    p.add_argument("--storyboard", default=str(ROOT / "output" / "storyboards" / "farmer_and_rusty_ep01_storyboard.json"))
    p.add_argument("--out-dir", default=None, help="default: output/stills/<series>_ep<NN>/")
    p.add_argument("--model", default="flux", help="pollinations image model")
    p.add_argument("--width", type=int, default=768)
    p.add_argument("--height", type=int, default=1344)
    p.add_argument("--seed-base", type=int, default=7000, help="seed = base + global still counter")
    p.add_argument("--retries", type=int, default=3)
    p.add_argument("--timeout", type=int, default=240, help="seconds per image request")
    p.add_argument("--only-missing", action="store_true", help="skip stills whose PNG already exists")
    return p.parse_args()


def fetch_image(prompt: str, width: int, height: int, seed: int, model: str, timeout: int) -> bytes:
    params = urllib.parse.urlencode({
        "width": width, "height": height, "seed": seed,
        "model": model, "nologo": "true", "private": "true",
    })
    url = f"{POLLINATIONS_BASE}/{urllib.parse.quote(prompt, safe='')}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "shorts-content-engine/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.status != 200:
            raise RuntimeError(f"HTTP {resp.status}")
        ctype = resp.headers.get("Content-Type", "")
        if "image" not in ctype:
            raise RuntimeError(f"unexpected content type: {ctype}")
        return resp.read()


def main() -> int:
    args = parse_args()
    doc = StoryboardDocument.model_validate(json.loads(Path(args.storyboard).read_text(encoding="utf-8")))
    out_dir = Path(args.out_dir) if args.out_dir else (ROOT / "output" / "stills" / f"{doc.series_id}_ep{doc.episode_num:02d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from PIL import Image
        import io as _io
        has_pil = True
    except ImportError:
        has_pil = False

    counter = 0
    done, skipped, failed = 0, 0, []
    total = doc.total_stills
    for scene in sorted(doc.scenes, key=lambda s: s.scene_index):
        for still in sorted(scene.stills, key=lambda st: st.image_index):
            counter += 1
            dest = out_dir / f"{still.label}.png"
            if args.only_missing and dest.exists() and dest.stat().st_size > 10_000:
                skipped += 1
                continue
            seed = args.seed_base + counter
            ok = False
            for attempt in range(1, args.retries + 1):
                try:
                    print(f"[{counter}/{total}] {still.label} ({still.shot_type}, seed={seed}) try {attempt}...", flush=True)
                    raw = fetch_image(still.image_prompt, args.width, args.height, seed, args.model, args.timeout)
                    if has_pil:
                        im = Image.open(_io.BytesIO(raw))
                        im.thumbnail((args.width, args.height))
                        im.save(dest, "PNG")
                    else:
                        dest.write_bytes(raw)
                    print(f"  saved {dest.name} ({len(raw)//1024}KB)", flush=True)
                    ok = True
                    break
                except Exception as exc:
                    print(f"  attempt {attempt} failed: {type(exc).__name__}: {exc}", flush=True)
                    time.sleep(5)
            if ok:
                done += 1
            else:
                failed.append(still.label)
            time.sleep(2)  # be polite to the free tier

    print(f"done: {done}, skipped: {skipped}, failed: {failed or 'none'}")
    print(f"stills dir: {out_dir}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
