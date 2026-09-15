"""Unit tests for the assistant's persistent memory + conversation store."""

import pytest

from agent.services import agent_memory


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the module at a throwaway directory."""
    monkeypatch.setattr(agent_memory, "BASE_DIR", tmp_path)
    monkeypatch.setattr(agent_memory, "MEMORY_FILE", tmp_path / "memory.md")
    monkeypatch.setattr(agent_memory, "CONVERSATIONS_DIR", tmp_path / "conversations")
    return tmp_path


# ---------------------------------------------------------------------------
# Long-term memory
# ---------------------------------------------------------------------------

class TestLongTermMemory:
    def test_read_returns_empty_string_when_file_missing(self, store):
        assert agent_memory.read_memory() == ""

    def test_write_then_read_round_trips(self, store):
        agent_memory.write_memory("# Facts\n- Arthur is a farmer\n")
        assert agent_memory.read_memory() == "# Facts\n- Arthur is a farmer\n"

    def test_write_replaces_previous_content(self, store):
        agent_memory.write_memory("old")
        agent_memory.write_memory("new")
        assert agent_memory.read_memory() == "new"

    def test_append_adds_a_bullet(self, store):
        agent_memory.append_memory("Rusty is a terrier")
        assert agent_memory.read_memory() == "- Rusty is a terrier\n"

    def test_append_does_not_double_up_bullets(self, store):
        agent_memory.append_memory("- already a bullet")
        assert agent_memory.read_memory() == "- already a bullet\n"

    def test_append_preserves_headings(self, store):
        agent_memory.append_memory("# Section")
        assert agent_memory.read_memory() == "# Section\n"

    def test_append_inserts_newline_when_file_has_no_trailing_one(self, store):
        agent_memory.write_memory("no trailing newline")
        agent_memory.append_memory("next")
        assert agent_memory.read_memory() == "no trailing newline\n- next\n"

    def test_blank_append_is_a_no_op(self, store):
        agent_memory.write_memory("keep me")
        agent_memory.append_memory("   ")
        assert agent_memory.read_memory() == "keep me"

    def test_write_truncates_at_the_size_cap(self, store):
        agent_memory.write_memory("x" * (agent_memory.MAX_MEMORY_CHARS + 1000))
        assert len(agent_memory.read_memory()) == agent_memory.MAX_MEMORY_CHARS


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class TestConversations:
    def test_save_then_load_round_trips(self, store):
        saved = agent_memory.save_conversation(
            "conv-1", [{"role": "user", "content": "hi"}], title="Greeting"
        )
        assert saved["title"] == "Greeting"
        loaded = agent_memory.load_conversation("conv-1")
        assert loaded["messages"][0]["content"] == "hi"

    def test_load_returns_none_for_unknown_id(self, store):
        assert agent_memory.load_conversation("nope") is None

    def test_overwrite_updates_messages(self, store):
        agent_memory.save_conversation("c", [{"role": "user", "content": "a"}])
        agent_memory.save_conversation("c", [{"role": "user", "content": "b"}])
        assert agent_memory.load_conversation("c")["messages"][0]["content"] == "b"

    def test_list_returns_summaries_sorted_newest_first(self, store):
        agent_memory.save_conversation("a", [{"role": "user", "content": "1"}], title="First")
        agent_memory.save_conversation("b", [{"role": "user", "content": "2"}], title="Second")
        listing = agent_memory.list_conversations()
        assert {c["id"] for c in listing} == {"a", "b"}
        assert all(c["message_count"] == 1 for c in listing)

    def test_list_is_empty_when_nothing_saved(self, store):
        assert agent_memory.list_conversations() == []

    def test_delete_removes_the_conversation(self, store):
        agent_memory.save_conversation("gone", [])
        assert agent_memory.delete_conversation("gone") is True
        assert agent_memory.load_conversation("gone") is None

    def test_delete_returns_false_for_unknown_id(self, store):
        assert agent_memory.delete_conversation("nope") is False

    def test_delete_never_raises_when_the_filesystem_refuses(self, store, monkeypatch):
        """A refused delete must be a return value, not an exception.

        This is called straight from a request handler. It surfaced as a 500 in
        production because the original ``except OSError`` did not catch the
        exception the environment's filesystem shim raises.
        """
        agent_memory.save_conversation("stuck", [])

        class _ShimRefusal(Exception):
            """Deliberately NOT an OSError — that is the whole point."""

        def refuse(self):
            raise _ShimRefusal("safe-delete refused")

        monkeypatch.setattr(agent_memory.Path, "unlink", refuse)
        assert agent_memory.delete_conversation("stuck") is False
        # And the record is genuinely still there, so the caller is not lied to.
        assert agent_memory.load_conversation("stuck") is not None

    def test_ids_are_sanitised_so_they_cannot_escape_the_dir(self, store):
        agent_memory.save_conversation("../../etc/passwd", [])
        # Nothing written outside the conversations dir.
        assert agent_memory.load_conversation(".._.._etc_passwd") is not None
        assert not (store.parent / "etc").exists()
