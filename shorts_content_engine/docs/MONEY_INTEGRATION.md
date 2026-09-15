# MoneyPrinterTurbo Integration (branch: `fork/money-bridge`)

Fork of `shorts_content_engine` that connects the episodic director +
slideshow storyboard to **MoneyPrinterTurbo** (`../Money`, v1.3.6) for
image generation and final video assembly.

## Verified end-to-end (2026-09-13, real Money CLI + `.venv`)

| Stage | Command (in `../Money`) | Result |
|---|---|---|
| Script | `--batch-file <local_tasks.json> --stop-at script` | ✅ `succeeded: 1` — our 604-char Ep1 narration accepted verbatim |
| Audio | `... --stop-at audio --voice-name en-US-ChristopherNeural` | ✅ `succeeded: 1` — free Edge TTS, `audio.mp3`, **42s** (≈ our 45s target), grandfather voice matching Arthur |
| Full video | `... --video-aspect 9:16 --video-transition-mode fade-in --video-concat-mode sequential --bgm-type none` (17 placeholder stills) | ⏳ ✅ `succeeded: 1` — `final-1.mp4`: **1080x1920, h264+aac, 41.2s, 3.0MB**, copied to `output/money_demo/farmer_and_rusty_ep01_demo.mp4` |

## Possibilities matrix

### A. `local` source — slideshow assembly (FREE, works today) ✅ RECOMMENDED for Ep1
- You generate the 17 stills with any image model using
  `output/storyboards/farmer_and_rusty_ep01_storyboard.pdf` prompts +
  `Charectors/` photos for likeness.
- Save as `output/stills/farmer_and_rusty_ep01/S1-IMG1.png … S6-IMG3.png`.
- `python scripts/export_to_money.py --source local` → batch JSON with
  `video_materials` (17 files), `video_script` (narration+dialogue),
  `sequential` concat, `match_materials_to_script: true`, clip 3s.
- Money adds: Edge-TTS narration (free), subtitles, BGM, 9:16 concat,
  fade transitions. No image/video API keys needed.

### B. `openai_image` source — auto still generation (1 image/term)
- `python scripts/export_to_money.py --source openai_image` → batch JSON with
  `video_terms` = our 17 full cinematic prompts.
- In Money's `config.toml` set `video_source = "openai_image"`,
  `openai_image_base_url` + `openai_image_model`, and
  `openai_image_prompt_template = "{term}"` so prompts pass through untouched.
- Works with local ComfyUI/SD gateways (free, no auth) or cloud relays
  (~$0.006/image). Money renders each image into a zoom-effect clip, then
  the same TTS/subtitle/assembly as A.

### C. True video clips — Seedance / MiniMax H3 / WaveSpeed / Ofox (paid)
- Same batch mechanism, `video_source` = `volcengine_seedance` / `ofox` /
  `metaso_minimax` (+ `--confirm-*-charge` flags), terms = scene action prompts.
- 2–15s moving clips instead of stills. Billed per clip/second. Best for
  later episodes once the slideshow cut is validated.

### D. API orchestration (future: `src/moneybridge/client.py`)
- Run Money API (`python main.py`, :8080) next to FlowKit (:8100).
  Endpoints exist: `POST /videos|/audio|/subtitle`, `GET /tasks`, task query,
  `/stream|/download` for artifacts.
- Add an async client mirroring `src/flowkit/orchestrator.py` phases:
  submit task → poll task status → download MP4 → record in
  `continuity_ledger.db` renders. Not yet implemented; CLI batch (A–C)
  already covers Ep1 without new services.

## Character consistency note
Money has no reference-entity model (unlike FlowKit). Likeness comes from
**our prompts**: every `video_terms` entry embeds Arthur's/Rusty's full
`visual_summary`, and the PDF thumbnails are the art-direction reference.
For `local` mode you control consistency directly at generation time.

## Quickstart (Ep1, free path)
```bash
# 1. storyboard (this repo, branch fork/money-bridge)
python scripts/generate_storyboard_pdf.py
# 2. generate 17 REAL AI stills (free, no key) -> output/stills/farmer_and_rusty_ep01/*.png
python scripts/generate_stills_pollinations.py
# (verified 2026-09-13: 17/17 first-try; likeness approximate, free tier
#  cannot see Charectors/ ref photos; final AI video: 1080x1920, 41.2s at
#  output/money_demo/farmer_and_rusty_ep01_ai.mp4)
# 3. export + validate
python scripts/export_to_money.py --source local
# 4. assemble (in ../Money)
.venv/Scripts/python.exe cli.py --batch-file "C:/Users/SATHYA TRADERS/Documents/Abi/Projects/shorts_content_engine/output/money_tasks/farmer_and_rusty_ep01_local_tasks.json" --video-aspect 9:16 --voice-name en-US-ChristopherNeural --video-transition-mode fade-in --video-concat-mode sequential
```
