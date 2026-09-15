#!/usr/bin/env python
"""Repair incomplete packages inside node_modules.

Why this exists
---------------
`npm install` verifies a package's *version and integrity hash of the tarball*,
not the files actually present on disk. If an install is interrupted partway
through extraction -- which happens here whenever the sandbox denies a write --
npm still considers the tree satisfied, so re-running `npm install` reports
"changed N packages" and leaves the hole in place. The symptom is a confusing
runtime error such as:

    Error: Cannot find module './ResultPlugin'

because a single file never made it out of the tarball. Two real examples found
in this repo: `enhanced-resolve/lib/ResultPlugin.js` (which broke `vite.config.ts`
and therefore the entire build) and `lucide-react/dist/esm/icons/badge-question-mark.js`.

What this does
--------------
Downloads each package's own tarball at the *installed* version (from the npm
cache where possible), compares it against the extracted directory, and copies
across anything missing. It only ever ADDS files -- it never deletes or
overwrites -- so it cannot make a working install worse, and it stays well under
the bulk-delete guard that blocks `rm -rf` style repairs.

Speed
-----
Spawning one `npm` process per package costs ~7s each, which is ~55 minutes for
a 472-package tree. `npm pack` accepts many specs at once, so `--all` packs in
batches and the cost drops to roughly a minute plus extraction.

Usage
-----
    python tools/repair_npm_package.py enhanced-resolve --project flowkit/dashboard
    python tools/repair_npm_package.py --all --project flowkit/dashboard
    python tools/repair_npm_package.py --all --project flowkit/dashboard --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Managed toolchain from the environment. Kept explicit rather than relying on
# PATH, because a bare `node`/`npm` here may resolve to a different install.
NODE = Path(
    r"C:\Users\SATHYA TRADERS\.workbuddy-ai\binaries\node\versions\22.22.2-2\node.exe"
)
NPM_CLI = NODE.parent / "node_modules" / "npm" / "bin" / "npm-cli.js"

# How many specs to hand to a single `npm pack` call. Large enough to amortise
# process startup, small enough that a failure does not lose a huge batch.
BATCH_SIZE = 40


# ---------------------------------------------------------------------------
# Installed state
# ---------------------------------------------------------------------------


def _installed_version(pkg_dir: Path) -> str | None:
    manifest = pkg_dir / "package.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (OSError, json.JSONDecodeError):
        return None


def _installed_packages(project: Path) -> list[str]:
    """Every package name directly under node_modules, scopes included."""
    node_modules = project / "node_modules"
    names: list[str] = []
    for child in sorted(node_modules.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name.startswith("@"):
            names.extend(
                f"{child.name}/{g.name}" for g in sorted(child.iterdir()) if g.is_dir()
            )
        else:
            names.append(child.name)
    return names


# ---------------------------------------------------------------------------
# Fetching pristine copies
# ---------------------------------------------------------------------------


def _manifest_member(tf: tarfile.TarFile) -> str | None:
    """Path of the tarball's root `package.json` member.

    The top-level directory is *almost* always `package/`, but not guaranteed:
    `npm pack @types/react@19.2.14` produced a root named `react/`. Hardcoding
    `package/` makes the manifest lookup return None, which this tool reports as
    "could not fetch a pristine copy" -- a confusing dead end for every `@types`
    package. Find the shallowest `*/package.json` instead.
    """
    candidates = [
        name
        for name in tf.getnames()
        if name.endswith("/package.json") and name.count("/") == 1
    ]
    if not candidates:
        candidates = sorted(
            (name for name in tf.getnames() if name.endswith("/package.json")),
            key=lambda name: name.count("/"),
        )
    return candidates[0] if candidates else None


def _tarball_root(tf: tarfile.TarFile) -> str | None:
    """The single top-level directory the archive unpacks into."""
    member = _manifest_member(tf)
    return member.rsplit("/", 1)[0] if member else None


def _manifest_from_tarball(tgz: Path) -> tuple[str, str] | None:
    """Read name+version out of the tarball's own package.json.

    Matching tarball filenames back to package names is unreliable -- a scoped
    `@babel/core@7.29.0` lands on disk as `babel-core-7.29.0.tgz` -- so read the
    manifest instead of parsing the filename.
    """
    try:
        with tarfile.open(tgz) as tf:
            member = _manifest_member(tf)
            if member is None:
                return None
            handle = tf.extractfile(member)
            if handle is None:
                return None
            data = json.loads(handle.read().decode("utf-8"))
        return data.get("name"), data.get("version")
    except (OSError, tarfile.TarError, json.JSONDecodeError, KeyError):
        return None


def _pack_specs(specs: list[str], into: Path) -> dict[str, Path]:
    """`npm pack` a batch of specs; returns package name -> tarball path."""
    proc = subprocess.run(
        [str(NODE), str(NPM_CLI), "pack", *specs, "--silent"],
        cwd=str(into),
        capture_output=True,
        text=True,
    )
    found: dict[str, Path] = {}
    for tgz in sorted(into.glob("*.tgz")):
        info = _manifest_from_tarball(tgz)
        if info and info[0]:
            found[info[0]] = tgz
    if proc.returncode != 0 and not found:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        print(f"    batch failed: {detail[-1][:160] if detail else 'unknown error'}")
    return found


def _extract(tgz: Path, dest: Path) -> Path | None:
    """Unpack a tarball and return the directory its files actually live in."""
    dest.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(tgz) as tf:
            root = _tarball_root(tf)
            if root is None:
                print(f"    no package.json inside {tgz.name}")
                return None
            tf.extractall(dest, filter="data")
    except (OSError, tarfile.TarError) as exc:
        print(f"    extract failed for {tgz.name}: {exc}")
        return None
    return dest / root


# ---------------------------------------------------------------------------
# Comparing and repairing
# ---------------------------------------------------------------------------


def _missing_files(pristine: Path, installed: Path) -> list[Path]:
    missing: list[Path] = []
    for src in pristine.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(pristine)
        if not (installed / rel).exists():
            missing.append(rel)
    return missing


def _repair(name: str, installed: Path, pristine: Path, dry_run: bool) -> int:
    missing = _missing_files(pristine, installed)
    if not missing:
        return 0

    print(f"  {name}: {len(missing)} missing file(s)")
    for rel in missing[:15]:
        print(f"      + {rel.as_posix()}")
    if len(missing) > 15:
        print(f"      … and {len(missing) - 15} more")

    if dry_run:
        print("      (dry run: nothing written)")
        return 1

    for rel in missing:
        dest = installed / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pristine / rel, dest)
    print(f"      restored {len(missing)} file(s)")
    return 1


def _count_files(path: Path) -> int:
    return sum(len(files) for _, _, files in os.walk(path))


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def repair_one(name: str, project: Path, dry_run: bool, verbose: bool) -> int:
    installed = project / "node_modules" / name
    if not installed.is_dir():
        print(f"  {name}: not installed, skipping")
        return 0

    version = _installed_version(installed)
    if version is None:
        print(f"  {name}: no readable package.json, skipping")
        return 0

    with tempfile.TemporaryDirectory(prefix="repair-npm-") as tmp:
        tmp_path = Path(tmp)
        tarballs = _pack_specs([f"{name}@{version}"], tmp_path)
        tgz = tarballs.get(name)
        if tgz is None:
            print(f"  {name}: could not fetch a pristine copy")
            return 1
        pristine = _extract(tgz, tmp_path / "x")
        if pristine is None:
            return 1
        if not dry_run and _missing_files(pristine, installed) == []:
            print(f"  {name}@{version}: complete ({_count_files(installed)} files)")
        return _repair(f"{name}@{version}", installed, pristine, dry_run)


def repair_all(project: Path, dry_run: bool, verbose: bool) -> int:
    names = _installed_packages(project)
    print(f"checking {len(names)} package(s) under {project}")

    damaged = 0
    unverifiable: list[str] = []

    with tempfile.TemporaryDirectory(prefix="repair-npm-all-") as tmp:
        tmp_path = Path(tmp)

        for start in range(0, len(names), BATCH_SIZE):
            batch = names[start : start + BATCH_SIZE]
            specs = []
            for name in batch:
                version = _installed_version(project / "node_modules" / name)
                if version:
                    specs.append(f"{name}@{version}")
                else:
                    unverifiable.append(name)

            batch_dir = tmp_path / f"batch{start}"
            batch_dir.mkdir(parents=True, exist_ok=True)
            tarballs = _pack_specs(specs, batch_dir)

            for name in batch:
                tgz = tarballs.get(name)
                if tgz is None:
                    unverifiable.append(name)
                    continue
                installed = project / "node_modules" / name
                pristine = _extract(tgz, batch_dir / "x" / name.replace("/", "_"))
                if pristine is None:
                    unverifiable.append(name)
                    continue
                damaged += _repair(name, installed, pristine, dry_run)

            done = min(start + BATCH_SIZE, len(names))
            print(f"  … {done}/{len(names)} checked, {damaged} repaired so far")

    if unverifiable:
        print(f"\n{len(unverifiable)} package(s) could not be verified:")
        for name in unverifiable[:20]:
            print(f"  ? {name}")
        if len(unverifiable) > 20:
            print(f"  … and {len(unverifiable) - 20} more")

    print(f"\n{damaged} package(s) needed repair")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Repair incomplete node_modules packages")
    ap.add_argument("package", nargs="?", help="package name, or @scope/name")
    ap.add_argument("--project", required=True, help="project dir containing node_modules")
    ap.add_argument("--all", action="store_true", help="check every installed package")
    ap.add_argument("--dry-run", action="store_true", help="report but do not write")
    ap.add_argument("--verbose", action="store_true", help="also list complete packages")
    args = ap.parse_args()

    project = Path(args.project)
    if not project.is_absolute():
        project = (REPO_ROOT / args.project).resolve()
    if not (project / "node_modules").is_dir():
        print(f"no node_modules under {project}")
        return 2

    if args.all:
        return repair_all(project, args.dry_run, args.verbose)
    if not args.package:
        ap.error("pass a package name or --all")
    return repair_one(args.package, project, args.dry_run, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
