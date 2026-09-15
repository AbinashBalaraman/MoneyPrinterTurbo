"""Media API router — serve and inspect pipeline-generated media artifacts.

Provides:
- GET /api/media/file : Stream local media files with Range support (video seeking, audio, images)
- GET /api/media/artifacts : List recently generated media files across output/ and storage/
- GET /api/media/inspect : Inspect metadata of a media file
"""

from __future__ import annotations

import logging
import mimetypes
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])

# AutoShorts root directory: flowkit/agent/api/media.py -> parents[3]
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]

MEDIA_EXTENSIONS = {
    # Video
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    # Audio
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    # Images
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _resolve_safe_path(raw_path: str) -> Path:
    """Resolve a raw path ensuring it resides within WORKSPACE_ROOT."""
    candidate = Path(raw_path.strip().strip('"').strip("'"))
    if not candidate.is_absolute():
        resolved = (WORKSPACE_ROOT / candidate).resolve()
    else:
        resolved = candidate.resolve()

    # Prevent directory traversal outside the repository
    try:
        resolved.relative_to(WORKSPACE_ROOT.resolve())
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: Path '{raw_path}' is outside the project workspace.",
        )

    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Media file not found: '{raw_path}'",
        )

    return resolved


@router.get("/file")
async def stream_media_file(path: str = Query(..., description="Relative or absolute path to the media file")):
    """Stream a local media file with HTTP Range support for scrubbing/seeking in video & audio."""
    resolved = _resolve_safe_path(path)
    suffix = resolved.suffix.lower()

    content_type = MEDIA_EXTENSIONS.get(suffix)
    if not content_type:
        guessed, _ = mimetypes.guess_type(str(resolved))
        content_type = guessed or "application/octet-stream"

    return FileResponse(
        path=str(resolved),
        media_type=content_type,
        filename=resolved.name,
    )


@router.get("/artifacts")
async def list_media_artifacts(
    limit: int = Query(60, ge=1, le=200, description="Max artifacts to return"),
    media_type: Optional[str] = Query(None, description="Filter by 'video', 'image', or 'audio'"),
):
    """Scan and list recently generated media artifacts across output/ and storage/."""
    search_dirs = [
        WORKSPACE_ROOT / "output",
        WORKSPACE_ROOT / "storage",
        WORKSPACE_ROOT / "flowkit" / "output",
        WORKSPACE_ROOT / "shorts_content_engine" / "output",
    ]

    artifacts = []
    seen_paths = set()

    for search_dir in search_dirs:
        if not search_dir.exists() or not search_dir.is_dir():
            continue

        try:
            for root, dirs, files in os.walk(search_dir):
                # Skip git, cache, and build folders
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "dist")]

                for f in files:
                    ext = Path(f).suffix.lower()
                    if ext not in MEDIA_EXTENSIONS:
                        continue

                    full_path = Path(root) / f
                    resolved_str = str(full_path.resolve())
                    if resolved_str in seen_paths:
                        continue
                    seen_paths.add(resolved_str)

                    try:
                        stat = full_path.stat()
                    except OSError:
                        continue

                    mtype = "video" if ext in (".mp4", ".webm", ".mov", ".mkv") else ("audio" if ext in (".mp3", ".wav", ".ogg", ".m4a") else "image")
                    if media_type and media_type != mtype:
                        continue

                    try:
                        rel_path = str(full_path.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
                    except ValueError:
                        rel_path = str(full_path).replace("\\", "/")

                    artifacts.append({
                        "name": f,
                        "path": rel_path,
                        "type": mtype,
                        "size_bytes": stat.st_size,
                        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                        "timestamp": stat.st_mtime,
                        "preview_url": f"/api/media/file?path={rel_path}",
                    })
        except Exception as e:
            logger.warning("Error scanning %s for artifacts: %s", search_dir, e)

    # Sort newest first
    artifacts.sort(key=lambda a: a["timestamp"], reverse=True)
    return {
        "artifacts": artifacts[:limit],
        "total": len(artifacts),
    }


@router.get("/inspect")
async def inspect_media_file(path: str = Query(..., description="Path to media file to inspect")):
    """Get metadata about a media file (size, modified time, mime type)."""
    resolved = _resolve_safe_path(path)
    stat = resolved.stat()
    suffix = resolved.suffix.lower()
    
    mtype = "video" if suffix in (".mp4", ".webm", ".mov", ".mkv") else ("audio" if suffix in (".mp3", ".wav", ".ogg", ".m4a") else "image")

    try:
        rel_path = str(resolved.relative_to(WORKSPACE_ROOT)).replace("\\", "/")
    except ValueError:
        rel_path = str(resolved).replace("\\", "/")

    return {
        "name": resolved.name,
        "path": rel_path,
        "absolute_path": str(resolved),
        "type": mtype,
        "mime_type": MEDIA_EXTENSIONS.get(suffix, "application/octet-stream"),
        "size_bytes": stat.st_size,
        "size_formatted": _format_bytes(stat.st_size),
        "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        "preview_url": f"/api/media/file?path={rel_path}",
    }


def _format_bytes(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"
