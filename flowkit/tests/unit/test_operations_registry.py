"""The operations catalog — one declaration, two front doors.

Why this file exists
--------------------
An operation used to be implemented twice (a REST route and a hand-written
chatbot tool) and the two drifted, twice in one week. The catalog is the fix, so
what needs pinning is not "does the registry work" but the properties that make
drift impossible:

* every operation declares a real department and a real risk level;
* names are unique (a duplicate would silently shadow, which is the bug again);
* the chatbot's tool specs and the risk gate both read from the same declaration.

The risk gate tests matter most: `spend` operations cost real money and this
pipeline runs unattended, so a gate that silently passes is worse than no gate.
"""

import pytest

from agent.operations import registry
from agent.operations.registry import (
    DEPARTMENTS,
    RISK_DESTRUCTIVE,
    RISK_READ,
    RISK_SPEND,
    RISK_WRITE,
    Operation,
    check_allowed,
    get,
    operation,
    tool_specs,
)


class TestRegistryIntegrity:
    def test_every_operation_declares_a_known_department(self):
        for name, op in registry.all_operations().items():
            assert op.department in DEPARTMENTS, f"{name} has department {op.department!r}"

    def test_every_operation_declares_a_known_risk(self):
        for name, op in registry.all_operations().items():
            assert op.risk in registry.VALID_RISKS, f"{name} has risk {op.risk!r}"

    def test_every_operation_has_a_description(self):
        """The model reads these; a blank one makes a tool unusable."""
        for name, op in registry.all_operations().items():
            assert op.description.strip(), f"{name} has no description"

    def test_every_operation_has_a_handler(self):
        for name, op in registry.all_operations().items():
            assert callable(op.handler), f"{name} has a non-callable handler"

    def test_an_unknown_department_is_rejected_at_declaration(self):
        """Failing at import beats failing when the model calls it."""
        with pytest.raises(ValueError, match="unknown department"):

            @operation(name="zz_bad_dept", department="not_a_department")
            async def _bad():
                return {}

    def test_an_unknown_risk_is_rejected_at_declaration(self):
        with pytest.raises(ValueError, match="unknown risk"):

            @operation(name="zz_bad_risk", department="render", risk="whatever")
            async def _bad():
                return {}

    def test_a_duplicate_name_is_rejected(self):
        """Two operations with one name means one silently shadows the other."""
        with pytest.raises(ValueError, match="Duplicate operation"):

            @operation(name="queue_status", department="render")
            async def _dupe():
                return {}

    def test_the_expected_departments_are_all_populated(self):
        grouped = registry.by_department()
        # ASSISTANT and OPS plus the six pipeline stages. A department with no
        # operations is a hole in the "connect the departments" story.
        for dept in ("ingest", "director", "render", "assembly", "post", "publish",
                     "assistant", "ops"):
            assert grouped.get(dept), f"department {dept!r} has no operations"


class TestToolSpecs:
    def test_specs_carry_the_fields_the_prompt_needs(self):
        for spec in tool_specs():
            for key in ("name", "department", "risk", "args", "description"):
                assert key in spec, f"{spec.get('name')} is missing {key}"

    def test_specs_cover_every_operation(self):
        assert {s["name"] for s in tool_specs()} == set(registry.all_operations())

    def test_specs_can_be_filtered_by_risk(self):
        reads = tool_specs(include_risks={RISK_READ})
        assert reads, "expected at least one read-only operation"
        assert all(s["risk"] == RISK_READ for s in reads)

    def test_an_argumentless_operation_shows_empty_args(self):
        spec = next(s for s in tool_specs() if s["name"] == "project_list")
        assert spec["args"] == "{}"

    def test_args_are_rendered_as_valid_json(self):
        import json

        for spec in tool_specs():
            json.loads(spec["args"])  # must not raise


class TestRiskGate:
    def _op(self, risk: str) -> Operation:
        return Operation(
            name=f"test_{risk}",
            department="render",
            handler=lambda **_: None,
            risk=risk,
        )

    def test_read_is_always_allowed(self):
        allowed, reason = check_allowed(self._op(RISK_READ), allow_spend=False)
        assert allowed is True
        assert reason is None

    def test_write_is_allowed(self):
        allowed, _ = check_allowed(self._op(RISK_WRITE), allow_spend=False)
        assert allowed is True

    def test_spend_is_refused_by_default(self):
        allowed, reason = check_allowed(self._op(RISK_SPEND), allow_spend=False)
        assert allowed is False
        assert "spends money" in reason
        # The refusal must say how to change it, or it is a dead end.
        assert "AGENT_ALLOW_SPEND" in reason

    def test_spend_is_allowed_when_enabled(self):
        allowed, reason = check_allowed(self._op(RISK_SPEND), allow_spend=True)
        assert allowed is True
        assert reason is None

    def test_destructive_is_refused_without_spend(self):
        allowed, reason = check_allowed(self._op(RISK_DESTRUCTIVE), allow_spend=False)
        assert allowed is False
        assert "destructive" in reason

    def test_destructive_needs_a_token_even_with_spend_enabled(self):
        allowed, reason = check_allowed(self._op(RISK_DESTRUCTIVE), allow_spend=True)
        assert allowed is False
        assert "confirmation" in reason

    def test_destructive_passes_with_spend_and_a_token(self):
        allowed, reason = check_allowed(
            self._op(RISK_DESTRUCTIVE), allow_spend=True, confirm_token="yes"
        )
        assert allowed is True
        assert reason is None


class TestHandlerSignatures:
    """The declared `args` are what the model is told to send.

    If a declaration names an argument the handler does not accept, every call
    fails with a TypeError the model cannot diagnose — it was told to send
    exactly that. Cheap to check, and it catches the drift at import.
    """

    def test_every_declared_arg_is_a_real_parameter(self):
        import inspect

        for name, op in registry.all_operations().items():
            params = inspect.signature(op.handler).parameters
            accepts_kwargs = any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if accepts_kwargs:
                continue
            for arg in op.args:
                assert arg in params, (
                    f"{name}: declares arg {arg!r} but the handler does not accept it "
                    f"(params: {sorted(params)})"
                )

    def test_every_handler_is_awaitable(self):
        import inspect

        for name, op in registry.all_operations().items():
            assert inspect.iscoroutinefunction(op.handler), (
                f"{name}: handler must be async — the tool loop awaits it"
            )


class TestReadLogs:
    """Regression: `LogBus.count` is a @property, not a method.

    Calling it as `log_bus.count()` raised `'int' object is not callable`, which
    the live agent surfaced as a confusing tool error. The unit test is here so
    it cannot come back.
    """

    @pytest.mark.asyncio
    async def test_read_logs_returns_records_without_erroring(self):
        from agent.operations import ops as ops_module

        out = await ops_module.read_logs(limit=5)
        assert "records" in out
        assert isinstance(out["records"], list)
        assert isinstance(out["buffered"], int)

    @pytest.mark.asyncio
    async def test_read_logs_clamps_a_silly_limit(self):
        from agent.operations import ops as ops_module

        out = await ops_module.read_logs(limit=10_000)
        assert out["returned"] <= 500

    @pytest.mark.asyncio
    async def test_read_logs_accepts_a_level_filter(self):
        from agent.operations import ops as ops_module

        out = await ops_module.read_logs(limit=10, level="ERROR")
        assert all(r.get("level") == "ERROR" for r in out["records"])
    """A spend operation is one the model must not reach on its own. Getting this
    classification wrong is how a model generates 40 images nobody asked for."""

    @pytest.mark.parametrize(
        "name",
        ["generate_episode", "generate_image", "run_batch", "assemble_episode"],
    )
    def test_these_spend(self, name):
        assert get(name).risk == RISK_SPEND

    @pytest.mark.parametrize("name", ["publish_episode"])
    def test_these_are_destructive(self, name):
        assert get(name).risk == RISK_DESTRUCTIVE

    @pytest.mark.parametrize(
        "name",
        [
            "project_list",
            "project_status",
            "queue_status",
            "consistency_check",
            "continuity_status",
            "publication_status",
            "list_topics",
            "read_logs",
            "memory_read",
            "web_search",
            "validate_script",
        ],
    )
    def test_these_are_read_only(self, name):
        """Inspection must never be gated — that is what makes the assistant
        useful for diagnosis."""
        assert get(name).risk == RISK_READ

    def test_run_command_is_write_not_destructive(self):
        """Marking it destructive would demand a token only the model can supply,
        i.e. a speed bump that looks like a safety check while checking nothing.
        The real controls are the cwd pin and the pattern denylist."""
        assert get("run_command").risk == RISK_WRITE
