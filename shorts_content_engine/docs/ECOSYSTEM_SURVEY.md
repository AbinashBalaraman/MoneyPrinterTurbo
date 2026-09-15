# Open-Source Video Automation & Story Directing Ecosystem Survey

**Author**: Shorts Content Engine Engineering Team  
**Date**: September 2026  
**Document Version**: 1.0.0  
**Target Architecture**: Automated Episodic Content Directing and Production Engine for Daily 30–60s Shorts  

---

## Executive Summary

Short-form algorithmic video platforms (YouTube Shorts, TikTok, Instagram Reels) have fundamentally transformed video consumption dynamics. Retaining viewers across a 30–60 second vertical video requires precise narrative pacing, rapid visual scene cuts, compelling narrative hooks within the first 3 seconds, and a continuous episodic arc that drives binge consumption.

Existing open-source video automation tools (such as MoneyPrinterTurbo, ShortGPT, and traditional B-roll aggregators) rely on monolithic monologue generation and naive stock-footage keyword matching. While effective for generic, faceless informational clips, these tools fail completely when applied to **character-driven dramatic storytelling**:
1. **Lack of Entity Persistence**: They cannot maintain the facial, anatomical, and sartorial identity of recurring characters across scene cuts.
2. **Coupled Prompts**: They interleave physical character descriptions with situational actions, triggering severe semantic cross-attention artifacts and face warping in generative diffusion models.
3. **Absence of Episodic Continuity**: They treat each video as an isolated, stateless event, unable to resolve previous cliffhangers or build evolving character arcs across multiple daily episodes.
4. **Uncalibrated Verbal Pacing**: They lack strict mathematical Word-Per-Minute (WPM) budgeting, causing voiceovers to drift, rush, or desynchronize from visual beats.

This report delivers a deep empirical investigation of **ten prominent open-source systems and frameworks**. We synthesize their strengths and failure modes into a unified architectural specification: the **Story-to-Prompt (S2P) Decoupled Directing Architecture**, powered by persistent character reference entities, a **5-Phase Short-Form Retention Arc**, and mathematical **140–160 WPM pacing budgets**.

---

## 1. Deep Survey of 10 Open-Source Repositories

### 1.1 MoneyPrinterTurbo (AutoShorts)
- **Repository / Source**: `https://github.com/harry0703/MoneyPrinterTurbo` / Local analysis at `AutoShorts` (v1.3.6)
- **Primary Tech Stack**: Python 3.11+, FastAPI, MoviePy 2.2.1, Streamlit, Edge-TTS, Faster-Whisper, SQLite WAL ledger.
- **Directing & Scripting Logic**:
  In `AutoShorts/app/services/llm.py` (`DEFAULT_SCRIPT_SYSTEM_PROMPT`), the system invokes an LLM with a single prompt string requesting raw paragraphs without formatting or stage cues. It then executes `llm.generate_terms()`, producing 5 to 8 generic 1–3 word English search terms (e.g., `"morning coffee"`, `"city traffic"`) used to query stock video APIs (Pexels, Pixabay, Coverr) or generic video generation APIs (Doubao Seedance, OFox).
- **Strengths**:
  - Robust multi-stage pipeline architecture (`script` $\to$ `terms` $\to$ `audio` $\to$ `subtitle` $\to$ `materials` $\to$ `video`).
  - Production-ready audio/video stitching in MoviePy 2.x, hardware-accelerated encoding (`h264_nvenc`, `h264_amf`, `h264_qsv`), and bouncy kinetic subtitle pop-spring animations (`_apply_subtitle_spring_animation`).
  - Solid SQLite WAL deduplication ledger with atomic `claim-before-work` concurrency semantics.
- **Weaknesses & Gaps**:
  - Entirely stateless and single-topic. No scene beats, no camera directives, no character entities.
  - Generates flat B-roll footage. Characters in stock footage change completely from shot to shot.
- **Applicability to Shorts Content Engine**:
  Its downstream assembly conventions (MoviePy/FFmpeg hardware-accelerated encoding, kinetic spring typography, SQLite WAL schema patterns) are highly reusable. However, its upstream scripting and material sourcing must be completely replaced by an agentic episodic story director and entity-based reference compiler.

---

### 1.2 ShortGPT
- **Repository / Source**: `https://github.com/RayVentura/ShortGPT` (Branch: `stable`)
- **Primary Tech Stack**: Python, MoviePy, TinyDB, Gradio, OpenAI API, Edge-TTS.
- **Directing & Scripting Logic**:
  ShortGPT employs YAML prompt templates (`facts_generator.yaml`, `editing_generate_videos.yaml`). The verbal script is capped at around 140 words for a 50-second video. It splits narration duration into uniform 4–5 second intervals and instructs the LLM to emit queries for each interval:
  ```json
  {
    "video_segments": [
      {
        "time_range": [0.0, 4.32],
        "queries": ["ancient library", "dusty book opening"]
      }
    ]
  }
  ```
- **Strengths**:
  - Early pioneer in automated short-form video generation from structured YAML templates.
  - Explicit awareness of verbal length constraints (~140 words verbal cap for 50s shorts).
  - Clean modular abstraction for audio synthesis and subtitle rendering.
- **Weaknesses & Gaps**:
  - Time slicing is mechanical and uniform (fixed 4–5s intervals) rather than beat-synchronized with narrative tension.
  - Monolithic factual monologue. No recurring characters, dramatic arcs, or multi-episode memory.
  - Relies on stock asset scraping; cannot coordinate visual identity across segments.
- **Applicability to Shorts Content Engine**:
  Provides validation of the ~140 words / 50s verbal pacing boundary, but its fixed-interval slicing and stock-query model are inadequate for dramatic episodic directing.

---

### 1.3 StoryDiffusion
- **Repository / Source**: `https://github.com/HVision-NKU/StoryDiffusion` (NeurIPS 2024)
- **Primary Tech Stack**: PyTorch, Hugging Face Diffusers, Stable Diffusion 1.5 / SDXL.
- **Core Directing & Consistency Innovation**:
  StoryDiffusion solves the core identity drift problem in generative image sequences through **Consistent Self-Attention**:
  $$\text{Attention}(Q_i, K_{\text{consistent}}, V_{\text{consistent}})$$
  where key and value matrices are shared across batch-generated frames without requiring custom per-character LoRA retraining. It also introduces a **Semantic Motion Predictor** that predicts transition dynamics between keyframe latents in image-to-video pipelines.
- **Strengths**:
  - Maintains high facial and clothing consistency across multi-panel comic stories and continuous keyframes.
  - Zero-training approach: runs inference directly without waiting 15–30 minutes to train character checkpoints.
- **Weaknesses & Gaps**:
  - High VRAM footprint during batched cross-attention.
  - Designed for synchronous batch generation; maintaining state across separate daily runs requires external attention cache management or latent vector caching.
- **Applicability to Shorts Content Engine**:
  Demonstrates that character visual consistency requires decoupling identity features from scene-specific actions. This validates our design choice of using Google Flow / FlowKit's persistent reference entity media bindings.

---

### 1.4 VideoLingo
- **Repository / Source**: `https://github.com/Huanshere/VideoLingo`
- **Primary Tech Stack**: Python, WhisperX, GPT-SoVITS, Streamlit, MoviePy.
- **Directing & Pacing Logic**:
  Focuses on high-retention video localization and subtitling. VideoLingo implements NLP-driven sentence segmentation combined with WhisperX forced phoneme alignment to guarantee **Netflix-standard subtitles**:
  - Single-line vertical display.
  - Strict maximum character length (under 32 characters per line).
  - Semantic chunking at natural syntactic and grammatical boundaries.
- **Strengths**:
  - Eliminates subtitle drift and cognitive overload for vertical viewing.
  - Demonstrates the critical importance of millisecond-accurate word boundaries for viewer engagement.
- **Weaknesses & Gaps**:
  - Purely a post-production translation/dubbing tool; does not generate scripts or direct visual action.
- **Applicability to Shorts Content Engine**:
  Informs our pacing and subtitle alignment strategy: short-form narration must be structured into concise, 4–8 word digestible beats synchronized to visual shot changes.

---

### 1.5 Remotion
- **Repository / Source**: `https://github.com/remotion-dev/remotion`
- **Primary Tech Stack**: TypeScript, React, Chromium, Node.js SSR, WebAssembly.
- **Directing & Synthesis Architecture**:
  Remotion redefines video as React code. Timelines, animations, and camera transitions are parameterized functions of `useCurrentFrame()` and `useVideoConfig()`. Rendered headlessly via Chromium, it enables frame-accurate overlays, animated kinetic typography (`@remotion/captions`), audio-reactive waveforms, and dynamic layout composition.
- **Strengths**:
  - Frame-accurate deterministic rendering; zero video/audio desynchronization.
  - Unrivaled programmatic control over overlays, lower thirds, progress bars, and kinetic subtitles.
  - Clean separation: accepts a pure JSON manifest describing scenes and timing, then executes the render.
- **Weaknesses & Gaps**:
  - Requires a Node/React runtime environment.
  - Does not contain native AI narrative generation or diffusion model orchestration.
- **Applicability to Shorts Content Engine**:
  Our `EpisodeManifest` schema is designed to be fully compatible with Remotion-style JSON specifications, allowing downstream web/React compositing or Python/FFmpeg assembly.

---

### 1.6 TaleCrafter
- **Repository / Source**: `https://github.com/AILab-CVC/TaleCrafter` (SIGGRAPH Asia 2023)
- **Primary Tech Stack**: PyTorch, ControlNet, Stable Diffusion, BLIP-2.
- **Directing & Pipeline Architecture**:
  TaleCrafter structures multi-character interactive storytelling into a formal 4-tier pipeline:
  1. **Story-to-Prompt (S2P)**: An LLM acts as director, extracting intrinsic character definitions (face, hair, attire) and generating decoupled, extrinsic action prompts for each scene.
  2. **Text-to-Layout (T2L)**: Generates spatial bounding boxes for multiple characters in the scene to prevent spatial blending.
  3. **Controllable Text-to-Image (C-T2I)**: Renders identity-preserving images guided by layout and identity LoRA/tokens.
  4. **Image-to-Video (I2V)**: Animates character actions and camera paths.
- **Strengths**:
  - Groundbreaking formulation of the **S2P (Story-to-Prompt)** decoupled directing paradigm.
  - Successfully prevents semantic collision between character identity and scene action.
- **Weaknesses & Gaps**:
  - Academic prototype; slow multi-stage inference requiring substantial GPU compute.
  - Lacks short-form viral retention mechanics, hooks, or audio voiceover integration.
- **Applicability to Shorts Content Engine**:
  The S2P decoupling architecture pioneered by TaleCrafter is a cornerstone of our engine's prompt compiler.

---

### 1.7 Director (VideoDB)
- **Repository / Source**: `https://github.com/video-db/Director`
- **Primary Tech Stack**: Python, VideoDB, Multi-Agent LLM Orchestration.
- **Directing & Multi-Agent Logic**:
  Treats video as structured data ("Video-as-Data"). Director deploys specialized sub-agents (Scriptwriter, Storyboarder, Asset Retrieval Agent, Video Editing Agent) that coordinate via a shared state object.
- **Strengths**:
  - Clean agentic separation of concerns between narrative writing, visual composition, and assembly.
  - Demonstrates that dividing scriptwriting and shot directing produces higher fidelity results than single-prompt monolithic generation.
- **Weaknesses & Gaps**:
  - Focused on video retrieval and editing rather than generative diffusion video synthesis.
  - Limited pacing budgeting for high-retention 30–60s Shorts.
- **Applicability to Shorts Content Engine**:
  Validates our modular separation between `CharacterRegistry`, `PacingBudgeter`, `PromptCompiler`, and `StoryDirector`.

---

### 1.8 WhisperX
- **Repository / Source**: `https://github.com/m-bain/whisperX` (INTERSPEECH)
- **Primary Tech Stack**: PyTorch, faster-whisper (CTranslate2), wav2vec2 forced phoneme alignment, pyannote-audio.
- **Core Functionality**:
  Provides batched, ultra-fast speech recognition with forced phoneme alignment. While standard Whisper produces segment timestamps with 1–3 second drift, WhisperX aligns audio phonetically to the underlying audio wave, achieving exact millisecond-accurate word boundaries.
- **Strengths**:
  - 70x realtime transcription speed with minimal VRAM.
  - Perfect word-level synchronization for kinetic pop-in subtitles.
- **Weaknesses & Gaps**:
  - Requires PyTorch and wav2vec2 models for local inference.
- **Applicability to Shorts Content Engine**:
  Essential for aligning TTS audio with video cuts and generating kinetic word-level subtitles.

---

### 1.9 Edge-TTS
- **Repository / Source**: `https://github.com/rany2/edge-tts`
- **Primary Tech Stack**: Python, Microsoft Edge WebSocket API.
- **Core Functionality**:
  Provides zero-cost, high-fidelity neural speech synthesis via Microsoft Azure's Edge endpoints (`en-US-ChristopherNeural`, `en-US-JennyNeural`, `en-US-GuyNeural`). It streams audio while emitting metadata events with word boundary timestamps directly over WebSockets.
- **Strengths**:
  - Zero cost, no API keys required, zero local GPU VRAM required.
  - Highly natural inflection, pacing adjustment (`--rate=+10%`), and direct word boundary events (`SubMaker`).
- **Weaknesses & Gaps**:
  - Dependent on external cloud service availability and network connectivity.
- **Applicability to Shorts Content Engine**:
  Serves as our primary default TTS engine for high-speed automated narration synthesis.

---

### 1.10 FlowKit Agent & Local Service
- **Repository / Source**: `C:/Users/SATHYA TRADERS/Documents/Abi/Projects/flowkit` (`http://127.0.0.1:8100/api`)
- **Primary Tech Stack**: Python 3.12+, FastAPI, SQLite, Chrome Extension WebSocket Relay to Google Flow (Veo 2/3 & Imagen 3).
- **Core Architecture & Schema**:
  FlowKit implements a dedicated entity-reference video production model:
  1. **Character & Entity Registry (`/characters`)**:
     Entities (`character`, `location`, `creature`, `visual_asset`, `generic_troop`, `faction`) are registered with `name`, `entity_type`, `description`, `image_prompt`, `voice_description`, and persistent Google Flow `media_id`.
  2. **Scene Specifications (`/scenes`)**:
     - `prompt`: Frame 0 image generation prompt.
     - `video_prompt`: Sub-clip timestamped camera and motion directive (e.g. `"0-3s: [Detective Rex] rushes into frame... 3-5s: camera pans left..."`).
     - `character_names`: List of bound reference entities (`["Detective Rex", "Abandoned Vault"]`).
     - `chain_type`: `ROOT`, `CONTINUATION` (chaining from previous scene's `vertical_end_scene_media_id`), or `INSERT`.
- **Strengths**:
  - Native multi-entity conditioning directly backed by Google's cutting-edge generative video models (Veo).
  - Clean REST API for project creation, scene sequencing, video synthesis, narration mixing, and video concatenation.
- **Weaknesses & Gaps**:
  - FlowKit is an execution backend; it does not contain a narrative director, episodic memory, or pacing budgeter.
- **Applicability to Shorts Content Engine**:
  FlowKit is our primary production execution engine. Our `shorts_content_engine` acts as the intelligent director that drives FlowKit.

---

## 2. Comprehensive Comparison Matrix

| Dimension | MoneyPrinterTurbo | ShortGPT | StoryDiffusion | VideoLingo | TaleCrafter | Remotion | Director (VideoDB) | WhisperX | Edge-TTS | **shorts_content_engine** (Our Target) |
|---|---|---|---|---|---|---|---|---|---|---|
| **Primary Focus** | Stock B-roll videos | Facts & trivia shorts | Consistent comic images | Subtitle localization | Multi-char storyboards | Programmatic video code | Multi-agent video ops | Forced ASR alignment | Zero-cost neural TTS | **Daily Episodic Dramatic Shorts (30–60s)** |
| **Recurring Character Persistence** | ❌ None | ❌ None | ✅ Attention-based (batch) | ❌ None | ✅ LoRA + Layout tokens | ⚠️ Manual asset injection | ❌ None | ❌ N/A | ❌ N/A | **✅ Full (Persistent Reference Entity Binding + SQLite State)** |
| **Prompt Decoupling (S2P)** | ❌ None (search terms) | ❌ None (keywords) | ⚠️ Partial (prompt split) | ❌ N/A | ✅ Full (S2P architecture) | ❌ N/A | ⚠️ Partial | ❌ N/A | ❌ N/A | **✅ Complete (Strict Entity Tokens + Action/Camera Separation)** |
| **Short-Form Retention Hooks (0–3s)** | ❌ Generic prompt | ⚠️ Basic trivia hook | ❌ None | ❌ N/A | ❌ None | ❌ N/A | ❌ None | ❌ N/A | ❌ N/A | **✅ Algorithmic Hook & 5-Phase Retention Mechanics** |
| **Episodic Multi-Part Memory** | ❌ None (single run) | ❌ None | ❌ Single batch only | ❌ None | ❌ None | ❌ None | ⚠️ Shared state dict | ❌ N/A | ❌ N/A | **✅ Episodic State Store (Tracks arcs, cliffhangers across Ep 1..N)** |
| **Mathematical Pacing & WPM Budget** | ⚠️ Paragraph count | ⚠️ Word cap guideline | ❌ None | ⚠️ Max subtitle chars | ❌ None | ✅ Frame-accurate timing | ❌ None | ✅ Word timestamps | ✅ Millisecond cues | **✅ Strict mathematical 140–160 WPM budget + explicit scene cuts** |
| **Video Generation Engine** | Stock (Pexels) / OFox | Stock (Pexels) | SD1.5 / SDXL diffusion | Source video reuse | SD + ControlNet + I2V | Headless React / WebGL | VideoDB media engine | ❌ N/A | ❌ N/A | **Google Flow (Veo 2/3 & Imagen 3 via FlowKit API)** |
| **Speech & Audio Pipeline** | Edge-TTS / MoviePy | Edge-TTS / MoviePy | ❌ None | WhisperX + GPT-SoVITS | ❌ None | @remotion/captions | Audio sub-agent | Forced phoneme align | Microsoft Neural TTS | **Edge-TTS / ElevenLabs + WhisperX alignment + audio ducking** |
| **Delivery Interface** | Streamlit / WebUI / CLI | Gradio / Python CLI | Python Scripts | Streamlit WebUI | Python Scripts | React / Node CLI | Python SDK | Python CLI / Module | Python CLI / Module | **Production CLI (Single & Batch $N$ daily runs) + REST API** |

---

## 3. Concrete Architectural Patterns for shorts_content_engine

### Pattern 1: S2P (Story-to-Prompt) Decoupling Architecture

#### The Problem: Semantic Cross-Attention Collision
In modern diffusion and video generation models conditioned on reference entity latents (e.g. Google Flow / Veo 2/3 / Imagen 3), including invariant physical character descriptions inside the scene prompt causes **semantic cross-attention collision**. 

When a prompt says:
> *"Detective Rex Vance, a rugged 40-year-old detective with square jaw, salt-and-pepper stubble, grey trench coat, runs through the rain..."*

The text encoder injects tokens for "square jaw", "grey trench coat", and "stubble" into the diffusion cross-attention layers. Concurrently, the reference image conditioning injects the reference character's latent feature maps. These two conditioning streams collide, producing:
1. **Facial Warping**: The face mutates as the model tries to satisfy both text tokens and reference pixels.
2. **Costume Drift**: The trench coat color shifts, buttons move, or duplicate collars appear.
3. **Ghost Clones**: The model often spawns a *second* detective in the background because the text tokens describe a person independent of the reference token.

#### The Solution: Strict Reference Token Binding
To achieve rock-solid character persistence across daily episodes, our engine decouples prompt generation into two strictly separated layers:

1. **Layer 1: Static Entity Profile (Registered in FlowKit /character)**:
   - `name`: `"Detective Rex Vance"`
   - `entity_type`: `"character"`
   - `visual_summary`: `"Rugged 40-year-old male detective, weathered face, salt-and-pepper stubble, intense grey eyes, dark charcoal fedora, tailored graphite trench coat."`
   - `voice_description`: `"Deep gravelly noir cadence, low resonance, mid-Atlantic accent."`
   - `media_id`: `"e3b0c442-98fc-1c14-9afbf4c8996fb924"` (reference portrait generated once and permanently cached).

2. **Layer 2: Decoupled Scene Specification (Passed to FlowKit /scene)**:
   - `bound_characters`: `["Detective Rex Vance"]`
   - `action_prompt`: `"[Detective Rex Vance] sprints past a flickering streetlamp in a downpour, his hand clutching a glowing microcassette. Cinematography: Low-angle tracking shot, 35mm anamorphic lens, neon reflections on wet asphalt, cinematic shallow depth of field."`
   - `video_prompt`: `"0-2s: [Detective Rex Vance] bolts through the rainy alleyway; 2-4s: he glances back in panic; 4-5s: dives behind an iron fire escape."`

By referencing the bound entity token `[Detective Rex Vance]`, Google Flow / Veo binds the invariant facial geometry and costume from the reference entity, while the prompt directs *only* situational movement, emotional expression, environment, lighting, and camera physics.

---

### Pattern 2: The 5-Phase Short-Form Narrative Retention Arc

Short-form algorithmic video platforms ruthlessly reward high completion rates (>80%) and high initial retention (>70% at 3s). Every generated episode strictly conforms to the **5-Phase Short-Form Retention Arc**:

```
0s                  3s                   15s                     35s                     50s           60s
├─── [1. HOOK] ─────┼── [2. RISING TENS] ─┼── [3. COMPLICATION] ──┼─── [4. CLIMAX/TWIST] ─┼── [5. CLIFF] ┤
  Pattern Interrupt    Dilemma Established   Escalation / Obstacle    Shocking Discovery     Next Ep / Loop
```

#### Phase 1: The Hook (0.0s – 3.0s)
- **Algorithmic Objective**: Defeat the immediate swipe-away. Retain $\ge 75\%$ of viewers at $t=3.0\text{s}$.
- **Directing Rules**:
  - Immediate in medias res entry. Never open with pleasantries, introductions, or scenic pans.
  - Deliver an impossible paradox, forbidden discovery, or immediate ticking clock.
  - Visually: Extreme close-up of character expression, sudden camera motion, or violent lighting change.
  - If Episode $N > 1$: Immediately address or invert the cliffhanger from Episode $N-1$.

#### Phase 2: Rising Tension & Context (3.0s – 15.0s)
- **Algorithmic Objective**: Sustain $60\%+$ viewership through the premise setup.
- **Directing Rules**:
  - Introduce the concrete dilemma through character action rather than static exposition.
  - Rapid scene cuts: 2 to 3 distinct shots (3.5 to 4.5 seconds per shot).
  - Bind secondary recurring characters or location entities.

#### Phase 3: Complication & Development (15.0s – 35.0s)
- **Algorithmic Objective**: Flatten the mid-video retention valley.
- **Directing Rules**:
  - The protagonist executes an intended solution that either fails catastrophically or uncovers a deeper conspiracy.
  - Pacing accelerates; dialogue/narration tightens; background music tempo increases.
  - 3 to 4 scene cuts exploring multiple visual perspectives.

#### Phase 4: Climax / Sudden Twist (35.0s – 50.0s)
- **Algorithmic Objective**: Deliver emotional payoff that validates the viewer's investment.
- **Directing Rules**:
  - Peak dramatic and visual intensity.
  - Answers the immediate question raised in Phase 1, but instantly reveals an unexpected truth.
  - High dynamic motion in the video prompt (rapid push-in, whip pan, dramatic lighting reveal).

#### Phase 5: Cliffhanger & Seamless Loop (50.0s – 60.0s)
- **Algorithmic Objective**: Maximize two vital algorithmic metrics:
  1. **Series Binge Rate**: Drives the viewer to click through to Episode $N+1$.
  2. **Loop Completion Rate (>100%)**: The final sentence is crafted to connect grammatically or conceptually back into the Phase 1 opening hook sentence when the Short auto-loops!
- **Directing Rules**:
  - Ends on an agonizing unresolved micro-cliffhanger.
  - Clear next-episode hook preview.

---

### Pattern 3: Mathematical Timing & Pacing Budgeting Rules

Pacing in vertical shorts is a precise science. Natural, high-retention English voiceover runs between **140 and 160 Words Per Minute (WPM)** (averaging $2.46$ to $2.55$ words per second).

If narration drops below 135 WPM, the video feels sluggish, inducing swipe-away. If narration exceeds 165 WPM, listener cognitive fatigue spikes, and subtitles fail to remain legible on mobile screens.

#### Narration Budget Formulas:
$$\text{Target Words} = \text{Duration (seconds)} \times \frac{150 \text{ words}}{60 \text{ seconds}} = \text{Duration} \times 2.50$$
$$\text{Min Words} = \text{Duration} \times \frac{140}{60} = \text{Duration} \times 2.33$$
$$\text{Max Words} = \text{Duration} \times \frac{160}{60} = \text{Duration} \times 2.67$$

#### Pacing & Scene Budget Allocation Table:

| Target Duration | Verbal Budget (Words) | Total Scenes / Cuts | Target Shot Length | Phase 1 (Hook) | Phase 2 (Rising) | Phase 3 (Complic.) | Phase 4 (Climax) | Phase 5 (Cliff/Loop) |
|---|---|---|---|---|---|---|---|---|
| **30.0s** | **70 – 80 words** | 6 – 7 scenes | 3.5 – 5.0s | 0.0–3.0s (7–8 w) | 3.0–9.0s (15–18 w) | 9.0–19.0s (25–28 w) | 19.0–26.0s (16–20 w) | 26.0–30.0s (9–11 w) |
| **45.0s** *(Optimal)* | **105 – 120 words** | 9 – 11 scenes | 3.5 – 5.0s | 0.0–3.0s (7–8 w) | 3.0–14.0s (26–30 w) | 14.0–32.0s (42–48 w) | 32.0–41.0s (22–26 w) | 41.0–45.0s (9–12 w) |
| **60.0s** *(Max)* | **140 – 160 words** | 12 – 14 scenes | 4.0 – 5.5s | 0.0–3.0s (7–8 w) | 3.0–15.0s (28–32 w) | 15.0–38.0s (54–60 w) | 38.0–52.0s (32–36 w) | 52.0–60.0s (18–22 w) |

#### Sub-Clip Action Formatting:
Each scene specification generated by the director divides its time into sub-clip action beats:
- `time_start: 14.0, time_end: 18.5 (duration: 4.5s)`
- `video_prompt`: `"0-2.5s: [Detective Rex Vance] pries open the cipher lock; 2.5-4.5s: spark erupts as alarm blares, camera whips to security gate."`

---

## 4. Architectural Bridge: Implementing shorts_content_engine

Translating these findings into our codebase establishes a clean four-layer separation of concerns:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        1. STORY DIRECTING ENGINE                       │
│  src/director/director.py, character.py, pacing.py, compiler.py         │
│  - Persistent Character Registry with visual/voice profiles & seeds     │
│  - 5-Phase Narrative Generator enforcing continuity across Ep 1..N     │
│  - Mathematical Pacing Budgeter (140-160 WPM & sub-clip cuts)          │
│  - S2P Compiler (decouples entity tokens from scene camera prompts)    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ EpisodeManifest
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         2. FLOWKIT ADAPTER                             │
│  src/flowkit/adapter.py, models.py, client.py                          │
│  - Maps EpisodeManifest -> FlowKit ProjectCreate, SceneCreate payloads │
│  - Pre-flight schema validation against http://127.0.0.1:8100/api      │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Validated Payloads
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   3. VIDEO GENERATION ORCHESTRATOR                     │
│  src/flowkit/orchestrator.py                                           │
│  - Entity registration (reference portraits, voice models)             │
│  - Keyframe generation (Imagen 3) & Video Clip generation (Veo)        │
│  - Scene chaining (CONTINUATION via endSceneMediaId)                   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Video + Audio Tracks
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               4. EPISODIC CONTINUITY LEDGER & BATCH CLI                │
│  src/storage/ledger.py, src/cli.py                                     │
│  - SQLite WAL persistence for series state, cliffhangers, and history  │
│  - Automated CLI for daily batch generation of N episodes              │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Verification Method

To independently verify the observations, references, and mathematical bounds in this document:
1. **AutoShorts Pipeline & Prompts**: Inspect `AutoShorts/app/services/llm.py:35` and `AutoShorts/app/services/task.py:312`.
2. **ShortGPT Time Ranges**: Inspect `shortGPT/prompt_templates/editing_generate_videos.yaml`.
3. **StoryDiffusion Equation**: Inspect `StoryDiffusion: Consistent Self-Attention for Long-Range Image and Video Generation` (NeurIPS 2024).
4. **FlowKit Reference Schema**: Inspect `flowkit/ARCHITECTURE.md:38–120`.
5. **Pacing Mathematics**: Test script word count against verbal duration:
   $$\text{WPM} = \frac{\text{word count}}{\text{duration in seconds}} \times 60$$
   Acceptance interval: $[140.0, 160.0]\text{ WPM}$.

---
*End of Ecosystem Survey Report.*
