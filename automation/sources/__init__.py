"""Source registry.

Add a new source by writing a module in this package, importing its class here,
and registering it in ``SOURCE_TYPES``. The runner never needs to change.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from automation.sources.base import Source, Topic, normalize_text, normalize_url
from automation.sources.rss import RssSource
from automation.sources.topics_file import TopicsFileSource

SOURCE_TYPES: Dict[str, Callable[..., Source]] = {
    "rss": RssSource,
    "topics_file": TopicsFileSource,
}

# Config key holding the feed URL / file path, per source type.
_LOCATION_KEYS = {
    "rss": "url",
    "topics_file": "path",
}


def build_source(source_type: str, **kwargs: Any) -> Source:
    """Instantiate a source by type name.

    Raises ValueError with the available options rather than a bare KeyError, so
    a typo in ``.env`` produces an actionable message.
    """
    key = (source_type or "").strip().lower()
    if key not in SOURCE_TYPES:
        available = ", ".join(sorted(SOURCE_TYPES))
        raise ValueError(f"unknown source type {source_type!r}; available: {available}")
    return SOURCE_TYPES[key](**kwargs)


def build_from_settings(settings: Dict[str, Any]) -> Source:
    """Build a source from a flat settings dict.

    Expects ``source_type`` plus the type's location key (``url`` for rss,
    ``path`` for topics_file), with an optional ``source_name`` override.
    """
    source_type = str(settings.get("source_type") or "").strip().lower()
    if not source_type:
        raise ValueError("source_type is required")

    location_key = _LOCATION_KEYS.get(source_type)
    if location_key is None:
        available = ", ".join(sorted(SOURCE_TYPES))
        raise ValueError(f"unknown source type {source_type!r}; available: {available}")

    location = settings.get(location_key)
    if not location:
        raise ValueError(
            f"source type {source_type!r} requires {location_key!r} to be set"
        )

    kwargs: Dict[str, Any] = {location_key: location}
    if settings.get("source_name"):
        kwargs["name"] = settings["source_name"]
    return build_source(source_type, **kwargs)


__all__ = [
    "Source",
    "Topic",
    "RssSource",
    "TopicsFileSource",
    "SOURCE_TYPES",
    "build_source",
    "build_from_settings",
    "normalize_text",
    "normalize_url",
]
