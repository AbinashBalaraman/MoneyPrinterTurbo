# Episodic Content Directing & Video Production Engine

An autonomous, agentic directing and production engine for daily 30–60s vertical Shorts featuring persistent recurring characters, intelligent narrative flow, prompt decoupling (S2P), and seamless integration with Google Flow via the local FlowKit API.

---

## 1. System Architecture & Ecosystem Comparison

### 1.1 High-Level Architecture

The platform is structured into four decoupled, modular subsystems:

```
+-----------------------------------------------------------------------------+
|                      1. STORY DIRECTING SUBSYSTEM                           |
|  - Character & Location Profile Registry (Entity Reference Model)           |
|  - 5-Phase Short-Form Retention Arc (Hook, Rise, Dilemma, Climax, Loop)     |
|  - 140-160 WPM Mathematical Pacing Budgeter & Dynamic Tempo Curves         |
|  - S2P Decoupling Engine with NLP N-Gram Attribute Quarantine Guard         |
|  - Dual-Loop Möbius Engine (Micro-Looping & Multi-Episode Macro-Looping)     |
+-----------------------------------------------------------------------------+
                                       |
                                       v [EpisodeManifest]
+-----------------------------------------------------------------------------+
|                      2. FLOWKIT & GOOGLE FLOW INTEGRATION                   |
|  - Asynchronous HTTP/REST Client (http://127.0.0.1:8100/api)                |
|  - Two-Step Scene Initialization Sequence (POST scene -> PATCH narration)   |
|  - Resilient Batch Polling Engine (guards against premature done traps)     |
|  - Dual-Path Audio Ducking (probe audio -> duck or direct map)              |
|  - Video Concatenation & Assembly (1080x1920@30fps, hardware acceleration)  |
+-----------------------------------------------------------------------------+
                                       |
                                       v [Video MP4 & Renders]
+-----------------------------------------------------------------------------+
|                      3. CONTINUITY LEDGER & BATCH CLI                       |
|  - SQLite Database in WAL Mode (busy_timeout=30000, foreign_keys=ON)        |
|  - Relational Schemas: series, characters, episodes, deltas, renders       |
|  - Multi-Run Continuity: cliffhanger & thread propagation across N days     |
|  - Rich CLI Runner: init-series, direct, generate, batch, status, validate  |
+-----------------------------------------------------------------------------+
                                       |
                                       v
+-----------------------------------------------------------------------------+
|                      4. VERIFICATION & TEST HARNESS                         |
|  - 4-Tier Opaque-Box & Tier 5 Adversarial Stress Test Coverage              |
|  - Pre-Flight FlowKit Payload Validation (Pydantic V2 schemas)              |
|  - Synthetic offline test harness & end-to-end media verification           |
+-----------------------------------------------------------------------------+
```

---

### 1.2 Open-Source Ecosystem Analysis

A comprehensive survey of 10 leading open-source video automation and agentic storytelling repositories informed the architectural design of this engine:

| Repository | Approach / Philosophy | Key Strengths | Critical Failure Modes & Bottlenecks | How This Engine Solves It |
|---|---|---|---|---|
| **MoneyPrinterTurbo** | Automated video generator using MoviePy and TTS. | Simple end-to-end workflow; fast assembly for generic facts. | Lacks recurring characters; zero narrative pacing; monolithic prompts cause visual drift. | **S2P Decoupled Prompts**: Separates persistent identity from situational action prompts. |
| **ShortGPT** | LLM-driven video engine with content scripting. | Modular architecture for script, voice, and visual assets. | Naive string truncation mid-sentence; flat pacing; no multi-episode continuity. | **Syntactic Pacing Budgeter**: Enforces 140–160 WPM without text truncation or filler padding. |
| **StoryDiffusion** | Consistent self-attention for multi-frame generation. | Strong cross-frame character identity using visual attention. | High compute requirements; image-only; lacks audio orchestration and clip assembly. | **FlowKit Reference Model**: Registers canonical character entities bound to Veo seeds. |
| **AutoShorts / ShortsAI** | Cloud-based TikTok/YouTube Shorts automation pipelines. | Automated scheduling and webhook delivery. | Black-box monolithic prompts; no episodic story arcs; cliffhangers are not tracked. | **SQLite Continuity Ledger**: Tracks state deltas, active threads, and cliffhangers across runs. |
| **Remotion Workflows** | React-based programmatic video composition. | Deterministic timeline control, frame-accurate animation. | Heavy setup; purely visual compositing; lacks narrative directing intelligence. | **Two-Step Scene Initialization**: Programmatic timeline mapped directly to FlowKit scenes. |
| **Bark / AudioCraft** | Neural audio, music, and dialogue generation. | Expressive prosody, laughter, sigh synthesis. | High hallucinations; uncalibrated word pacing; difficult duration budgeting. | **Mixed-Mode Directing**: Spoken dialogue lines with emotional delivery directives. |
| **ComfyUI / AnimateDiff** | Node-based diffusion and temporal video synthesis. | Fine-grained node control; IP-Adapter character conditioning. | Complex maintenance; brittle web interfaces; unsuited for automated daily batches. | **Headless CLI Runner**: Zero-GUI batch automation executable via cron or terminal. |
| **Open-Sora** | Open-source large video generation model. | High-quality text-to-video diffusion. | Heavy compute; slow per-second generation; prone to physical attribute hallucinations. | **Quarantine Guard**: NLP n-gram extractor strips biometrics from action prompts. |
| **CoDeF / ControlNet Video** | Content and deformation decoupled video synthesis. | Rigid temporal consistency across video edits. | Limited narrative scope; focuses on video-to-video restyling rather than text story. | **5-Phase Retention Arc**: Dynamic pacing curve engineered for short-form retention. |
| **LangChain Video Director** | LLM agent chains for script writing. | Flexible reasoning chains and memory modules. | Prone to prompt leakage; character descriptions hallucinate across scenes; context bloat. | **Short-Lived WAL Transactions**: Episodic state persisted cleanly without context bloat. |

---

## 2. Story Directing & Prompt Decoupling Engine

### 2.1 The S2P (Separation of Identity from Action) Architecture
Monolithic AI video prompts like `"Detective Rex Vance in a dark trench coat with cybernetic eye running down a neon corridor"` fail because the generative video model attempts to redraw and re-interpret the character's physical identity in every scene. This leads to **face blending**, **costume mutation**, and **biometric drift**.

The S2P Architecture strictly isolates:
1. **Reference Entity Profiles**: Biometric appearance, permanent wardrobe, facial features, voice profile, and seed conditioning. Registered once with FlowKit.
2. **Decoupled Action Prompts**: Situational choreography, emotional acting, camera motion, and atmosphere.
3. **Quarantine Guard (`compiler.py`)**: An NLP multi-category n-gram feature extractor dynamically scans action prompts and eliminates accidental leakage of physical attributes (hair color, eye color, attire, scars, glasses).

### 2.2 5-Phase Short-Form Retention Arc
Every directed Short strictly conforms to the human retention curve for vertical video:

```
  Retention %
  100% |  [Hook]
       |    \
   80% |     ---[Rising Tension]-----\
       |                              \
   60% |                               ---[Complication]---
       |                                                   \
   40% |                                                    \--[Climax/Twist]--
       |                                                                       \
   20% |                                                                        -[Cliffhanger]
       +------------------------------------------------------------------------------------->
       0.0s       3.0s              15.0s               35.0s               50.0s         60.0s
```

1. **Phase 1: Hook (0.0s – 3.0s)**: Visual pattern interrupt, shock discovery, immediate ticking clock.
2. **Phase 2: Rising Tension (3.0s – 15.0s)**: Dilemma established, stakes introduced, tactical coordination.
3. **Phase 3: Complication (15.0s – 35.0s)**: Attempted resolution backfires, environmental cutaway, mystery deepens.
4. **Phase 4: Climax / Twist (35.0s – 50.0s)**: Peak dramatic confrontation, shocking reveal, high-cadence pacing.
5. **Phase 5: Cliffhanger & Loop (50.0s – 60.0s)**: Unresolved peril, next episode hook, seamless loop closure.

### 2.3 Mathematical Verbal Budgeting (140–160 WPM)
- Standard English conversational speech operates at ~150 words per minute (2.5 words/sec).
- **Intelligent Syntactic Budgeter (`pacing.py`)**: Unlike naive scripts that truncate words mid-sentence (`"He ran but..."`) or inject canned filler phrases (`"Every second matters now"`), our budgeter dynamically aligns word counts to scene duration via syntactic clause optimization.
- **Dynamic Tempo Curves**:
  - `PULSE_ACTION`: Rapid micro-cuts (1.5s–4.5s), high-velocity cuts for suspense and combat.
  - `NOIR_SUSPENSE`: Measured establishing shots (3.0s–7.0s) for atmosphere and psychological tension.

### 2.4 Dual-Loop Möbius Engine
- **Micro-Looping**: The closing line of the Short is grammatically engineered to lead directly into the opening hook line of the same episode, creating an infinite retention loop for TikTok/Reels algorithms.
- **Macro-Looping**: Season finale episodes feature a loop phrase connecting back to Episode 1's hook, rewarding binge watchers with cyclical narrative satisfaction.

---

## 3. FlowKit & Google Flow Integration Subsystem

### 3.1 FlowKit API Service Architecture
The integration subsystem communicates asynchronously with the local FlowKit service (`http://127.0.0.1:8100/api`):

1. **Entity Registration (`POST /api/projects`)**: Registers series metadata alongside canonical reference entities (`CharacterProfile` and `LocationProfile`).
2. **Two-Step Scene Creation**:
   - **Step 1 (`POST /api/scenes`)**: Initializes scene with `video_id`, `display_order`, `prompt` (action), and `character_names`. Notice that `narrator_text` is intentionally omitted to avoid silent server-side drops.
   - **Step 2 (`PATCH /api/scenes/{id}`)**: Updates the created scene with `narrator_text`.
3. **Resilient Batch Polling**:
   - Standard FlowKit polling can report `done: true` when `total: 0` before background worker jobs are registered.
   - Our client asserts `status.total >= expected_count` before evaluating completion status.
4. **Dual-Path Resilient Audio Ducking**:
   - Probes video clips with `ffprobe`.
   - If audio exists: executes dual-stream ducking (`[0:a]volume=0.4[sfx]; [1:a]volume=1.0[narr]; [sfx][narr]amerge`).
   - If silent: maps narration directly as sole audio stream (`-map 0:v -map 1:a -c:a aac`), eliminating FFmpeg filtergraph crash `4294967274`.
5. **Video Assembly**:
   - Normalizes clips to 1080x1920 @ 30fps using hardware-accelerated transcoding (`h264_mf`, `h264_nvenc`, or `libx264`).

---

## 4. Continuity Ledger & State Tracking Subsystem

The storage subsystem (`src/storage/ledger.py`) provides an atomic, transactional continuity ledger backed by SQLite in WAL (Write-Ahead Logging) mode.

### 4.1 Schema Overview

```sql
-- Series metadata and progression
CREATE TABLE series (
    series_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    genre TEXT NOT NULL,
    logline TEXT NOT NULL DEFAULT '',
    target_duration REAL NOT NULL DEFAULT 45.0,
    pacing_rhythm TEXT NOT NULL DEFAULT 'pulse_action',
    current_season INTEGER NOT NULL DEFAULT 1,
    current_episode INTEGER NOT NULL DEFAULT 0,
    last_cliffhanger TEXT,
    unresolved_threads TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Persistent character and location entities
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    character_id TEXT NOT NULL,
    name TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT 'character',
    visual_summary TEXT NOT NULL,
    personality TEXT NOT NULL DEFAULT '',
    voice_profile TEXT NOT NULL DEFAULT 'en-US-ChristopherNeural',
    seed INTEGER,
    reference_image_url TEXT,
    media_id TEXT,
    relationships TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(series_id, character_id)
);

-- Episode manifests and production status
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    episode_num INTEGER NOT NULL,
    season_num INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    premise TEXT NOT NULL DEFAULT '',
    target_duration REAL NOT NULL,
    actual_duration REAL NOT NULL DEFAULT 0.0,
    total_word_count INTEGER NOT NULL DEFAULT 0,
    overall_wpm REAL NOT NULL DEFAULT 0.0,
    cliffhanger TEXT,
    next_episode_hook TEXT,
    micro_loop TEXT,
    loop_phrase TEXT,
    manifest_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(series_id, episode_num, season_num)
);

-- Character state deltas (injuries, inventory, discoveries)
CREATE TABLE character_state_deltas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    episode_num INTEGER NOT NULL,
    character_name TEXT NOT NULL,
    delta_type TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Render outputs and assembled video artifacts
CREATE TABLE renders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    episode_num INTEGER NOT NULL,
    output_path TEXT NOT NULL,
    duration REAL NOT NULL,
    generation_mode TEXT NOT NULL DEFAULT 'mock',
    status TEXT NOT NULL DEFAULT 'completed',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

-- Multi-platform social media uploads (YouTube, TikTok, Instagram)
CREATE TABLE publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    episode_num INTEGER NOT NULL,
    platform TEXT NOT NULL,
    post_id TEXT,
    video_url TEXT,
    status TEXT NOT NULL DEFAULT 'published',
    metadata TEXT NOT NULL DEFAULT '{}',
    published_at TEXT NOT NULL
);
```

### 4.2 SQLite WAL Guarantees
- `PRAGMA busy_timeout = 30000;`: Blocks up to 30 seconds during concurrent transaction writes rather than throwing immediate `SQLITE_BUSY` errors.
- `PRAGMA journal_mode = WAL;`: Allows non-blocking concurrent reads during database writes.
- `PRAGMA foreign_keys = ON;`: Enforces cascade deletions and referential integrity.
- **Short-Lived Transactions**: Locks are never held across external operations (e.g. FlowKit HTTP requests or FFmpeg rendering jobs).

---

## 5. Command-Line Interface (CLI) Manual

The platform provides a zero-friction CLI runner executable via `python -m src.cli`.

### 5.1 Subcommands Overview

| Command | Purpose | Key Arguments |
|---|---|---|
| `init-series` | Initializes a new series with persistent recurring characters | `--series-id`, `--title`, `--genre`, `--logline`, `--target-duration`, `--pacing-rhythm` |
| `direct` | Directs next episode with 5-phase retention arc and S2P prompt decoupling | `--series-id`, `--episode`, `--duration`, `--rhythm`, `--output-manifest` |
| `storyboard` | Builds a slideshow still-image prompt set plus a PDF storyboard from an episode script | `--manifest`, `--series-id`, `--episode`, `--style`, `--output-dir`, `--output-pdf`, `--output-json`, `--characters-dir`, `--db-path` |
| `generate` | Orchestrates FlowKit generation (mock/live), audio ducking, and MP4 assembly | `--series-id`, `--episode`, `--mock`, `--live`, `--output-dir`, `--material` |
| `batch` | Daily batch automation runner directing and generating $N$ daily episodes | `--series-id`, `-n`, `--start-episode`, `--mock`, `--live`, `--output-dir`, `--auto-scrub`, `--auto-publish` |
| `scrub` | Removes AI watermarks and container metadata from an MP4 video file | `-i` / `--input`, `-o` / `--output`, `--profile`, `--mode`, `--no-metadata-strip` |
| `publish` | Publishes an episode video to YouTube Shorts, TikTok, and Instagram Reels | `--series-id`, `-e` / `--episode`, `--video-path`, `--title`, `--platforms`, `--mock`, `--live` |
| `status` | Displays series continuity state, episode history, character status, and renders | `--series-id` (optional, lists all if omitted) |
| `validate` | Pre-flight payload validation against FlowKit API schemas | `--series-id`, `--episode`, `--live-url` |

---

### 5.2 Step-by-Step CLI Walkthrough

#### Step 1: Initialize a New Series
```bash
python -m src.cli init-series \
  --series-id the_chronos_cipher \
  --title "The Chronos Cipher" \
  --genre "Cyberpunk Noir" \
  --logline "A gritty detective discovers a temporal chronometer ticking backwards at a locked vault crime scene." \
  --target-duration 45.0 \
  --pacing-rhythm pulse_action
```

#### Step 2: Direct Single Episode
```bash
python -m src.cli direct \
  --series-id the_chronos_cipher \
  --episode 1 \
  --duration 45.0 \
  --output-manifest output/ep1_manifest.json
```

#### Step 3: Generate Video Clip (Mock or Live Mode)
```bash
# Offline simulated mode with genuine local synthetic FFmpeg media:
python -m src.cli generate \
  --series-id the_chronos_cipher \
  --episode 1 \
  --mock \
  --output-dir output

# Live mode against running FlowKit server (http://127.0.0.1:8100/api):
python -m src.cli generate \
  --series-id the_chronos_cipher \
  --episode 1 \
  --live \
  --output-dir output
```

#### Step 4: Run Daily Batch Automation (3 Sequential Episodes)
```bash
python -m src.cli batch \
  --series-id the_chronos_cipher \
  -n 3 \
  --mock \
  --output-dir output
```

#### Step 5: Check Continuity & Production Status
```bash
# Inspect specific series:
python -m src.cli status --series-id the_chronos_cipher

# List all registered series in database:
python -m src.cli status
```

#### Step 6: Validate Payloads Against FlowKit Schemas
```bash
python -m src.cli validate --series-id the_chronos_cipher --episode 1
```

#### Step 7: Scrub AI Watermarks & Provenance Metadata
```bash
python -m src.cli scrub \
  --input output/episode_01_the_chronos_cipher.mp4 \
  --output output/clean_episode_01.mp4 \
  --profile veo_bottom_right \
  --mode delogo
```

#### Step 8: Multi-Platform Automated Publishing
```bash
python -m src.cli publish \
  --series-id the_chronos_cipher \
  --episode 1 \
  --platforms youtube,tiktok,instagram \
  --mock
```

---

## 6. Testing & Verification

### 6.1 Test Suite Execution
The repository includes a comprehensive 4-tier unit and opaque-box test suite:

```bash
# Run all tests across the repository:
pytest -v tests/

# Run storage & continuity ledger unit tests:
pytest -v tests/unit/test_ledger.py

# Run CLI runner unit tests:
pytest -v tests/unit/test_cli.py

# Run story director unit tests:
pytest -v tests/unit/test_director.py

# Run FlowKit integration unit tests:
pytest -v tests/unit/test_flowkit.py
```

### 6.2 Standalone Demonstration Scripts
```bash
# Run 3-part continuous episodic arc demonstration:
python scripts/demo_3part_arc.py

# Run standalone FlowKit payload validation suite:
python scripts/validate_flowkit_payloads.py
```
