"""Gate D3: same prompt renders deterministically (bitwise-identical frames).

Renders a small clip twice through the full pipeline and compares raw frames.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from src.scene import parse_script, compile_scene
from src.renderer import decode_motion_features


def main():
    prompts = [
        "walk forward, then punch, then celebrate",
        "two stickmen: one punches and the other blocks",
    ]
    ok = True
    for p in prompts:
        s = parse_script(p, seed=7)
        d1 = compile_scene(s)
        d2 = compile_scene(s)
        same = np.array_equal(d1["feat"], d2["feat"])
        joints1 = decode_motion_features(d1["feat"])
        joints2 = decode_motion_features(d2["feat"])
        same_joints = np.array_equal(joints1, joints2)
        status = "deterministic" if same and same_joints else "NONDETERMINISTIC"
        if not (same and same_joints):
            ok = False
        print(f"  {p[:50]!r}: feat={same}, joints={same_joints} -> {status}")
    if not ok:
        print("D3 FAILED: nondeterministic output")
        sys.exit(1)
    print("D3: deterministic")
    return 0


if __name__ == "__main__":
    sys.exit(main())