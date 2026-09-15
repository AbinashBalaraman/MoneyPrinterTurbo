# BUILD PLAN — LLM-drivable stickman world

**Planner:** 4.1 Agent (w1:p6) · **Date:** 2026-09-11
**Locked decisions (user):**
- The **LLM owns the world** (semantics); the **engine owns execution** (never invents).
- Planner integration = **bring-your-own adapter** (author-time / cloud / local pluggable).
- Order: **schema/contract → vocabulary → objects → camera → planner**.
- Object v1: **spawn/place, attach, throw, pickup/drop, collision/impact**.
- Interface need not be literal MCP; whatever is optimal.

## Architecture

```
user text
  │  LLM / human planner        (src/planner.py — adapter, BYO backend)
  ▼
SceneScript JSON                (declared by src/contract.py)
  │  validate_scene()           (fail-fast; errors = unrenderable)
  ▼
compile_scene()                 (src/scene.py — deterministic)
  │   ├── beats  → puppets      (sequencer + choreography)
  │   ├── objects→ prop tracks  (src/objects.py)
  │   └── camera → cam track    (src/camera.py)
  ▼
renderer (512 SD / 1280x720 HD) → ffmpeg → video
```

**Golden rule:** only `src/contract.py` defines what is expressible. The LLM
targets `capabilities()`; `validate_scene()` is the gate. No module may invent
motion or semantics.

---

## Foundation (DONE by planner)

- `src/contract.py` — **frozen interface**: `OBJECT_REGISTRY`, `JOINT_INDEX`,
  `resolve_joint`, `resolve_object`, `capabilities()`, `validate_scene()`,
  `SCENE_SCHEMA`, `ContractError`. **Do not edit without planner approval.**

---

## Task 1 — Vocabulary widening  → **w1:p1 (opencode)**

**Files (owned exclusively):** `src/parser.py`, `tests/test_vocab.py`
**Do NOT touch:** any other file.

Deliverable: widen the lexicon beyond the fixed catalog so natural phrasing hits.

1. Expand `SYNONYMS` for **every** existing action with inflections
   (plural / gerund / past), common idioms, and sport/martial synonyms.
   - Required fix: `"guards"`, `"guarding"` must map to `block`
     (benchmark prompt `stickman guards against danger` currently fails).
   - Add e.g. dodges: `"sidestep"`, `"weave"`, `"bob"`, `"evade"` → `squat`/`duck` family;
     locomotion: `"stride"`, `"wander"`, `"pace"`, `"charge"` → walk/run/walkback;
     gestures: `"salute"`, `"beckon"`, `"cheer"`, `"applaud"` → wave/celebrate;
     acrobatics: `"tumble"`, `"roll"`, `"cartwheel"`, `"vault"` → jump/squat.
2. Widen the **adjective/adverb** word lists inside `parse_prompt`
   (`direction`, `speed`, `amplitude`): add intensifiers (`"furiously"`,
   `"cautiously"`, `"wildly"`, `"subtly"`), and distance/force words.
   Keep the existing return-dict keys and value ranges EXACTLY.
3. **Extend object aliases in `src/contract.py` ONLY by adding alias strings to
   existing `OBJECT_REGISTRY` entries** — do not reorder/rename keys, do not
   change functions. (This one shared-file edit is whitelisted for you.)

Constraints:
- Keep `match_actions(text)` and `parse_prompt(prompt,...)` signatures/behaviour;
  new terms must not create false positives (word-boundary matching already guards).
- All 68 existing tests must still pass.

Verification (paste output in your report):
```
python -m pytest tests/ -q
python -m src.eval
```
`74 passed` (or more) and eval `100/100` with **no failures list**.

Ack format in `conversation.md`: start your entry `To @4.1 Agent:`.

---

## Task 2 — Object runtime  → **w1:p2 (pi)**

**Files (owned exclusively):** `src/objects.py` (new), `tests/test_objects.py` (new)
**Do NOT touch:** renderer, scene.py, contract.py, parser.py.

Deliverable: deterministic object simulation → per-frame renderer props.

Fixed interface (planner calls this exactly):
```python
def evaluate_objects(objects, joints, fps=24, T=None):
    """objects: validated list from contract.validate_scene (out['objects'])
       joints:  np.ndarray (T, N, 15, 2) world-space joints
       returns: (prop_tracks, impacts)
         prop_tracks : List[List[dict]]  length T; prop_tracks[t] = props at frame t
         impacts     : List[dict]  each {"frame": int, "x": float, "y": float, "kind": "impact_burst"}
    """
```

Rules:
- `spawn_frame` / `despawn_frame`: object absent outside `[spawn, despawn]`.
- no `attach` / `throw` / `pickup`: static prop `{"kind","x","y","scale"}`.
- `attach`: while `from_frame <= t < to_frame` (or `to_frame<0` = forever) the prop
  is joint-locked → `{"kind","anchor_puppet",:active_actor_index,"joint","scale"}`.
  The actor id→index map is the order characters/beats appear (caller passes
  `joints` with N actors in that order; assume index = actor index).
- `pickup`: before `frame` the object sits at `at`; from `frame` on it is attached
  to `pickup.actor` at `pickup.joint` (use `attach` logic for rendering).
- `throw` at `throw.frame`: free flight from current position with
  `vx, vy, gravity` (world units/sec, +y up). Phase `x(t)=x0+vx*dt`,
  `y(t)=y0+vy*dt-0.5*g*dt^2`. If `bounce` and y < ground (-0.42) and vy<0:
  reflect vy with restitution 0.45, damp vx by 0.7, emit an `impacts` entry and
  a `dust_puff`-style event dict at landing. Rest when speed < 0.05.
- `throw` on a non-attached object: launch from `at`.
- Collision/impact: when a thrown object's x passes within 0.12 world units of any
  actor's chest (joint 2) at the same frame, append `{"frame","x","y","kind":"impact_burst"}`
  and (if `bounce`) start a small bounce.
- Determinism: same inputs → identical output. Pure numpy, no RNG unless seeded.
- Guard malformed specs defensively (skip bad entry) — never raise on a single object.

Tests (`tests/test_objects.py`, pytest) — at minimum:
1. static prop appears every frame in-window, not outside.
2. attach prop is joint-locked (anchor_puppet==actor index, joint int) mid-window.
3. throw produces a y arc that rises then falls; deterministic across two runs.
4. bounce emits ≥1 impact and y never goes far below ground.
5. pickup flips from world coords to anchored coords at the pickup frame.
6. malformed object (unknown keys) is skipped without raising.

Verification:
```
python -m pytest tests/test_objects.py -q
python -m pytest tests/ -q
```

Ack `To @4.1 Agent:`.

---

## Task 3 — Camera & staging  → **w1:p4 (agy / Gemini)**

**Files (owned exclusively):** `src/camera.py` (new), `tests/test_camera.py` (new)
**Do NOT touch:** renderer, scene.py, contract.py, parser.py.

Deliverable: deterministic camera track from a validated camera spec.

Fixed interface:
```python
def compute_camera(joints, spec, fps=24):
    """joints: (T, N, 15, 2).  spec: validated dict from contract.validate_scene
         {"mode": "auto|static|follow|close|wide|pan", "zoom": float,
          "focus": "mid"|actor_id, "follow": bool, "actors": [ids] (optional)}
       returns {"camera_x": np.ndarray(T,), "zoom": float, "mode": str}
    """
```

Rules:
- `static` → camera_x all 0.0.
- `auto` → smooth follow of the actors' horizontal midpoint (reuse a simple
  critically-damped/cosine-smoothed tracker, alpha 0.10); zoom 1.0.
- `follow` → track `focus` actor's root x (actor index = position in `actors`
  list, default 0) with the same smoothing.
- `close` → auto framing, zoom ×1.6 (clamped 0.25–4.0).
- `wide` → auto framing, zoom ×0.7.
- `pan` → slow linear traverse across the actors' full x-range over T.
- Always return monotonically-shaped `camera_x` (T,) float32, no NaN.
- Pure numpy; no renderer import; deterministic.

Tests (`tests/test_camera.py`, pytest):
1. static → zeros.
2. auto → finite, and tracks midpoint (corr with per-frame midpoint > 0.9).
3. close/wide → zoom bounds respected.
4. pan → start != end and monotone direction.
5. determinism: two calls identical.

Verification:
```
python -m pytest tests/test_camera.py -q
```

Ack `To @4.1 Agent:`.

---

## Task 4 — Integration + planner adapter  → **w1:p6 (planner / me)**

- `src/planner.py`: `PlannerAdapter` protocol + `NoOpPlanner` (author-time) +
  `plan(prompt, backend=None) -> SceneScript dict`; cloud/local backends plug in.
- Wire `objects` + `camera` into `SceneScript` / `compile_scene` (`src/scene.py`).
- Renderers accept per-frame prop tracks + camera track (512 SD + 1280x720 HD).
- End-to-end: `python tools/prompt_to_video.py "<script>" -o out/x.mp4`.
- Verify: pytest, eval, audit, and two rendered demos (solo object + armed duel).

## Collision-avoidance rule
Each agent edits ONLY its owned files. Need a change elsewhere? Message the
planner (`herdr agent prompt w1:p6 "..."`) — do not edit shared files.
