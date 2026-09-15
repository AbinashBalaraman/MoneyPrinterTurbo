"""Tests for src/interactions.py: reaction resolution, staging, paired compilation, aimed strikes."""
import numpy as np
import pytest

from src.interactions import (
    INTERACTIONS,
    get_reaction_action,
    get_combat_pair_template,
    stage_for_interaction,
    compile_interaction_pair,
    aim_strike_at_target,
    resolve_interactions,
)
from src.rig import forward_kinematics
from src.renderer import decode_motion_features
from src.preview import interaction_stats


class TestInteractionBasics:
    def test_interactions_enum(self):
        assert set(INTERACTIONS) == {"strike", "block", "dodge", "grab", "knockdown", "assist", "talk"}

    def test_reaction_action_mapping(self):
        assert get_reaction_action("punch", "strike") == "block"
        assert get_reaction_action("kick", "dodge") == "squat"
        assert get_reaction_action("punch", "knockdown") == "knockdown"
        assert get_reaction_action("wave", "talk") == "wave"
        assert get_reaction_action("celebrate", "assist") == "celebrate"

    def test_combat_pair_templates(self):
        assert get_combat_pair_template("punch", "strike") == "punch_block"
        assert get_combat_pair_template("kick", "dodge") == "kick_dodge"
        assert get_combat_pair_template("punch", "knockdown") == "knockdown_getup"
        assert get_combat_pair_template("punch", "exchange") == "exchange"


class TestStagingAndCompilation:
    def test_stage_for_interaction_left_attacker(self):
        pos_a, pos_b, facing_a, facing_b = stage_for_interaction(
            attacker_x=-1.0, defender_x=0.5, desired_gap=0.90
        )
        assert facing_a == 1
        assert facing_b == -1
        assert pos_b == 0.5
        assert np.isclose(pos_a, 0.5 - 0.90)

    def test_stage_for_interaction_right_attacker(self):
        pos_a, pos_b, facing_a, facing_b = stage_for_interaction(
            attacker_x=1.0, defender_x=-0.2, desired_gap=0.80
        )
        assert facing_a == -1
        assert facing_b == 1
        assert pos_b == -0.2
        assert np.isclose(pos_a, -0.2 + 0.80)

    def test_compile_interaction_pair_has_contact(self):
        feat_a, feat_b, events = compile_interaction_pair(
            action="punch",
            interaction="strike",
            duration_s=2.0,
            speed=1.0,
            pos_a=-0.45,
            pos_b=0.45,
            facing_a=1
        )
        assert feat_a.shape == (48, 30)
        assert feat_b.shape == (48, 30)
        assert not np.isnan(feat_a).any()
        assert not np.isnan(feat_b).any()

        # Check for impact burst event
        bursts = [e for e in events if e.get("kind") == "impact_burst"]
        assert len(bursts) > 0

        # Stack into 2-person features and verify contact ratio > 0.20
        pair_feat = np.concatenate([feat_a, feat_b], axis=-1)
        joints = decode_motion_features(pair_feat)  # (48, 2, 15, 2)
        stats = interaction_stats(joints)
        assert stats["interacting"] is True
        assert stats["contact_ratio"] > 0.20


class TestResolveInteractions:
    def test_resolve_solo_and_paired(self):
        beats = [
            {"actor": "a", "action": "walk", "duration_s": 2.0},
            {"actor": "a", "action": "punch", "target": "b", "interaction": "strike", "duration_s": 2.0},
            {"actor": "b", "action": "block", "target": "a", "duration_s": 2.0},
            {"actor": "a", "action": "celebrate", "duration_s": 1.5},
        ]
        resolved = resolve_interactions(beats)
        assert len(resolved) == 3
        assert resolved[0]["type"] == "solo"
        assert resolved[0]["actor"] == "a"

        assert resolved[1]["type"] == "interaction"
        assert resolved[1]["attacker"] == "a"
        assert resolved[1]["defender"] == "b"
        assert resolved[1]["defender_action"] == "block"
        assert resolved[1]["impact_frame"] > 0

        assert resolved[2]["type"] == "solo"
        assert resolved[2]["actor"] == "a"


class TestAimStrikeAtTarget:
    def test_aim_strike(self):
        root = np.array([0.0, 0.0])
        angles = np.zeros(14)
        target = np.array([0.35, 0.20])
        solved, res, lean = aim_strike_at_target(root, angles, target, end_joint="hand_r")
        assert solved.shape == (14,)
        assert not np.isnan(solved).any()
