"""Integration tests: SceneScript dict -> validate -> compile -> render contract."""
import numpy as np
import pytest

from src.scene import SceneScript, compile_scene, compile_scene_dict
from src.contract import ContractError


ARMED_DUEL = {
    "title": "duel",
    "theme": "dark",
    "camera": {"mode": "follow", "focus": "a", "actors": ["a", "b"]},
    "characters": [{"id": "a", "start_x": -0.45}, {"id": "b", "start_x": 0.45}],
    "beats": [{"actor": "a", "action": "punch", "duration_s": 2.0},
              {"actor": "b", "action": "block", "duration_s": 2.0}],
    "objects": [
        {"id": "sw", "kind": "katana", "attach": {"actor": "a", "joint": "hand"}},
        {"id": "rock", "kind": "boulder", "at": [0.2, -0.4],
         "throw": {"frame": 24, "vx": 1.0, "vy": 1.1}, "bounce": True},
    ],
}


class TestCompileSceneDict:
    def test_full_scene_compiles(self):
        res = compile_scene_dict(ARMED_DUEL)
        assert res["feat"].shape[1] == 60 and res["n_person"] == 2
        assert len(res["prop_tracks"]) == res["T"]
        assert res["camera_track"]["camera_x"].shape[0] == res["T"]
        assert np.isfinite(res["camera_track"]["camera_x"]).all()
        assert res["theme"] == "dark"

    def test_object_attached_to_hand(self):
        res = compile_scene_dict(ARMED_DUEL)
        anchored = [p for fr in res["prop_tracks"] for p in fr if p.get("anchor_puppet") == 0]
        assert len(anchored) == res["T"]  # sword held every frame

    def test_throw_produces_impact(self):
        res = compile_scene_dict(ARMED_DUEL)
        assert len(res["impacts"]) >= 1
        assert any(i["kind"] == "impact_burst" for i in res["impacts"])

    def test_deterministic(self):
        a = compile_scene_dict(ARMED_DUEL)
        b = compile_scene_dict(ARMED_DUEL)
        assert np.array_equal(a["feat"], b["feat"])
        assert a["prop_tracks"] == b["prop_tracks"]

    def test_invalid_scene_rejected(self):
        with pytest.raises(ContractError):
            compile_scene_dict({"beats": [{"action": "teleport"}]})

    def test_motion_only_compile_has_no_tracks(self):
        script = SceneScript.from_dict(ARMED_DUEL)
        res = compile_scene(script, resolve_props=False)
        assert res["feat"].shape[1] == 60
        assert "prop_tracks" not in res


class TestSceneScriptRoundtrip:
    def test_roundtrip_preserves_fields(self):
        s = SceneScript.from_dict(ARMED_DUEL)
        d = s.to_dict()
        assert d["theme"] == "dark"
        assert d["camera"]["mode"] == "follow"
        assert len(d["objects"]) == 2
        s2 = SceneScript.from_dict(d)
        assert s2.beats[0].action == "punch"
        assert s2.characters[0].facing == 1


class TestRenderIntegration:
    def test_sd_render_with_objects_and_camera(self, tmp_path):
        import os
        from src.renderer import render_to_video
        scene = dict(ARMED_DUEL)
        scene["beats"] = [{"actor": "a", "action": "walk", "duration_s": 0.6}]
        res = compile_scene_dict(scene)
        out = tmp_path / "smoke.mp4"
        render_to_video(res["feat"], str(out), fix_contact=False,
                        vfx_events=res["vfx_events"], prop_tracks=res["prop_tracks"],
                        camera_track=res["camera_track"], impacts=res["impacts"])
        assert os.path.exists(out) and os.path.getsize(out) > 2000

    def test_hd_render_with_objects_and_camera(self, tmp_path):
        import os
        from src.stage_renderer import render_stage_video
        scene = dict(ARMED_DUEL)
        scene["beats"] = [{"actor": "a", "action": "walk", "duration_s": 0.6}]
        res = compile_scene_dict(scene)
        out = tmp_path / "smoke_hd.mp4"
        render_stage_video(res["feat"], str(out), theme_name=res["theme"],
                           scenery=res["scenery"], fix_contact=False,
                           vfx=res["vfx_events"], prop_tracks=res["prop_tracks"],
                           camera_track=res["camera_track"], impacts=res["impacts"])
        assert os.path.exists(out) and os.path.getsize(out) > 2000
