"""RSS 2.0 / Atom source.

Implemented with the standard library only -- no ``feedparser`` dependency, so
nothing needs to be added to ``pyproject.toml`` and the lockfile stays frozen.

Handles both feed dialects, which differ in almost every detail:

* RSS 2.0:  ``<item><title> <link> <guid> <pubDate>``
* Atom:     ``<entry><title> <link href> <id> <updated>``
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Iterable, List, Optional

from automation.sources.base import Topic

USER_AGENT = "AutoShorts/1.0 (+rss source)"
DEFAULT_TIMEOUT = 20

# Atom namespaces vary by producer; match on the local tag name instead of
# hard-coding one namespace URI.
_ATOM_LINK_RELS = ("alternate", "", None)


def _local_name(tag: str) -> str:
    """Return the tag without its ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_text(element: ET.Element, *names: str) -> Optional[str]:
    for child in element:
        if _local_name(child.tag) in names:
            text = (child.text or "").strip()
            if text:
                return text
    return None


def _find_link(element: ET.Element) -> Optional[str]:
    """Extract a link from either dialect.

    RSS puts the URL in the element text; Atom puts it in an ``href`` attribute
    and may offer several links distinguished by ``rel``.
    """
    candidates: List[tuple[str, str]] = []
    for child in element:
        if _local_name(child.tag) != "link":
            continue
        href = (child.get("href") or "").strip()
        if href:
            candidates.append((child.get("rel") or "", href))
        elif (child.text or "").strip():
            candidates.append(("", child.text.strip()))

    for rel in _ATOM_LINK_RELS:
        for candidate_rel, href in candidates:
            if candidate_rel == rel:
                return href
    return candidates[0][1] if candidates else None


class RssSource:
    """Pull topics from an RSS or Atom feed.

    ``url`` may be an ``http(s)`` URL, a local file path, or a ``file://`` URI,
    which makes the source testable without network access.
    """

    def __init__(
        self,
        url: str,
        name: str = "rss",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        if not url or not url.strip():
            raise ValueError("RssSource requires a feed url")
        self.url = url.strip()
        self.name = name
        self.timeout = timeout

    def _read(self) -> bytes:
        if self.url.startswith(("http://", "https://")):
            request = urllib.request.Request(
                self.url,
                headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"},
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()

        path = self.url
        if path.startswith("file://"):
            path = path[len("file://") :]
        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"feed file not found: {path}")
        with open(path, "rb") as handle:
            return handle.read()

    def fetch(self, limit: int = 20) -> Iterable[Topic]:
        """Fetch and parse the feed, returning at most ``limit`` topics.

        Order is the feed's own order, which for both dialects is newest first.
        A malformed individual entry is skipped rather than failing the run --
        one bad item should not stall the whole pipeline.
        """
        if limit <= 0:
            return []

        raw = self._read()
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError(f"could not parse feed {self.url}: {exc}") from exc

        # RSS items live under channel; Atom entries live directly under feed.
        entries = [el for el in root.iter() if _local_name(el.tag) in ("item", "entry")]
        if not entries:
            # Some feeds nest further; fall back to a shallow search.
            for channel in root.iter():
                if _local_name(channel.tag) == "channel":
                    entries = [
                        el
                        for el in channel
                        if _local_name(el.tag) in ("item", "entry")
                    ]
                    if entries:
                        break

        topics: List[Topic] = []
        for entry in entries:
            if len(topics) >= limit:
                break
            title = _find_text(entry, "title")
            if not title:
                continue
            try:
                topics.append(
                    Topic(
                        source=self.name,
                        title=title,
                        url=_find_link(entry),
                        external_id=_find_text(entry, "guid", "id"),
                        published_at=_find_text(
                            entry, "pubDate", "published", "updated", "date"
                        ),
                    )
                )
            except ValueError:
                continue

        if not topics:
            raise ValueError(
                f"feed {self.url} parsed but contained no usable entries "
                f"({len(entries)} raw entries)"
            )
        return topics
