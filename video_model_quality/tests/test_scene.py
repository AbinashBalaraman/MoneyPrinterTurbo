"""Tests for the SceneScript plan layer (multi-action, multi-actor, deterministic)."""
import numpy as np
import pytest

from src.scene import (SceneScript, Beat, Character, parse_script, compile_scene,
                       PAIR_EXPANSION)


class TestParseScript:
    def test_multi_action_preserved_in_order(self):
        s = parse_script("walk forward, then punch, then celebrate")
        assert [b.action for b in s.beats] == ["walk", "punch", "celebrate"]

    def test_clause_order_not_dict_order(self):
        s = parse_script("punch then walk")
        assert [b.action for b in s.beats] == ["punch", "walk"]

    def test_pair_action_expands_to_two_actors(self):
        s = parse_script("punch and block")
        assert {c.id for c in s.characters} == {"a", "b"}
        assert len(s.beats) == 2
        assert {b.actor for b in s.beats} == {"a", "b"}
        assert [b.action for b in s.beats] == ["punch", "block"]

    def test_duration_parsed_per_clause(self):
        s = parse_script("walk for 3 seconds then punch")
        assert s.beats[0].duration_s == 3.0

    def test_consecutive_synonym_not_duplicated(self):
        s = parse_script("celebrate victory")
        assert [b.action for b in s.beats] == ["celebrate"]

    def test_unknown_prompt_raises(self):
        with pytest.raises(ValueError):
            parse_script("a thief steals a diamond")

    def test_empty_prompt_raises(self):
        with pytest.raises(ValueError):
            parse_script("   ")


class TestCompileScene:
    def test_single_actor_shape(self):
        s = parse_script("walk then punch")
        res = compile_scene(s)
        assert res["feat"].shape[1] == 30
        assert res["n_person"] == 1
        assert res["T"] > 0

    def test_deterministic(self):
        s = parse_script("walk then punch then celebrate")
        a = compile_scene(s)["feat"]
        b = compile_scene(s)["feat"]
        assert np.array_equal(a, b)

    def test_two_actor_shape(self):
        s = parse_script("punch and block")
        res = compile_scene(s)
        assert res["n_person"] == 2
        assert res["feat"].shape[1] == 60

    def test_empty_scene_raises(self):
        with pytest.raises(ValueError):
            compile_scene(SceneScript(characters=[Character("a", 0.0)], beats=[]))

    def test_roundtrip_dict(self):
        s = parse_script("walk then punch")
        s2 = SceneScript.from_dict(s.to_dict())
        assert [b.action for b in s2.beats] == [b.action for b in s.beats]

    def test_targeted_interaction_compile(self):
        from src.renderer import decode_motion_features
        from src.preview import interaction_stats

        script = SceneScript(
            title="Duel",
            characters=[Character("a", start_x=-0.45), Character("b", start_x=0.45)],
            beats=[
                Beat(actor="a", action="punch", target="b", interaction="strike", duration_s=2.0),
            ]
        )
        res = compile_scene(script)
        assert res["n_person"] == 2
        assert res["feat"].shape[1] == 60
        assert res["T"] > 0
        joints = decode_motion_features(res["feat"])
        stats = interaction_stats(joints)
        assert stats["interacting"] is True
        assert stats["contact_ratio"] > 0.20

    def test_shots_compile(self):
        script = SceneScript(
            title="Two Shots",
            shots=[
                {"id": "shot_0", "beats": [{"actor": "a", "action": "walk", "duration_s": 2.0}]},
                {"id": "shot_1", "beats": [{"actor": "a", "action": "punch", "duration_s": 1.5}]},
            ]
        )
        res = compile_scene(script)
        assert res["n_person"] == 1
        assert res["T"] > 0
        tl0 = compile_scene(SceneScript(beats=[Beat("walk", 2.0)]))
        tl1 = compile_scene(SceneScript(beats=[Beat("punch", 1.5)]))
        assert res["T"] == tl0["T"] + tl1["T"]

    def test_solo_beat_before_interaction_keeps_staging(self):
        """A solo beat before a targeted exchange must not desync the pair.

        Regression: blend_feature_clips re-anchored each actor's interaction
        clip to its own previous root, so a walk-in pushed the fighters apart
        (gap ~1.7) and the strike never connected.
        """
        from src.renderer import decode_motion_features
        from src.preview import interaction_stats

        script = SceneScript(
            title="Walk-in Duel",
            characters=[Character("a", start_x=-1.3), Character("b", start_x=1.3)],
            beats=[
                Beat(actor="a", action="walk", duration_s=1.5),
                Beat(actor="a", action="punch", target="b",
                     interaction="strike", duration_s=2.0),
            ],
        )
        res = compile_scene(script)
        joints = decode_motion_features(res["feat"])
        stats = interaction_stats(joints, windows=res.get("interactions"))
        # The declared exchange must actually land despite the solo intro.
        assert res["interactions"], "interaction should be recorded"
        win = stats["windows"][0]
        assert win["contact_ratio"] > 0.20, f"exchange did not engage: {win}"
        assert win["min_dist"] < 0.5
