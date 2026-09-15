# Create Video Content Using ONLY Free Text LLMs

**Research date:** 2026-09-12 · **Verified via:** GitHub REST API (live star/license/push data) + web sources
**Machine profile detected:** no NVIDIA GPU (`nvidia-smi` absent) · ffmpeg 8.1.2 present · Node v22.22.2 present

---

## 0. The one-sentence answer

A text LLM cannot emit pixels — so you make it emit **code** and **structured JSON**, and let free renderers
(Remotion / Motion Canvas / Manim / ffmpeg) turn that into video. Narration comes from free TTS
(Edge-TTS, Kokoro, Piper), visuals from stock footage or code-drawn graphics, and *only if you want real
diffusion footage* do you run an Apache-2.0 video model (Wan2.2, LTX-Video) on a **free cloud GPU**.

That is the entire trick. Everything below is the verified tool inventory and 4 concrete stacks.

---

## 1. The three "rendering substrates" (pick one — this is the real decision)

| Substrate | What the LLM outputs | What renders pixels | GPU needed? | Visual style |
|---|---|---|---|---|
| **A. Code renderer** | React/TSX (Remotion), TS (Motion Canvas), Python (Manim) | Headless Chromium / canvas → ffmpeg | **No** | Motion graphics, kinetic type, charts, explainers |
| **B. Stock + archival footage** | JSON scene plan + search queries | ffmpeg editing real clips | **No** | Real footage, docs, B-roll, montages |
| **C. Local diffusion** | Image/video prompts | Wan2.2 / LTX-Video / CogVideo on GPU | **Yes** (or free cloud GPU) | AI-generated cinematic shots |

**On this machine (no NVIDIA GPU): A and B work today. C needs Kaggle/Colab free GPU (~30 h/week T4).**

---

## 2. Layer map of the fully-free stack

```
[Free text LLM]  →  script + scene JSON + image prompts
        │
        ├─→ [TTS]           Edge-TTS (no key) / Kokoro-82M / Piper (local, offline)
        ├─→ [Visuals]       A: Remotion|MotionCanvas|Manim code
        │                   B: Pexels/Pixabay API (free key) + Archive.org/NASA/Wikimedia (no key)
        │                   C: Wan2.2 / LTX-Video via ComfyUI (GPU)
        ├─→ [Music]         ACE-Step (Apache-2.0) / MusicGen (MIT)
        ├─→ [Subtitles]     faster-whisper / whisperX (word-level timestamps)
        └─→ [Assembly]      ffmpeg  ← single point of truth, always free
```

---

## 3. Free text-LLM layer (verified 2026-09-12)

### Local / zero-cost, zero-key
| Option | Stars | License | Notes |
|---|---|---|---|
| [ollama/ollama](https://github.com/ollama/ollama) | 180,711 | MIT | Runs Qwen, GLM, DeepSeek, gpt-oss, Gemma, Kimi locally. Zero API cost. |
| [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | 127,931 | MIT | Lower-level; best for CPU/GGUF quantized models. |

### Hosted free tiers — keyless (no signup)
| Provider | Access signal | Verified 2026-09-12? |
|---|---|---|
| **OVHcloud AI Endpoints** | Anonymous, OpenAI-compatible. `https://oai.endpoints.kepler.ai.cloud.ovh.net/v1/chat/completions`, models `Qwen3-32B` / `Mistral-7B-Instruct-v0.3`. Per-IP rate limit (~ tens of req/min; back off on 429). | **Yes** — used end-to-end in `demo/plan.py --provider ovhcloud` to generate valid scene JSON. |
| **Kilo Gateway** | Anonymous, ~200 req/hr per IP | OpenAI-compat endpoint TBD |
| Pollinations (`text.pollinations.ai/openai`) | Anonymous | **No — now requires a wallet/key (returns 402 "KEY_BUDGET_EXHAUSTED").** Treat as keyed. |

### Hosted free tiers — free key, permanent tier
Groq · Google Gemini · OpenRouter · NVIDIA NIM · Cloudflare Workers AI (daily Neuron allowance) ·
Z.ai/GLM (~1,000 req/day) · Ollama Cloud · HF Inference router (monthly credits) ·
Mistral · Cohere · ModelScope (2,000 calls/day) · Aion Labs (20K tokens/day, no card) · SiliconFlow ·
Cerebras (finite trial only).

> Pooling tool: [0xzr/freellmpool](https://github.com/0xzr/freellmpool) (MIT) — one OpenAI-compatible
> endpoint with failover across 22 providers / 178 enabled chat routes. `pip install freellmpool`.
> Source of the tier table: [free-llm-api-providers-list](https://0xzr.github.io/freellmpool/free-llm-api-providers-list.html)
> (updated 2026-08-29). Limits change — always re-verify.

**Practical advice:** use Ollama locally as primary, and keep one keyless provider (Pollinations) plus
one free-key provider (Groq or Gemini) as automatic fallbacks. Never build on a single free tier.

---

## 4. The four recommended stacks

### ⭐ Stack 1 — "Code-only video" (best fit for this machine, zero GPU, zero cost)

The LLM writes code; the code renders video. Fully deterministic, brandable, and repeatable.

| Role | Tool | Stars | License | Last push |
|---|---|---|---|---|
| React video renderer | [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | 58,966 | custom (free for individuals/small teams; paid license for larger companies — **read it**) | 2026-09-11 |
| Remotion agent skills | [remotion-dev/skills](https://github.com/remotion-dev/skills) | 4,551 | — | 2026-09-09 |
| Code-driven animation | [motion-canvas/motion-canvas](https://github.com/motion-canvas/motion-canvas) | 19,090 | MIT | 2026-07-02 |
| Motion Canvas agent skills | [VideoZero/skills](https://github.com/VideoZero/skills) | 67 | Apache-2.0 | 2026-08-11 |
| Math/education animation | [3b1b/manim](https://github.com/3b1b/manim) | 93,779 (community fork 40,796) | MIT | 2026-09-09 |
| Narration | edge-tts (see §5) | 11,920 | — | 2026-03-22 |
| Subtitles/ASR | [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | 25,353 | MIT | 2025-11-19 |

**Why this wins:** output is *code*, so it is versionable, template-able, and never drifts. An LLM
writes a 200-line Remotion composition; `npx remotion render` produces a pixel-perfect MP4. No model
hallucinates your logo or your CTA text — text is real DOM text, not generated pixels.

### ⭐ Stack 2 — "Agentic production system" (fastest path to a finished video today)

[calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) — **57,548★ · AGPL-3.0 · pushed 2026-09-06**

> "The first open-source, agentic video production system… There is no code orchestrator. **Your AI
> coding assistant IS the orchestrator.**" — and: "You don't need paid API keys to make real videos."

- 12 pipelines: animated explainer, animation/motion graphics, avatar spokesperson, cinematic, clip
  factory, **documentary montage**, hybrid, localization & dub, podcast repurpose, screen demo,
  talking head, character animation.
- Enforced flow: `research → proposal → script → scene_plan → assets → edit → compose`, with human
  approval gates and post-render self-review (ffprobe + frame sampling + audio analysis).
- **Zero-key free path:** Piper TTS (offline narration) + Archive.org / NASA / Wikimedia Commons
  (no-key footage) + Pexels/Unsplash/Pixabay (free developer keys) + Remotion & HyperFrames
  (HTML/CSS/GSAP) composition + ffmpeg post.
- Optional upgrades: `VIDEO_GEN_LOCAL_MODEL=wan2.2-ti2v-5b | wan2.1-1.3b | hunyuan-1.5 | ltx2-local | cogvideo-5b`.
- Requires: Python 3.10+, Node 18+, ffmpeg, and an AI coding assistant (Claude Code / Cursor / Copilot / Windsurf / Codex).

Other turnkey options:
| Project | Stars | License | Notes |
|---|---|---|---|
| [harry0703/MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) | **122,586** | MIT | Supports **Ollama** for the script LLM and **Edge TTS (free, no key)**; Pexels/Pixabay stock. Its AI-video providers are all paid — use it for script+TTS+stock, not generation. |
| [FujiwaraChoki/MoneyPrinterV2](https://github.com/FujiwaraChoki/MoneyPrinterV2) | 31,867 | AGPL-3.0 | Twitter/YouTube automation oriented. |
| [Hao0321/video-autopilot-kit](https://github.com/Hao0321/video-autopilot-kit) | 2,096 | MIT | Fill-in-your-own-data templates → CapCut JSON + ffmpeg. Deterministic, no AI needed. |

### Stack 3 — "Free stock-footage montage" (real footage, no GPU, no generation)

Same as Stack 2's documentary pipeline, hand-rolled:
- LLM → topic research → 60s narration script → per-sentence **search query** list.
- Fetch clips: **Pexels API** / **Pixabay API** (free keys) · **Wikimedia Commons**, **Archive.org**,
  **NASA** (no key at all).
- Assemble with ffmpeg (`concat` + `zoompan` Ken Burns + crossfade), overlay TTS, burn word-level
  captions via whisperX timestamps, duck a royalty-free music bed.

### Stack 4 — "Real AI-generated footage" (needs GPU; free via Kaggle/Colab)

Open-weight video models — all **Apache-2.0** unless noted:

| Model | Repo | Stars | VRAM (verified from README) |
|---|---|---|---|
| **Wan2.2 TI2V-5B** | [Wan-Video/Wan2.2](https://github.com/Wan-Video/Wan2.2) | 17,475 | **≥24 GB** (RTX 4090) with `--offload_model True --convert_model_dtype --t5_cpu`; 5 s 720p in **<9 min** on one consumer GPU |
| Wan2.2 T2V/I2V-A14B | same | — | MoE ~27B total / 14B active; **≥80 GB** |
| **LTX-Video 0.9.8 2B distilled** | [Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video) | 10,946 | "light VRAM"; FP8 variants; community **Q8: 720×480×121 in <1 min on an RTX 4060 8 GB** |
| LTX-2 (4K/50fps audio+video) | [Lightricks/LTX-2](https://github.com/Lightricks/LTX-2) | 9,396 | **custom license — not OSI**; check commercial terms |
| CogVideoX | [zai-org/CogVideo](https://github.com/zai-org/CogVideo) | 13,011 | Apache-2.0, 2B/5B |
| HunyuanVideo | [Tencent-Hunyuan/HunyuanVideo](https://github.com/Tencent-Hunyuan/HunyuanVideo) | 12,517 | **NOASSERTION / custom — not OSI** |
| Mochi 1 | [genmoai/mochi](https://github.com/genmoai/mochi) | 3,724 | Apache-2.0 |
| Open-Sora | [hpcaitech/Open-Sora](https://github.com/hpcaitech/Open-Sora) | 29,774 | Apache-2.0 |

Memory hacks that make 8–24 GB GPUs viable:
[modelscope/DiffSynth-Studio](https://github.com/modelscope/DiffSynth-Studio) (13,088★, Apache-2.0 —
FP8 quantization + layer-by-layer offload) and
[ModelTC/LightX2V](https://github.com/ModelTC/LightX2V) (2,804★, Apache-2.0 — step-distilled + quantized).
Orchestrate either via [Comfy-Org/ComfyUI](https://github.com/Comfy-Org/ComfyUI) (132,637★, **GPL-3.0**).

**Free GPU sources (2026):** Kaggle Notebooks ≈ 30 h/week T4 (sessions capped ~12 h);
Google Colab free tier T4/L4, ~12 h sessions with idle disconnects.
Rule of thumb: generate 4–6 short clips per session, cache them, edit locally in ffmpeg.

---

## 5. Free narration (TTS) — the layer most people overpay for

| Option | Stars | License | Key? | Notes |
|---|---|---|---|---|
| **Edge-TTS** ([rany2/edge-tts](https://github.com/rany2/edge-tts)) | 11,920 | — | **No** | Best free default. "Free, no API key required" — used as Azure TTS V1 in MoneyPrinterTurbo. Online service, so keep volume sane and check ToS for commercial use. |
| **Kokoro-82M** | — | Apache-2.0 | No | Best quality/CPU ratio. Serve with [remsky/Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) (5,432★, OpenAI-compatible + Docker) or [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (2,722★, MIT, CPU). |
| **Dia** ([nari-labs/dia](https://github.com/nari-labs/dia)) | 19,398 | Apache-2.0 | No | Ultra-realistic dialogue, multiple speakers in one pass. |
| **Piper** ([rhasspy/piper](https://github.com/rhasspy/piper)) | 11,280 | MIT | No | Fastest CPU/offline — **but repo is archived**; pin a version. |
| IndexTTS | 23,906 | custom | No | Industrial-level zero-shot voice cloning. |
| coqui-ai/TTS (XTTS-v2) | 46,000 | MPL-2.0 | No | Last push 2024 — aging, but the `/models` still work. |

**Music:** [ace-step/ACE-Step](https://github.com/ace-step/ACE-Step) (4,822★, Apache-2.0) ·
[facebookresearch/audiocraft](https://github.com/facebookresearch/audiocraft) MusicGen (23,619★, MIT).
**SFX/ambience:** Freesound (CC0 filters) — always check per-asset license.

---

## 6. The LLM → video contract (copy-paste prompt)

The single most important engineering decision: force the LLM into a strict JSON contract. This is what
makes the pipeline reliable instead of vibe-driven.

```text
You are a video scene planner. Output ONLY valid JSON, no prose.

Schema:
{
  "title": string,
  "aspect": "9:16" | "16:9",
  "voice": { "style": string, "wpm": number },
  "scenes": [
    {
      "id": number,
      "narration": string,          // <= 18 words, spoken aloud
      "visual": string,             // concrete on-screen description
      "render": "code" | "stock" | "diffusion",
      "stock_query": string|null,   // 3-6 keyword search terms
      "diffusion_prompt": string|null,
      "motion": "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "static",
      "duration_hint": number       // seconds
    }
  ]
}

Rules:
- 60s total, 6-9 scenes, each scene advances the story.
- narration must be speakable: no markdown, no URLs, spell out numbers.
- stock_query must be visual nouns only (no abstract concepts).
```

Then validate with a JSON schema before spending a single second of render time.

---

## 7. Recommended pick for this machine

**No NVIDIA GPU → start with Stack 1 + Stack 3, graduate to Stack 4 later.**

```bash
# 1) Free local LLM
winget install Ollama.Ollama  &&  ollama pull qwen3:8b        # or glm4 / gpt-oss

# 2) Code-rendered video (zero GPU)
npx create-video@latest my-video                              # Remotion
npx skills add videozero/skills                               # Motion Canvas agent skills

# 3) Narration
pip install edge-tts        # keyless
#   or: docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu   # offline, better quality

# 4) Assembly — ffmpeg 8.1.2 already installed here
```

Then, when you want true AI footage:
```bash
pip install diffsynth-studio         # FP8 + layer offload for Wan2.2 on ≤24GB
# or run ComfyUI + Wan2.2 on Kaggle (~30h/week free T4), download the clips, edit locally
```

**If you want a finished video in the next hour:** clone
[OpenMontage](https://github.com/calesthio/OpenMontage), run `make setup`, open it in your coding
assistant, and say *"make a 60-second explainer about X using only free tools."* It already wires
Piper + Wikimedia/Archive.org + Remotion/HyperFrames + ffmpeg, and its quality gates stop it from
handing you a slideshow.

---

## 8. Reality checks (read before committing)

1. **License traps.** "Open weights" ≠ MIT. HunyuanVideo and LTX-2 use custom non-OSI licenses;
   FLUX.1[dev] weights are non-commercial (FLUX.1[schnell] is Apache-2.0). ComfyUI is now GPL-3.0.
   Check each model card before commercial use.
2. **Free tiers are not SLAs.** Keyless/free routes get rate-limited, disabled, or repriced without
   notice (freellmpool's own table marks several providers as *disabled pending verification*).
   Build in provider failover from day one.
3. **Free GPU is queue-based.** Kaggle/Colab will disconnect; design for resumable, checkpointed runs.
4. **Edge-TTS is a reverse-engineered Microsoft endpoint.** Great for prototyping and internal work;
   for commercial distribution prefer Kokoro (Apache-2.0) or Piper (MIT).
5. **Watermarks/terms on stock.** Pexels/Pixabay are free but check per-clip terms; Archive.org/NASA/
   Wikimedia vary by asset (NASA imagery is generally public domain, Wikimedia is per-file CC).
6. **Voice cloning & likeness** carry real legal risk in most jurisdictions. Keep it to your own voice.

---

## 9. Working demo in this repo

`demo/` contains a proven end-to-end pipeline that uses **zero paid services**:
a script JSON → free TTS narration → free imagery → ffmpeg render → captioned MP4.
See `demo/README.md`.
