"""Resolves character reference photos from the Charectors/ folder.

The repo uses the literal folder name ``Charectors`` (with that spelling).
Matching is case-insensitive so manifest names like ``Arthur`` resolve to
``Charectors/Arthur/*.webp|*.jpg|*.png``.
"""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = {".webp", ".jpg", ".jpeg", ".png", ".bmp"}


class CharacterPhotoResolver:
    """Maps character display names to on-disk reference photos."""

    def __init__(self, characters_dir: str | Path) -> None:
        self.characters_dir = Path(characters_dir)
        if not self.characters_dir.exists():
            raise FileNotFoundError(f"Characters folder not found: {self.characters_dir}")
        # index subfolders by lowercased name for case-insensitive lookup
        self._dir_by_lower: dict[str, Path] = {}
        for child in self.characters_dir.iterdir():
            if child.is_dir():
                self._dir_by_lower[child.name.strip().lower()] = child

    def resolve(self, character_name: str) -> list[str]:
        """Returns sorted photo paths for a character, or [] if none found."""
        key = character_name.strip().lower()
        folder = self._dir_by_lower.get(key)
        if folder is None:
            return []
        photos = [
            str(p.resolve())
            for p in sorted(folder.iterdir())
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS
        ]
        return photos

    def resolve_all(self, character_names: list[str]) -> dict[str, list[str]]:
        """Resolves photos for every name in the list."""
        return {name: self.resolve(name) for name in character_names}

    def available_characters(self) -> list[str]:
        """Lists subfolder names that contain at least one image."""
        out: list[str] = []
        for name, folder in sorted(self._dir_by_lower.items()):
            has_image = any(
                p.is_file() and p.suffix.lower() in IMAGE_EXTS for p in folder.iterdir()
            )
            if has_image:
                out.append(folder.name)
        return out
