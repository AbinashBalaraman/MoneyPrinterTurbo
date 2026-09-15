# Adversarial Debate Consensus & Elevation Plan

**Date**: 2026-09-12T20:33:00Z  
**Participants**:
- **Creative Director** (`teamwork_preview_critic_creative_1`)
- **Pipeline Architect** (`teamwork_preview_challenger_pipeline_1`)
- **Consistency & Integrity Auditor** (`teamwork_preview_auditor_consistency_1`)
- **Project Orchestrator** (`teamwork_preview_orchestrator_1`)

---

## 1. Debate Summary & Conflict Resolution

| Dimension | Creative Director | Pipeline Architect | Consistency Auditor | **Consensus Resolution** |
|---|---|---|---|---|
| **Scene Count & Pacing** | Demands 12–18 micro-cuts (1.5–3.0s) for TikTok retention | Argues 12+ scenes causes an 11–15 min Veo latency explosion | Demands strict staging for all bound entities | **Resolved**: Budget 5–8 macro-scenes per 45s Short, using Veo sub-clip prompts (`0-3s: ... 3-6s: ...`) to create visual speed without extra API latency. |
| **Prompt Decoupling** | Wants emotional performance adjectives in scene prompts | Demands simple predictable prompts for stability | Vetoes physical attribute leakage; demands strict quarantine | **Resolved**: Strict isolation of permanent biometric traits (hair, eyes, wardrobe) to reference entity profiles. Allow situational acting directives (`knuckles white with tension`, `glances frantically`). |
| **Entity Binding** | Demands multi-character banter and ensemble staging | Warns that 3+ character references causes Frankenstein facial blending in Veo | Proves that binding un-actioned characters creates disembodied phantom faces | **Resolved**: Max 1–2 bound characters per scene. Strict bijectivity: every bound entity MUST have an explicit action directive. Environmental cutaways must have `bound_characters = []`. |
| **Script Timing & Budget** | Rejects naive string slicing mid-sentence (`"but preserve..."`) and canned fillers (`"Every second matters now."`) | Proves text-first word budgeting is brittle; advocates Audio-Driven Scene Timing | Demands authentic script generation without artificial padding | **Resolved**: Abolish mid-sentence amputation and canned filler phrases. Employ intelligent syntactic compression and Audio-Driven duration adjustments. |
| **Audio & Dialogue** | Demands direct spoken character dialogue with emotional delivery | Notes FlowKit `narrate_video` uses a single voice model per scene | Demands voice profile binding integrity | **Resolved**: Support Mixed-Mode Directing (`narration` + `dialogue` lines with speaker attribution and vocal directives). |
| **FlowKit Integration Traps** | Agrees on pipeline reliability | Uncovers `batch-status` polling trap (`done: true` on `total: 0`) and FFmpeg filtergraph crash on silent videos | Uncovers silent drop of `narrator_text` on `POST /api/scenes` and Location entity prompt distortion | **Resolved**: Enforce robust batch polling, dual-path audio ducking, two-step scene initialization (`POST` + `PATCH`), and EntityType-aware reference generation. |

---

## 2. Concrete Actionable Engineering Improvements

### Improvement 1: Dynamic N-Gram Attribute Quarantine Guard (`compiler.py`)
- Replace the 7-word list with an NLP multi-category n-gram feature extractor covering hair, eyes, facial features, attire, and build.
- Eliminate the multi-word dead token bug (`'trench coat'`).
- Reject any prompt containing permanent physical traits from bound profiles.

### Improvement 2: Strict Bijective Staging & Cutaway Cleanliness (`director.py`, `compiler.py`)
- For pure environmental and establishing cutaways, set `bound_characters = []`.
- When characters are bound, ensure each character has a concrete visual action.
- Remove the artificial compiler patch `". Featuring [Name] in frame"`.

### Improvement 3: EntityType-Aware Reference Generation (`models.py`)
- For `EntityType.LOCATION`: Generate wide landscape establishing shots (`16:9 framing`) with `voice_description = None`.
- For `EntityType.CHARACTER`: Generate full-body canonical portraits with `voice_description`.

### Improvement 4: Intelligent Syntactic Budgeter & Dual-Loop Engine (`pacing.py`, `director.py`)
- Abolish string truncation mid-sentence and canned filler phrases.
- Implement **Dynamic Tempo Curves** (`PULSE_ACTION`, `NOIR_SUSPENSE`).
- Implement **Dual-Loop Möbius Engine**: Single-episode micro-looping (closing line seamlessly opens hook) + multi-episode macro-looping.

### Improvement 5: Mixed-Mode Directing Schema (`models.py`)
- Add `DialogueLine` model (`speaker`, `text`, `emotion`, `word_count`, `wpm`) to `SceneBeat`.
- Format `video_prompt` to inject dialogue action verbs (`says:`, `whispers:`, `snarls:`) to trigger Veo's voice synthesis.

### Improvement 6: Resilient FlowKit API Client & Pipeline Orchestrator (`flowkit/`)
- Implement robust batch status polling: verify `status.total >= expected_count` before evaluating `done`.
- Implement two-step scene creation: `POST /api/scenes` followed by `PATCH /api/scenes/{id}` with `narrator_text`.
- Implement dual-path audio mixer: probe for video audio; duck if audio exists, map directly if video is silent.
- Standardize final video concatenation with hardware-accelerated transcoding (`h264_mf` / `h264_nvenc` / `libx264`) at 1080x1920@30fps.
- Configure SQLite WAL connections with `busy_timeout = 30000` (30s) and short-lived atomic commits.
