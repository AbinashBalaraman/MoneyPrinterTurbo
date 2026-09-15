# Zero-Cost Video Pipeline (proof of concept)

End-to-end: **free text LLM → scene JSON → free TTS → free imagery → ffmpeg → captioned MP4.**
No paid API. No GPU. Runs on this machine.

```
topic ──▶ plan.py ──▶ script.json ──▶ make_video.py ──▶ final.mp4
          (free LLM)   (contract)      (TTS + ffmpeg)
```

## Run it

```bash
# 1. create env + install the only two deps
python -m venv .venv && ./.venv/Scripts/pip install edge-tts requests

# 2. use the bundled example (skip the LLM)
./.venv/Scripts/python demo/make_video.py --script demo/script.example.json --out out/demo.mp4

# 3. or generate a new script from a topic with a FREE text LLM
./.venv/Scripts/python demo/plan.py --topic "why sleep matters more than you think" --out out/script.json
./.venv/Scripts/python demo/make_video.py --script out/script.json --out out/sleep.mp4
```

## The free LLM layer (`plan.py`)

Tries, in order:

1. **Ollama** (`http://localhost:11434`) — local model, zero cost, no key. `ollama pull qwen3:8b`
2. **OVHcloud AI Endpoints** (`https://oai.endpoints.kepler.ai.cloud.ovh.net/v1`) —
   **truly anonymous keyless tier**, OpenAI-compatible, `Qwen3-32B` /
   `Mistral-7B-Instruct-v0.3`. Per-IP rate-limited; the script backs off 8 s on a 429.
   *Verified end-to-end:* `python demo/plan.py --provider ovhcloud --topic "..."`
   produced valid scene JSON that rendered into captioned MP4s in `out/`.
3. **Pollinations** (`https://text.pollinations.ai/openai`) — was keyless, now requires
   a wallet key (returns 402). Kept as a fallback if you have one.
4. **Bundled example script** — offline fallback so the pipeline always runs

Set `--provider ollama|ovhcloud|pollinations|example` to force one. Any other free
OpenAI-compatible endpoint works too:
`python demo/plan.py --topic "..." --provider custom \
    --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile`.

## What `make_video.py` does

1. Per scene: synthesize narration with **edge-tts** (keyless), capturing word-boundary
   timings (`boundary="WordBoundary"` — edge-tts defaults to sentence-level, which gives
   no usable word timings for captions).
2. Fetch a free image per scene, in order: **Wikimedia Commons API** (keyless, themed)
   → **Picsum** (random) → ffmpeg gradient fallback.
3. Render each scene as a slow Ken-Burns push (`zoompan`) at the audio's exact duration,
   burning **word-timed captions** with `drawtext` in the same pass.
4. Concat the burnt scene videos (stream copy), mux narration.

## Swapping components

| Need | Free swap |
|---|---|
| Offline / commercial-safe TTS | Kokoro-82M via `remsky/Kokoro-FastAPI` (Apache-2.0) — edit `VOICE` in `make_video.py` |
| Real footage instead of photos | Wikimedia Commons / Archive.org / NASA (no key) or Pexels/Pixabay (free key) |
| AI-generated footage | Render clips with Wan2.2 / LTX-Video on Kaggle's free T4, drop them in, set `"image": "path.mp4"` |
| Background music | ACE-Step (Apache-2.0) or MusicGen (MIT); ffmpeg `amix` with ducking |

## Implementation note: drawtext, not subtitles

Captions are burned with **ffmpeg `drawtext`** (libfreetype) per scene, not the
`subtitles` filter (libass). On this ffmpeg build (8.1.2 gyan, libass enabled),
the `subtitles` filter silently produces no overlay when applied to the
`zoompan` output's `yuvj420p pc bt470bg` color format — the filter runs without
error but draws nothing. `drawtext` reads each chunk from a per-caption text
file and is gated by `enable='between(t,start,end)'`, giving word-timed
captions that always render. Trade-off: captions are rasterised at encode time
(not text streams), so they scale with the export resolution and can't be
re-positioned by the player.
