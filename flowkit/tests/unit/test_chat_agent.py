"""The chat tool loop: the assistant acts instead of narrating.

What this pins down
-------------------
The in-app chat used to stream straight to OpenCode with no tools, so asked to
run a test it replied with a command for the user to paste. The loop in
``agent/services/chat_agent.py`` closes that gap with a prompt-level protocol:
the model emits a marker, the server scrapes it, runs the tool, and feeds the
result back.

The parsing is where the risk lives. An earlier draft used a non-greedy
``\\{.*?\\}`` regex, which stops at the first inner brace and silently mangles
any tool call with nested arguments — so the nested-JSON and brace-in-string
cases below are the point of this file, not padding.
"""

import json

import pytest

from agent.services import chat_agent

OPEN = chat_agent.TOOL_OPEN
CLOSE = chat_agent.TOOL_CLOSE


def call(name: str, args: dict) -> str:
    """Render a tool marker the way the prompt asks the model to."""
    return f"{OPEN}{name} {json.dumps(args)}{CLOSE}"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def scripted(rounds: list[list[dict]]):
    """A ``model_call`` that replays scripted rounds and records what it saw.

    Returns ``(model_call, seen)`` where ``seen`` is the list of conversations
    passed in, so a test can assert what the model was actually shown.
    """
    queue = list(rounds)
    seen: list[list[dict]] = []

    async def model_call(messages: list[dict]):
        seen.append([dict(m) for m in messages])
        if not queue:
            return
        for delta in queue.pop(0):
            yield delta

    return model_call, seen


async def collect(messages, model_call, **kwargs) -> list[dict]:
    return [event async for event in chat_agent.run_agent(messages, model_call, **kwargs)]


def texts(events: list[dict]) -> str:
    return "".join(e.get("text", "") for e in events if e.get("type") == "text")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestExtractToolCalls:
    def test_simple_call_is_lifted_out_of_the_prose(self):
        prose, calls = chat_agent.extract_tool_calls(
            f'Let me look that up.\n{call("web_search", {"query": "veo"})}\n'
        )
        assert len(calls) == 1
        assert calls[0]["name"] == "web_search"
        assert calls[0]["args"] == {"query": "veo"}
        assert calls[0]["parse_error"] is None
        assert "Let me look that up." in prose
        assert OPEN not in prose

    def test_nested_arguments_survive(self):
        """The case a non-greedy regex gets wrong."""
        args = {"manifest": {"scenes": [{"duration": 8, "phase": "Hook"}]}, "strict": True}
        _, calls = chat_agent.extract_tool_calls(call("validate_script", args))
        assert len(calls) == 1
        assert calls[0]["args"] == args

    def test_brace_inside_a_string_does_not_close_the_object(self):
        _, calls = chat_agent.extract_tool_calls(
            call("run_command", {"command": "echo '}' && echo done"})
        )
        assert len(calls) == 1
        assert calls[0]["args"]["command"] == "echo '}' && echo done"

    def test_escaped_quote_inside_a_string_is_tracked(self):
        _, calls = chat_agent.extract_tool_calls(
            call("memory_append", {"text": 'he said \\"hello\\" loudly'})
        )
        assert len(calls) == 1
        assert "hello" in calls[0]["args"]["text"]

    def test_multiple_calls_in_one_reply(self):
        text = f'{call("queue_status", {})} and {call("memory_read", {})}'
        _, calls = chat_agent.extract_tool_calls(text)
        assert [c["name"] for c in calls] == ["queue_status", "memory_read"]

    def test_argumentless_call_before_prose_with_braces(self):
        """A brace later in the reply must not be mistaken for this call's args."""
        text = f"{OPEN}memory_read{CLOSE}\n\nHere is a dict: {{'a': 1}}"
        prose, calls = chat_agent.extract_tool_calls(text)
        assert [c["name"] for c in calls] == ["memory_read"]
        assert calls[0]["args"] == {}
        assert "{'a': 1}" in prose

    def test_malformed_json_is_reported_not_dropped(self):
        text = f'{OPEN}web_search {{"query": "unclosed{CLOSE}'
        _, calls = chat_agent.extract_tool_calls(text)
        assert len(calls) == 1
        assert calls[0]["parse_error"] is not None
        assert calls[0]["args"] == {}

    def test_unterminated_marker_stays_as_prose(self):
        """Mid-stream truncation is not a tool call; deleting it loses the answer."""
        text = f"Here is my answer. {OPEN}web_search"
        prose, calls = chat_agent.extract_tool_calls(text)
        assert calls == []
        assert "Here is my answer." in prose

    def test_unterminated_json_stays_as_prose(self):
        text = f'{OPEN}web_search {{"query": "abc"'
        prose, calls = chat_agent.extract_tool_calls(text)
        assert calls == []
        assert "web_search" in prose

    def test_square_bracket_syntax_is_accepted(self):
        """Only one syntax is advertised, but a bracket slip should still run."""
        _, calls = chat_agent.extract_tool_calls('[[tool:queue_status {"project_id": "p"}]]')
        assert len(calls) == 1
        assert calls[0]["name"] == "queue_status"
        assert calls[0]["args"] == {"project_id": "p"}

    def test_angle_bracket_syntax_is_accepted(self):
        _, calls = chat_agent.extract_tool_calls("<<tool:memory_read>>")
        assert [c["name"] for c in calls] == ["memory_read"]

    def test_text_after_a_call_is_preserved(self):
        text = f'{call("memory_read", {})}And here is the summary.'
        prose, _ = chat_agent.extract_tool_calls(text)
        assert "And here is the summary." in prose

    def test_no_markers_means_no_calls(self):
        prose, calls = chat_agent.extract_tool_calls("Just a normal reply with {braces}.")
        assert calls == []
        assert prose == "Just a normal reply with {braces}."

    def test_strip_tool_calls_removes_markers(self):
        stripped = chat_agent.strip_tool_calls(f'Checking.{call("memory_read", {})}')
        assert OPEN not in stripped
        assert stripped.startswith("Checking.")


class TestSafeEmitLen:
    def test_never_emits_a_partial_marker(self):
        """Half a marker on screen is the bug this holdback exists to prevent."""
        text = "Answer so far ⟦to"
        emitted = text[: chat_agent._safe_emit_len(text)]
        assert "⟦" not in emitted

    def test_stops_at_a_complete_marker(self):
        text = f"Prose.{OPEN}memory_read{CLOSE}"
        assert chat_agent._safe_emit_len(text) == len("Prose.")

    def test_plain_text_holds_back_a_tail_for_lookahead(self):
        """The withheld tail is recovered when the round ends."""
        text = "hello world"
        assert chat_agent._safe_emit_len(text) < len(text)

    def test_empty_text_emits_nothing(self):
        assert chat_agent._safe_emit_len("") == 0


# ---------------------------------------------------------------------------
# Preamble
# ---------------------------------------------------------------------------


class TestPreamble:
    def test_inject_is_idempotent(self):
        once = chat_agent.inject_preamble("You are a director.")
        twice = chat_agent.inject_preamble(once)
        assert once == twice

    def test_inject_into_an_empty_prompt(self):
        assert OPEN in chat_agent.inject_preamble("")

    def test_prepare_messages_extends_the_existing_system_message(self):
        prepared = chat_agent.prepare_messages(
            [{"role": "system", "content": "Base."}, {"role": "user", "content": "hi"}]
        )
        assert len(prepared) == 2
        assert prepared[0]["role"] == "system"
        assert prepared[0]["content"].startswith("Base.")
        assert OPEN in prepared[0]["content"]

    def test_prepare_messages_adds_a_system_message_when_absent(self):
        prepared = chat_agent.prepare_messages([{"role": "user", "content": "hi"}])
        assert prepared[0]["role"] == "system"
        assert prepared[1]["content"] == "hi"

    def test_prepare_messages_does_not_mutate_the_input(self):
        original = [{"role": "system", "content": "Base."}]
        chat_agent.prepare_messages(original)
        assert original[0]["content"] == "Base."

    def test_unavailable_search_is_advertised_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(chat_agent, "_search_available", lambda: False)
        preamble = chat_agent.build_preamble()
        assert "UNAVAILABLE (TINYFISH" in preamble

    def test_available_search_is_listed_as_a_usable_tool(self, monkeypatch):
        monkeypatch.setattr(chat_agent, "_search_available", lambda: True)
        preamble = chat_agent.build_preamble()
        assert '`web_search` {"query"' in preamble
        assert "UNAVAILABLE (TINYFISH" not in preamble


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_names_the_available_ones(self):
        out = await chat_agent.execute_tool("nope", {})
        assert out["ok"] is False
        assert "web_search" in out["error"]

    @pytest.mark.asyncio
    async def test_a_raising_tool_becomes_an_error_result(self, monkeypatch):
        async def boom(_args):
            raise RuntimeError("kaboom")

        monkeypatch.setitem(chat_agent.TOOLS, "explode", boom)
        out = await chat_agent.execute_tool("explode", {})
        assert out["ok"] is False
        assert "kaboom" in out["error"]


class TestRunCommand:
    """`run_command` is `destructive`, so these pass the gate explicitly.

    The gate itself is covered by TestRiskGate — these tests are about the
    command's own guards (cwd pinning, pattern refusal), so they enable spending
    to get past the gate rather than asserting through it.
    """

    @pytest.mark.asyncio
    async def test_rejects_an_empty_command(self):
        out = await chat_agent.execute_tool("run_command", {"command": "  "}, allow_spend=True)
        assert out["ok"] is False

    @pytest.mark.asyncio
    async def test_refuses_to_leave_the_workspace(self):
        out = await chat_agent.execute_tool(
            "run_command", {"command": "echo hi", "cwd": "../../../.."}, allow_spend=True
        )
        assert out["ok"] is False
        assert "outside the workspace" in out["error"]

    @pytest.mark.asyncio
    async def test_refuses_a_destructive_pattern(self):
        out = await chat_agent.execute_tool(
            "run_command", {"command": "rm -rf / --no-preserve-root"}, allow_spend=True
        )
        assert out["ok"] is False
        assert "destructive pattern" in out["error"]

    @pytest.mark.asyncio
    async def test_runs_a_real_command_and_returns_output(self):
        out = await chat_agent.execute_tool(
            "run_command", {"command": "echo JARVIS_TOOL_OK"}, allow_spend=True
        )
        assert out["ok"] is True
        assert "JARVIS_TOOL_OK" in out["result"]["output"]
        assert out["result"]["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_resolves_a_relative_cwd_inside_the_workspace(self):
        out = await chat_agent.execute_tool(
            "run_command", {"command": "echo hi", "cwd": "flowkit"}, allow_spend=True
        )
        assert out["ok"] is True
        assert out["result"]["cwd"].replace("\\", "/") == "flowkit"


async def _fake_ok(_args):
    """A stand-in TOOLS entry: takes the args dict, does nothing, succeeds."""
    return {"ran": True}


class TestRiskGate:
    """The gate is the difference between "the model decided to spend" and "the
    model asked to". These pin that it actually refuses."""

    @pytest.mark.asyncio
    async def test_spend_is_refused_by_default(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", False)
        out = await chat_agent.execute_tool("generate_episode", {"manifest_path": "x.json"})
        assert out["ok"] is False
        assert out.get("refused") is True
        assert "spends money" in out["error"]

    @pytest.mark.asyncio
    async def test_read_operations_are_never_gated(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", False)
        # `memory_read` rather than a DB-backed read: this test is about the
        # gate, and opening the shared SQLite file while the agent is running
        # can block on the lock, which has nothing to do with what is asserted.
        out = await chat_agent.execute_tool("memory_read", {})
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_spend_is_allowed_when_enabled(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", True)
        # Swap the handler so enabling the gate does not run a real batch.
        monkeypatch.setitem(chat_agent.TOOLS, "run_batch", _fake_ok)
        out = await chat_agent.execute_tool("run_batch", {"series_id": "s"})
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_destructive_needs_confirmation_even_when_spend_is_on(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", True)
        out = await chat_agent.execute_tool("publish_episode", {"series_id": "s", "episode": 1})
        assert out["ok"] is False
        assert "explicit confirmation" in out["error"]

    @pytest.mark.asyncio
    async def test_destructive_passes_with_a_confirm_token(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", True)
        monkeypatch.setitem(chat_agent.TOOLS, "publish_episode", _fake_ok)
        # Explicit out-of-band token authorizes (e.g. future approve endpoint).
        out = await chat_agent.execute_tool(
            "publish_episode", {"series_id": "s", "episode": 1}, confirm_token="user-approved"
        )
        assert out["ok"] is True

    @pytest.mark.asyncio
    async def test_destructive_rejects_model_confirm_in_args(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", True)
        monkeypatch.setitem(chat_agent.TOOLS, "publish_episode", _fake_ok)
        # Model-generated {"confirm": true} must NOT self-authorize.
        out = await chat_agent.execute_tool(
            "publish_episode", {"series_id": "s", "episode": 1, "confirm": True}
        )
        assert out["ok"] is False
        assert out.get("refused") is True



class TestRiskVisibility:
    """The gate is only useful if the user can see it.

    A refusal the UI renders as a generic tool failure is indistinguishable from
    a broken assistant, so the frames have to carry enough to say "this was
    blocked, and here is why".
    """

    @pytest.mark.asyncio
    async def test_a_refusal_is_marked_as_refused_not_just_failed(self, monkeypatch):
        from agent import config

        monkeypatch.setattr(config, "AGENT_ALLOW_SPEND", False)
        model_call, _ = scripted([
            [{"type": "text", "text": call("generate_episode", {"manifest_path": "m.json"})}],
            [{"type": "text", "text": "I could not run that."}],
        ])
        events = await collect([{"role": "user", "content": "go"}], model_call)

        finished = [e for e in events if e["type"] == "tool" and e["status"] != "start"]
        assert finished[0]["status"] == "error"
        assert finished[0].get("refused") is True
        assert "AGENT_ALLOW_SPEND" in finished[0]["message"]

    @pytest.mark.asyncio
    async def test_frames_carry_the_risk_so_the_card_can_warn(self, monkeypatch):
        async def fake(_args):
            return {"series_id": "s"}

        monkeypatch.setitem(chat_agent.TOOLS, "run_batch", fake)
        model_call, _ = scripted([
            [{"type": "text", "text": call("run_batch", {"series_id": "s"})}],
            [{"type": "text", "text": "done"}],
        ])
        events = await collect([{"role": "user", "content": "go"}], model_call)

        tool_events = [e for e in events if e["type"] == "tool"]
        assert tool_events, "expected tool frames"
        # Both start and done, so the badge is present throughout.
        assert all(e.get("risk") == "spend" for e in tool_events)

    @pytest.mark.asyncio
    async def test_a_read_tool_carries_its_own_risk(self, monkeypatch):
        async def fake(_args):
            return {"ok": True}

        monkeypatch.setitem(chat_agent.TOOLS, "queue_status", fake)
        model_call, _ = scripted([
            [{"type": "text", "text": call("queue_status", {})}],
            [{"type": "text", "text": "done"}],
        ])
        events = await collect([{"role": "user", "content": "go"}], model_call)
        assert [e for e in events if e["type"] == "tool"][0]["risk"] == "read"

    @pytest.mark.asyncio
    async def test_an_ordinary_failure_is_not_marked_refused(self, monkeypatch):
        async def boom(_args):
            raise chat_agent.OperationError("something else went wrong")

        monkeypatch.setitem(chat_agent.TOOLS, "queue_status", boom)
        model_call, _ = scripted([
            [{"type": "text", "text": call("queue_status", {})}],
            [{"type": "text", "text": "failed"}],
        ])
        events = await collect([{"role": "user", "content": "go"}], model_call)
        finished = [e for e in events if e["type"] == "tool" and e["status"] != "start"]
        assert finished[0]["status"] == "error"
        assert "refused" not in finished[0]


class TestCapabilitiesEndpoint:
    """The dashboard reads this to state which mode the assistant is in."""

    @pytest.mark.asyncio
    async def test_reports_the_spend_switch_and_the_catalog(self):
        from agent.api.agent_tools import capabilities

        out = await capabilities()
        assert "allow_spend" in out
        assert out["operation_count"] > 0
        assert out["by_risk"].get("read", 0) > 0
        assert "AGENT_ALLOW_SPEND" in out["note"]

    @pytest.mark.asyncio
    async def test_every_department_is_reported(self):
        from agent.api.agent_tools import capabilities

        out = await capabilities()
        for dept in ("ingest", "director", "render", "assembly", "post", "publish",
                     "assistant", "ops"):
            assert out["departments"].get(dept), f"{dept} missing from capabilities"


class TestMemoryTools:
    @pytest.fixture
    def store(self, tmp_path, monkeypatch):
        from agent.services import agent_memory

        monkeypatch.setattr(agent_memory, "BASE_DIR", tmp_path)
        monkeypatch.setattr(agent_memory, "MEMORY_FILE", tmp_path / "memory.md")
        monkeypatch.setattr(agent_memory, "CONVERSATIONS_DIR", tmp_path / "c")
        return tmp_path

    @pytest.mark.asyncio
    async def test_read_reports_empty_memory_plainly(self, store):
        out = await chat_agent.execute_tool("memory_read", {})
        assert out["ok"] is True
        assert out["result"]["memory"] == ""

    @pytest.mark.asyncio
    async def test_append_then_read_round_trips(self, store):
        saved = await chat_agent.execute_tool("memory_append", {"text": "Abi prefers Windows"})
        assert saved["ok"] is True
        read = await chat_agent.execute_tool("memory_read", {})
        assert "Abi prefers Windows" in read["result"]["memory"]

    @pytest.mark.asyncio
    async def test_append_requires_text(self, store):
        out = await chat_agent.execute_tool("memory_append", {"text": "  "})
        assert out["ok"] is False

    @pytest.mark.asyncio
    async def test_write_requires_content(self, store):
        out = await chat_agent.execute_tool("memory_write", {})
        assert out["ok"] is False


class TestValidateScript:
    def test_accepts_a_well_formed_manifest(self):
        manifest = {
            "scenes": [
                {"duration": 8, "phase": "Hook", "image_prompt": "a"},
                {"duration": 9, "phase": "Tension", "image_prompt": "b"},
                {"duration": 8, "phase": "Twist", "image_prompt": "c"},
                {"duration": 9, "phase": "Cliffhanger", "image_prompt": "d"},
            ]
        }
        out = chat_agent.validate_script(manifest)
        assert out["valid"] is True
        assert out["scene_count"] == 4

    def test_flags_a_scene_over_ten_seconds(self):
        manifest = {"scenes": [{"duration": 14, "image_prompt": "a"}] * 5}
        out = chat_agent.validate_script(manifest)
        assert out["valid"] is False
        assert any("10s limit" in e for e in out["errors"])

    def test_flags_the_wrong_scene_count(self):
        out = chat_agent.validate_script({"scenes": [{"duration": 8, "image_prompt": "a"}]})
        assert any("want 4-6" in e for e in out["errors"])

    def test_rejects_a_non_object(self):
        assert chat_agent.validate_script("nope")["valid"] is False

    def test_rejects_an_empty_scene_list(self):
        assert chat_agent.validate_script({"scenes": []})["valid"] is False


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_plain_answer_streams_and_stops(self):
        model_call, seen = scripted([[{"type": "text", "text": "Hello there."}]])
        events = await collect([{"role": "user", "content": "hi"}], model_call)
        assert texts(events) == "Hello there."
        assert len(seen) == 1

    @pytest.mark.asyncio
    async def test_reasoning_and_usage_pass_through(self):
        model_call, _ = scripted(
            [[{"type": "reasoning", "text": "thinking"}, {"type": "usage", "total_tokens": 5}]]
        )
        events = await collect([{"role": "user", "content": "hi"}], model_call)
        assert [e["type"] for e in events] == ["reasoning", "usage"]

    @pytest.mark.asyncio
    async def test_a_tool_call_is_executed_and_answered(self, monkeypatch):
        async def fake_search(args):
            return {"query": args["query"], "results": [{"title": "Veo"}]}

        monkeypatch.setitem(chat_agent.TOOLS, "web_search", fake_search)

        model_call, seen = scripted([
            [{"type": "text", "text": f'Searching. {call("web_search", {"query": "veo"})}'}],
            [{"type": "text", "text": "Veo needs paid access."}],
        ])
        events = await collect([{"role": "user", "content": "veo?"}], model_call)

        tool_events = [e for e in events if e["type"] == "tool"]
        assert [e["status"] for e in tool_events] == ["start", "done"]
        assert tool_events[0]["tool"] == "web_search"
        assert "Veo needs paid access." in texts(events)
        assert len(seen) == 2

    @pytest.mark.asyncio
    async def test_the_marker_never_reaches_the_visible_text(self, monkeypatch):
        async def fake_search(_args):
            return {"results": []}

        monkeypatch.setitem(chat_agent.TOOLS, "web_search", fake_search)
        model_call, _ = scripted([
            [{"type": "text", "text": f'One moment. {call("web_search", {"query": "x"})}'}],
            [{"type": "text", "text": "Done."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)
        assert OPEN not in texts(events)
        assert "One moment." in texts(events)

    @pytest.mark.asyncio
    async def test_the_tool_result_is_fed_back_to_the_model(self, monkeypatch):
        async def fake_status(_args):
            return {"request_counts": {"FAILED": 3}}

        monkeypatch.setitem(chat_agent.TOOLS, "project_status", fake_status)
        model_call, seen = scripted([
            [{"type": "text", "text": call("project_status", {})}],
            [{"type": "text", "text": "Three failures."}],
        ])
        await collect([{"role": "user", "content": "status?"}], model_call)

        follow_up = json.dumps(seen[1], default=str)
        assert "Tool results" in follow_up
        assert "FAILED" in follow_up
        # The assistant's own call is kept so the conversation stays coherent.
        assert any(m["role"] == "assistant" and "project_status" in m["content"] for m in seen[1])

    @pytest.mark.asyncio
    async def test_a_failing_tool_is_reported_as_an_error_event(self, monkeypatch):
        async def failing(_args):
            raise chat_agent.OperationError("TINYFISH_API_KEY is not set.")

        monkeypatch.setitem(chat_agent.TOOLS, "web_search", failing)
        model_call, _ = scripted([
            [{"type": "text", "text": call("web_search", {"query": "x"})}],
            [{"type": "text", "text": "I cannot search right now."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)
        finished = [e for e in events if e["type"] == "tool" and e["status"] != "start"]
        assert finished[0]["status"] == "error"
        assert "TINYFISH" in finished[0]["message"]

    @pytest.mark.asyncio
    async def test_search_results_are_shaped_for_the_result_cards(self, monkeypatch):
        """The dashboard's search card reads `results[].title/url/snippet`."""
        async def fake_search(_args):
            return {
                "query": "veo api",
                "total_results": 1,
                "results": [
                    {"title": "Veo docs", "url": "https://x/veo", "snippet": "paid only"}
                ],
            }

        monkeypatch.setitem(chat_agent.TOOLS, "web_search", fake_search)
        model_call, _ = scripted([
            [{"type": "text", "text": call("web_search", {"query": "veo api"})}],
            [{"type": "text", "text": "Answered."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)

        done = [e for e in events if e["type"] == "tool" and e["status"] == "done"][0]
        assert done["tool"] == "web_search"
        assert done["query"] == "veo api"
        assert done["results"] == [
            {"title": "Veo docs", "url": "https://x/veo", "snippet": "paid only"}
        ]

    @pytest.mark.asyncio
    async def test_command_output_is_shaped_for_the_terminal_block(self, monkeypatch):
        """The dashboard's command card reads `command` / `output` / `exit_code`."""
        async def fake_cmd(_args):
            return {
                "command": "echo hi",
                "cwd": ".",
                "exit_code": 0,
                "output": "hi\n",
            }

        monkeypatch.setitem(chat_agent.TOOLS, "run_command", fake_cmd)
        model_call, _ = scripted([
            [{"type": "text", "text": call("run_command", {"command": "echo hi"})}],
            [{"type": "text", "text": "Ran it."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)

        done = [e for e in events if e["type"] == "tool" and e["status"] == "done"][0]
        assert done["command"] == "echo hi"
        assert done["output"] == "hi\n"
        assert done["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_memory_ops_use_the_ui_tool_name_and_operation(self, monkeypatch):
        """The dashboard's memory row keys off `tool: 'memory'` + `operation`."""
        async def fake_read(_args):
            return {"memory": "Abi prefers Windows"}

        monkeypatch.setitem(chat_agent.TOOLS, "memory_read", fake_read)
        model_call, _ = scripted([
            [{"type": "text", "text": call("memory_read", {})}],
            [{"type": "text", "text": "Recalled."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)

        start = [e for e in events if e["type"] == "tool"][0]
        done = [e for e in events if e["type"] == "tool" and e["status"] == "done"][0]
        assert start["tool"] == "memory"
        assert start["operation"] == "read"
        assert done["tool"] == "memory"
        assert done["operation"] == "read"

    @pytest.mark.asyncio
    async def test_project_status_uses_the_snapshot_card(self, monkeypatch):
        async def fake_status(_args):
            return {
                "scene_count": 6,
                "request_counts": {"COMPLETED": 9},
                "scenes": [],
            }

        monkeypatch.setitem(chat_agent.TOOLS, "project_status", fake_status)
        model_call, _ = scripted([
            [{"type": "text", "text": call("project_status", {})}],
            [{"type": "text", "text": "Six scenes."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)

        done = [e for e in events if e["type"] == "tool" and e["status"] == "done"][0]
        assert done["tool"] == "project_snapshot"
        assert "6 scenes" in done["summary"]
        assert done["data"]["scene_count"] == 6

    @pytest.mark.asyncio
    async def test_malformed_calls_are_retried_not_executed(self, monkeypatch):
        executed: list[str] = []

        async def spy(_args):
            executed.append("ran")
            return {}

        monkeypatch.setitem(chat_agent.TOOLS, "web_search", spy)

        model_call, seen = scripted([
            [{"type": "text", "text": f'{OPEN}web_search {{"query": broken{CLOSE}'}],
            [{"type": "text", "text": "Recovered."}],
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)

        assert executed == []
        assert any(e["type"] == "tool" and e["status"] == "error" for e in events)
        assert "malformed" in json.dumps(seen[1], default=str)
        assert "Recovered." in texts(events)

    @pytest.mark.asyncio
    async def test_the_round_limit_is_enforced(self, monkeypatch):
        async def fake(_args):
            return {}

        monkeypatch.setitem(chat_agent.TOOLS, "memory_read", fake)
        # Every round asks for another tool: without a cap this never ends.
        endless = [[{"type": "text", "text": call("memory_read", {})}] for _ in range(10)]
        model_call, seen = scripted(endless)

        events = await collect([{"role": "user", "content": "go"}], model_call, max_rounds=3)
        assert len(seen) == 3
        assert "Stopped after 3 tool rounds" in texts(events)

    @pytest.mark.asyncio
    async def test_a_model_failure_surfaces_as_an_error_event(self):
        async def broken(_messages):
            raise RuntimeError("upstream 500")
            yield  # pragma: no cover - makes this an async generator

        events = await collect([{"role": "user", "content": "hi"}], broken)
        assert events[-1]["type"] == "error"
        assert "upstream 500" in events[-1]["message"]

    @pytest.mark.asyncio
    async def test_the_loop_does_not_mutate_the_caller_messages(self):
        model_call, _ = scripted([[{"type": "text", "text": "ok"}]])
        original = [{"role": "user", "content": "hi"}]
        await collect(original, model_call)
        assert original == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_a_single_chunk_reply_keeps_its_held_back_tail(self):
        """The partial-marker holdback must not eat the end of a normal reply."""
        model_call, _ = scripted([[{"type": "text", "text": "Short."}]])
        events = await collect([{"role": "user", "content": "hi"}], model_call)
        assert texts(events) == "Short."

    @pytest.mark.asyncio
    async def test_text_split_across_chunks_streams_in_order(self):
        model_call, _ = scripted([
            [
                {"type": "text", "text": "The ans"},
                {"type": "text", "text": "wer is 42"},
                {"type": "text", "text": "."},
            ]
        ])
        events = await collect([{"role": "user", "content": "q"}], model_call)
        assert texts(events) == "The answer is 42."

class TestFailureBreaker:
    """A tool that keeps failing must not burn every round."""

    @pytest.mark.asyncio
    async def test_same_tool_skipped_after_two_failures(self):
        model_call, _ = scripted(
            [
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": "done"}],
            ]
        )
        events = await collect([{"role": "user", "content": "go"}], model_call, max_rounds=6)
        starts = [
            e
            for e in events
            if e.get("type") == "tool" and e.get("status") == "start"
        ]
        assert len(starts) == 2
        assert any("failed twice already" in (e.get("message") or "") for e in events)

    @pytest.mark.asyncio
    async def test_three_dead_rounds_stop_the_loop(self):
        model_call, _ = scripted(
            [
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": call("nope_tool", {})}],
            ]
        )
        events = await collect([{"role": "user", "content": "go"}], model_call, max_rounds=6)
        assert "Three straight tool rounds failed" in texts(events)

    @pytest.mark.asyncio
    async def test_success_does_not_punish_other_tools(self):
        model_call, _ = scripted(
            [
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": call("memory_read", {})}],
                [{"type": "text", "text": call("nope_tool", {})}],
                [{"type": "text", "text": "done"}],
            ]
        )
        events = await collect([{"role": "user", "content": "go"}], model_call, max_rounds=6)
        starts = [
            e
            for e in events
            if e.get("type") == "tool"
            and e.get("status") == "start"
            and e.get("tool") == "nope_tool"
        ]
        assert len(starts) == 2
        assert "done" in texts(events)


class TestRouteMap:
    def test_preamble_contains_route_map(self):
        preamble = chat_agent.build_preamble()
        assert "ROUTE MAP" in preamble
        assert "generate_image" in preamble
        assert "If a tool errors twice in a row" in preamble
