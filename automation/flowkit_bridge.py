"""Pull flowkit-generated stills into AutoShorts' ``video_source="local"`` path.

Why this needs no change to ``app/``
------------------------------------
AutoShorts already treats ``video_source="local"`` as "materials the caller
supplies". In ``app/services/video.py::preprocess_video`` any material whose
extension is in ``const.FILE_TYPE_IMAGES`` is rendered through
``render_image_zoom_video`` — an ``ImageClip`` held for ``video_clip_duration``
seconds with a slow zoom to ~120% — and the resulting mp4s are concatenated with
TTS narration, subtitles and BGM by the normal pipeline. So the "images -> video"
stage already exists; flowkit only has to deliver files.

Two constraints from that code path drive the implementation here:

1. ``preprocess_video`` resolves every material through
   ``file_security.resolve_path_within_directory(local_videos_dir, url)``, so
   images must live under ``storage/local_videos/``. A relative path such as
   ``<task_id>/01_foo.png`` is accepted (it is joined to the base directory and
   the ``commonpath`` check passes for subdirectories).
2. The image branch is chosen by extension. ``const.FILE_TYPE_IMAGES`` is
   ``["jpg", "jpeg", "png", "bmp"]`` — notably **not webp**. A webp would fall
   through to the video branch, never get a zoom clip, and hand a raw image to
   the concatenation stage. The bridge therefore normalises every download into
   an accepted format instead of trusting what Flow returns.

Everything in here fails loudly. A skipped image means a video with fewer stills
than the script asked for, which is exactly the kind of silent degradation that
makes an unattended run untrustworthy.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import parse_qsl, urlsplit

import requests

logger = logging.getLogger(__name__)

FLOWKIT_DEFAULT_URL = "http://127.0.0.1:8100"

# Mirrors app/models/const.py::FILE_TYPE_IMAGES. Keep in sync.
ACCEPTED_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".bmp"})

# Mirrors app/services/video.py. A material below 480px on either side is
# rejected, with a small tolerance for encoders that round dimensions down.
MIN_MATERIAL_DIMENSION = 480
MIN_DIMENSION_TOLERANCE = 10
MIN_ACCEPTED_SIDE = MIN_MATERIAL_DIMENSION - MIN_DIMENSION_TOLERANCE

# flowkit's GenerateImageRequest defaults to this; it is the 9:16 short format.
DEFAULT_ASPECT_RATIO = "IMAGE_ASPECT_RATIO_PORTRAIT"
DEFAULT_CLIP_DURATION = 5
DEFAULT_TIMEOUT = 30.0
DEFAULT_GENERATE_TIMEOUT = 180.0
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_SLUG_LENGTH = 40


class FlowkitError(RuntimeError):
    """A failure that must stop the run rather than be silently skipped."""


@dataclass(frozen=True)
class ImageAsset:
    """One image flowkit has generated, before it is downloaded."""

    media_id: str
    url: str
    prompt: str = ""


@dataclass
class StagedImage:
    """A downloaded, validated image sitting under ``storage/local_videos``."""

    path: str
    """Path relative to ``storage/local_videos`` — this is what goes in the material."""

    absolute_path: str
    prompt: str
    media_id: str
    width: int
    height: int
    converted: bool = False
    duration: Optional[float] = None
    """Exact hold in seconds, when the storyboard specified one."""

    rendered_clip: bool = False
    """True when ``path`` points at a pre-rendered mp4 rather than a still.

    Set when an exact per-still hold is required. ``video_clip_duration`` is a
    single int for the whole task, so per-still timing cannot survive as images;
    rendering each still to its own clip lets ``combine_videos`` honour the real
    durations instead of drifting against the narration.
    """

    def as_material(self, clip_duration: int = DEFAULT_CLIP_DURATION) -> dict[str, Any]:
        """Shape matching ``app/models/schema.py::MaterialInfo``.

        ``provider`` is informational; ``preprocess_video`` keys off the file
        extension, not this field. It is set to ``flowkit`` so task records show
        where the still came from.
        """
        duration = int(round(self.duration)) if self.duration else int(clip_duration)
        return {
            "provider": "flowkit",
            "url": self.path,
            "duration": max(1, duration),
        }


@dataclass
class StagedVideo:
    """A downloaded FlowKit video sitting under ``storage/local_videos``."""

    path: str
    """Path relative to ``storage/local_videos`` — this is what goes in the material."""

    absolute_path: str
    prompt: str
    media_id: str
    scene_id: str = ""

    def as_material(self, clip_duration: int = DEFAULT_CLIP_DURATION) -> dict[str, Any]:
        """Same ``MaterialInfo`` shape as stills; the clip keeps its own length."""
        return {
            "provider": "flowkit",
            "url": self.path,
            "duration": max(1, int(clip_duration)),
        }


def _is_loopback(base_url: str) -> bool:
    """True when ``base_url`` points at this machine."""
    from urllib.parse import urlparse

    host = (urlparse(base_url).hostname or "").lower()
    return host in {"localhost", "::1", "0.0.0.0"} or host.startswith("127.")


def _slugify(text: str, max_length: int = MAX_SLUG_LENGTH) -> str:
    """Filesystem-safe, stable-ish label for an image filename."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text or "").strip("_").lower()
    if not slug:
        return "image"
    return slug[:max_length].rstrip("_") or "image"


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return int(img.width), int(img.height)


def _normalise_image(source: Path, dest_dir: Path, stem: str) -> tuple[Path, bool]:
    """Ensure ``source`` is in a format ``preprocess_video`` renders as an image.

    Returns ``(final_path, converted)``. Unsupported containers (webp, tiff, …)
    are re-encoded to PNG. An already-accepted file is only renamed, so the
    common path does not pay a re-encode.
    """
    suffix = source.suffix.lower()
    if suffix in ACCEPTED_IMAGE_EXTS:
        target = dest_dir / f"{stem}{suffix}"
        if source != target:
            source.replace(target)
        return target, False

    from PIL import Image

    target = dest_dir / f"{stem}.png"
    try:
        with Image.open(source) as img:
            # PNG cannot hold CMYK; convert so the re-encode cannot fail.
            if img.mode not in ("RGB", "RGBA", "L", "P"):
                img = img.convert("RGB")
            img.save(target, format="PNG")
    except Exception as exc:  # noqa: BLE001 - re-raised as a domain error
        raise FlowkitError(
            f"could not convert {source.name} ({suffix or 'no extension'}) to PNG: {exc}"
        ) from exc
    finally:
        source.unlink(missing_ok=True)

    return target, True


def _download_error(kind: str, status: int, media_id: str) -> str:
    """Explain a failed media download in terms the caller can act on.

    Flow serves media through **signed, expiring URLs**. The database keeps a
    scene marked COMPLETED with its URL, but that URL stops working a few days
    after generation — measured on this project: `Expires` about five days
    before "now", and a plain `curl` of the same URL also returns 403.

    So a 403 here almost always means the media is no longer reachable, not that
    anything is misconfigured, and the fix is to regenerate the scene rather
    than to go looking at credentials. Saying that plainly matters because this
    runs unattended: "HTTP 403" invites a hunt in the wrong place.
    """
    if status == 403:
        return (
            f"{kind} download refused (HTTP 403) for media {media_id}: Flow's "
            f"signed URL has almost certainly expired. Completed media stays in "
            f"the database but stops being downloadable after a few days. "
            f"Regenerate this scene's {kind} in FlowKit, or stage a project whose "
            f"media was generated recently."
        )
    return f"{kind} download failed with HTTP {status} for media {media_id}"


def _signed_url_expiry(url: str) -> Optional[int]:
    """The ``Expires`` timestamp on a signed Flow URL, or None if it has none.

    Returns None for anything unparseable, which callers must treat as "let the
    download decide" rather than "expired" -- refusing to stage a project
    because a URL did not look the way we expected would be worse than trying it.
    """
    try:
        query = urlsplit(url).query
    except ValueError:
        return None
    for key, value in parse_qsl(query):
        if key.lower() == "expires":
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _is_usable(url: Optional[str]) -> bool:
    """True when a signed URL has not expired, or carries no expiry to check."""
    if not url:
        return False
    expiry = _signed_url_expiry(str(url))
    return expiry is None or expiry > time.time()


def _refuse_if_all_media_expired(
    scenes: Sequence[dict[str, Any]], media: str, project: dict[str, Any]
) -> None:
    """Fail before downloading anything when every scene's media has expired.

    Flow serves media through signed URLs that stop working a few days after
    generation, while the database goes on reporting the scene as COMPLETED.
    Measured on this project: 13 of 13 signed URLs expired, ~5 days past, and a
    plain curl of the same URL also returns 403.

    Without this, staging walks the scenes, downloads what it can, and dies
    partway through -- wasted work and a failure that points at the first scene
    rather than at the real cause. For a pipeline meant to run unattended, that
    is the difference between "regenerate the project" and an hour of reading
    stack traces.

    Only refuses when *nothing* is usable: a partly-expired project is still
    worth staging, and the per-download error covers the scenes that fail.
    """
    if not scenes:
        return

    usable = 0
    expired = 0
    for scene in scenes:
        candidates = []
        if media in ("auto", "video"):
            candidates.append(scene.get("vertical_video_url"))
        if media in ("auto", "still"):
            candidates.append(scene.get("vertical_image_url"))
        for url in candidates:
            if not url:
                continue
            expiry = _signed_url_expiry(str(url))
            if expiry is None or expiry > time.time():
                usable += 1
            else:
                expired += 1

    if usable == 0 and expired:
        name = project.get("name", "?") if isinstance(project, dict) else "?"
        raise FlowkitError(
            f"every signed media URL for project {name!r} has expired "
            f"({expired} checked, none still valid), so there is nothing to "
            f"download. Flow's media URLs last only a few days. Regenerate the "
            f"project's media in FlowKit and stage it promptly."
        )


class FlowkitImageSource:
    """Thin client for the flowkit agent's image endpoints.

    flowkit must already be running with its Chrome extension connected —
    ``require_ready()`` checks that and explains what to start if it is not.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        project_id: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        generate_timeout: float = DEFAULT_GENERATE_TIMEOUT,
        session: Optional[requests.Session] = None,
        trust_env: Optional[bool] = None,
    ) -> None:
        self.base_url = (
            base_url
            or os.getenv("AUTOSHORTS_FLOWKIT_URL")
            or FLOWKIT_DEFAULT_URL
        ).rstrip("/")
        self.project_id = project_id or os.getenv("AUTOSHORTS_FLOWKIT_PROJECT_ID") or ""
        self.timeout = float(timeout)
        self.generate_timeout = float(generate_timeout)
        self._session = session if session is not None else requests.Session()

        # A loopback flowkit must never be reached through an ambient HTTP proxy.
        # On this machine the sandbox proxy answers 200 for /health but 404 for
        # /api/flow/status, which is indistinguishable from a broken flowkit —
        # exactly the kind of environment-dependent flake that makes an
        # unattended run untrustworthy. Only a remote flowkit may use a proxy.
        if trust_env is None:
            trust_env = not _is_loopback(self.base_url)
        self._session.trust_env = bool(trust_env)

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "FlowkitImageSource":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _get(self, path: str, timeout: Optional[float] = None) -> Any:
        try:
            resp = self._session.get(f"{self.base_url}{path}", timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise FlowkitError(
                f"flowkit is not reachable at {self.base_url} ({exc}). "
                "Start the flowkit agent and confirm its Chrome extension is connected."
            ) from exc
        if resp.status_code >= 400:
            raise FlowkitError(f"flowkit GET {path} returned HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def flow_status(self) -> dict[str, Any]:
        return self._get("/api/flow/status")

    def resolve_project_id(self) -> str:
        """Configured project id, else the one flowkit is already pinned to.

        SCE and flowkit share a Flow project uuid, so adopting flowkit's avoids
        a second source of truth for the same value.
        """
        if self.project_id:
            return self.project_id
        status = self.flow_status()
        discovered = (status or {}).get("flow_project_id") or ""
        if discovered:
            self.project_id = discovered
        return self.project_id

    def require_ready(self) -> str:
        """Fail fast with an actionable message. Returns the resolved project id."""
        health = self.health()
        if health.get("status") != "ok":
            raise FlowkitError(f"flowkit /health is not ok: {health}")

        if not health.get("extension_connected"):
            raise FlowkitError(
                "flowkit is running but its Chrome extension is not connected. "
                "Open Chrome with the flowkit extension and a signed-in "
                "flow.google.com tab, then retry."
            )

        status = self.flow_status()
        if not status.get("connected"):
            raise FlowkitError(f"flowkit reports the Flow client is not connected: {status}")

        project_id = self.resolve_project_id()
        if not project_id:
            raise FlowkitError(
                "no Flow project id: set AUTOSHORTS_FLOWKIT_PROJECT_ID, or pin one in "
                "flowkit (its /api/flow/status reports flow_project_id)."
            )
        return project_id

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        character_media_ids: Optional[Sequence[str]] = None,
        project_id: Optional[str] = None,
        user_paygate_tier: Optional[str] = None,
    ) -> list[ImageAsset]:
        """Generate one still. Returns the asset(s) flowkit reports."""
        pid = project_id or self.resolve_project_id()
        if not pid:
            raise FlowkitError("generate_image requires a project id")

        body: dict[str, Any] = {
            "prompt": prompt,
            "project_id": pid,
            "aspect_ratio": aspect_ratio,
        }
        if user_paygate_tier:
            body["user_paygate_tier"] = user_paygate_tier
        if character_media_ids:
            body["character_media_ids"] = list(character_media_ids)

        try:
            resp = self._session.post(
                f"{self.base_url}/api/flow/generate-image",
                json=body,
                timeout=self.generate_timeout,
            )
        except requests.RequestException as exc:
            raise FlowkitError(f"flowkit generate-image request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise FlowkitError(
                f"flowkit generate-image returned HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return self._parse_media(resp.json(), prompt)

    @staticmethod
    def _parse_media(payload: Any, prompt: str) -> list[ImageAsset]:
        """Read flowkit's ``{"media": [...]}`` shape.

        flowkit nests each result as ``media[].image.generatedImage`` with
        ``mediaId`` and ``fifeUrl`` (see ``_as_media_record`` in its
        ``flow_client``). Also accepts a bare list, so a future shape change
        degrades to a clear error rather than a KeyError.
        """
        if isinstance(payload, dict):
            records = payload.get("media")
            if records is None:
                records = payload.get("data", {}).get("media") if isinstance(payload.get("data"), dict) else None
        elif isinstance(payload, list):
            records = payload
        else:
            records = None

        if not records:
            raise FlowkitError(f"flowkit returned no media for prompt {prompt!r}: {str(payload)[:300]}")

        assets: list[ImageAsset] = []
        for record in records:
            generated = (record or {}).get("image", {}).get("generatedImage", {}) or {}
            url = generated.get("fifeUrl") or generated.get("url") or ""
            media_id = generated.get("mediaId") or (record or {}).get("name") or ""
            if not url:
                raise FlowkitError(
                    f"flowkit media record has no image URL for prompt {prompt!r}: {str(record)[:300]}"
                )
            assets.append(ImageAsset(media_id=media_id, url=url, prompt=prompt))
        return assets

    def download(self, asset: ImageAsset, dest: Path) -> None:
        """Stream one image to ``dest``, refusing oversized or empty responses."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with self._session.get(asset.url, stream=True, timeout=self.timeout) as resp:
                if resp.status_code >= 400:
                    raise FlowkitError(
                        _download_error("image", resp.status_code, asset.media_id)
                    )
                with open(dest, "wb") as handle:
                    for chunk in resp.iter_content(65536):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_IMAGE_BYTES:
                            raise FlowkitError(
                                f"image {asset.media_id} exceeds {MAX_IMAGE_BYTES} bytes; refusing"
                            )
                        handle.write(chunk)
        except requests.RequestException as exc:
            raise FlowkitError(f"image download failed for media {asset.media_id}: {exc}") from exc
        except Exception:
            dest.unlink(missing_ok=True)
            raise

        if written == 0:
            dest.unlink(missing_ok=True)
            raise FlowkitError(f"image {asset.media_id} downloaded as an empty file")

    def download_video(self, url: str, media_id: str, dest: Path) -> None:
        """Stream one FlowKit video to ``dest``.

        Same guards as stills with a video-sized cap. No format normalisation:
        Flow serves mp4, which ``preprocess_video`` takes down its video branch.
        The caller scrubs through ``ProjectScrubber`` (veo profile) before staging.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        try:
            with self._session.get(url, stream=True, timeout=self.timeout) as resp:
                if resp.status_code >= 400:
                    raise FlowkitError(
                        _download_error("video", resp.status_code, media_id)
                    )
                with open(dest, "wb") as handle:
                    for chunk in resp.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > MAX_VIDEO_BYTES:
                            raise FlowkitError(
                                f"video {media_id} exceeds {MAX_VIDEO_BYTES} bytes; refusing"
                            )
                        handle.write(chunk)
        except requests.RequestException as exc:
            raise FlowkitError(f"video download failed for media {media_id}: {exc}") from exc
        except Exception:
            dest.unlink(missing_ok=True)
            raise

        if written == 0:
            dest.unlink(missing_ok=True)
            raise FlowkitError(f"video {media_id} downloaded as an empty file")


def _ensure_project_root_on_path() -> None:
    """Make ``import app`` work when this file is run as a script.

    ``python automation/flowkit_bridge.py`` puts ``automation/`` on ``sys.path``,
    not the project root, so ``from app.utils import utils`` fails with
    ModuleNotFoundError. Running as ``-m automation.flowkit_bridge`` would work,
    but the documented invocation is the direct one, so fix it here.
    """
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)


class ProjectScrubber:
    """Watermark scrubbing through the project's own SCE engine.

    Wraps ``shorts_content_engine/src/postprocess/watermark.py``
    (ffmpeg delogo, no new dependencies) with the bridge's fail-loud
    contract: ``available()`` gates the run up front, and a failed scrub
    raises instead of shipping a watermarked material. Stills use the
    ``gemini_bottom_right`` badge profile, videos the ``veo_bottom_right`` one.
    """

    STILL_PROFILE = "gemini_bottom_right"
    VIDEO_PROFILE = "veo_bottom_right"

    def __init__(self) -> None:
        import importlib.util

        module_path = (
            Path(__file__).resolve().parent.parent
            / "shorts_content_engine"
            / "src"
            / "postprocess"
            / "watermark.py"
        )
        spec = importlib.util.spec_from_file_location("sce_watermark", module_path)
        if spec is None or spec.loader is None:
            raise FlowkitError(f"cannot load project scrubber from {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(spec.name, None)
            raise
        self._impl = module.WatermarkScrubber()

    def available(self) -> bool:
        """True when ffmpeg is on PATH (the scrubber's only requirement)."""
        return self._impl.is_ffmpeg_available()

    def _scrub_in_place(self, path: Path, profile: str, kind: str) -> None:
        tmp = path.with_name(f"{path.stem}.scrubbed{path.suffix}")
        try:
            ok = self._impl.scrub_video(str(path), str(tmp), profile=profile)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise FlowkitError(f"{kind} scrub failed for {path.name}: {exc}") from exc
        if not ok or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise FlowkitError(f"{kind} scrub failed for {path.name}: ffmpeg reported failure")
        os.replace(tmp, path)

    def scrub(self, image_path: Path) -> None:
        """Scrub a still in place."""
        self._scrub_in_place(Path(image_path), self.STILL_PROFILE, "still")

    def scrub_video(self, video_path: Path) -> None:
        """Scrub a video in place."""
        self._scrub_in_place(Path(video_path), self.VIDEO_PROFILE, "video")


def _local_videos_dir() -> Path:
    """The only directory ``preprocess_video`` will read materials from."""
    _ensure_project_root_on_path()
    from app.utils import utils

    return Path(utils.storage_dir("local_videos", create=True))


def _render_exact_clip(image_path: Path, hold_seconds: float) -> Path:
    """Render a still into a Ken Burns clip of an exact duration.

    Reuses the pipeline's own ``render_image_zoom_video`` so the zoom effect is
    identical to what ``preprocess_video`` would have produced — the only
    difference is that the duration is a float taken from the storyboard instead
    of the task-wide integer.

    The result is an mp4, so ``preprocess_video`` takes its video branch and does
    not re-render it; ``combine_videos`` then honours the clip's real length.
    """
    _ensure_project_root_on_path()
    from app.services.video import render_image_zoom_video

    clip_path = render_image_zoom_video(str(image_path), hold_seconds)
    rendered = Path(clip_path)
    if not rendered.is_file():
        raise FlowkitError(f"failed to render an exact-duration clip for {image_path.name}")
    return rendered


def stage_flowkit_images(
    prompts: Sequence[str],
    task_id: str,
    *,
    clip_duration: int = DEFAULT_CLIP_DURATION,
    source: Optional[FlowkitImageSource] = None,
    aspect_ratio: str = DEFAULT_ASPECT_RATIO,
    character_media_ids: Optional[Sequence[str]] = None,
    local_videos_dir: Optional[Path] = None,
    scrubber: Optional["ProjectScrubber"] = None,
    holds: Optional[Sequence[float]] = None,
) -> list[StagedImage]:
    """Generate one still per prompt and stage it as a usable local material.

    Images land in ``storage/local_videos/<task_id>/`` so concurrent tasks do not
    collide. Raises ``FlowkitError`` on any failure — a partial set would produce
    a shorter video than the script asked for.

    When ``scrubber`` is supplied each image is passed through it before being
    returned, so the material the pipeline renders is already watermark-free.

    When ``holds`` is supplied (one exact duration per prompt) each still is
    pre-rendered into a clip of that length and the *clip* is staged. Without it
    every still shares ``clip_duration``, which is what the pipeline would do
    anyway — but that single int cannot represent a storyboard whose holds vary,
    and rounding them all up overruns the narration and drops the final stills.
    """
    if not prompts:
        raise FlowkitError("no prompts supplied")
    if holds is not None and len(holds) != len(prompts):
        raise FlowkitError(
            f"holds has {len(holds)} entries but there are {len(prompts)} prompts"
        )

    base_dir = Path(local_videos_dir) if local_videos_dir else _local_videos_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    task_dir = base_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    owns_source = source is None
    client = source or FlowkitImageSource()
    try:
        client.require_ready()
        staged: list[StagedImage] = []

        for index, prompt in enumerate(prompts, start=1):
            assets = client.generate_image(
                prompt,
                aspect_ratio=aspect_ratio,
                character_media_ids=character_media_ids,
            )
            asset = assets[0]
            stem = f"{index:02d}_{_slugify(prompt)}"
            raw_path = task_dir / f"{stem}{Path(asset.url.split('?')[0]).suffix or '.img'}"

            client.download(asset, raw_path)
            final_path, converted = _normalise_image(raw_path, task_dir, stem)

            width, height = _image_size(final_path)
            if min(width, height) < MIN_ACCEPTED_SIDE:
                final_path.unlink(missing_ok=True)
                raise FlowkitError(
                    f"image {index} for prompt {prompt!r} is {width}x{height}; the pipeline "
                    f"requires at least {MIN_MATERIAL_DIMENSION}px per side "
                    f"(tolerance {MIN_DIMENSION_TOLERANCE}px)."
                )

            # Scrub before staging so the material the pipeline renders is
            # already clean. Done after the resolution check so a rejected image
            # never costs a scrub.
            if scrubber is not None:
                scrubber.scrub(final_path)

            hold = float(holds[index - 1]) if holds is not None else None
            material_path = final_path
            rendered_clip = False
            if hold is not None:
                material_path = _render_exact_clip(final_path, hold)
                rendered_clip = True

            staged.append(
                StagedImage(
                    path=str(material_path.relative_to(base_dir)).replace(os.sep, "/"),
                    absolute_path=str(material_path),
                    prompt=prompt,
                    media_id=asset.media_id,
                    width=width,
                    height=height,
                    converted=converted,
                    duration=hold,
                    rendered_clip=rendered_clip,
                )
            )
            logger.info(
                "staged %d/%d %s (%dx%d%s%s)",
                index,
                len(prompts),
                staged[-1].path,
                width,
                height,
                ", converted" if converted else "",
                f", {hold:.2f}s clip" if rendered_clip else "",
            )

        return staged
    finally:
        if owns_source:
            client.close()


def fetch_project_scenes(
    client: FlowkitImageSource, project_ref: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch a FlowKit project's scenes in story order over HTTP.

    ``project_ref`` is a project id or an exact project name. Returns
    (project, scenes) with scenes sorted by ``display_order``. This is the
    read half of project mode; staging decides still-vs-video per scene.
    """
    ref = (project_ref or "").strip()
    if not ref:
        raise FlowkitError("project reference must be a project id or name")
    client.require_ready()
    try:
        project = client._get(f"/api/projects/{ref}")
    except FlowkitError:
        project = None
    if not project:
        projects = client._get("/api/projects")
        matches = [
            p
            for p in projects
            if str(p.get("name", "")).strip().lower() == ref.lower()
        ]
        if not matches:
            # A bare "not found" is unhelpful when the reference is a near miss.
            # "farmer_and_rusty" does not resolve, because the project is really
            # called "farmer_and_rusty - Ep 1: The Whispering Furrow" -- which is
            # exactly the name someone would write in flowkit_project. Name the
            # prefix matches and list what does exist, so the fix is one step
            # rather than a round of API poking.
            #
            # Deliberately a suggestion, not an auto-resolve: silently picking a
            # project from a prefix is how a run stages the wrong episode.
            available = sorted(
                str(p.get("name", "")).strip() for p in projects if p.get("name")
            )
            prefix = [
                name for name in available if name.lower().startswith(ref.lower())
            ]
            hint = (
                f" Did you mean {', '.join(repr(n) for n in prefix)}?"
                if prefix
                else ""
            )
            listing = "; ".join(available) if available else "none"
            raise FlowkitError(
                f"FlowKit project not found: {ref!r}.{hint} "
                f"Available projects: {listing}. "
                f"Pass an exact project id or name."
            )
        project = matches[0]
    scenes: list[dict[str, Any]] = []
    for video in client._get(f"/api/videos?project_id={project['id']}"):
        scenes.extend(client._get(f"/api/scenes?video_id={video['id']}"))
    scenes.sort(key=lambda s: s.get("display_order", 0))
    return project, scenes


def stage_flowkit_project(
    project_ref: str,
    task_id: str,
    *,
    clip_duration: int = DEFAULT_CLIP_DURATION,
    source: Optional[FlowkitImageSource] = None,
    local_videos_dir: Optional[Path] = None,
    scrubber: Optional["ProjectScrubber"] = None,
    media: str = "auto",
) -> tuple[list[Any], str]:
    """Stage one FlowKit project's completed media as local materials.

    Per scene, in story order: a COMPLETED vertical video wins (``media``
    ``auto`` or ``video``); otherwise the COMPLETED vertical still is
    downloaded, scrubbed and staged (``auto`` or ``still``). Stills reuse the
    same download guards, format normalisation and resolution checks as the
    prompt path — one staging standard, not two.

    Returns (staged, narration) where narration is the scenes'
    ``narrator_text`` stitched in order, for manifests that omit a script.
    """
    if media not in ("auto", "video", "still"):
        raise FlowkitError(f"unknown media mode {media!r}: use auto, video or still")
    base_dir = Path(local_videos_dir) if local_videos_dir else _local_videos_dir()
    base_dir.mkdir(parents=True, exist_ok=True)
    task_dir = base_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    owns_source = source is None
    client = source or FlowkitImageSource()
    try:
        project, scenes = fetch_project_scenes(client, project_ref)
        _refuse_if_all_media_expired(scenes, media, project)
        staged: list[Any] = []
        narrations: list[str] = []
        for order, scene in enumerate(scenes):
            video_url = scene.get("vertical_video_url")
            still_url = scene.get("vertical_image_url")
            # "COMPLETED" describes what Flow generated, not what is still
            # reachable: the URL can have expired since. Treating an expired
            # video as usable would make media="auto" fail where a perfectly
            # good still was available, which is the opposite of what the
            # fallback is for.
            video_completed = scene.get("vertical_video_status") == "COMPLETED"
            still_completed = scene.get("vertical_image_status") == "COMPLETED"
            video_ok = video_completed and _is_usable(video_url)
            still_ok = still_completed and _is_usable(still_url)
            if video_completed and video_url and not video_ok:
                logger.info(
                    "scene %d has a completed video whose signed URL has expired; "
                    "using the still if it is still reachable",
                    order,
                )
            prompt = str(scene.get("prompt", ""))
            if scene.get("narrator_text"):
                narrations.append(str(scene["narrator_text"]).strip())
            if media in ("auto", "video") and video_ok:
                dest = task_dir / f"{order:02d}_scene.mp4"
                client.download_video(
                    video_url,
                    scene.get("vertical_video_media_id", f"scene-{order}"),
                    dest,
                )
                if scrubber is not None:
                    scrubber.scrub_video(dest)
                staged.append(
                    StagedVideo(
                        path=str(dest.relative_to(base_dir)).replace(os.sep, "/"),
                        absolute_path=str(dest),
                        prompt=prompt,
                        media_id=str(scene.get("vertical_video_media_id", "")),
                        scene_id=str(scene.get("id", "")),
                    )
                )
            elif media in ("auto", "still") and still_ok:
                asset = ImageAsset(
                    media_id=str(scene.get("vertical_image_media_id", f"scene-{order}")),
                    url=still_url,
                    prompt=prompt,
                )
                raw = task_dir / f"{order:02d}_scene.download"
                client.download(asset, raw)
                stem = f"{order:02d}_{_slugify(prompt)}"
                final, converted = _normalise_image(raw, task_dir, stem)
                width, height = _image_size(final)
                if (
                    width < MIN_ACCEPTED_SIDE or height < MIN_ACCEPTED_SIDE
                ):
                    final.unlink(missing_ok=True)
                    raise FlowkitError(
                        f"staged still below {MIN_MATERIAL_DIMENSION}px: {width}x{height}"
                    )
                if scrubber is not None:
                    scrubber.scrub(final)
                staged.append(
                    StagedImage(
                        path=str(final.relative_to(base_dir)).replace(os.sep, "/"),
                        absolute_path=str(final),
                        prompt=prompt,
                        media_id=asset.media_id,
                        width=width,
                        height=height,
                        converted=converted,
                    )
                )
            else:
                logger.info("scene %d has no completed media; skipped", order)
                continue
            logger.info("staged %d/%d %s", order + 1, len(scenes), staged[-1].path)
        if not staged:
            want = "videos" if media == "video" else "stills" if media == "still" else "media"
            raise FlowkitError(
                f"project {project.get('name', project_ref)!r} has no completed {want} yet"
            )
        return staged, " ".join(n for n in narrations if n)
    finally:
        if owns_source:
            client.close()


def _absolute_material_urls(
    params: dict[str, Any], staged: Sequence[StagedImage | StagedVideo]
) -> dict[str, Any]:
    """Point emitted materials at absolute file locations.

    Staging keeps repo-relative paths (portable, and what the unit tests pin),
    but ``cli.py --batch-file`` resolves relative material URLs against the
    *manifest* directory — so a manifest outside ``storage/local_videos``
    would point at files that do not exist. Absolute paths survive that
    resolution and ``preprocess_video`` explicitly accepts them.
    """
    for material, item in zip(params.get("video_materials", []), staged):
        material["url"] = item.absolute_path
    return params


def apply_to_params(
    params: dict[str, Any],
    staged: Sequence[StagedImage | StagedVideo],
    clip_duration: int = DEFAULT_CLIP_DURATION,
) -> dict[str, Any]:
    """Point a ``VideoParams`` dict at the staged media.

    Mutates and returns ``params`` for convenience. ``video_source`` must be
    ``local`` — that is the branch in ``get_video_materials`` that reads
    ``video_materials`` instead of downloading stock footage.
    """
    if not staged:
        raise FlowkitError("no staged media to apply")
    params["video_source"] = "local"
    params["video_materials"] = [image.as_material(clip_duration) for image in staged]
    return params


def _main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="flowkit -> AutoShorts image bridge")
    parser.add_argument("--check", action="store_true", help="verify flowkit connectivity, generate nothing")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="load prompts/holds and print the plan, but generate nothing",
    )
    parser.add_argument("--url", default=None, help=f"flowkit base URL (default {FLOWKIT_DEFAULT_URL})")
    parser.add_argument("--project-id", default=None, help="Flow project id (else read from flowkit)")
    parser.add_argument("--prompts-file", default=None, help="one prompt per line; '#' comments")
    parser.add_argument(
        "--storyboard",
        default=None,
        help="storyboard/manifest JSON; supplies prompts AND exact per-still holds",
    )
    parser.add_argument(
        "--exact-timing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="with --storyboard, pre-render each still at its exact hold (default: on)",
    )
    parser.add_argument(
        "--emit-params",
        default=None,
        help="write a cli.py --batch-file params JSON using the staged materials",
    )
    parser.add_argument("--task-id", default="flowkit-bridge", help="subdirectory under storage/local_videos")
    parser.add_argument("--clip-duration", type=int, default=DEFAULT_CLIP_DURATION)
    parser.add_argument(
        "--from-project",
        default=None,
        help="stage completed media from a FlowKit project (id or name) instead of generating",
    )
    parser.add_argument(
        "--media",
        default="auto",
        choices=("auto", "video", "still"),
        help="with --from-project: prefer completed videos, stills only, or either (default: auto)",
    )
    parser.add_argument(
        "--aspect-ratio",
        default=DEFAULT_ASPECT_RATIO,
        help="flowkit aspect ratio enum (default PORTRAIT = 9:16)",
    )
    parser.add_argument(
        "--scrub",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="scrub Flow watermarks with the project's own engine (default: on)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # The scrubber is the project's own SCE engine (ffmpeg delogo), so the
    # project root must be importable before it can be loaded.
    scrubber = None
    if args.scrub:
        _ensure_project_root_on_path()
        try:
            scrubber = ProjectScrubber()
        except FlowkitError as exc:
            print(f"watermark scrubber failed to load: {exc}", file=sys.stderr)
            return 1
        if not scrubber.available():
            print(
                "watermark scrubber is enabled but ffmpeg was not found on PATH. "
                "Install ffmpeg or pass --no-scrub to stage watermarked media deliberately.",
                file=sys.stderr,
            )
            return 1

    # Argument problems are checked before touching the network: a typo'd path
    # should not require a running flowkit to diagnose.
    prompts: list[str] = []
    holds: Optional[list[float]] = None
    script_text = ""
    from_project = args.from_project
    if not args.check:
        if from_project and (args.storyboard or args.prompts_file):
            print(
                "pass either --from-project or --storyboard/--prompts-file, not both",
                file=sys.stderr,
            )
            return 2
        if args.storyboard and args.prompts_file:
            print(
                "pass either --storyboard or --prompts-file, not both "
                "(--storyboard already carries the prompts)",
                file=sys.stderr,
            )
            return 2

        if args.storyboard:
            _ensure_project_root_on_path()
            from automation.storyboard_prompts import StoryboardError, load_storyboard

            try:
                board = load_storyboard(args.storyboard)
            except StoryboardError as exc:
                print(f"storyboard error: {exc}", file=sys.stderr)
                return 2
            prompts = board.prompts()
            script_text = board.script
            if args.exact_timing:
                holds = board.holds()
            print(
                f"storyboard: {board.title} — {len(prompts)} stills, "
                f"{board.total_hold_seconds}s total, "
                f"{'uniform' if board.has_uniform_holds else 'varying'} holds"
                f"{' (exact timing)' if holds else ''}"
            )
            if script_text:
                print(f"narration:  {len(script_text)} chars (will drive the TTS voiceover)")
        elif args.prompts_file:
            prompts_path = Path(args.prompts_file)
            if not prompts_path.is_file():
                print(f"prompts file not found: {prompts_path}", file=sys.stderr)
                return 2
            prompts = [
                line.strip()
                for line in prompts_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if not prompts:
                print(f"no prompts found in {prompts_path}", file=sys.stderr)
                return 2
        elif from_project:
            pass
        else:
            print("nothing to do: pass --from-project, --storyboard, --prompts-file (or --check)", file=sys.stderr)
            return 2

    client = FlowkitImageSource(base_url=args.url, project_id=args.project_id)
    try:
        project_id = client.require_ready()
    except FlowkitError as exc:
        print(f"NOT READY: {exc}", file=sys.stderr)
        return 1

    health = client.health()
    print(f"flowkit {health.get('version', '?')} at {client.base_url}")
    print(f"extension connected: {health.get('extension_connected')}")
    print(f"flow project id:     {project_id}")

    if args.check:
        print("ready.")
        return 0

    if args.dry_run:
        if from_project:
            print(f"\ndry run — would stage completed {args.media} media from project {from_project}")
            print(f"  task dir:      storage/local_videos/{args.task_id}")
            print(f"  scrub:         {'on' if scrubber else 'off'}")
            if args.emit_params:
                print(f"  params out:    {args.emit_params}")
            return 0
        # Verify the whole plan before spending a single generation credit.
        print(f"\ndry run — would generate {len(prompts)} still(s)")
        if holds:
            print(f"  exact holds:   {', '.join(f'{h:.2f}' for h in holds)}s")
            print(f"  total runtime: {sum(holds):.2f}s")
        else:
            print(f"  clip duration: {args.clip_duration}s each "
                  f"(total {len(prompts) * args.clip_duration}s)")
        print(f"  task dir:      storage/local_videos/{args.task_id}")
        print(f"  scrub:         {'on' if scrubber else 'off'}")
        print(f"  aspect ratio:  {args.aspect_ratio}")
        print(f"  narration:     {len(script_text)} chars" if script_text else "  narration:     none (AutoShorts would write its own script)")
        if args.emit_params:
            print(f"  params out:    {args.emit_params}")
        return 0

    if from_project:
        try:
            staged, project_narration = stage_flowkit_project(
                from_project,
                args.task_id,
                clip_duration=args.clip_duration,
                source=client,
                scrubber=scrubber,
                media=args.media,
            )
        except FlowkitError as exc:
            print(f"FAILED: {exc}", file=sys.stderr)
            return 1
        if project_narration and not script_text:
            script_text = project_narration
        params = apply_to_params({"video_clip_duration": args.clip_duration}, staged, args.clip_duration)
        print(f"\nstaged {len(staged)} material(s) from project; video_source={params['video_source']}")
        for item in staged:
            print(f"  {item.path}")
        if args.emit_params:
            if script_text:
                params["video_script"] = script_text
            _absolute_material_urls(params, staged)
            out = Path(args.emit_params)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps([params], indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nparams written to {out}")
            print(f"run it with:  python cli.py --batch-file {out}")
        return 0
    else:
        staged = stage_flowkit_images(
        prompts,
        args.task_id,
        clip_duration=args.clip_duration,
        source=client,
        aspect_ratio=args.aspect_ratio,
        scrubber=scrubber,
        holds=holds,
    )
    params = apply_to_params({"video_clip_duration": args.clip_duration}, staged, args.clip_duration)
    total = sum(s.duration for s in staged if s.duration) or None
    print(f"\nstaged {len(staged)} material(s); video_source={params['video_source']}")
    if total:
        print(f"total runtime: {total:.2f}s")
    for image in staged:
        hold = f"{image.duration:.2f}s" if image.duration else "-"
        print(f"  {image.path}  {image.width}x{image.height}  {hold}")

    if args.emit_params:
        if script_text:
            params["video_script"] = script_text
        _absolute_material_urls(params, staged)
        out = Path(args.emit_params)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps([params], indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nparams written to {out}")
        print(f"run it with:  python cli.py --batch-file {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
