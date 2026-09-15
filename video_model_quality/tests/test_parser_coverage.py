"""Gate D1: parser fails fast with an actionable gap instead of silent idle."""
import pytest

from src.parser import parse_prompt, SYNONYMS


class TestCoverageGap:
    def test_unknown_prompt_raises(self):
        with pytest.raises(ValueError) as ei:
            parse_prompt("a thief steals a diamond", seed=1)
        msg = str(ei.value)
        assert "Unsupported" in msg or "Could not match" in msg
        # Must be actionable: list what IS supported.
        assert "Supported" in msg or "known" in msg

    def test_multi_action_is_not_silently_collapsed(self):
        # The single-action parser must raise rather than silently pick one
        # action from a multi-action script (the F-P0-1 defect).
        with pytest.raises(ValueError) as ei:
            parse_prompt("walk forward, then punch, then celebrate", seed=1)
        assert "multi-action" in str(ei.value).lower() or "ambiguous" in str(ei.value).lower()

    def test_every_catalog_action_has_a_synonym(self):
        from src.catalog import ACTIONS_1P, ACTIONS_2P
        for action in ACTIONS_1P + ACTIONS_2P:
            assert action in SYNONYMS, f"{action} missing from SYNONYMS"

    def test_intentional_rest_maps_to_idle(self):
        p = parse_prompt("stand still", seed=1)
        assert p["action"] == "idle"

    def test_pair_phrase_not_split(self):
        # "punch and block" is the single 2P action, not punch+block.
        p = parse_prompt("two fighters punch and block for 3s", seed=1)
        assert p["action"] == "punch_block"
        assert p["n_person"] == 2