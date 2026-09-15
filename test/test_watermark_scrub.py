"""Tests for the Gemini/Flow watermark scrubber.

The gwr CLI is never executed: subprocess.run is faked, and the fake writes the
``--output`` file the real CLI would write, so the in-place replace logic is
exercised for real.
"""

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from automation.watermark_scrub import (
    GWR_PACKAGE,
    GeminiWatermarkScrubber,
    ScrubResult,
    WatermarkScrubError,
    _resolve_gwr_entry,
)

APPLIED_PAYLOAD = {
    "input": "in.png",
    "output": "out.png",
    "kind": "image",
    "meta": {
        "applied": True,
        "size": 48,
        "position": {"x": 647, "y": 1255, "width": 48, "height": 48},
        "qualityStatus": "clean",
        "decisionTier": "validated-match",
    },
}

CLEAN_PAYLOAD = {
    "input": "in.png",
    "output": "out.png",
    "kind": "image",
    "meta": {"applied": False, "size": None, "position": None, "qualityStatus": "clean"},
}


def make_png(path: Path, size=(64, 64)) -> Path:
    Image.new("RGB", size, (120, 90, 60)).save(path)
    return path


def fake_run(monkeypatch, payload, returncode=0, stderr="", write_output=True):
    """Replace subprocess.run, emulating the CLI's --output write."""
    calls = []

    def _run(cmd, capture_output=True, text=True, timeout=None, check=False):
        calls.append({"cmd": cmd, "timeout": timeout})
        if write_output and returncode == 0:
            out_index = cmd.index("--output") + 1
            Path(cmd[out_index]).write_bytes(b"scrubbed-bytes")
        stdout = json.dumps(payload) if payload is not None else ""
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(subprocess, "run", _run)
    return calls


def scrubber(entry=None):
    return GeminiWatermarkScrubber(node="node", entry=entry or Path("gwr.mjs"))


# --- JSON parsing ----------------------------------------------------------


def test_parse_json_reads_a_plain_payload():
    assert GeminiWatermarkScrubber._parse_json(json.dumps(APPLIED_PAYLOAD), Path("a.png"))["meta"]["applied"]


def test_parse_json_tolerates_leading_log_lines():
    noisy = "INFO starting\nINFO decoding\n" + json.dumps(APPLIED_PAYLOAD)
    parsed = GeminiWatermarkScrubber._parse_json(noisy, Path("a.png"))
    assert parsed["meta"]["size"] == 48


def test_parse_json_raises_on_empty_output():
    with pytest.raises(WatermarkScrubError, match="no JSON"):
        GeminiWatermarkScrubber._parse_json("   ", Path("a.png"))


def test_parse_json_raises_on_non_json():
    with pytest.raises(WatermarkScrubError, match="was not JSON"):
        GeminiWatermarkScrubber._parse_json("totally not json", Path("a.png"))


# --- scrub behaviour -------------------------------------------------------


def test_scrub_raises_for_missing_file(tmp_path):
    with pytest.raises(WatermarkScrubError, match="no such image"):
        scrubber().scrub(tmp_path / "absent.png")


def test_scrub_in_place_replaces_original_and_leaves_no_temp(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")
    fake_run(monkeypatch, APPLIED_PAYLOAD)

    result = scrubber().scrub(image)

    assert result.applied is True
    assert result.size == 48
    assert result.quality_status == "clean"
    assert result.decision_tier == "validated-match"
    assert image.read_bytes() == b"scrubbed-bytes"
    # The temp file must not survive: the pipeline scans this directory.
    assert list(tmp_path.glob("*.tmp*")) == []


def test_scrub_to_explicit_output_leaves_source_untouched(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")
    before = image.read_bytes()
    out = tmp_path / "clean.png"
    fake_run(monkeypatch, APPLIED_PAYLOAD)

    scrubber().scrub(image, output_path=out)

    assert image.read_bytes() == before
    assert out.exists()


def test_scrub_raises_when_nonzero_exit(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")
    fake_run(monkeypatch, APPLIED_PAYLOAD, returncode=2, stderr="sharp exploded", write_output=False)

    with pytest.raises(WatermarkScrubError, match="exited 2"):
        scrubber().scrub(image)


def test_scrub_raises_on_timeout(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")

    def _timeout(cmd, capture_output=True, text=True, timeout=None, check=False):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", _timeout)
    with pytest.raises(WatermarkScrubError, match="timed out"):
        scrubber().scrub(image)


def test_scrub_raises_when_success_but_no_output_written(tmp_path, monkeypatch):
    """Guards against the original being replaced by nothing."""
    image = make_png(tmp_path / "a.png")
    before = image.read_bytes()
    fake_run(monkeypatch, APPLIED_PAYLOAD, write_output=False)

    with pytest.raises(WatermarkScrubError, match="wrote no output"):
        scrubber().scrub(image)
    assert image.read_bytes() == before


def test_scrub_reports_clean_image_without_claiming_removal(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")
    fake_run(monkeypatch, CLEAN_PAYLOAD)

    result = scrubber().scrub(image)

    assert result.applied is False
    assert result.found_watermark is False


def test_scrub_passes_json_flag_and_output_path(tmp_path, monkeypatch):
    image = make_png(tmp_path / "a.png")
    calls = fake_run(monkeypatch, APPLIED_PAYLOAD)

    scrubber().scrub(image)

    cmd = calls[0]["cmd"]
    assert "--json" in cmd
    assert "--output" in cmd
    assert cmd[cmd.index("remove") - 1].endswith("gwr.mjs") or "gwr.mjs" in cmd


def test_scrub_many_processes_every_file(tmp_path, monkeypatch):
    images = [make_png(tmp_path / f"{i}.png") for i in range(3)]
    calls = fake_run(monkeypatch, APPLIED_PAYLOAD)

    results = scrubber().scrub_many(images)

    assert len(results) == 3
    assert len(calls) == 3
    assert all(r.applied for r in results)


# --- availability ----------------------------------------------------------


def test_available_false_when_entry_missing():
    assert GeminiWatermarkScrubber(node="node", entry=Path("definitely/not/here.mjs")).available() is False


def test_available_true_when_entry_exists(tmp_path):
    entry = tmp_path / "gwr.mjs"
    entry.write_text("// stub")
    assert GeminiWatermarkScrubber(node="node", entry=entry).available() is True


def test_resolve_entry_honours_explicit_override(tmp_path, monkeypatch):
    entry = tmp_path / "custom.mjs"
    entry.write_text("// stub")
    monkeypatch.setenv("AUTOSHORTS_GWR_ENTRY", str(entry))
    assert _resolve_gwr_entry() == entry


def test_resolve_entry_raises_when_override_is_wrong(monkeypatch):
    monkeypatch.setenv("AUTOSHORTS_GWR_ENTRY", "C:/nope/missing.mjs")
    with pytest.raises(WatermarkScrubError, match="does not exist"):
        _resolve_gwr_entry()


def test_error_message_names_the_package(monkeypatch, tmp_path):
    """The install hint must be actionable, so pin the package name."""
    monkeypatch.setenv("AUTOSHORTS_GWR_ENTRY", "")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr("automation.watermark_scrub.shutil.which", lambda _: None)
    with pytest.raises(WatermarkScrubError) as exc:
        _resolve_gwr_entry()
    assert GWR_PACKAGE in str(exc.value)


# --- result shape ----------------------------------------------------------


def test_scrub_result_found_watermark_property():
    assert ScrubResult(path="a.png", applied=True).found_watermark is True
    assert ScrubResult(path="a.png", applied=False).found_watermark is False
