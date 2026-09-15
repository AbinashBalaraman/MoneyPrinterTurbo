# Platform Hardening & Audit Plan (4.1 Agent — Head)

**Date:** 2026-09-10
**Baseline HEAD:** `6dc2cb1` — 56/56 pytest green, eval 100/100, working tree clean (only `out/` artifacts untracked).
**Directive (user):** Harden & audit the platform before new features (defer Level 5 / TASK-016).

## Dispatch policy
- **Own subagents:** primary workforce for audits and fixes.
- **Gemini (w1:p4):** all visual-inspection work.
- **OC2 (w1:p1) / Pi (w1:p2):** other tasks, as a last resort.

## Audit workstreams (in flight)
| # | Workstream | Owner | Focus |
|---|-----------|-------|-------|
| A | Repo structural health | subagent | inventory, coverage gaps, dead code, duplication, stale docs |
| B | Math/IK correctness | subagent | DLS IK, limits, CoM/balance, collision/HitTracker, determinism |
| C | Renderer pipeline | subagent | 512-vs-HD divergence, VFX windows/anchors, props, determinism/FPS |
| D | Visual inspection | Gemini w1:p4 | fresh audit of 16-scene suite + inspections inventory |

## Acceptance gates (every hardening fix)
1. `python -m pytest tests/ -q` — full suite green, **no regressions**, new tests for each fixed defect.
2. `python -m src.eval` — **100/100** benchmark, no FPS regression beyond noise.
3. **Determinism:** same input renders/evaluates identically twice.
4. **No silent fallbacks:** defects fail fast; no bare `except: pass` masking errors.
5. **Visual proof:** any motion/render fix has before/after stills inspected by Gemini.
6. **Root-cause fix, never delete:** disabled/bypassed actions must be repaired, not removed (per charter).

## Rules
- No agent-bus posting; coordination is Herdr-direct only.
- One owner per file region; commits attributed to the actual author.
- Head (4.1) consolidates findings, assigns fixes, and verifies before closing.

## Visual audit baseline (Gemini, commit f84139c) — avg 76.01/100
Columns: score (floor-penetration events/depth, jerk spikes/max rad/s², foot-slide events, dead-hold frames).

| # | Scene | Score | Pen | Jerk | Slide | Dead |
|---|-------|-------|-----|------|-------|------|
| 01 | walk_forward | 80.00 | 0 | 0 | 21 | 0 |
| 02 | walk_backward | 87.32 | 17 / 3.3cm | 0 | 4 | 0 |
| 03 | combat_punch | 72.75 | 4 / 3.9cm | 1 | 1 | 24 |
| 04 | combat_kick | 75.75 | 2 / 3.9cm | 0 | 1 | 23 |
| 05 | jump_acrobatic | 61.00 | 85 / 19.0cm | 4 / 3619 | 4 | 3 |
| 06 | combat_pair_exchange | 87.01 | 12 / 2.7cm | 1 | 9 | 5 |
| 07 | combat_pair_knockdown | 84.18 | 44 / 3.6cm | 1 | 9 | 17 |
| 08 | combat_pair_punch_block | 72.89 | 16 / 2.9cm | 6 | 23 | 19 |
| 09 | combat_pair_kick_dodge | 95.00 | 0 | 0 | 0 | 18 |
| 10 | expressive_celebrate | 100.00 | 0 | 0 | 0 | 7 |
| 11 | expressive_wave | 94.00 | 0 | 0 | 4 | 3 |
| 12 | expressive_distress | 65.40 | 200 / 6.8cm | 0 | 0 | 29 |
| 13 | run_and_leap | 48.50 | 82 / 19.0cm | 5 / 3619 | 11 | 1 |
| 14 | narrative_martial_artist | 53.00 | 0 | 1 | 45 | 77 |
| 15 | combat_pair_sword_duel | 71.36 | 63 / 2.4cm | 5 | 9 | 56 |
| 16 | acrobatic_slide | 67.20 | 74 / 11.2cm | 3 | 1 | 11 |

| Sev | Defect | Scene(s) | Metric |
|-----|--------|----------|--------|
| P0 | Acrobatics floor penetration | jump_acrobatic, run_and_leap | 19.0 cm |
| P0 | Angular jerk explosion (takeoff→apex) | run_and_leap | 3,619 rad/s² |
| P1 | Dead-hold collapse | narrative (3.21s), sword_duel (2.33s), punch/kick (1.0s) | >0.35s threshold |
| P1 | Slide/distress floor penetration | slide, distress | 11.2 cm / 6.8 cm |
| P2 | Stance foot sliding | walk transitions | 21 events, up to 4.9 cm |

## Status log
- [ ] A — repo structural audit (subagent, in flight)
- [ ] B — math/IK audit (subagent, in flight)
- [ ] C — renderer audit (subagent, in flight)
- [x] D — visual audit (Gemini) → baseline captured, defects listed above
- [ ] Fix P0/P1 choreography defects (subagent, in flight)
- [ ] Gemini re-audit verdict after fixes
- [ ] Consolidated defect register + disposition (fix / accept / defer)
- [ ] Fixes landed & verified
