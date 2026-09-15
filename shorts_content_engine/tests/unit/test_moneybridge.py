"""Unit tests for the MoneyPrinterTurbo bridge (no Money deps required)."""

from __future__ import annotations

import json
from pathlib import Path

from src.models import EpisodeManifest
from src.moneybridge.adapter import MoneyBridgeAdapter
from src.storyboard.models import StoryboardDocument

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = ROOT / "output" / "manifests" / "farmer_and_rusty_ep01.json"
STORYBOARD = ROOT / "output" / "storyboards" / "farmer_and_rusty_ep01_storyboard.json"


def _load():
    manifest = EpisodeManifest.model_validate(json.loads(MANIFEST.read_text(encoding="utf-8-sig")))
    doc = StoryboardDocument.model_validate(json.loads(STORYBOARD.read_text(encoding="utf-8")))
    return manifest, doc


def test_local_task_maps_17_stills_to_materials(tmp_path):
    manifest, doc = _load()
    adapter = MoneyBridgeAdapter(stills_dir=tmp_path / "stills")
    task = adapter.to_task(manifest, doc, source="local")
    params = task.to_params()
    assert params["video_source"] == "local"
    assert len(params["video_materials"]) == doc.total_stills == 17
    assert params["video_aspect"] == "9:16"
    assert params["video_concat_mode"] == "sequential"  # story order preserved
    assert params["match_materials_to_script"] is True
    assert "Arthur" in params["video_script"] or "well was bone dry" in params["video_script"]
    assert MoneyBridgeAdapter.validate_task(params) == []


def test_openai_image_task_carries_full_prompts():
    manifest, doc = _load()
    adapter = MoneyBridgeAdapter()
    task = adapter.to_task(manifest, doc, source="openai_image")
    params = task.to_params()
    assert params["video_source"] == "openai_image"
    assert len(params["video_terms"]) == 17
    # Full cinematic prompts must survive (Money template "{term}" passes through)
    assert "9:16" in params["video_terms"][0]
    assert "Arthur" in params["video_terms"][0]
    assert params.get("video_materials") is None
    assert MoneyBridgeAdapter.validate_task(params) == []


def test_validator_rejects_bad_tasks():
    assert MoneyBridgeAdapter.validate_task({"video_subject": "", "video_script": ""})
    bad_source = {"video_subject": "x", "video_source": "nope", "video_aspect": "9:16"}
    assert any("video_source" in e for e in MoneyBridgeAdapter.validate_task(bad_source))
    local_no_mats = {"video_subject": "x", "video_source": "local", "video_aspect": "9:16"}
    assert any("video_materials" in e for e in MoneyBridgeAdapter.validate_task(local_no_mats))


def test_batch_file_roundtrip(tmp_path):
    manifest, doc = _load()
    adapter = MoneyBridgeAdapter(stills_dir=tmp_path)
    out = adapter.to_batch_file(manifest, doc, tmp_path / "tasks.json", source="local")
    tasks = json.loads(Path(out).read_text(encoding="utf-8"))
    assert len(tasks) == 1
    assert MoneyBridgeAdapter.validate_task(tasks[0]) == []
