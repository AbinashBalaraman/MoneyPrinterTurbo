# GATES — full-project audit & goal alignment

Mode: **solo**. Author: 4.1 Agent. Date: 2026-09-10.
Goal: see `docs/GOAL.md` (open-vocabulary text → stickman video; procedural engine; accuracy first).

One observable outcome per gate. Runnable gates carry `CHECK:` (command) and `EXPECT:`.
Evidence is recorded inline as each gate is executed.

---

## Gate A — Baseline is green and reproducible
- [x] **A1** Full test suite passes.
  - CHECK: `python -m pytest tests/ -q`
  - EXPECT: `passed`
  - EVIDENCE: `68 passed in 11.39s` (2026-09-10)
- [x] **A2** Benchmark + determinism + diversity pass.
  - CHECK: `python -m src.eval`
  - EXPECT: `100/100 passed`
  - EVIDENCE: `100/100 passed; Determinism True; Diversity True; Rejection True`
- [x] **A3** Working tree reviewable.
  - EVIDENCE: `git status --short` shows intended src/tools/docs/tests changes.

## Gate B — No silent fallbacks / swallowed errors remain (fail-fast)
- [x] **B1** `eval.py` no longer falls back to legacy sine on builder error.
  - CHECK: `python -c "import inspect,src.eval as e; print('gen_single' in inspect.getsource(e))"`
  - EXPECT: `False`
  - EVIDENCE: fallback blocks removed; determinism check now uses `build_motion_from_action`.
- [x] **B2** Silent-swallow sites classified.
  - CHECK: `python tools/audit_exceptions.py`
  - EVIDENCE: 10 sites found; all are **intentional defensive coercion guards** (malformed VFX
    dict / bad duration string) that skip or return, not masked errors. Accepted, not "fixed".

## Gate C — Neural track correctly scoped
- [ ] **C1** Neural modules documented as deferred, no runtime import from core.
  - STATUS: partial — documented in `docs/RESEARCH.md`/`HEAD_STATE.md`; `train.py` still
    imports `model.py` (standalone, not on the runtime path). **Open (low priority).**

## Gate D — Open-vocabulary / multi-action coverage (core accuracy)
- [x] **D2** Ordered multi-action script compiles to a correct timeline.
  - CHECK: `python -m pytest tests/test_scene.py -q`
  - EXPECT: all pass
  - EVIDENCE: `12 passed` (order preserved, pair expansion, per-clause duration, dedup).
- [x] **D3** Same input renders deterministically.
  - EVIDENCE: eval `Determinism Verified: True`; `test_scene.py::test_deterministic`.
- [ ] **D1** Open-vocabulary coverage gap is *reported* (not silently idle).
  - STATUS: parser raises on unknown input (verified). **Vocabulary breadth still limited to
    catalog actions — open-vocabulary is a future milestone.**

## Gate E — Motion correctness
- [x] **E1** Visual audit average ≥ 90 with no P0/P1 defects.
  - CHECK: `python tools/audit_16_scenes.py`
  - EVIDENCE: `Average Quality Score: 94.8/100` (baseline 76.0), 4 scenes perfect.
- [x] **E2** No un-abandoned floor penetrations.
  - EVIDENCE: `enforce_ground_contact` at author time; audit shows no floor-penetration flaws.
- [x] **E3** No un-abandoned dead-holds.
  - EVIDENCE: `hold_breath` + zero-diff hold detection; audit shows no dead-hold flaws.

## Gate F — Structural hygiene
- [ ] **F1** Orphaned modules classified.
  - STATUS: `model.py`/`train.py`/`onnx_runner.py` identified as deferred neural track.
    Tooling `tools/audit_orphans.py` not yet written. **Partial.**
- [ ] **F2** Renderer duplication documented/mitigated.
  - STATUS: documented divergence risk; shared helpers partially extracted. **Open (minor).**

## Gate G — End-to-end goal demo
- [x] **G1** A multi-action paragraph renders to a playable mp4 without error.
  - CHECK: `python tools/prompt_to_video.py "a stickman walks forward, then punches, then celebrates victory" -o out/audit_multiaction.mp4 --sd`
  - EVIDENCE: scene plan 3 beats -> rendered (117,838 bytes). Pair demo also rendered.

---

## Abandonments
(none)

## Status log
- 2026-09-10: ledger created; Gate A baseline previously verified green (56/56, 100/100).
- 2026-09-10: **SceneScript layer + parser fix landed.** `src/scene.py` (plan + deterministic
  compiler), `tests/test_scene.py`, CLI multi-action compile, eval fail-fast + seeds vary motion.
  Suite 68/68, eval 100/100 (det+diversity), audit 94.8.
- Still open: C1, D1 (open vocab), F1, F2 — see above. All are scope/next-milestone, not defects.
- **F-P0-1 (goal-critical, silent wrong output):** `src/parser.py` matches at most **one**
  action, and selection is by **dict-iteration order**, not prompt order. `parse_prompt`
  therefore silently drops the rest of a script:
  - `"walk forward, then punch, then celebrate"` -> `walk` only
  - `"he runs, jumps over a fence, and lands"` -> `run` only
  - `"two warriors duel with swords then one cheers"` -> `exchange` (loses sword + cheer)
  Open vocabulary (`"a thief steals a diamond"`) raises (acceptable, but no path forward).
- **F-P0-2 (silent fallback):** `src/eval.py` catches builder exceptions and falls back to
  legacy `data_gen.gen_single/gen_pair` sine primitives — masks real regressions during the
  100/100 benchmark.
- **F-P1-1:** `src/data_gen.py` is legacy sine motion; still imported by `catalog.py` only for
  the `ACTIONS_1P/2P` lists, and by `eval.py` as fallback. Museum or isolate.
- **F-P2-1:** 9 `except` sites flagged by `tools/audit_exceptions.py` in `renderer.py` +
  `parser.py`; all are **justified defensive type-coercion guards** (skip malformed VFX dicts /
  bad duration strings), not masked errors. Reclassify, do not "fix".
- **F-P1-2 (neural orphans):** `model.py`, `train.py`, `onnx_runner.py` are out of scope
  (platform is the engine) but remain linked only via `train.py`; document as deferred.
- **F-P1-3:** `renderer.py` vs `stage_renderer.py` duplicate prop/VFX/camera logic (partial
  shared import already exists). Divergence risk.
- **F-P2-2 (residual):** composite blend-seam foot-slide (narrative/slide) and real one-frame
  jerk reversals — documented in `docs/HEAD_STATE.md`.

