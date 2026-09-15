# Shorts Content Directing & Video Production Engine — Master Architecture Guide

> **Quick Context for LLMs & Developers:**  
> This file is a self-contained, comprehensive technical specification of the entire `shorts_content_engine` project. Reading this file provides complete understanding of the system's architecture, data contracts, directing mechanics, FlowKit integration, SQLite continuity storage, and CLI workflows without needing to parse individual source files.

---

## 1. System Overview

`shorts_content_engine` is an autonomous episodic content directing and video production engine designed to produce daily 30–60s vertical Shorts (YouTube Shorts, TikTok, Instagram Reels) featuring persistent recurring characters, high-retention pacing, and automated video generation via **Google Flow** and **FlowKit**.

### Core Value Propositions:
1. **Intelligent Script & Narrative Director:** Enforces short-form video retention psychology (the 0–3s visual hook, rising tension, mid-episode twist, and seamless loopable cliffhanger) at an exact 140–160 WPM verbal pace.
2. **Strict S2P (Scene-to-Prompt) Decoupling:** Separates permanent character visual attributes from dynamic scene actions using an automated NLP n-gram quarantine filter to prevent Google Flow reference degradation.
3. **FlowKit / Google Flow Integration:** Direct programmatic bridge to the local FlowKit engine (`http://127.0.0.1:8100/api`) handling reference image generation, scene still composition, 8-second video clip generation (Google Veo), voiceover synthesis, and FFmpeg concatenation.
4. **Cross-Episode Continuity Ledger:** An SQLite WAL database that tracks character relationship states, injury/status deltas, unresolved plot threads, and rendering artifact manifests across daily episodes.

---

## 2. Complete File & Directory Map

```
shorts_content_engine/
│
├── docs/
│   ├── ECOSYSTEM_SURVEY.md      # 30KB evaluation of 10 video automation repos (MPT, ShortGPT, StoryDiffusion, etc.)
│   └── DEBATE_CONSENSUS.md      # Adversarial debate report (Creative Director vs. Architect vs. Auditor)
│
├── src/
│   ├── __init__.py              # Package root
│   ├── models.py                # Core domain entities (CharacterProfile, SceneBeat, EpisodeManifest, etc.)
│   ├── cli.py                   # Production CLI runner (init-series, direct, generate, batch, status, validate)
│   │
│   ├── director/                # Narrative & Script Directing Brain
│   │   ├── __init__.py          # Exports StoryDirector, CharacterRegistry, PacingBudgeter, PromptCompiler
│   │   ├── director.py          # 5-phase episodic story director and timeline compiler
│   │   ├── character.py         # Persistent character registry with cross-episode relationship tracking
│   │   ├── pacing.py            # 140–160 WPM timing budgeter, timeline generator, rhythm curves
│   │   └── compiler.py          # S2P prompt compiler, n-gram biometric quarantine, temporal sub-clip formatter
│   │
│   ├── flowkit/                 # FlowKit / Google Flow API Bridge
│   │   ├── __init__.py          # Exports FlowKitAsyncClient, FlowKitPayloadAdapter, FlowKitPipelineOrchestrator
│   │   ├── models.py            # Strict Pydantic V2 schemas matching FlowKit's REST API endpoints
│   │   ├── client.py            # Asynchronous REST client with retry policies & zero-total polling resilience
│   │   ├── adapter.py           # Transforms EpisodeManifest into FlowKit project, entity, and scene payloads
│   │   └── orchestrator.py      # 5-stage lifecycle coordinator (Entities -> Stills -> Clips -> TTS -> Concat)
│   │
│   └── storage/                 # Persistence & Show Continuity
│       ├── __init__.py          # Exports EpisodicLedger
│       └── ledger.py            # SQLite WAL continuity database with atomic transactions
│
├── scripts/
│   ├── demo_3part_arc.py        # Continuous 3-episode multi-part demonstration runner
│   ├── create_farmer_episode.py # Script initializing the "Arthur & Rusty" premiere episode (<10s scenes)
│   └── validate_flowkit_payloads.py # Pre-flight validation CLI checking manifests against FlowKit schemas
│
├── tests/                       # 271 passing tests (100% green)
│   ├── unit/                    # Unit test suites (director, flowkit, ledger, cli)
│   └── e2e/                     # 4-Tier E2E test harness + Tier 5 white-box adversarial stress tests
│
├── output/
│   └── manifests/               # Exported EpisodeManifest JSON files ready for production rendering
│
├── continuity_ledger.db         # Live SQLite WAL continuity database
├── pyproject.toml               # Project configuration and dependency declarations
├── README.md                    # User-facing production manual and CLI guide
├── PROJECT.md                   # Feature tracking specification
└── PROJECT_ARCHITECTURE.md      # This master architecture guide
```

---

## 3. Data Contracts & Domain Models (`src/models.py`)

### 1. `CharacterProfile`
Defines recurring character identity. Decouples physical appearance from dynamic action:
```python
class CharacterProfile(BaseModel):
    character_id: str           # Unique slug, e.g. "char_arthur"
    name: str                   # Display name, e.g. "Arthur"
    entity_type: EntityType     # CHARACTER | LOCATION | CREATURE | VISUAL_ASSET
    visual_summary: str         # Permanent physical appearance (used ONLY for reference image generation)
    personality: str            # Psychological baseline, emotional tone
    voice_profile: str          # TTS voice identifier or vocal delivery description
    relationships: dict[str, str] # e.g. {"Rusty": "beloved loyal dog and protector"}
```

### 2. `SceneBeat`
A single timed shot within an episode (strictly $\le 10$ seconds):
```python
class SceneBeat(BaseModel):
    scene_index: int            # 0-indexed sequence order
    time_start: float           # Start time in seconds (e.g. 0.0)
    time_end: float             # End time in seconds (e.g. 6.0)
    narration: str              # Verbal narration line
    dialogue: Optional[DialogueLine] # In-scene character spoken dialogue
    action_prompt: str          # Decoupled visual still prompt (NO character biometric attributes)
    video_prompt: str           # Sub-clip temporal directives: "0-3s: [zoom] ... 3-6s: [reaction]"
    bound_characters: list[str] # List of character names present in this scene (max 1–2)
    phase: EngagementPhase      # HOOK | RISING_TENSION | COMPLICATION | CLIMAX_TWIST | CLIFFHANGER_LOOP
    camera_directive: str       # Cinematography cue (e.g. "Low angle dynamic push-in")
    word_count: int             # Calculated verbal word count
    wpm: float                  # Calculated pacing speed
```

### 3. `EpisodeManifest`
The complete production package for a 30–60s episode:
```python
class EpisodeManifest(BaseModel):
    series_id: str              # Parent series ID
    episode_num: int            # Episode index
    title: str                  # Episode title
    target_duration: float      # Target duration in seconds (30.0 to 60.0s)
    actual_duration: float      # Sum of scene durations
    scenes: list[SceneBeat]     # Ordered sequence of scenes
    character_profiles: list[CharacterProfile] # Referenced character entities
    cliffhanger: str            # Unresolved tension for the end of the episode
    next_episode_hook: str      # Teaser question for Episode N+1
    micro_loop: Optional[str]   # Audio phrase designed to loop into Episode 1
```

---

## 4. The 5-Phase Retention Directing Formula (`src/director/`)

Short-form video algorithms heavily reward high completion rates and immediate retention. Every episode is budgeted into 5 distinct phases:

| Phase | Time Window | Retention Purpose | Cinematography & Audio Directives |
| :--- | :--- | :--- | :--- |
| **1. Hook** | `0.0s – 3.0s` | Pattern interrupt; stop scrolling | Extreme close-up / snap zoom; startling discovery or ticking clock |
| **2. Rising Tension** | `3.0s – 15.0s` | Establish the core dilemma & stakes | Tracking dolly shots; urgency in narration; rapid scene cut ($\le 7$s) |
| **3. Complication** | `15.0s – 35.0s` | Resolution attempt backfires | Macro shots, over-the-shoulder perspectives, in-scene dialogue |
| **4. Climax / Twist** | `35.0s – 50.0s` | Peak emotional intensity / revelation | Ascending crane shots, rapid whip-pans, unexpected plot pivot |
| **5. Cliffhanger / Loop** | `50.0s – 60.0s` | Trigger comments, loop video replay | Dramatic Dutch-tilt cut; loop phrase connects back to Scene 1 hook |

### Pacing Rules:
* **Speech Rate:** Strictly maintained between **140 and 160 Words Per Minute** (WPM) — optimal cadence for clear mobile comprehension.
* **Scene Duration Cap:** **Every scene must be $\le 10$ seconds** (typically 6s–8s). This ensures a direct 1:1 mapping to Google Flow's 8-second Veo video clips.

---

## 5. S2P Prompt Decoupling & N-Gram Quarantine (`src/director/compiler.py`)

Google Flow uses reference images to maintain character consistency. A common pitfall in AI video generation is **Biometric Leakage**: repeating physical descriptions (e.g. *"Arthur with his white beard and blue overalls"*) inside scene action prompts. This confuses the diffusion model and degrades character identity.

### The Decoupling Architecture:
1. **Entity Registration Stage:** Character physical traits (`visual_summary`) are sent **once** to create the canonical reference image.
2. **Scene Generation Stage:** The scene prompt receives **only situational actions, environment, and camera movements**.
3. **Automated N-Gram Quarantine:** When scene text is generated, the `PromptCompiler` scans for adjectives and biometric descriptors (e.g., beard, wrinkles, overalls, floppy ear) and quarantines them out of the final prompt.
4. **Bijective Binding Rule:** A scene binds at most **1 or 2 characters**. If an environmental establishing shot occurs, character bindings are explicitly cleared (`bound_characters: []`).
5. **Sub-Clip Temporal Formatting:** To simulate fast cuts without triggering multiple video renders, video prompts use temporal markers:
   ```text
   0-3s: Low angle push-in as [Arthur] inspects the cracked soil. 3-7s: [Rusty] frantically claws into the furrow.
   ```

---

## 6. FlowKit & Google Flow Integration (`src/flowkit/`)

FlowKit runs locally at `http://127.0.0.1:8100/api` and connects to Chrome via WebSocket (`ws://127.0.0.1:9223`).

### The 5-Stage Production Pipeline:
```
1. ENTITY REGISTRATION   -> POST /api/projects with character & location reference entities
2. REFERENCE GENERATION  -> POST /api/requests (GENERATE_IMAGE) for character portraits & location plates
3. SCENE INITIALIZATION  -> POST /api/scenes (action_prompt, video_prompt) + PATCH /api/scenes/{id} (narrator_text)
4. VIDEO CLIP RENDERING  -> POST /api/requests (GENERATE_VIDEO) using start_image_media_id + Veo model
5. CONCAT & POST-PROCESS -> POST /api/videos/{id}/narrate (TTS voiceover, FFmpeg audio ducking, final MP4 assembly)
```

### Critical API Edge Cases Handled:
* **Two-Step Scene Initialization:** FlowKit ignores `narrator_text` if passed during initial scene `POST`. The engine always issues a `POST` followed by an immediate `PATCH`.
* **Zero-Total Batch Status Trap:** FlowKit's polling endpoint `/api/requests/batch-status` can momentarily return `total: 0` before the queue worker picks up the request. The client treats `total: 0` as pending rather than complete.
* **Audio Ducking:** Automatically lowers background music by 60% during spoken narration segments via FFmpeg filtergraphs.

---

## 7. SQLite Continuity Ledger (`src/storage/ledger.py`)

Database: `continuity_ledger.db` (enforces SQLite WAL mode for high concurrency).

### Key Tables:
1. `series`: Holds show metadata, genre, logline, target duration, current season, and current episode.
2. `characters`: Persistent character profiles and entity types.
3. `episodes`: Record of all directed episodes, durations, WPM, and cliffhangers.
4. `character_state_deltas`: Dynamic changes across episodes (e.g., injuries, newfound knowledge, relationship upgrades).
5. `renders`: Artifact tracking for FlowKit project IDs, media IDs, and final MP4 paths.

---

## 8. Production CLI Cheat-Sheet (`src/cli.py`)

Navigate to project root:
```bash
cd "C:\Users\SATHYA TRADERS\Documents\Abi\Projects\shorts_content_engine"
```

### 1. Initialize a New Show:
```bash
python src/cli.py init-series \
  --series-id "farmer_and_rusty" \
  --title "Arthur & Rusty: The Whispering Earth" \
  --genre "Pastoral Fantasy" \
  --logline "A poor farmer and his loyal dog discover an ancient glowing seed." \
  --target-duration 45 \
  --pacing-rhythm "pulse_action"
```

### 2. Direct an Episode:
```bash
python src/cli.py direct \
  --series-id "farmer_and_rusty" \
  --episode-num 1 \
  --duration 45 \
  --output-manifest "output/manifests/ep01.json"
```

### 3. Validate Manifest against FlowKit Schemas:
```bash
python scripts/validate_flowkit_payloads.py --manifest "output/manifests/ep01.json"
```

### 4. Run Daily Batch Generation ($N$ Episodes):
```bash
python src/cli.py batch --series-id "farmer_and_rusty" --count 3 --duration 45
```

### 5. Check Series Continuity & Status:
```bash
python src/cli.py status --series-id "farmer_and_rusty"
```

---

## 9. Instructions for LLMs Generating New Episodes

When an LLM is asked to direct an episode for this engine, follow these strict constraints:
1. **Target Duration:** 30–60 seconds (default 45s).
2. **Scene Count & Length:** 5 to 7 scenes; **no single scene may exceed 10 seconds** (recommended 6s–8s).
3. **Word Count Budget:** Calculate verbal words = $\text{Duration} \times \frac{145}{60}$ (e.g., 45s = ~105 words).
4. **Scene Prompts:** Never include character physical descriptions in `action_prompt` or `video_prompt`. Reference characters by exact name in square brackets: `[Arthur]`, `[Rusty]`.
5. **Video Motion:** Format `video_prompt` with sub-clip intervals: `0-4s: [action A] ... 4-8s: [action B]`.
6. **Closing Arc:** End with an unresolved cliffhanger and a `micro_loop` audio phrase that seamlessly loops into the Scene 1 hook.
