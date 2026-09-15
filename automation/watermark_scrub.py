"""Strip Google's visible Gemini/Flow watermark from generated stills.

Why this exists
---------------
Flow's image output carries a visible semi-transparent Gemini sparkle badge in
the bottom-right corner. Verified on a real generation: 48x48 at (647, 1255) on
a 768x1376 still. The pixel-level test that "proved" it was absent was wrong —
the badge is subtle enough to miss by eye, but the scrubber's detector scored it
"strong" evidence and removed it, and a before/after crop shows the badge and
the recovered earth texture underneath it.

Why not SCE's scrubber
----------------------
``shorts_content_engine/src/postprocess/watermark.py`` uses ffmpeg ``delogo``,
which interpolates over a rectangle — it leaves a smudge and destroys whatever
was behind the badge. This module drives ``GargantuaX/gemini-watermark-remover``
(MIT, ~5.5k stars) which uses **reverse alpha blending**::

    watermarked = alpha * logo + (1 - alpha) * original
    original    = (watermarked - alpha * logo) / (1 - alpha)

That recovers the true underlying pixels instead of guessing. On the test still
it changed 993 of 1,056,768 pixels (0.094%) and reconstructed the cracked-earth
pattern through the badge. No GPU and no ML model — it is pure arithmetic, so it
is fast and deterministic enough to run on every still in a batch.

Limits, stated plainly
----------------------
It removes the **visible** badge only. It cannot touch SynthID, which is an
invisible watermark embedded in the pixels and designed to survive re-encoding.
Nothing in this pipeline removes SynthID.

A missing scrubber is treated as a hard failure, not a skip. Silently shipping
watermarked frames is exactly the kind of quiet degradation that makes an
unattended run untrustworthy.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)

GWR_PACKAGE = "@pilio/gemini-watermark-remover"
GWR_ENTRY_RELATIVE = Path("node_modules") / "@pilio" / "gemini-watermark-remover" / "bin" / "gwr.mjs"
DEFAULT_SCRUB_TIMEOUT = 180.0


class WatermarkScrubError(RuntimeError):
    """The scrubber could not run, or reported a failure."""


@dataclass
class ScrubResult:
    """What the scrubber did to one file."""

    path: str
    applied: bool
    """True when a watermark was found and removed."""

    size: Optional[int] = None
    position: Optional[dict] = None
    quality_status: Optional[str] = None
    decision_tier: Optional[str] = None
    raw: Optional[dict] = None

    @property
    def found_watermark(self) -> bool:
        return bool(self.applied)


def _node_executable() -> str:
    """Prefer the managed Node runtime, then PATH."""
    configured = os.getenv("AUTOSHORTS_NODE")
    if configured and Path(configured).exists():
        return configured

    managed_root = Path.home() / ".workbuddy-ai" / "binaries" / "node" / "versions"
    if managed_root.is_dir():
        candidates = sorted(managed_root.glob("*/node.exe")) or sorted(managed_root.glob("*/bin/node"))
        if candidates:
            return str(candidates[-1])

    found = shutil.which("node")
    if not found:
        raise WatermarkScrubError(
            "no Node runtime found. Install Node, or set AUTOSHORTS_NODE to the node executable."
        )
    return found


def _resolve_gwr_entry() -> Path:
    """Locate the scrubber entry point.

    Order: explicit override, then the managed Node workspace, then a project
    local install. ``npx`` is deliberately not used as a fallback — it would
    silently fetch a package from the network mid-batch.
    """
    override = os.getenv("AUTOSHORTS_GWR_ENTRY")
    if override:
        path = Path(override)
        if not path.exists():
            raise WatermarkScrubError(f"AUTOSHORTS_GWR_ENTRY does not exist: {path}")
        return path

    workspaces = [
        Path.home() / ".workbuddy-ai" / "binaries" / "node" / "workspace",
        Path(__file__).resolve().parent.parent,
    ]
    for workspace in workspaces:
        candidate = workspace / GWR_ENTRY_RELATIVE
        if candidate.exists():
            return candidate

    raise WatermarkScrubError(
        f"{GWR_PACKAGE} is not installed. Run:\n"
        f'  npm install {GWR_PACKAGE} sharp\n'
        "from the Node workspace, or set AUTOSHORTS_GWR_ENTRY to bin/gwr.mjs."
    )


class GeminiWatermarkScrubber:
    """Drives the gwr CLI over one or many image files."""

    def __init__(
        self,
        node: Optional[str] = None,
        entry: Optional[Path] = None,
        timeout: float = DEFAULT_SCRUB_TIMEOUT,
        extra_args: Optional[Sequence[str]] = None,
    ) -> None:
        self._node = node
        self._entry = entry
        self.timeout = float(timeout)
        self.extra_args = list(extra_args or [])

    @property
    def node(self) -> str:
        if self._node is None:
            self._node = _node_executable()
        return self._node

    @property
    def entry(self) -> Path:
        if self._entry is None:
            self._entry = _resolve_gwr_entry()
        return self._entry

    def available(self) -> bool:
        """True when both Node and the scrubber can be located."""
        try:
            return bool(self.node) and self.entry.exists()
        except WatermarkScrubError:
            return False

    def scrub(self, image_path: Path, output_path: Optional[Path] = None) -> ScrubResult:
        """Remove the watermark from ``image_path``.

        Writes to ``output_path`` when given, otherwise scrubs in place via a
        temporary file so a crash cannot leave a half-written image where the
        video pipeline expects a material.
        """
        image_path = Path(image_path)
        if not image_path.is_file():
            raise WatermarkScrubError(f"no such image: {image_path}")

        in_place = output_path is None
        target = image_path.with_suffix(".scrub.tmp" + image_path.suffix) if in_place else Path(output_path)

        cmd = [
            self.node,
            str(self.entry),
            "remove",
            str(image_path),
            "--output",
            str(target),
            "--json",
            *self.extra_args,
        ]

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WatermarkScrubError(f"scrub timed out after {self.timeout}s for {image_path}") from exc
        except OSError as exc:
            raise WatermarkScrubError(f"could not launch the scrubber for {image_path}: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:400]
            raise WatermarkScrubError(f"scrubber exited {completed.returncode} for {image_path}: {detail}")

        payload = self._parse_json(completed.stdout, image_path)
        meta = payload.get("meta") or {}
        result = ScrubResult(
            path=str(image_path),
            applied=bool(meta.get("applied")),
            size=meta.get("size"),
            position=meta.get("position"),
            quality_status=meta.get("qualityStatus"),
            decision_tier=meta.get("decisionTier"),
            raw=payload,
        )

        if in_place:
            if not target.exists():
                raise WatermarkScrubError(f"scrubber reported success but wrote no output for {image_path}")
            target.replace(image_path)

        if result.applied:
            logger.info(
                "watermark removed: %s (%sx%s at %s, quality=%s)",
                image_path.name,
                result.position.get("width") if result.position else result.size,
                result.position.get("height") if result.position else result.size,
                f"({result.position.get('x')},{result.position.get('y')})" if result.position else "unknown",
                result.quality_status,
            )
        else:
            logger.info("no watermark detected: %s", image_path.name)

        return result

    def scrub_many(self, paths: Sequence[Path]) -> list[ScrubResult]:
        return [self.scrub(Path(p)) for p in paths]

    @staticmethod
    def _parse_json(stdout: str, image_path: Path) -> dict:
        text = (stdout or "").strip()
        if not text:
            raise WatermarkScrubError(f"scrubber produced no JSON for {image_path}")
        # The CLI emits a single JSON object, but tolerate leading log lines.
        start = text.find("{")
        if start < 0:
            raise WatermarkScrubError(f"scrubber output was not JSON for {image_path}: {text[:200]}")
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError as exc:
            raise WatermarkScrubError(f"could not parse scrubber JSON for {image_path}: {exc}") from exc


def _main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="remove the Gemini/Flow watermark from images")
    parser.add_argument("images", nargs="+", help="image files to scrub")
    parser.add_argument("--check", action="store_true", help="report whether the scrubber is available")
    parser.add_argument("--timeout", type=float, default=DEFAULT_SCRUB_TIMEOUT)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    scrubber = GeminiWatermarkScrubber(timeout=args.timeout)

    if args.check:
        try:
            print(f"node:  {scrubber.node}")
            print(f"entry: {scrubber.entry}")
            print("available.")
            return 0
        except WatermarkScrubError as exc:
            print(f"NOT AVAILABLE: {exc}", file=sys.stderr)
            return 1

    scrubbed = 0
    for image in args.images:
        try:
            result = scrubber.scrub(Path(image))
        except WatermarkScrubError as exc:
            print(f"FAILED {image}: {exc}", file=sys.stderr)
            return 1
        scrubbed += 1 if result.applied else 0
        print(f"{'removed' if result.applied else 'clean  '}  {image}")
    print(f"\n{scrubbed} of {len(args.images)} had a watermark removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
