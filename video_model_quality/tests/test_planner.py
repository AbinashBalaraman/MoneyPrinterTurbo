"""Tests for the bring-your-own planner adapter."""
import pytest

from src.contract import ContractError
from src.planner import (
    CallablePlanner, DeterministicPlanner, NoOpPlanner, PlanUnavailable,
    llm_system_prompt, parse_scene_json, plan_scene,
)


class TestParseSceneJson:
    def test_plain_json(self):
        assert parse_scene_json('{"title":"x"}')["title"] == "x"

    def test_fenced_json(self):
        txt = 'here\n```json\n{"title":"y","beats":[]}\n```\ndone'
        assert parse_scene_json(txt)["title"] == "y"

    def test_garbage_raises(self):
        with pytest.raises(PlanUnavailable):
            parse_scene_json("no json here")

    def test_malformed_raises(self):
        with pytest.raises(PlanUnavailable):
            parse_scene_json("{not valid}")


class TestPlanners:
    def test_noop_refuses(self):
        with pytest.raises(PlanUnavailable):
            plan_scene("anything")

    def test_explicit_scene_bypasses_backend(self):
        scene = {"characters": [{"id": "a"}], "beats": [{"actor": "a", "action": "idle"}]}
        out = plan_scene("ignored", scene=scene)
        assert out["beats"][0]["action"] == "idle"

    def test_explicit_invalid_scene_rejected(self):
        with pytest.raises(ContractError):
            plan_scene("x", scene={"beats": [{"action": "nope"}]})

    def test_callable_backend_accepts_dict(self):
        cb = CallablePlanner(lambda p: {"characters": [{"id": "a"}],
                                        "beats": [{"actor": "a", "action": "kick"}]})
        assert plan_scene("kick", backend=cb)["beats"][0]["action"] == "kick"

    def test_callable_backend_accepts_json_string(self):
        cb = CallablePlanner(lambda p: '{"beats":[{"action":"wave"}]}')
        assert plan_scene("wave", backend=cb)["beats"][0]["action"] == "wave"

    def test_deterministic_backend(self):
        out = plan_scene("walk then punch", backend=DeterministicPlanner())
        assert [b["action"] for b in out["beats"]] == ["walk", "punch"]

    def test_llm_system_prompt_mentions_registry(self):
        s = llm_system_prompt()
        assert "walk" in s and "sword" in s and "hand_r" in s and "JSON" in s
