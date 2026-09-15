"""Generates scene stills via the live FlowKit service (Google Flow website backend).

Uses the existing FlowKitClient + FlowKitPayloadAdapter (project -> video ->
two-step scenes -> GENERATE_IMAGE batch -> poll), then downloads each scene's
still URL. Requires: FlowKit agent up, Chrome extension connected, and a
signed-in flow.google.com tab (else fails fast with NO_FLOW_TAB, no cost).

Example:
    python scripts/generate_flowkit_stills.py
    python scripts/generate_flowkit_stills.py --episode 1 --out-dir output/flowkit_stills
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.render_client.adapter import FlowKitPayloadAdapter
from src.render_client.client import FlowKitClient
from src.models import EpisodeManifest
from src.storyboard.characters import CharacterPhotoResolver


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Live FlowKit still generation")
    p.add_argument("--manifest", default=str(ROOT / "output" / "manifests" / "farmer_and_rusty_ep01.json"))
    p.add_argument("--material", default="realistic")
    p.add_argument("--out-dir", default=str(ROOT / "output" / "flowkit_stills"))
    p.add_argument("--characters-dir", default=str(ROOT / "Charectors"))
    p.add_argument("--skip-refs", action="store_true",
                   help="Skip reference-photo upload (reuse existing character media_ids)")
    p.add_argument("--poll-timeout", type=float, default=1200.0)
    return p.parse_args()


async def _download(url: str, dest: Path) -> int:
    async with httpx.AsyncClient(timeout=120.0) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return len(resp.content)


async def amain() -> int:
    args = parse_args()
    manifest = EpisodeManifest.model_validate(
        json.loads(Path(args.manifest).read_text(encoding="utf-8-sig"))
    )
    out_dir = Path(args.out_dir) / f"{manifest.series_id}_ep{manifest.episode_num:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    async with FlowKitClient() as client:
        if not await client.verify_connection():
            print("FlowKit extension not connected. Open Chrome with the extension active.", file=sys.stderr)
            return 1
        project = await client.create_project(
            FlowKitPayloadAdapter.to_project_payload(manifest, material=args.material)
        )
        project_id = project["id"]
        print(f"project: {project_id}", flush=True)

        # Scene stills are gated on character reference images. Upload the
        # first Charectors/ photo per bound character and attach its Flow
        # media_id so Arthur/Rusty keep exact likeness in every still.
        if not args.skip_refs:
            resolver = CharacterPhotoResolver(args.characters_dir)
            entities = await client.get_characters(project_id=project_id)
            bound = sorted({c for s in manifest.scenes for c in s.bound_characters})
            for char in entities:
                name = str(char.get("name", ""))
                if name.strip().lower() not in {b.strip().lower() for b in bound}:
                    continue
                if char.get("media_id"):
                    print(f"  {name}: already has media_id", flush=True)
                    continue
                photos = resolver.resolve(name)
                if not photos:
                    print(f"  {name}: NO photo in Charectors/, skipping", flush=True)
                    continue
                up = await client.upload_image(photos[0], project_id=project_id)
                media_id = up.get("media_id")
                if not media_id:
                    print(f"  {name}: upload failed: {up}", flush=True)
                    continue
                await client.update_character(char["id"], {"media_id": media_id})
                print(f"  {name}: reference attached ({Path(photos[0]).name} -> {media_id[:8]}...)", flush=True)
        video = await client.create_video(
            FlowKitPayloadAdapter.to_video_payload(manifest, project_id=project_id)
        )
        video_id = video["id"]
        print(f"video: {video_id}")

        scene_ids: list[str] = []
        for scene_create, narrator_text in FlowKitPayloadAdapter.to_scene_payloads(manifest, video_id=video_id):
            created = await client.create_scene(scene_create, narrator_text=narrator_text)
            scene_ids.append(created["id"])
        print(f"scenes: {len(scene_ids)}")

        reqs = FlowKitPayloadAdapter.to_batch_requests(
            scene_ids, project_id=project_id, video_id=video_id,
            req_type="GENERATE_IMAGE", orientation="VERTICAL",
        )
        await client.submit_batch_requests(reqs)
        print("GENERATE_IMAGE submitted, polling...")
        status = await client.poll_batch_resilient(
            expected_count=len(scene_ids), video_id=video_id,
            req_type="GENERATE_IMAGE", orientation="VERTICAL",
            timeout=args.poll_timeout, poll_interval=10.0,
        )
        print(f"batch done: completed={status.completed} failed={status.failed}")

        scenes = await client.get_scenes(video_id=video_id)
        saved = 0
        for s in scenes:
            order = s.get("display_order", saved)
            url = (
                s.get("vertical_image_url") or s.get("image_url")
                or s.get("horizontal_image_url") or ""
            )
            if not url:
                print(f"  scene order={order}: NO image url (keys: {sorted(s.keys())})")
                continue
            dest = out_dir / f"flow_S{int(order) + 1}.png"
            nbytes = await _download(url, dest)
            print(f"  saved {dest.name} ({nbytes // 1024}KB)")
            saved += 1
        print(f"stills saved: {saved}/{len(scenes)} -> {out_dir}")
        return 0 if saved else 1


def main() -> int:
    return asyncio.run(amain())


if __name__ == "__main__":
    raise SystemExit(main())
