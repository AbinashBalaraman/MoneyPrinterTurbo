"""Source abstraction for the automation pipeline.

A *source* is anything that produces candidate video topics: an RSS feed, a
trending list, an API, or a file you maintain by hand. The pipeline only needs
two things from a source -- a name, and a list of :class:`Topic` objects -- so
swapping the source is a new file in this package, not a change to the runner.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional, Protocol, runtime_checkable

_WHITESPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize_text(value: str) -> str:
    """Fold a string into a comparison-safe form.

    Case, punctuation and whitespace all differ between runs of the same feed,
    so they are stripped before hashing. Unicode is normalised so that
    composed and decomposed accents hash identically.
    """
    folded = unicodedata.normalize("NFKC", value or "").casefold()
    folded = _NON_WORD.sub(" ", folded)
    return _WHITESPACE.sub(" ", folded).strip()


def normalize_url(value: str) -> str:
    """Strip the parts of a URL that change between fetches of the same item."""
    url = (value or "").strip()
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    url = url.split("#", 1)[0]
    return url.rstrip("/").casefold()


@dataclass
class Topic:
    """One candidate video subject, plus the provenance needed to dedupe it."""

    source: str
    title: str
    url: Optional[str] = None
    external_id: Optional[str] = None
    published_at: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable dedupe key.

        Preference order is deliberate: a publisher-assigned id is the most
        reliable, then the URL, and only then a hash of the title. Title hashing
        is last because two genuinely different articles can share a headline.
        """
        if self.external_id:
            return f"{self.source}:id:{normalize_text(str(self.external_id))}"
        if self.url and normalize_url(self.url):
            return f"{self.source}:url:{normalize_url(self.url)}"
        digest = hashlib.sha1(
            normalize_text(self.title).encode("utf-8")
        ).hexdigest()[:16]
        return f"{self.source}:title:{digest}"

    def __post_init__(self) -> None:
        self.title = _WHITESPACE.sub(" ", (self.title or "").strip())
        if not self.title:
            raise ValueError("Topic.title must not be empty")


@runtime_checkable
class Source(Protocol):
    """Anything the runner can pull candidate topics from."""

    name: str

    def fetch(self, limit: int = 20) -> Iterable[Topic]:
        """Return up to ``limit`` candidate topics, newest first.

        Implementations must be safe to call repeatedly: the ledger, not the
        source, is responsible for deduplication.
        """
        ...
