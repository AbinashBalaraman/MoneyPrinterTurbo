"""build_batch_task operation: full-surface MoneyPrinterTurbo task builder.

Covers the gap where the agent could only point assemble_episode at a
hand-written file with none of the GUI's settings (voice, BGM, subtitles,
source, concat, transitions, ratio) exposed. Uses monkeypatch throughout —
no DB, no network, no repo writes.
"""

import json

from pathlib import Path

import pytest

from agent.operations import registry

registry.all_operations()  # force the full catalog load before direct module import

from agent.operations import assembly as assembly_ops
from agent.operations.registry import OperationError, get


def _op():
    return get("build_batch_task")


async def _run(**kwargs):
    return await _op().handler(**kwargs)


class _FakeBridge:
    """Stand-in for run_bridge: writes the --emit-params file like the CLI would."""

    def __init__(self, staged_params=None, exit_code=0, output="staged 2 material(s)"):
        self._staged = staged_params
        self.exit_code = exit_code
        self.output = output
        self.calls = []

    async def __call__(self, args, *, timeout=1200.0):
        self.calls.append(args)
        if self.exit_code == 0 and self._staged is not None:
            out = Path(args[args.index("--emit-params") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(self._staged), encoding="utf-8")
        return {"exit_code": self.exit_code, "output": self.output}


STAGED_PARAMS = [
    {
        "video_source": "local",
        "video_clip_duration": 5,
        "video_materials": [
            {"provider": "flowkit", "url": "t/00_scene.mp4", "duration": 5},
            {"provider": "flowkit", "url": "t/01_scene.png", "duration": 5},
        ],
        "video_script": "Beat 0. Beat 1.",
    }
]


@pytest.mark.asyncio
async def test_registered_as_assembly_write(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    op = _op()
    assert op.department == "assembly"
    assert op.risk == "write"


@pytest.mark.asyncio
async def test_rejects_empty_subject(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError):
        await _run(subject="  ")


@pytest.mark.asyncio
async def test_rejects_non_dict_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError):
        await _run(subject="Topic", settings=["voice_name"])


@pytest.mark.asyncio
async def test_writes_manifest_with_full_surface(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    out = await _run(
        subject="AI farming",
        script="Hook. Rising. Twist.",
        terms="farm, drone",
        settings={"voice_name": "zh-CN-XiaoxiaoNeural-Female", "font_size": 60},
    )
    assert out["video_source"] == "pexels"
    assert out["script_chars"] == len("Hook. Rising. Twist.")
    assert "voice_name" in out["settings_applied"]
    entries = json.loads(open(out["manifest"], encoding="utf-8").read())
    assert entries[0]["video_subject"] == "AI farming"
    assert entries[0]["font_size"] == 60
    assert entries[0]["video_terms"] == "farm, drone"


@pytest.mark.asyncio
async def test_explicit_args_win_over_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    out = await _run(
        subject="Real", settings={"video_subject": "Fake", "voice_volume": 0.5}
    )
    entries = json.loads(open(out["manifest"], encoding="utf-8").read())
    assert entries[0]["video_subject"] == "Real"
    assert entries[0]["voice_volume"] == 0.5


@pytest.mark.asyncio
async def test_flowkit_project_uses_bridge_staging(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    bridge = _FakeBridge(staged_params=STAGED_PARAMS)
    monkeypatch.setattr(assembly_ops, "run_bridge", bridge)
    out = await _run(subject="Ep 1", flowkit_project="Test Project")
    assert out["video_source"] == "local"
    assert out["material_count"] == 2
    assert out["media_staged"] == 2
    assert "--from-project" in bridge.calls[0]
    entries = json.loads(open(out["manifest"], encoding="utf-8").read())
    assert entries[0]["video_materials"][0]["provider"] == "flowkit"
    assert "Beat 0. Beat 1." in entries[0]["video_script"]


@pytest.mark.asyncio
async def test_explicit_script_wins_over_staged_narration(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(assembly_ops, "run_bridge", _FakeBridge(staged_params=STAGED_PARAMS))
    out = await _run(subject="Ep 1", script="Mine.", flowkit_project="proj-1")
    entries = json.loads(open(out["manifest"], encoding="utf-8").read())
    assert entries[0]["video_script"] == "Mine."


@pytest.mark.asyncio
async def test_bridge_failure_is_loud(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    monkeypatch.setattr(
        assembly_ops, "run_bridge",
        _FakeBridge(staged_params=None, exit_code=1, output="FAILED: no completed media"),
    )
    with pytest.raises(OperationError, match="flowkit staging failed"):
        await _run(subject="Ep 1", flowkit_project="proj-1")


# --- settings validation, derived from VideoParams -------------------------
#
# These read the real surface out of the assembly venv (cached per process).
# The point of the feature is that the field list is never hand-copied, so a
# test that stubbed the surface would not be testing the thing that matters.


@pytest.mark.asyncio
async def test_rejects_unknown_setting_and_suggests_the_real_one(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError) as excinfo:
        await _run(subject="Topic", settings={"voice": "en-US-AriaNeural-Female"})
    message = str(excinfo.value)
    assert "voice" in message
    assert "voice_name" in message, "should suggest the real field name"


@pytest.mark.asyncio
async def test_rejects_a_value_the_engine_would_not_accept(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError) as excinfo:
        await _run(subject="Topic", settings={"video_aspect": "vertical"})
    message = str(excinfo.value)
    assert "video_aspect" in message
    assert "9:16" in message, "should list the allowed values"


@pytest.mark.asyncio
async def test_rejects_a_wrongly_typed_value(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError, match="font_size"):
        await _run(subject="Topic", settings={"font_size": "big"})


@pytest.mark.asyncio
async def test_reports_every_problem_at_once(monkeypatch, tmp_path):
    """One round trip should be enough to fix all the mistakes."""
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    with pytest.raises(OperationError) as excinfo:
        await _run(subject="Topic", settings={"nope": 1, "video_aspect": "vertical"})
    message = str(excinfo.value)
    assert "nope" in message and "video_aspect" in message


@pytest.mark.asyncio
async def test_schema_op_describes_the_surface():
    from agent.operations.registry import get

    described = await get("assembly_settings_schema").handler()
    assert described["field_count"] >= 35
    assert "video_subject" in described["required"]
    assert "video_aspect" in described["fields_with_allowed_values"]
    assert "9:16" in described["fields_with_allowed_values"]["video_aspect"]
    names = {field["name"] for field in described["fields"]}
    assert {"voice_name", "bgm_volume", "font_size", "subtitle_enabled"} <= names


@pytest.mark.asyncio
async def test_schema_op_is_read_risk():
    assert get("assembly_settings_schema").risk == "read"


@pytest.mark.asyncio
async def test_valid_settings_still_pass(monkeypatch, tmp_path):
    """The gate must not reject legitimate use — the whole existing surface."""
    monkeypatch.setattr(assembly_ops, "WORKSPACE_ROOT", tmp_path)
    out = await _run(
        subject="Topic",
        settings={
            "voice_name": "en-US-AriaNeural-Female",
            "video_aspect": "9:16",
            "video_concat_mode": "sequential",
            "bgm_volume": 0.2,
            "subtitle_enabled": True,
            "font_size": 60,
        },
    )
    assert "video_aspect" in out["settings_applied"]
