"""Visual Audit Runner for the 16-Scene Platform Suite.

Executes frame-by-frame biomechanical and visual audits across all 16 standard scenes
using VisualInspector. Produces detailed per-scene metrics and a prioritized defect inventory.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
from src.visual_inspector import VisualInspector
from src.puppet.choreography import build_motion_from_action, build_combat_pair
from tools.render_scene_suite import _run_and_leap, _narrative_martial_artist, _build


def run_full_16_scene_audit():
    inspector = VisualInspector()

    scenes = [
        ("01_walk_forward", lambda: build_motion_from_action("walk", duration_s=3.0), False),
        ("02_walk_backward", lambda: build_motion_from_action("walkback", duration_s=3.0), False),
        ("03_combat_punch", lambda: build_motion_from_action("punch", duration_s=2.5), False),
        ("04_combat_kick", lambda: build_motion_from_action("kick", duration_s=2.5), False),
        ("05_jump_acrobatic", lambda: build_motion_from_action("jump", duration_s=2.5), False),
        ("06_combat_pair_exchange", lambda: build_combat_pair("exchange", duration_s=3.0), True),
        ("07_combat_pair_knockdown", lambda: build_combat_pair("knockdown_getup", duration_s=3.5), True),
        ("08_combat_pair_punch_block", lambda: build_combat_pair("punch_block", duration_s=3.0), True),
        ("09_combat_pair_kick_dodge", lambda: build_combat_pair("kick_dodge", duration_s=3.0), True),
        ("10_expressive_celebrate", lambda: build_motion_from_action("celebrate", duration_s=2.5), False),
        ("11_expressive_wave", lambda: build_motion_from_action("wave", duration_s=2.5), False),
        ("12_expressive_distress", lambda: build_motion_from_action("distress", duration_s=2.5), False),
        ("13_run_and_leap", _run_and_leap, False),
        ("14_narrative_martial_artist", _narrative_martial_artist, False),
        ("15_combat_pair_sword_duel", lambda: build_combat_pair("sword_clash", duration_s=3.0), True),
        ("16_acrobatic_slide", lambda: build_motion_from_action("slide", duration_s=2.5), False),
    ]

    results = []
    print("=" * 80)
    print("RUNNING FULL VISUAL AUDIT ON 16-SCENE SUITE")
    print("=" * 80)

    for name, gen_fn, is_pair in scenes:
        feat, _ = _build(gen_fn)
        if is_pair:
            feat_a = feat[..., :30]
            feat_b = feat[..., 30:]
            rep = inspector.audit_combat_pair(feat_a, feat_b, name=name)
        else:
            rep = inspector.audit_motion(feat, name=name)

        results.append(rep)
        status = "PASS" if rep.passed() else "WARN" if rep.quality_score >= 80 else "FAIL"
        print(f"[{status}] {name:30s} | Score: {rep.quality_score:5.1f} | Flaws: {len(rep.flaws_detected)}")
        if rep.flaws_detected:
            for f in rep.flaws_detected:
                print(f"       - {f}")

    print("=" * 80)
    print("AUDIT SUMMARY:")
    avg_score = np.mean([r.quality_score for r in results])
    passed_count = sum(1 for r in results if r.passed())
    print(f"Total Scenes: {len(results)}")
    print(f"Average Quality Score: {avg_score:.1f}/100")
    print(f"Passed (Score >= 90 & 0 Flaws): {passed_count}/{len(results)}")
    print("=" * 80)

    return results


if __name__ == "__main__":
    run_full_16_scene_audit()
