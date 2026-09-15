"""Plain-text topic backlog source.

For when "reactive" should still be under human control. One topic per line,
``#`` comments and blank lines ignored, and an optional reference URL after a
``|`` separator::

    # topics.txt
    Why deep-sea creatures glow
    The physics of a perfect espresso shot | https://example.com/espresso
    How cities are redesigning for heat

This is the safest source to start with: nothing is generated that you did not
write down yourself.
"""

from __future__ import annotations

import os
from typing import Iterable, List

from automation.sources.base import Topic


class TopicsFileSource:
    """Read candidate topics from a newline-delimited text file."""

    def __init__(self, path: str, name: str = "topics_file"):
        if not path or not path.strip():
            raise ValueError("TopicsFileSource requires a file path")
        self.path = os.path.expanduser(path.strip())
        self.name = name

    def fetch(self, limit: int = 20) -> Iterable[Topic]:
        if limit <= 0:
            return []
        if not os.path.isfile(self.path):
            raise FileNotFoundError(f"topics file not found: {self.path}")

        topics: List[Topic] = []
        with open(self.path, "r", encoding="utf-8-sig") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                title, _, url = line.partition("|")
                title = title.strip()
                if not title:
                    continue
                try:
                    topics.append(
                        Topic(
                            source=self.name,
                            title=title,
                            url=url.strip() or None,
                            # Line number is a poor identity: editing the file
                            # shifts it. Use title/url so reordering is safe.
                            external_id=None,
                            extra={"line": line_number},
                        )
                    )
                except ValueError:
                    continue
                if len(topics) >= limit:
                    break

        if not topics:
            raise ValueError(f"topics file contained no usable topics: {self.path}")
        return topics
