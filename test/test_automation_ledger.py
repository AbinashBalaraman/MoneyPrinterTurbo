"""Tests for the AutoShorts dedupe ledger.

The ledger is what stands between an unattended pipeline and duplicate uploads,
so its guarantees are tested directly rather than inferred.
"""

from automation.ledger import (
    STATUS_CLAIMED,
    STATUS_FAILED,
    STATUS_GENERATED,
    Ledger,
)
from automation.sources.base import Topic, normalize_text, normalize_url


def _ledger(tmp_path) -> Ledger:
    return Ledger(str(tmp_path / "ledger.db"))


# --------------------------------------------------------------- dedupe keys


def test_key_is_stable_across_case_and_punctuation():
    a = Topic(source="rss", title="Why Deep-Sea Creatures Glow!")
    b = Topic(source="rss", title="why deep sea creatures glow")
    assert a.key == b.key


def test_key_prefers_external_id_then_url_then_title():
    by_id = Topic(source="rss", title="Same headline", url="https://a/1", external_id="42")
    by_url = Topic(source="rss", title="Same headline", url="https://a/1")
    by_title = Topic(source="rss", title="Same headline")

    assert by_id.key.startswith("rss:id:")
    assert by_url.key.startswith("rss:url:")
    assert by_title.key.startswith("rss:title:")
    assert len({by_id.key, by_url.key, by_title.key}) == 3


def test_url_key_ignores_scheme_www_and_fragment():
    a = Topic(source="rss", title="x", url="https://www.example.com/post#section")
    b = Topic(source="rss", title="x", url="http://example.com/post/")
    assert a.key == b.key


def test_same_title_from_different_sources_does_not_collide():
    a = Topic(source="feed_a", title="Shared headline")
    b = Topic(source="feed_b", title="Shared headline")
    assert a.key != b.key


def test_normalizers_handle_empty_input():
    assert normalize_text("") == ""
    assert normalize_url("") == ""


# -------------------------------------------------------------------- claims


def test_claim_succeeds_once_then_refuses(tmp_path):
    with _ledger(tmp_path) as ledger:
        assert ledger.claim("k1", "rss", "First") is True
        # A second, concurrent run must not be able to claim the same topic.
        assert ledger.claim("k1", "rss", "First") is False
        assert ledger.get_topic("k1")["status"] == STATUS_CLAIMED


def test_claimed_topic_is_skipped(tmp_path):
    with _ledger(tmp_path) as ledger:
        assert ledger.should_skip("unknown") is False
        ledger.claim("k1", "rss", "First")
        assert ledger.should_skip("k1") is True


def test_generated_topic_is_never_reclaimed(tmp_path):
    with _ledger(tmp_path) as ledger:
        ledger.claim("k1", "rss", "First")
        ledger.mark_generated("k1")
        assert ledger.is_done("k1") is True
        assert ledger.should_skip("k1") is True
        assert ledger.claim("k1", "rss", "First") is False


def test_failed_topic_retries_until_budget_is_spent(tmp_path):
    with _ledger(tmp_path) as ledger:
        # First claim consumes attempt 1.
        assert ledger.claim("k1", "rss", "Flaky") is True
        ledger.mark_failed("k1", "boom")

        # Retryable while under the attempt budget (default max is 3).
        assert ledger.claim("k1", "rss", "Flaky") is True
        ledger.mark_failed("k1", "boom")
        assert ledger.claim("k1", "rss", "Flaky") is True
        ledger.mark_failed("k1", "boom")

        # Budget spent: no more automatic retries.
        assert ledger.claim("k1", "rss", "Flaky") is False
        assert ledger.should_skip("k1") is True
        assert ledger.get_topic("k1")["status"] == STATUS_FAILED


# ------------------------------------------------------------------- outputs


def test_record_output_is_idempotent(tmp_path):
    with _ledger(tmp_path) as ledger:
        ledger.claim("k1", "rss", "First")
        ledger.start_run("run-1", "rss", 1, dry_run=False)

        for _ in range(3):
            ledger.record_output(
                topic_key="k1",
                run_id="run-1",
                task_id="task-1",
                state="generated",
                video_paths=["/tmp/a.mp4"],
                cross_post_state="complete",
            )

        # Re-parsing the same CLI summary must not inflate the upload count.
        assert ledger.stats()["uploads_recorded"] == 1


def test_distinct_tasks_are_recorded_separately(tmp_path):
    with _ledger(tmp_path) as ledger:
        ledger.start_run("run-1", "rss", 2, dry_run=False)
        for index in (1, 2):
            ledger.claim(f"k{index}", "rss", f"Topic {index}")
            ledger.record_output(
                topic_key=f"k{index}",
                run_id="run-1",
                task_id=f"task-{index}",
                state="generated",
                cross_post_state="complete",
            )
        assert ledger.stats()["uploads_recorded"] == 2


def test_stats_report_topic_statuses(tmp_path):
    with _ledger(tmp_path) as ledger:
        ledger.claim("k1", "rss", "A")
        ledger.mark_generated("k1")
        ledger.claim("k2", "rss", "B")
        ledger.mark_failed("k2", "boom")

        stats = ledger.stats()
        assert stats["topics"][STATUS_GENERATED] == 1
        assert stats["topics"][STATUS_FAILED] == 1
        assert stats["runs"] == 0


def test_ledger_survives_reopen(tmp_path):
    path = str(tmp_path / "ledger.db")
    with Ledger(path) as ledger:
        ledger.claim("k1", "rss", "First")
        ledger.mark_generated("k1")

    with Ledger(path) as reopened:
        assert reopened.is_done("k1") is True
        assert reopened.should_skip("k1") is True
