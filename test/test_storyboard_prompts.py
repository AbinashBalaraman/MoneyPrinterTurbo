"""Tests for the storyboard/manifest prompt reader.

Fixtures mirror the real shapes from shorts_content_engine: the storyboard form
carries ``scenes[].stills[]`` with ``image_prompt`` + ``hold_seconds``, the
manifest form carries only ``scenes[].action_prompt`` + ``duration``.
"""

import json

import pytest

from automation.storyboard_prompts import (
    Storyboard,
    StoryboardError,
    StoryboardStill,
    find_storyboards,
    load_storyboard,
)

STORYBOARD = {
    "series_id": "farmer_and_rusty",
    "episode_num": 1,
    "title": "The Whispering Furrow",
    "target_duration": 45.0,
    "actual_duration": 45.0,
    "style": "cinematic_photorealistic",
    "scenes": [
        {
            "scene_index": 1,
            "duration": 6.0,
            "narration": "The well was bone dry.",
            "stills": [
                {
                    "label": "S1-IMG1",
                    "image_prompt": "wide establishing shot of a dry stone well",
                    "hold_seconds": 3.0,
                    "shot_type": "Wide establishing",
                    "transition": "cross-dissolve",
                    "motion_hint": "Slow push-in",
                    "negative_prompt": "cartoon, blurry",
                },
                {
                    "label": "S1-IMG2",
                    "image_prompt": "close up of the farmer's weathered face",
                    "hold_seconds": 3.0,
                    "shot_type": "Close emotional beat",
                },
            ],
        },
        {
            "scene_index": 2,
            "duration": 7.0,
            "narration": "Rusty sniffed the arid wind.",
            "stills": [
                {
                    "label": "S2-IMG1",
                    "image_prompt": "the dog raises its head into the wind",
                    "hold_seconds": 2.33,
                    "shot_type": "Wide establishing",
                },
                {
                    "label": "S2-IMG2",
                    "image_prompt": "medium shot of the farmer looking down",
                    "hold_seconds": 2.34,
                    "shot_type": "Medium action",
                },
            ],
        },
    ],
}

MANIFEST = {
    "series_id": "farmer_and_rusty",
    "episode_num": 2,
    "title": "A Manifest Episode",
    "style": "cinematic",
    "scenes": [
        {
            "scene_index": 1,
            "time_start": 0.0,
            "time_end": 6.0,
            "duration": 6.0,
            "narration": "narration one",
            "action_prompt": "the farmer stares into the well",
            "camera_directive": "Low angle push-in",
        },
        {
            "scene_index": 2,
            "time_start": 6.0,
            "time_end": 13.0,
            "duration": 7.0,
            "narration": "narration two",
            "action_prompt": "the dog runs across the cracked earth",
            "camera_directive": "Tracking shot",
        },
    ],
}


def write(tmp_path, payload, name="board.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- storyboard shape ------------------------------------------------------


def test_loads_storyboard_with_per_still_prompts(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))

    assert board.title == "The Whispering Furrow"
    assert board.series_id == "farmer_and_rusty"
    assert board.episode_num == 1
    assert board.style == "cinematic_photorealistic"
    assert len(board.stills) == 4
    assert [s.label for s in board.stills] == ["S1-IMG1", "S1-IMG2", "S2-IMG1", "S2-IMG2"]


def test_holds_and_prompts_preserve_order(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))

    assert board.prompts() == [
        "wide establishing shot of a dry stone well",
        "close up of the farmer's weathered face",
        "the dog raises its head into the wind",
        "medium shot of the farmer looking down",
    ]
    assert board.holds() == [3.0, 3.0, 2.33, 2.34]


def test_total_hold_seconds_sums_the_storyboard(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))
    assert board.total_hold_seconds == pytest.approx(10.67)


def test_detects_varying_holds(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))
    assert board.has_uniform_holds is False


def test_detects_uniform_holds(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    for scene in payload["scenes"]:
        for still in scene["stills"]:
            still["hold_seconds"] = 3.0
    board = load_storyboard(write(tmp_path, payload))
    assert board.has_uniform_holds is True


def test_carries_shot_type_and_motion_hint(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))
    first = board.stills[0]
    assert first.shot_type == "Wide establishing"
    assert first.transition == "cross-dissolve"
    assert first.motion_hint == "Slow push-in"
    assert first.negative_prompt == "cartoon, blurry"
    assert first.scene_index == 1


def test_derives_hold_from_time_range_when_hold_seconds_missing(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    del payload["scenes"][0]["stills"][0]["hold_seconds"]
    payload["scenes"][0]["stills"][0]["time_start"] = 0.0
    payload["scenes"][0]["stills"][0]["time_end"] = 3.0

    board = load_storyboard(write(tmp_path, payload))
    assert board.stills[0].hold_seconds == 3.0


# --- manifest shape --------------------------------------------------------


def test_falls_back_to_manifest_shape(tmp_path):
    board = load_storyboard(write(tmp_path, MANIFEST))

    assert board.title == "A Manifest Episode"
    assert len(board.stills) == 2
    assert board.stills[0].image_prompt == "the farmer stares into the well"
    assert board.stills[0].hold_seconds == 6.0
    assert board.stills[0].shot_type == "Low angle push-in"
    assert board.total_hold_seconds == pytest.approx(13.0)


def test_manifest_derives_hold_from_time_range(tmp_path):
    payload = json.loads(json.dumps(MANIFEST))
    del payload["scenes"][0]["duration"]
    board = load_storyboard(write(tmp_path, payload))
    assert board.stills[0].hold_seconds == 6.0


# --- failures --------------------------------------------------------------


def test_missing_file_raises(tmp_path):
    with pytest.raises(StoryboardError, match="not found"):
        load_storyboard(tmp_path / "nope.json")


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StoryboardError, match="not valid JSON"):
        load_storyboard(path)


def test_non_object_root_raises(tmp_path):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(StoryboardError, match="must be an object"):
        load_storyboard(path)


def test_no_scenes_raises(tmp_path):
    with pytest.raises(StoryboardError, match="no usable stills"):
        load_storyboard(write(tmp_path, {"title": "empty", "scenes": []}))


def test_empty_prompt_raises(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    payload["scenes"][0]["stills"][0]["image_prompt"] = "   "
    with pytest.raises(StoryboardError, match="empty image prompt"):
        load_storyboard(write(tmp_path, payload))


def test_still_without_any_timing_raises(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    del payload["scenes"][0]["stills"][0]["hold_seconds"]
    with pytest.raises(StoryboardError, match="neither hold_seconds nor a time range"):
        load_storyboard(write(tmp_path, payload))


def test_still_model_rejects_non_positive_hold():
    with pytest.raises(StoryboardError, match="non-positive hold"):
        StoryboardStill(label="X", image_prompt="a barn", hold_seconds=0)


def test_still_model_rejects_blank_prompt():
    with pytest.raises(StoryboardError, match="empty image prompt"):
        StoryboardStill(label="X", image_prompt="  ", hold_seconds=2.0)


# --- discovery -------------------------------------------------------------


def test_find_storyboards_prefers_storyboards_over_manifests(tmp_path):
    (tmp_path / "output/storyboards").mkdir(parents=True)
    (tmp_path / "output/manifests").mkdir(parents=True)
    (tmp_path / "output/storyboards/ep01_storyboard.json").write_text("{}")
    (tmp_path / "output/manifests/ep01.json").write_text("{}")
    (tmp_path / "output/manifests/~$ep01.json").write_text("{}")

    found = [p.name for p in find_storyboards(tmp_path)]
    assert found == ["ep01_storyboard.json", "ep01.json"]


def test_find_storyboards_on_missing_tree_is_empty(tmp_path):
    assert find_storyboards(tmp_path / "absent") == []


def test_storyboard_defaults_are_safe():
    board = Storyboard(title="x")
    assert board.total_hold_seconds == 0
    assert board.has_uniform_holds is True
    assert board.prompts() == []
    assert board.script == ""


# --- narration / script ----------------------------------------------------


def test_script_joins_narration_in_scene_order(tmp_path):
    board = load_storyboard(write(tmp_path, STORYBOARD))
    assert board.script == "The well was bone dry. Rusty sniffed the arid wind."


def test_script_comes_from_the_manifest_too(tmp_path):
    board = load_storyboard(write(tmp_path, MANIFEST))
    assert board.script == "narration one narration two"


def test_script_skips_blank_narration(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    payload["scenes"][0]["narration"] = "   "
    board = load_storyboard(write(tmp_path, payload))
    assert board.script == "Rusty sniffed the arid wind."


def test_script_is_empty_when_no_narration(tmp_path):
    payload = json.loads(json.dumps(STORYBOARD))
    for scene in payload["scenes"]:
        del scene["narration"]
    board = load_storyboard(write(tmp_path, payload))
    # Empty means AutoShorts would generate its own script, so this must be
    # distinguishable from a real one.
    assert board.script == ""

