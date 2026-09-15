"""Tests for the SceneScript contract: capability registry + validator."""
import pytest

from src.contract import (
    ContractError, OBJECT_REGISTRY, JOINT_INDEX, capabilities,
    resolve_joint, resolve_object, validate_scene,
)


class TestCapabilityRegistry:
    def test_capabilities_are_json_safe(self):
        caps = capabilities()
        assert "actions" in caps and "objects" in caps and "joints" in caps
        assert isinstance(caps["actions"], list) and len(caps["actions"]) == 17
        assert "sword" in caps["objects"]

    def test_joint_lookup_and_aliases(self):
        assert resolve_joint("hand") == 8
        assert resolve_joint("right_hand") == 8
        assert resolve_joint("head") == 4
        assert resolve_joint("left_foot") == 11
        assert resolve_joint(8) == 8
        assert resolve_joint("nose") is None

    def test_object_lookup_and_aliases(self):
        assert resolve_object("katana") == "sword"
        assert resolve_object("boulder") == "ball"
        assert resolve_object("stool") == "chair"
        assert resolve_object("unobtainium") is None


class TestValidateScene:
    def _min_scene(self, **kw):
        s = {"title": "t", "characters": [{"id": "a"}],
             "beats": [{"actor": "a", "action": "walk", "duration_s": 2}]}
        s.update(kw)
        return s

    def test_minimal_normalised(self):
        out, rep = validate_scene(self._min_scene())
        assert out["characters"][0]["id"] == "a"
        assert out["beats"][0]["action"] == "walk"
        assert out["camera"]["mode"] == "auto"
        assert rep["errors"] == []

    def test_unknown_action_rejected(self):
        with pytest.raises(ContractError):
            validate_scene(self._min_scene(beats=[{"action": "fly"}]))

    def test_unknown_object_rejected(self):
        with pytest.raises(ContractError):
            validate_scene(self._min_scene(objects=[{"kind": "unobtainium"}]))

    def test_object_aliases_normalised(self):
        out, _ = validate_scene(self._min_scene(
            objects=[{"kind": "katana", "attach": {"actor": "a", "joint": "hand"}}]))
        assert out["objects"][0]["kind"] == "sword"
        assert out["objects"][0]["attach"]["joint"] == 8

    def test_attach_to_undeclared_actor_rejected(self):
        with pytest.raises(ContractError):
            validate_scene(self._min_scene(
                objects=[{"kind": "sword", "attach": {"actor": "ghost", "joint": "hand"}}]))

    def test_unknown_joint_rejected(self):
        with pytest.raises(ContractError):
            validate_scene(self._min_scene(
                objects=[{"kind": "sword", "attach": {"actor": "a", "joint": "nose"}}]))

    def test_unsupported_capability_rejected(self):
        # tree cannot be attached
        with pytest.raises(ContractError):
            validate_scene(self._min_scene(
                objects=[{"kind": "tree", "attach": {"actor": "a", "joint": "hand"}}]))

    def test_unknown_theme_and_camera_warn_not_raise(self):
        out, rep = validate_scene(self._min_scene(theme="neon", camera={"mode": "spiral"}))
        assert out["theme"] == "light" and out["camera"]["mode"] == "auto"
        assert len(rep["warnings"]) >= 2

    def test_actor_referenced_by_beat_is_added(self):
        out, rep = validate_scene({"beats": [{"actor": "z", "action": "idle"}]})
        assert any(c["id"] == "z" for c in out["characters"])

    def test_interactions_in_capabilities(self):
        caps = capabilities()
        assert "interactions" in caps
        assert set(caps["interactions"]) == {"strike", "block", "dodge", "grab", "knockdown", "assist", "talk"}

    def test_target_and_interaction_normalised(self):
        out, rep = validate_scene(self._min_scene(
            characters=[{"id": "a", "role": "attacker"}, {"id": "b", "role": "defender"}],
            beats=[{"actor": "a", "action": "punch", "target": "b", "interaction": "strike"}],
        ))
        assert out["characters"][0]["role"] == "attacker"
        assert out["characters"][1]["role"] == "defender"
        assert out["beats"][0]["target"] == "b"
        assert out["beats"][0]["interaction"] == "strike"
        assert rep["errors"] == []

    def test_unknown_interaction_rejected(self):
        with pytest.raises(ContractError) as exc_info:
            validate_scene(self._min_scene(
                characters=[{"id": "a"}, {"id": "b"}],
                beats=[{"actor": "a", "action": "punch", "target": "b", "interaction": "teleport"}],
            ))
        assert "unknown interaction" in str(exc_info.value)

    def test_shots_normalised(self):
        out, rep = validate_scene(self._min_scene(
            shots=[
                {"id": "shot_0", "duration_s": 2.5, "beats": [{"actor": "a", "action": "walk"}]},
                {"id": "shot_1", "duration_s": 3.0, "camera": {"mode": "close"}}
            ]
        ))
        assert "shots" in out
        assert len(out["shots"]) == 2
        assert out["shots"][0]["duration_s"] == 2.5
        assert out["shots"][1]["camera"]["mode"] == "close"
        assert rep["errors"] == []

    def test_expressions_in_capabilities_and_validation(self):
        from src.contract import EXPRESSIONS, resolve_expression
        caps = capabilities()
        assert "expressions" in caps
        assert len(caps["expressions"]) == 16
        assert "angry" in caps["expressions"]
        assert "focused" in caps["expressions"]

        assert resolve_expression("furious") == "angry"
        assert resolve_expression("typing") == "focused"
        assert resolve_expression("normal") == "neutral"

        out, rep = validate_scene(self._min_scene(
            characters=[{"id": "a", "expression": "focused"}],
            beats=[{"actor": "a", "action": "punch", "expression": "angry"}]
        ))
        assert out["characters"][0]["expression"] == "focused"
        assert out["beats"][0]["expression"] == "angry"
        assert rep["errors"] == []

    def test_desk_and_laptop_objects(self):
        assert resolve_object("desk") == "desk"
        assert resolve_object("table") == "desk"
        assert resolve_object("laptop") == "laptop"
        assert resolve_object("computer") == "laptop"

        out, rep = validate_scene(self._min_scene(
            objects=[
                {"kind": "desk", "at": [0.0, -0.42]},
                {"kind": "laptop", "attach": {"actor": "a", "joint": "hand"}}
            ]
        ))
        assert out["objects"][0]["kind"] == "desk"
        assert out["objects"][1]["kind"] == "laptop"
        assert rep["errors"] == []

