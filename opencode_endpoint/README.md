> Legacy reference only. Source of truth for agent path is flowkit/agent/services/opencode_models.py (fixes responses vs chat/completions routing). See flowkit/agent/api/opencode.py:31.

# OpenCode Endpoint Integration SDK

Standalone Python & TypeScript integration client for **OpenCode AI Zen** models with automated model discovery and reasoning effort detection.

---

## Features

1. **Auto Model Discovery**:
   - Queries OpenCode `/models` endpoint to list all available models.
   - Parses local VS Code configurations (`chatLanguageModels.json`).
   - Automatically tags free models (`--free` flag).
2. **Auto Reasoning Resolver**:
   - Automatically detects whether a model supports reasoning (`xhigh`, `high`, `medium`, `low`, `off`).
   - Automatically defaults Muse Spark models to `xhigh` reasoning effort.
3. **Dual Protocol Routing**:
   - Automatically routes Muse models to the `/responses` endpoint.
   - Automatically routes DeepSeek, Mimo, and standard models to `/chat/completions`.
4. **Zero External Dependencies** (Python standard library only).
5. **Universal Support**: Works in Python, Node.js, Bun, and Vite/Browser projects.

---

## Directory Structure

```
opencode_endpoint/
├── .env                  # Environment variables (API key & base URL)
├── __init__.py           # Python package export
├── client.py             # Core OpenCodeClient implementation
├── models.py             # Model discovery & reasoning resolver
├── cli.py                # Command-line interface tool
├── index.ts              # Full TypeScript/JavaScript SDK
├── test_endpoint.py      # Verification and test script
└── README.md             # Documentation
```

---

## Python Quick Start

### 1. Import and Chat

```python
from opencode_endpoint import OpenCodeClient

client = OpenCodeClient()

# Auto-detects endpoint and uses default 'xhigh' reasoning for Muse Spark
reply = client.chat("Explain forward kinematics in 2 sentences.")
print(reply)
```

### 2. Auto-Fetch Available Models & Reasoning

```python
from opencode_endpoint import OpenCodeClient

client = OpenCodeClient()

# List all free models
free_models = client.list_models(only_free=True)
for m in free_models:
    print(f"{m.id}: default reasoning = {m.default_reasoning}")

# Inspect reasoning options for any model
options = client.get_reasoning_options("muse-spark-1.3-contributor-free")
print(options["supported_tiers"])  # ['xhigh', 'high', 'medium', 'low', 'off']
print(options["default_tier"])     # 'xhigh'
```

### 3. CLI Usage

```bash
# List all models
python -m opencode_endpoint.cli models

# List only free models
python -m opencode_endpoint.cli models --free

# Auto-fetch reasoning options for a model
python -m opencode_endpoint.cli reasoning muse-spark-1.3-contributor-free

# Quick chat query
python -m opencode_endpoint.cli chat "What is inverse kinematics?"

# Launch interactive terminal chat
python -m opencode_endpoint.cli interactive
```

---

## TypeScript / Browser Usage

```typescript
import { OpenCodeClient } from './index';

const client = new OpenCodeClient({
  apiKey: process.env.OPENCODE_API_KEY,
});

// Auto-fetches reasoning and routes to /responses
const response = await client.chat("Hello from TypeScript!");
console.log(response);

// Fetch models
const freeModels = await client.listModels({ onlyFree: true });
console.log(freeModels);
```

### In Browser / Vite Projects
To avoid CORS issues in browser apps, proxy requests in `vite.config.ts`:
```typescript
export default defineConfig({
  server: {
    proxy: {
      '/api/opencode': {
        target: 'https://opencode.ai/zen/v1',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/opencode/, ''),
      },
    },
  },
});
```
The client will automatically use `/api/opencode` when running in the browser!
