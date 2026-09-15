"""The one rule for matching a scene's declared reference names to entities.

Why this is its own module
--------------------------
The rule — a declared name matches an entity by ``slug`` **or** display ``name``
— was implemented separately in ``sdk/services/operations.py`` (which generates
the image), and again in ``services/consistency.py`` (which reports on it).

Two copies of a matching rule is a correctness hazard, not just duplication: the
generator and the report would silently disagree the moment one side changed,
and the report would either flag scenes that were fine or clear scenes that were
not. That is exactly the failure this module exists to prevent, so all three
call sites import from here.

``operations.py`` importing this is also why it is deliberately dependency-free
— no DB, no HTTP, no SDK. It must be safe to import from anywhere.
"""

from __future__ import annotations

import json

#: Fields on a character/entity row that a scene may name it by.
_NAME_FIELDS = ("slug", "name")


def matches_entity(entity: dict, names: set[str]) -> bool:
    """Whether ``entity`` is named by any of ``names`` (slug or display name)."""
    slug = entity.get("slug") or ""
    name = entity.get("name") or ""
    return bool((slug and slug in names) or (name and name in names))


def entity_names(entity: dict) -> set[str]:
    """Every name an entity can be referenced by."""
    return {n for n in (entity.get(f) for f in _NAME_FIELDS) if n}


def declared_names(scene: dict) -> set[str]:
    """Parse ``scene['character_names']``, which is a JSON array stored as text.

    Tolerates a list (already parsed), a JSON string, ``None``, and a malformed
    value — a bad column should not take down a whole report.
    """
    raw = (scene or {}).get("character_names")
    if not raw:
        return set()
    if isinstance(raw, list):
        return {str(n) for n in raw if n}
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return set()
        if isinstance(parsed, list):
            return {str(n) for n in parsed if n}
    return set()


def resolve_matched(
    declared: set[str], linked: list[dict], *, require_media: bool = False
) -> tuple[set[str], set[str]]:
    """Split ``declared`` into ``(matched, unmatched)`` against ``linked``.

    ``require_media=True`` additionally requires the entity to have a reference
    image, which is what actually makes conditioning possible.
    """
    matched: set[str] = set()
    for entity in linked:
        if not matches_entity(entity, declared):
            continue
        if require_media and not entity.get("media_id"):
            continue
        matched |= entity_names(entity)
    return matched, declared - matched
