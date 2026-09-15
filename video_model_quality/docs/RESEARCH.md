# RESEARCH — controllable stickman universe → video

**Author:** 4.1 Agent · **Date:** 2026-09-10
**Thesis under test (user):** if we can control the stickman universe (puppets + objects)
properly, converting to video is the easy part.

**Verdict:** **Confirmed.** Every serious project puts ~90% of effort in the *control/plan
layer* and treats rendering as a thin, swappable back-end. Our codebase already has a strong
control core (entity/IK, controllers, director, sequencer, props) — it is **missing the
decisive layer above it: a declarative scene/script plan that a compiler turns into a
timeline.**

## References reviewed

| Project | What it is | Lesson for us |
|---------|-----------|----------------|
| **animdsl** (frankhart2018) | DSL for 2D movies; text in → mp4 out; procedural characters, 23 pose params, camera, transitions, overlap detection | **DSL-first**: a declarative scene language beats ad-hoc function calls. Camera + transitions are first-class. |
| **Stick-Gen** (gestura-ai) | Text→stickman video; **ScriptSchema** (JSON: characters, actions, duration, camera) → Script-to-Scene → render. 42 actions, 25+ objects, 7 camera moves, expressions | **Plan→Compile→Execute**: LLM/planner emits a *structured schema*; a deterministic compiler builds the scene. Objects and camera are part of the schema. |
| **blender-llm-animator** | LLM emits rig-agnostic JSON intent plan; deterministic **plan compiler** emits executable keyframes | **Never let the planner emit raw code/motion.** Separate *intent* (JSON) from *execution* (our compiler). Prevents hallucination, preserves determinism. |
| **Storyboard/script pipelines** (AniME, story-to-animation, etc.) | Script → NLP/LLM → **beat/shot JSON** (characters, action, camera, duration) → downstream | Consistent pattern: **segmentation into ordered beats** is the core NLP job. |
| **Spine / DragonBones / Godot cutout** | Skeletal rig + timelines + `AnimationState` (crossfade mixing, **layering** tracks) | Proven runtime model for **mixing and layering** actions (upper body over locomotion). Our sequencer/controllers mirror this — keep that shape. |
| **Unity 2D IK / ik-proc-anim-2d** | Procedural locomotion via **CoM + support polygon + foot IK arc + step anticipation** | Validates our IK; suggests CoM-driven stepping to kill residual foot-slide. |
| **"Marionette" pattern** (2D Hyper-Motion) | Decouple root from limbs; damped follow-through; squash/stretch; anticipation→strike→recovery | Secondary motion + follow-through is a cheap quality multiplier. |

## Adopted architecture (target)

```
text / script
   │  (planner: deterministic grammar now; optional LLM later)
   ▼
SceneScript  (declarative, serialisable, inspectable)
   │  characters[], beats[] (ordered), objects[], camera[], duration
   ▼
Compiler  (deterministic; rig-agnostic → our directors/sequencer/armature)
   │
   ▼
Timeline  (per-actor (T,30) feature streams + VFX/object events)
   │
   ▼
Renderer + encoder  (thin, swappable: 512 SD / 720p HD / future stylers)
```

**Rules borrowed:**
- Planner output is **data** (SceneScript), never code or raw motion.
- Compiler is **deterministic** and fails fast on unknown actions.
- **Objects are anchored to joints** (already supported) and can be **declared** in the scene.
- **Camera is first-class** in the schema (we already have camera track + impulses).
- Keep the **rig-agnostic** boundary: SceneScript names semantic actions/poses, not joint angles.

## Gap analysis (our repo vs. target)

| Layer | Status | Gap |
|-------|--------|-----|
| Rig / FK / IK | ✅ strong (entity, armature two-bone IK) | CoM-driven stepping polish |
| Controllers / director | ✅ good (locomotion, strike, recoil) | object interaction, layering API |
| Sequencer / mixing | ✅ good | expose at scene level |
| Props / VFX | ✅ good (joint-locked props) | **object lifecycle** (spawn, handoff, throw) |
| **SceneScript + compiler** | ❌ **missing** | **the decisive gap** |
| Text→plan | ⚠️ single-action keyword parser | **multi-action, ordered, multi-actor** |
| Render / encode | ✅ good (512 + 720p) | none critical |

## Decision
Build the **SceneScript → compiler** layer and fix the parser's silent single-action
collapse. This is the highest-leverage step toward "anything a user throws."
