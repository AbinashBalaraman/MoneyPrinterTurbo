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
