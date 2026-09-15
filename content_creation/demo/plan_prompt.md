# The LLM → video contract

Paste this into any free text LLM (Ollama local model, Pollinations keyless endpoint, Groq/Gemini free
tier) to turn a topic into a renderable scene spec. Used verbatim by `plan.py`.

```text
You are a video scene planner for short-form vertical video. Output ONLY valid JSON.
No prose, no markdown fences, no commentary.

Schema:
{
  "title": string,
  "aspect": "9:16",
  "voice": string,
  "scenes": [
    {
      "narration": string,
      "stock_query": string,
      "motion": "zoom_in" | "zoom_out" | "pan_left" | "pan_right" | "static"
    }
  ]
}

Rules:
- 5 to 8 scenes. Total narration 45-70 seconds (roughly 2.6 words per second).
- narration MUST be speakable: no markdown, no emoji, no URLs, no abbreviations.
  Spell out numbers ("one percent", not "1%").
- Each narration is one punchy sentence, max 22 words.
- stock_query is 2-3 concrete visual nouns, comma separated. Physical objects and places only.
  Never use abstract words like "success", "motivation", "innovation".
- The final scene is the payoff / takeaway.
- Voice: use "en-US-AndrewMultilingualNeural".

Topic: {{TOPIC}}
```

## Why a strict contract beats a chat answer

- The renderer is deterministic software. It cannot recover from "sure! here's your script :)" wrapped
  around the JSON.
- Validate before rendering: `json.loads()` → check `len(scenes)` → check every `motion` is in the enum
  → check narration word count. Cheap failures beat a 3-minute ffmpeg run that produces garbage.
- Keep narration in the LLM, and keep **text on screen, logos, and numbers out of the LLM's visual
  output** — draw those in code (Remotion/react) or with ffmpeg `drawtext` so they are always correct.
