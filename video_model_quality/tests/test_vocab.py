"""Tests for Task 1: Vocabulary widening (lexicon expansion, modifiers, object aliases)."""
import pytest

from src.parser import parse_prompt, match_actions, SYNONYMS
from src.catalog import ACTIONS_1P, ACTIONS_2P
from src.contract import resolve_object


class TestGuardsFix:
    """Benchmark prompt 'stickman guards against danger' must map to block."""

    def test_guards_against_danger(self):
        res = parse_prompt("stickman guards against danger")
        assert res["action"] == "block"
        assert res["supported"] is True

    def test_guarding_against_danger(self):
        res = parse_prompt("stickman guarding against danger")
        assert res["action"] == "block"

    def test_guards_defensively(self):
        res = parse_prompt("stickman guards defensively")
        assert res["action"] == "block"


class TestSynonymsExpansion:
    """Test widened synonyms and inflections across all 17 catalog actions."""

    @pytest.mark.parametrize("action", ACTIONS_1P + ACTIONS_2P)
    def test_every_action_in_synonyms(self, action):
        assert action in SYNONYMS
        assert len(SYNONYMS[action]) >= 6

    def test_dodges_map_to_squat(self):
        for phrase in ["stickman sidestep", "stickman weave low", "stickman bob", "stickman evaded strike"]:
            res = parse_prompt(phrase)
            assert res["action"] == "squat", f"Failed on {phrase}"

    def test_locomotion_widening(self):
        assert parse_prompt("stickman stride forward")["action"] == "walk"
        assert parse_prompt("stickman wanders calmly")["action"] == "walk"
        assert parse_prompt("stickman pacing slowly")["action"] == "walk"
        assert parse_prompt("stickman charging forward")["action"] == "run"
        assert parse_prompt("stickman bolted right")["action"] == "run"
        assert parse_prompt("stickman scurried away")["action"] == "run"
        assert parse_prompt("stickman stepping back")["action"] == "walkback"
        assert parse_prompt("stickman backpedals left")["action"] == "walkback"
        assert parse_prompt("stickman retreating quickly")["action"] == "walkback"

    def test_gestures_widening(self):
        assert parse_prompt("stickman saluting the crowd")["action"] == "wave"
        assert parse_prompt("stickman beckoning forward")["action"] == "wave"
        assert parse_prompt("stickman signaling right")["action"] == "wave"
        assert parse_prompt("stickman applauding proudly")["action"] == "celebrate"
        assert parse_prompt("stickman fist pump wildly")["action"] == "celebrate"
        assert parse_prompt("stickman rejoicing victory")["action"] == "celebrate"

    def test_acrobatics_widening(self):
        assert parse_prompt("stickman vaulted high")["action"] == "jump"
        assert parse_prompt("stickman cartwheeling right")["action"] == "jump"
        assert parse_prompt("stickman flipping up")["action"] == "jump"
        assert parse_prompt("stickman somersaulting high")["action"] == "jump"
        assert parse_prompt("stickman roll forward")["action"] == "squat"
        assert parse_prompt("stickman tumbling low")["action"] == "squat"

    def test_combat_widening(self):
        assert parse_prompt("stickman throws a punch")["action"] == "punch"
        assert parse_prompt("stickman uppercutting right")["action"] == "punch"
        assert parse_prompt("stickman fist strike forward")["action"] == "punch"
        assert parse_prompt("stickman roundhouse kick")["action"] == "kick"
        assert parse_prompt("stickman dropkick left")["action"] == "kick"
        assert parse_prompt("stickman punts forward")["action"] == "kick"
        assert parse_prompt("stickman parrying blow")["action"] == "block"
        assert parse_prompt("stickman warding off hit")["action"] == "block"
        assert parse_prompt("stickman raising shield")["action"] == "block"

    def test_reactions_widening(self):
        assert parse_prompt("stickman hit the deck")["action"] == "knockdown"
        assert parse_prompt("stickman wiped out")["action"] == "knockdown"
        assert parse_prompt("stickman toppling down")["action"] == "knockdown"
        assert parse_prompt("stickman stand back up")["action"] == "getup"
        assert parse_prompt("stickman rose slowly")["action"] == "getup"
        assert parse_prompt("stickman recovering from ground")["action"] == "getup"
        assert parse_prompt("stickman back on feet")["action"] == "getup"

    def test_paired_actions_widening(self):
        assert parse_prompt("fighters punches and blocks")["action"] == "punch_block"
        assert parse_prompt("one punches the other blocks")["action"] == "punch_block"
        assert parse_prompt("fighters kicks and dodges")["action"] == "kick_dodge"
        assert parse_prompt("fighters kick and evade")["action"] == "kick_dodge"
        assert parse_prompt("fighters knock down and get up")["action"] == "knockdown_getup"
        assert parse_prompt("fighter kicks opponent down and opponent recovers")["action"] == "knockdown_getup"
        assert parse_prompt("fighters trade blows")["action"] == "exchange"
        assert parse_prompt("fighters brawling vigorously")["action"] == "exchange"


class TestModifiersWidening:
    """Test direction, speed, and amplitude word lists with intensifiers and distance/force words."""

    def test_direction_modifiers(self):
        assert parse_prompt("stickman walk to the left")["direction"] == -1
        assert parse_prompt("stickman walk leftward")["direction"] == -1
        assert parse_prompt("stickman walk rearward")["direction"] == -1
        assert parse_prompt("stickman walk to the right")["direction"] == 1
        assert parse_prompt("stickman walk rightward")["direction"] == 1
        assert parse_prompt("stickman walk ahead")["direction"] == 1

    def test_speed_modifiers(self):
        assert parse_prompt("stickman walk furiously")["speed"] == 1.5
        assert parse_prompt("stickman run wildly")["speed"] == 1.5
        assert parse_prompt("stickman walk swiftly")["speed"] == 1.5
        assert parse_prompt("stickman walk briskly")["speed"] == 1.5
        assert parse_prompt("stickman walk cautiously")["speed"] == 0.6
        assert parse_prompt("stickman walk deliberately")["speed"] == 0.6
        assert parse_prompt("stickman walk sluggishly")["speed"] == 0.6

    def test_amplitude_modifiers(self):
        assert parse_prompt("stickman punch furiously")["amplitude"] == 1.4
        assert parse_prompt("stickman punch forcefully")["amplitude"] == 1.4
        assert parse_prompt("stickman squat deeply")["amplitude"] == 1.4
        assert parse_prompt("stickman punch subtly")["amplitude"] == 0.6
        assert parse_prompt("stickman punch cautiously")["amplitude"] == 0.6
        assert parse_prompt("stickman punch delicately")["amplitude"] == 0.6
        assert parse_prompt("stickman squat shallow")["amplitude"] == 0.6

    def test_return_contract_preserved(self):
        res = parse_prompt("stickman punch wildly forward for 4s", seed=7)
        expected_keys = {
            "action", "n_person", "direction", "speed", "amplitude",
            "duration_seconds", "seed", "supported", "raw_prompt"
        }
        assert set(res.keys()) == expected_keys
        assert res["speed"] in (0.6, 1.0, 1.5)
        assert res["amplitude"] in (0.6, 1.0, 1.4)
        assert res["direction"] in (-1, 1)
        assert res["duration_seconds"] == 4.0
        assert res["seed"] == 7


class TestObjectRegistryAliases:
    """Test object registry alias expansions in contract.py."""

    def test_aliases_resolve_correctly(self):
        assert resolve_object("dagger") == "sword"
        assert resolve_object("broadsword") == "sword"
        assert resolve_object("stick") == "staff"
        assert resolve_object("cane") == "staff"
        assert resolve_object("throne") == "chair"
        assert resolve_object("armchair") == "chair"
        assert resolve_object("orb") == "ball"
        assert resolve_object("package") == "box"
        assert resolve_object("parcel") == "box"
        assert resolve_object("glitter") == "confetti"
        assert resolve_object("sledgehammer") == "gavel"
        assert resolve_object("cheerers") == "crowd"


class TestRejectionIntegrity:
    """Out-of-vocabulary and ambiguous prompts must still raise ValueError."""

    def test_unsupported_prompts_raise(self):
        with pytest.raises(ValueError):
            parse_prompt("a thief steals a diamond")
        with pytest.raises(ValueError):
            parse_prompt("a submarine flying to mars")

    def test_multi_action_prompts_raise(self):
        with pytest.raises(ValueError):
            parse_prompt("walk forward, then punch")
