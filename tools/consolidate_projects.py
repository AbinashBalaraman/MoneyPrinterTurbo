#!/usr/bin/env python
"""Vendor the sibling sub-projects into AutoShorts as one consolidated tree.

AutoShorts is the single working project. Everything else (flowkit,
shorts_content_engine, the video_model* trees, ...) becomes a vendored
sub-directory inside it rather than a separate project folder.

What this does
--------------
For each source project it copies the *source* only. Regenerable and
repo-nesting directories are pruned:

    .git  .hg  .svn            -> keeps AutoShorts a single repo, not a nest
    .venv  venv  env           -> recreate with `python -m venv`
    node_modules               -> recreate with `npm install`
    __pycache__ .pytest_cache  -> recreate by running anything
    .mypy_cache .ruff_cache

The originals are left completely untouched in Projects/ as a backup, so
nothing is destroyed. A manifest (AutoShorts/.vendored.json) records, for
every project, where it came from, its original commit, whether it was dirty,
and how much was skipped -- so the vendoring is auditable and reversible.

Idempotent: an existing destination is skipped, never overwritten.

Usage
-----
    python tools/consolidate_projects.py            # copy what is missing
    python tools/consolidate_projects.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECTS_ROOT = Path(r"C:\Users\SATHYA TRADERS\Documents\Abi\Projects")
AUTOSHORTS = PROJECTS_ROOT / "AutoShorts"

SOURCES = [
    "flowkit",
    "shorts_content_engine",
    "opencode_endpoint",
    "video_model",
    "video_model_dev",
    "video_model_quality",
    "content_creation",
    # Renamed from "agentMemory" -> "vscode-agentmemory-ext" to avoid collision
    # with flowkit/agent_data assistant memory. Original source was
    # Projects/agentMemory; dest is now vscode-agentmemory-ext (already present,
    # so future runs SKIP instead of re-vendoring the old name).
    "vscode-agentmemory-ext",
]

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn",
    ".venv", "venv", "env", ".env.d",
    "node_modules", "bower_components",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".ipynb_checkpoints", ".cache",
}

EXCLUDE_FILE_SUFFIXES = {".pyc", ".pyo", ".pyd"}
EXCLUDE_FILE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def git_info(path: Path) -> dict:
    """Best-effort git provenance for a source project."""

    def run(*args: str):
        try:
            r = subprocess.run(
                ["git", "-C", str(path), *args],
                capture_output=True, text=True, timeout=30,
            )
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:
            return None

    head = run("rev-parse", "HEAD")
    if not head:
        return {"git": False}

    status = run("status", "--porcelain") or ""
    return {
        "git": True,
        "head": head,
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "remote": run("config", "--get", "remote.origin.url"),
        "dirty": bool(status.strip()),
        "dirty_files": len([ln for ln in status.splitlines() if ln.strip()]),
    }


def copy_source(src: Path, dst: Path, counter: dict, errors: list) -> None:
    """Copy a project tree, pruning EXCLUDE_DIRS and counting what we skip.

    A per-file copy (rather than shutil.copytree) so that one unreadable file
    records an error instead of aborting the whole 25k-file copy.
    """
    for dirpath, dirnames, filenames in os.walk(src):
        keep = []
        for d in dirnames:
            if d in EXCLUDE_DIRS:
                counter["dirs"] += 1
            else:
                keep.append(d)
        dirnames[:] = keep

        rel = os.path.relpath(dirpath, src)
        target = dst if rel == "." else dst / rel
        os.makedirs(target, exist_ok=True)

        for name in filenames:
            if name in EXCLUDE_FILE_NAMES:
                counter["files"] += 1
                continue
            if os.path.splitext(name)[1].lower() in EXCLUDE_FILE_SUFFIXES:
                counter["files"] += 1
                continue

            s = os.path.join(dirpath, name)
            t = os.path.join(target, name)
            try:
                shutil.copy2(s, t)
                counter["copied"] += 1
                counter["bytes"] += os.path.getsize(s)
            except Exception as exc:  # noqa: BLE001 - we want to keep going
                errors.append(f"{s} -> {type(exc).__name__}: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be copied without writing anything")
    args = ap.parse_args()

    if not AUTOSHORTS.is_dir():
        print(f"ERROR: {AUTOSHORTS} does not exist", file=sys.stderr)
        return 2

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_by": "tools/consolidate_projects.py",
        "note": (
            "Sub-projects vendored flat into AutoShorts (nested .git pruned). "
            "Originals remain untouched at source_path."
        ),
        "excluded_dirs": sorted(EXCLUDE_DIRS),
        "projects": {},
    }

    print(f"AutoShorts : {AUTOSHORTS}")
    print(f"dry run    : {args.dry_run}")
    print()

    all_errors: list = []

    for name in SOURCES:
        src = PROJECTS_ROOT / name
        dst = AUTOSHORTS / name

        if not src.is_dir():
            print(f"  MISS  {name:<24} source not found")
            manifest["projects"][name] = {"status": "source_missing"}
            continue

        if dst.exists():
            print(f"  SKIP  {name:<24} already present (never overwritten)")
            manifest["projects"][name] = {
                "status": "skipped_exists",
                "source_path": str(src),
                "dest_path": str(dst),
            }
            continue

        info = git_info(src)
        tag = ""
        if info.get("git"):
            tag = f" [{info['head'][:8]}{'-dirty' if info['dirty'] else ''}]"

        if args.dry_run:
            n = sum(len(f) for _, _, f in os.walk(src))
            print(f"  WOULD {name:<24} ~{n} files{tag}")
            manifest["projects"][name] = {"status": "dry_run", "source": info}
            continue

        counter = {"dirs": 0, "files": 0, "copied": 0, "bytes": 0}
        errors: list = []
        t0 = time.time()
        copy_source(src, dst, counter, errors)

        # Safety net: nothing should have survived, but a stray .git (e.g. a
        # submodule checkout) would silently nest a repo inside AutoShorts.
        for stray in dst.rglob(".git"):
            if stray.is_dir():
                shutil.rmtree(stray, ignore_errors=True)
            else:
                try:
                    stray.unlink()
                except OSError:
                    pass

        all_errors.extend(errors)
        manifest["projects"][name] = {
            "status": "copied",
            "source_path": str(src),
            "dest_path": str(dst),
            "source": info,
            "files_copied": counter["copied"],
            "bytes_copied": counter["bytes"],
            "excluded_dirs": counter["dirs"],
            "excluded_files": counter["files"],
            "errors": errors,
            "seconds": round(time.time() - t0, 1),
        }

        flag = "OK  " if not errors else "WARN"
        print(
            f"  {flag}  {name:<24} {counter['copied']:>6} files  "
            f"{counter['bytes'] / 1e6:>7.1f} MB  "
            f"skipped {counter['dirs']} dirs  "
            f"{time.time() - t0:>5.1f}s{tag}"
        )

    if not args.dry_run:
        out = AUTOSHORTS / ".vendored.json"
        out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\nmanifest -> {out}")

    if all_errors:
        print(f"\n{len(all_errors)} error(s) during copy:")
        for e in all_errors[:40]:
            print(f"  {e}")
        if len(all_errors) > 40:
            print(f"  ... and {len(all_errors) - 40} more")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
