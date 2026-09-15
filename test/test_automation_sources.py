"""Tests for the AutoShorts topic sources.

Both feed dialects are exercised against local fixtures so the tests do not
depend on network access or on any particular feed staying online.
"""

import pytest

from automation.sources import build_from_settings, build_source
from automation.sources.rss import RssSource
from automation.sources.topics_file import TopicsFileSource

RSS_2_0 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>First RSS item</title>
      <link>https://example.com/first</link>
      <guid>guid-1</guid>
      <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second RSS item</title>
      <link>https://example.com/second</link>
      <guid>guid-2</guid>
    </item>
  </channel>
</rss>
"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Feed</title>
  <entry>
    <title>First Atom entry</title>
    <link rel="alternate" href="https://example.com/atom-first"/>
    <id>urn:uuid:1111</id>
    <updated>2026-09-01T10:00:00Z</updated>
  </entry>
  <entry>
    <title>Second Atom entry</title>
    <link rel="edit" href="https://example.com/edit-link"/>
    <link rel="alternate" href="https://example.com/atom-second"/>
    <id>urn:uuid:2222</id>
  </entry>
</feed>
"""

MALFORMED_ENTRY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item><title>Good item</title><link>https://example.com/good</link></item>
    <item><link>https://example.com/no-title</link></item>
  </channel>
</rss>
"""


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


# ------------------------------------------------------------------- RSS 2.0


def test_parses_rss_2_0(tmp_path):
    source = RssSource(_write(tmp_path, "feed.xml", RSS_2_0))
    topics = list(source.fetch(limit=10))

    assert [t.title for t in topics] == ["First RSS item", "Second RSS item"]
    assert topics[0].url == "https://example.com/first"
    assert topics[0].external_id == "guid-1"
    assert topics[0].published_at == "Mon, 01 Sep 2026 10:00:00 GMT"
    assert topics[0].key.startswith("rss:id:")


def test_limit_is_respected(tmp_path):
    source = RssSource(_write(tmp_path, "feed.xml", RSS_2_0))
    assert len(list(source.fetch(limit=1))) == 1
    assert list(source.fetch(limit=0)) == []


def test_custom_source_name_flows_into_key(tmp_path):
    source = RssSource(_write(tmp_path, "feed.xml", RSS_2_0), name="my_feed")
    topics = list(source.fetch(limit=1))
    assert topics[0].source == "my_feed"
    assert topics[0].key.startswith("my_feed:")


# ---------------------------------------------------------------------- Atom


def test_parses_atom_and_prefers_alternate_link(tmp_path):
    source = RssSource(_write(tmp_path, "atom.xml", ATOM))
    topics = list(source.fetch(limit=10))

    assert [t.title for t in topics] == ["First Atom entry", "Second Atom entry"]
    # rel="alternate" must win over rel="edit".
    assert topics[1].url == "https://example.com/atom-second"
    assert topics[0].external_id == "urn:uuid:1111"


# ----------------------------------------------------------------- resilience


def test_entry_without_title_is_skipped_not_fatal(tmp_path):
    source = RssSource(_write(tmp_path, "partial.xml", MALFORMED_ENTRY))
    topics = list(source.fetch(limit=10))
    assert [t.title for t in topics] == ["Good item"]


def test_unparseable_feed_raises_value_error(tmp_path):
    source = RssSource(_write(tmp_path, "bad.xml", "not xml at all"))
    with pytest.raises(ValueError):
        list(source.fetch())


def test_feed_with_no_usable_entries_raises(tmp_path):
    source = RssSource(_write(tmp_path, "empty.xml", "<rss><channel></channel></rss>"))
    with pytest.raises(ValueError):
        list(source.fetch())


def test_missing_file_raises(tmp_path):
    source = RssSource(str(tmp_path / "nope.xml"))
    with pytest.raises(FileNotFoundError):
        list(source.fetch())


# --------------------------------------------------------------- topics file


def test_topics_file_skips_comments_and_blanks(tmp_path):
    path = _write(
        tmp_path,
        "topics.txt",
        "# a comment\n\nFirst topic\nSecond topic | https://example.com/ref\n",
    )
    topics = list(TopicsFileSource(path).fetch(limit=10))

    assert [t.title for t in topics] == ["First topic", "Second topic"]
    assert topics[0].url is None
    assert topics[1].url == "https://example.com/ref"


def test_topics_file_is_order_independent(tmp_path):
    """Reordering the backlog must not change a topic's identity."""
    path = _write(tmp_path, "topics.txt", "Alpha\nBeta\n")
    before = {t.title: t.key for t in TopicsFileSource(path).fetch(limit=10)}

    reordered = _write(tmp_path, "topics2.txt", "Beta\nAlpha\n")
    after = {t.title: t.key for t in TopicsFileSource(reordered).fetch(limit=10)}

    assert before == after


def test_topics_file_empty_raises(tmp_path):
    path = _write(tmp_path, "empty.txt", "# only a comment\n")
    with pytest.raises(ValueError):
        list(TopicsFileSource(path).fetch())


# ------------------------------------------------------------------- factory


def test_build_source_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown source type"):
        build_source("carrier_pigeon", url="x")


def test_build_from_settings_requires_location():
    with pytest.raises(ValueError, match="requires 'url'"):
        build_from_settings({"source_type": "rss"})
    with pytest.raises(ValueError, match="source_type is required"):
        build_from_settings({})


def test_build_from_settings_selects_the_right_location_key(tmp_path):
    path = _write(tmp_path, "topics.txt", "A topic\n")
    source = build_from_settings({"source_type": "topics_file", "path": path})
    assert isinstance(source, TopicsFileSource)
    assert len(list(source.fetch(limit=1))) == 1
