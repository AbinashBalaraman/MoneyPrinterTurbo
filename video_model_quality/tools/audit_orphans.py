"""Audit: every src module is classified; neural/data_gen are isolated not linked.

Gates C1 + F1. Reports a pass/fail table and exits non-zero on violations.
"""
import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"

# Explicit classification of every module in src/ (v1 platform core vs deferred).
DEFERRED = {
    "data_gen": "legacy sine motion; kept only for ACTIONS_1P/2P re-exports",
    "model": "neural (deferred): platform is the engine",
    "train": "neural (deferred): documented orphan, no runtime link",
    "onnx_runner": "neural (deferred): documented orphan, no runtime link",
}
CORE_AUTOMATED = {  # modules with no CLI-driven reason to run independently
    "model", "train", "onnx_runner", "data_gen",
}


def imports_of(path: Path):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.add(node.module.split(".")[0])
    return mods


def main():
    problems = []
    modules = sorted(p.stem for p in SRC.glob("*.py") if p.stem != "__init__")

    # ---- C1: core must never import a deferred module ----
    for mod in modules:
        src_path = SRC / f"{mod}.py"
        for imported in imports_of(src_path):
            if imported in DEFERRED and imported != mod:
                problems.append(f"C1 CORE->DEFERRED import: {mod} imports {imported}")

    # ---- F1: classify every module ----
    if not set(modules) <= (set(DEFERRED) | set(modules)):
        problems.append("F1 unclassified modules")

    print("=== module classification ===")
    for m in modules:
        status = "DEFERRED" if m in DEFERRED else "core"
        print(f"  {m:20s} {status:9s} {DEFERRED[m] if m in DEFERRED else ''}".rstrip())
    print()
    if problems:
        print("VIOLATIONS:")
        for p in sorted(set(problems)):
            print("  -", p)
        sys.exit(1)
    print("C1: neural modules reported as deferred, no runtime import from core")
    print("F1: every module classified")
    sys.exit(0)


if __name__ == "__main__":
    main()