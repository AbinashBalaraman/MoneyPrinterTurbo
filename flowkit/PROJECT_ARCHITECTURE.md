# FlowKit & Shorts Directing Engine — Master Unified Architecture

> **Quick Orientation for External LLMs & Autonomous Agents:**  
> This specification provides the complete end-to-end architectural, protocol, and code reference for both **FlowKit** (the Google Flow browser-automated video creation engine) and **Shorts Content Engine** (the agentic episodic script director and continuity tracker), along with the **OpenCode AI Studio** gateway.  
> Any LLM can read this single file to understand how to direct scripts, construct video generation payloads, interact with the local APIs, and chat with terminal agents.

---

## 1. High-Level System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               USER / BROWSER UI                                 │
│  FlowKit Dashboard (React 19 + Vite 8 + Tailwind 4) on http://localhost:5173     │
│  ├── Projects & Scenes Management                                              │
│  ├── Live Video & Asset Gallery                                                │
│  ├── Chrome Extension Worker Status                                            │
│  └── 🌟 Agent Studio (OpenCode Free Models + Reasoning up to xhigh)             │
└────────────┬─────────────────────────────┬───────────────────────────┬──────────┘
             │ Proxy: /api                 │ Proxy: /api/opencode      │ WS: /ws
             ▼                             ▼                           ▼
┌───────────────────────────┐ ┌───────────────────────────┐ ┌─────────────────────┐
│    FlowKit Agent Server   │ │   OpenCode Zen API Gateway│ │ FlowKit WebSocket   │
│    Python FastAPI / Uvicorn│ │   https://opencode.ai/zen │ │ Port 9223 (Chrome   │
│    Port 8100              │ │   Models: muse-spark-1.3  │ │ Extension Worker)   │
│    SQLite (flow_agent.db) │ │   Reasoning: xhigh / high │ │ CDP Bridge          │
└────────────┬──────────────┘ └───────────────────────────┘ └──────────┬──────────┘
             │                                                         │
             │ Dispatches video & still rendering                      │ Dispatches
             ▼                                                         ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     Google Flow (Browser Automation via CDP)                     │
│  - Reference Image Generation (Character / Location entities)                   │
│  - Still Image Generation (16:9 or 9:16)                                        │
│  - Google Veo Video Generation (5-8s per scene beat)                            │
│  - Asset download, upscaling, and post-processing                               │
└─────────────────────────────────────────────────────────────────────────────────┘
             ▲
             │ Directs narrative & feeds scene manifests
┌────────────┴────────────────────────────────────────────────────────────────────┐
│                    Shorts Content Engine (Story Director)                       │
│  Directory: Documents/Abi/Projects/shorts_content_engine                        │
│  ├── Narrative Director: 5-beat retention arc (Hook, Tension, Twist, Cliff)     │
│  ├── Pacing Budgeter: Strict <=10s scenes, 140-160 WPM verbal pace              │
│  ├── S2P Decoupler: Strict separation of character traits vs scene action       │
│  ├── Continuity Ledger: SQLite WAL database tracking cross-episode state       │
│  └── FlowKit Orchestrator: Auto-translates manifests into FlowKit API jobs      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Ports & Network Services Matrix

| Service | Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- |
| **FlowKit Dashboard** | `5173` | HTTP | React Web GUI (Projects, Gallery, Logs, Agent Studio) |
| **FlowKit Agent Server** | `8100` | HTTP / REST | API for Projects, Videos, Scenes, Characters, Requests |
| **FlowKit Extension WS** | `9223` | WebSocket | Real-time command bridge to Chrome Extension / CDP |
| **OpenCode AI Gateway** | `https://opencode.ai/zen/v1` | HTTPS (proxied via `/api/opencode`) | LLM reasoning & script directing (`muse-spark-1.3-contributor-free`) |

---

## 3. Shorts Directing Engine Rules & Constraints

When an LLM generates a video script for this engine, it **MUST** strictly obey these mathematical and narrative rules:

### Rule 1: Scene Duration Limit ($\le 10$ Seconds per Scene)
- Google Flow / Veo generates video in discrete blocks (typically 5–8s per generation).
- **Hard Limit:** No individual scene can exceed **10.0 seconds**.
- An episode of 30–60s total duration must be split into **4 to 6 discrete scenes**.

### Rule 2: 5-Phase Narrative Retention Arc
Every short-form episode follows this psychological engagement structure:
1. **HOOK (0–3s / Scene 0):** Immediate sensory impact, visual anomaly, high-stakes question. No slow introductory pans.
2. **RISING_TENSION (3–12s / Scene 1):** Discovery, escalating problem, physical movement.
3. **COMPLICATION (12–25s / Scene 2–3):** Unexpected barrier, failure, or sensory shift.
4. **CLIMAX / TWIST (25–40s / Scene 4):** Dramatic revelation, peak action, emotional zenith.
5. **CLIFFHANGER / LOOP (40–50s / Scene 5):** Unresolved mystery that seamlessly loops back to Scene 0.

### Rule 3: Scene-to-Prompt (S2P) Decoupling (Crucial for Google Flow)
- **Reference Image Prompts:** Character visual traits (face, clothing, body, colors) belong **ONLY** in the Character Entity reference prompt.
- **Scene Action Prompts:** Must **NEVER** restate character physical traits (e.g., do NOT say "old weathered farmer with grey beard walks"). Restating traits pollutes the visual embedding and causes character deformation in Veo.
- **Correct Action Prompt:** `"Arthur walks toward the glowing well, muddy boots stepping on dry soil, dramatic low-angle cinematic lighting."`

### Rule 4: Pacing & Word Count (140–160 WPM)
- Narrator word count per scene = $\text{Duration (seconds)} \times \frac{150}{60} = \text{Duration} \times 2.5\text{ words}$.
- A 6-second scene can have at most $15$ words of narration/dialogue.

---

## 4. FlowKit REST API Contracts (`http://127.0.0.1:8100/api`)

### 1. Create Project
- **POST** `/api/projects`
```json
{
  "name": "Arthur & Rusty: The Whispering Earth",
  "description": "Episode 1: The Hollow Beneath",
  "story": "A humble farmer and his loyal golden retriever discover an ancient secret beneath their drought-stricken field.",
  "language": "en"
}
```
*Returns:* `{ "id": "proj_uuid", "name": "...", ... }`

### 2. Register Characters / Entities
- **POST** `/api/characters`
```json
{
  "name": "Arthur",
  "entity_type": "character",
  "description": "Weathered elderly farmer with silver-grey stubble and gentle blue eyes, wearing worn brown canvas overalls and blue flannel shirt.",
  "image_prompt": "Cinematic portrait of Arthur, weathered 62-year-old farmer, silver stubble, gentle blue eyes, worn brown canvas work shirt, natural morning rim light, photorealistic, 8k"
}
```

### 3. Create Video Entry
- **POST** `/api/videos`
```json
{
  "project_id": "proj_uuid",
  "title": "Episode 01 - The Hollow Beneath",
  "description": "Premiere episode of the Whispering Earth arc"
}
```
*Returns:* `{ "id": "vid_uuid", ... }`

### 4. Create Scenes
- **POST** `/api/scenes`
```json
{
  "video_id": "vid_uuid",
  "display_order": 0,
  "prompt": "Arthur stands frozen at sunrise, staring at a sudden sinkhole in the parched earth.",
  "image_prompt": "Cinematic wide shot, sunrise over dry parched soil, Arthur standing near sudden dark fissure, mist rising from ground, anamorphic lens, hyperrealistic",
  "video_prompt": "0-3s: camera slow push toward dark ground fissure, dust particles drifting; 3-6s: low angle showing Arthur frozen in shock",
  "character_names": "[\"Arthur\", \"Rusty\"]",
  "narrator_text": "The dry earth had not spoken in thirty years. Until this morning.",
  "duration": 6.0
}
```

### 5. Enqueue Rendering Requests
- **POST** `/api/requests`
```json
{
  "project_id": "proj_uuid",
  "video_id": "vid_uuid",
  "scene_id": "scene_uuid",
  "type": "GENERATE_VIDEO",
  "orientation": "VERTICAL"
}
```

---

## 5. OpenCode AI Studio & Reasoning Integration

The dashboard features an integrated AI Director powered by **OpenCode free tier models**:

### Available Free Models:
1. `muse-spark-1.3-contributor-free` (Default, Meta, Supports `xhigh`, `high`, `medium`, `low`, `off`)
2. `muse-spark-1.2-contributor-free` (Meta, Supports `xhigh`, `high`, `medium`, `low`, `off`)
3. `deepseek-v4-flash-free` (DeepSeek, Supports `high`, `medium`, `off`)
4. `mimo-v2.5-free` (Mimo, Supports `high`, `medium`, `off`)
5. `ling-3.0-flash-fin-free` (Ling, Speed-optimized)
6. `nemotron-3-ultra-free` (NVIDIA Nemotron)
7. `nemotron-3.5-lightning-free` (NVIDIA Nemotron Lightning)

### OpenCode API Protocol:
- **Base URL:** `https://opencode.ai/zen/v1` (proxied in browser to `/api/opencode`)
- **API Key:** supplied at runtime via `OPENCODE_API_KEY`. It is never committed
  and never compiled into the dashboard bundle; the agent injects it server-side.
- **Routing:**
  - `muse-spark` models use **POST** `/responses`:
    ```json
    {
      "model": "muse-spark-1.3-contributor-free",
      "input": [{ "role": "user", "content": "..." }],
      "reasoning": { "effort": "xhigh" }
    }
    ```
    Reasoning trace is returned in `output[0].encrypted_content` or `output[0].summary` and token usage in `usage.output_tokens_details.reasoning_tokens`.
  - Standard models use **POST** `/chat/completions`:
    ```json
    {
      "model": "deepseek-v4-flash-free",
      "messages": [{ "role": "user", "content": "..." }],
      "reasoningEffort": "high"
    }
    ```

---

## 6. Terminal Agent Bridge & CLI Workflows

Autonomous coding agents (such as Antigravity) and developers run tasks directly using the following commands:

```bash
# 1. Start FlowKit Server (Port 8100 & WebSocket 9223)
cd "C:/Users/SATHYA TRADERS/Documents/Abi/Projects/flowkit"
.venv/Scripts/python -m agent.main

# 2. Run FlowKit Dashboard (Port 5173)
cd "C:/Users/SATHYA TRADERS/Documents/Abi/Projects/flowkit/dashboard"
npm run dev

# 3. Direct Arthur & Rusty Premiere Episode (<10s scenes)
cd "C:/Users/SATHYA TRADERS/Documents/Abi/Projects/shorts_content_engine"
python scripts/create_farmer_episode.py

# 4. Validate All FlowKit Payloads
python scripts/validate_flowkit_payloads.py

# 5. Direct New Episode via Shorts CLI
python -m src.cli direct-episode --prompt "Arthur investigates ancient glowing runes inside the well" --duration 45

# 6. Check Episode Continuity Ledger
python -m src.cli status
```

---

## 7. Directing Cheat-Sheet for LLMs

Whenever asked to write an episode script:
1. Structure exactly **4 to 6 scenes**, each between **5.0s and 10.0s**. Total duration = **30s to 55s**.
2. Keep narration under **25 words** per scene.
3. Decouple visual action from character identity: use character names only, never biometric descriptions in scene prompts.
4. Output cleanly formatted JSON matching the Episode Manifest schema so the FlowKit Dispatcher can deploy it in 1 click.
