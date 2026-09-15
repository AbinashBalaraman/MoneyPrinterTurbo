"""Configuration constants."""
import json
import os
from pathlib import Path


# ─── .env loading ────────────────────────────────────────────
# This is a consolidated checkout: the shared secrets file lives at the
# repository root, one level above this package. Everything below reads
# os.environ at import time, so the files must be folded in first.
#
# Precedence, highest first: a variable already present in the real environment
# (an explicit `export`, a container env, a systemd unit) always wins and is
# never overwritten. That keeps `OPENCODE_API_KEY=x python -m agent` working as
# an override and stops a stale file from silently beating a deliberate value.
#
# The parser is deliberately tiny and stdlib-only: no quoting tricks, no
# multi-line values, no command substitution. Anything fancier would be a
# liability in a secrets file.
def _load_env_files() -> None:
    package_dir = Path(__file__).resolve().parent.parent  # …/flowkit
    for candidate in (package_dir / ".env", package_dir.parent / ".env"):
        if not candidate.is_file():
            continue
        try:
            raw_lines = candidate.read_text(encoding="utf-8").splitlines()
        except OSError:
            # An unreadable secrets file must not stop the app from starting;
            # the affected integrations report "not configured" instead.
            continue
        for raw in raw_lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            if not key or key in os.environ:
                continue
            value = value.strip()
            # Strip one layer of matching quotes if present. Values in the
            # current file are unquoted, but hand-edited files often are not.
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ[key] = value


_load_env_files()

# ─── Paths ───────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("FLOW_AGENT_DIR", Path(__file__).parent.parent))
DB_PATH = BASE_DIR / "flow_agent.db"

# ─── API Server ──────────────────────────────────────────────
API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8100"))

# ─── WebSocket Server (extension connects here) ─────────────
WS_HOST = os.environ.get("WS_HOST", "127.0.0.1")
WS_PORT = int(os.environ.get("WS_PORT", "9223"))

# ─── Google Flow API ────────────────────────────────────────
# Legacy REST host. Flow moved to flow.google.com in September 2026 and stopped
# minting the `Bearer ya29.…` this host needs, so these are only reachable with
# USE_BATCH_RPC=0 on a browser profile that still has an old token.
GOOGLE_FLOW_API = "https://aisandbox-pa.googleapis.com"
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "REDACTED_GOOGLE_API_KEY")
RECAPTCHA_SITE_KEY = os.environ.get("RECAPTCHA_SITE_KEY", "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV")

# ─── Flow batchexecute (the current path) ───────────────────
# Every call is signed in the page with the session cookie plus a per-page `at`
# token, so the extension runs it inside a signed-in flow.google.com tab. Set
# USE_BATCH_RPC=0 only to fall back to the dead REST path for a post-mortem.
USE_BATCH_RPC = os.environ.get("USE_BATCH_RPC", "1") == "1"

# The Flow project every RPC is scoped to. Project creation went with the old
# labs.google tRPC endpoint, so a project is made once in the Flow UI and its
# uuid pinned here; POST /api/projects falls back to it when no id is given.
FLOW_PROJECT_ID = os.environ.get("FLOW_PROJECT_ID", "").strip() or "f5ce611c-3f4c-471d-8dcf-c26059defa3f"

# Capabilities whose payloads were never captured off the new UI (4K upscale,
# reference-to-video, start+end-frame chaining) fail loudly by default. With
# this on, the two that have a sane fallback degrade instead: chaining and r2v
# both drop to plain i2v off the start frame. Upscale has no fallback.
FLOW_ALLOW_DEGRADED = os.environ.get("FLOW_ALLOW_DEGRADED", "0") == "1"

# The tier no longer picks a model — aspect is its own slot and the model names
# are fixed — so it is only carried for the DB column and the dashboard.
DEFAULT_PAYGATE_TIER = os.environ.get("DEFAULT_PAYGATE_TIER", "PAYGATE_TIER_TWO")

# TinyFish web search (free tier). Endpoint: GET https://api.search.tinyfish.ai
TINYFISH_API_KEY = os.environ.get("TINYFISH_API_KEY", "").strip()
TINYFISH_SEARCH_URL = os.environ.get(
    "TINYFISH_SEARCH_URL", "https://api.search.tinyfish.ai"
).strip()

# ─── Operations catalog ──────────────────────────────────────
# Whether the assistant may run operations that cost money or destroy data.
# Opt-in, deliberately: this pipeline is built to run unattended, so the failure
# mode of a wrong default is a queue of paid generations nobody asked for.
AGENT_ALLOW_SPEND = os.environ.get("AGENT_ALLOW_SPEND", "0") == "1"

# The pipeline and the assembly engine have separate virtualenvs, so a CLI
# wrapper cannot just use sys.executable. Overridable for a fresh clone; the
# defaults are this machine's layout.
_HERE = Path(__file__).resolve()
_WORKSPACE = _HERE.parents[2]  # AutoShorts/

PIPELINE_PYTHON = os.environ.get(
    "PIPELINE_PYTHON",
    r"C:\Users\SATHYA TRADERS\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe",
).strip()
ASSEMBLY_PYTHON = os.environ.get(
    "ASSEMBLY_PYTHON", str(_WORKSPACE / ".venv" / "Scripts" / "python.exe")
).strip()
PIPELINE_ROOT = os.environ.get(
    "PIPELINE_ROOT", str(_WORKSPACE / "shorts_content_engine")
).strip()

# Fonts bundled with the repo, used when ffmpeg needs one explicitly.
# `drawtext` otherwise asks fontconfig, which has no config on a bare Windows
# box — so frame extraction fails with "Fontconfig error: Cannot load default
# config file". Pointing at a real file removes the dependency entirely.
FONT_DIR = os.environ.get("FONT_DIR", str(_WORKSPACE / "resource" / "fonts")).strip()

# ─── Worker ──────────────────────────────────────────────────
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
VIDEO_POLL_INTERVAL = int(os.environ.get("VIDEO_POLL_INTERVAL", "10"))  # polling interval for video/upscale status
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
VIDEO_POLL_TIMEOUT = int(os.environ.get("VIDEO_POLL_TIMEOUT", "420"))
API_COOLDOWN = int(os.environ.get("API_COOLDOWN", "10"))  # seconds between API calls (anti-spam)
MAX_CONCURRENT_REQUESTS = int(os.environ.get("MAX_CONCURRENT_REQUESTS", "5"))  # Google Flow max parallel requests
STALE_PROCESSING_TIMEOUT = int(os.environ.get("STALE_PROCESSING_TIMEOUT", "600"))  # 10 min

# ─── Model Keys (loaded from models.json for easy updates) ──
_MODELS_FILE = Path(__file__).parent / "models.json"
with open(_MODELS_FILE) as _f:
    _MODELS = json.load(_f)

VIDEO_MODELS = _MODELS["video_models"]
UPSCALE_MODELS = _MODELS["upscale_models"]
IMAGE_MODELS = _MODELS["image_models"]
# Nickname from image_models. The batch path accepts GEM_PIX_2 (Nano Banana Pro)
# and NARWHAL (Banana 2) and rejects everything else.
DEFAULT_IMAGE_MODEL = _MODELS.get("default_image_model", "NANO_BANANA_PRO")

# ─── API Endpoints ───────────────────────────────────────────
ENDPOINTS = {
    "generate_images": "/v1/projects/{project_id}/flowMedia:batchGenerateImages",
    "generate_video": "/v1/video:batchAsyncGenerateVideoStartImage",
    "generate_video_start_end": "/v1/video:batchAsyncGenerateVideoStartAndEndImage",
    "generate_video_references": "/v1/video:batchAsyncGenerateVideoReferenceImages",
    "upscale_video": "/v1/video:batchAsyncGenerateVideoUpsampleVideo",
    "upscale_image": "/v1/flow/upsampleImage",
    "upload_image": "/v1/flow/uploadImage",
    "check_video_status": "/v1/video:batchCheckAsyncVideoGenerationStatus",
    "get_credits": "/v1/credits",
    "get_media": "/v1/media/{media_id}",
}

# ─── Output Directories ─────────────────────────────────────
OUTPUT_DIR = BASE_DIR / "output"
SHARED_OUTPUT_DIR = OUTPUT_DIR / "_shared"
TTS_TEMPLATES_DIR = SHARED_OUTPUT_DIR / "tts_templates"
MUSIC_OUTPUT_DIR = SHARED_OUTPUT_DIR / "music"

# ─── TTS (OmniVoice) ─────────────────────────────────────────
TTS_MODEL = os.environ.get("TTS_MODEL", "k2-fsa/OmniVoice")
TTS_DEVICE = os.environ.get("TTS_DEVICE", "cpu")  # MPS produces gibberish; CPU+fp32 works
TTS_SAMPLE_RATE = int(os.environ.get("TTS_SAMPLE_RATE", "24000"))

# ─── Review / Claude Vision ──────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
REVIEW_MODEL = os.environ.get("REVIEW_MODEL", "claude-haiku-4-5-20251001")
REVIEW_FPS_LIGHT = float(os.environ.get("REVIEW_FPS_LIGHT", "4"))
REVIEW_FPS_DEEP = float(os.environ.get("REVIEW_FPS_DEEP", "8"))
REVIEW_MAX_FRAMES = int(os.environ.get("REVIEW_MAX_FRAMES", "64"))
REVIEW_SHEET_COLS = int(os.environ.get("REVIEW_SHEET_COLS", "3"))
REVIEW_SHEET_ROWS = int(os.environ.get("REVIEW_SHEET_ROWS", "3"))

# ─── OpenCode (Agent Studio) ─────────────────────────────────
# Server-side only. This key must never be sent to the browser: it used to be
# compiled into the dashboard bundle as DEFAULT_OPENCODE_KEY, which put a live
# credential in any JS a visitor could read.
#
# No default on purpose -- an empty value makes the UI say "not configured"
# rather than quietly authenticating as whoever last committed a key.
OPENCODE_API_KEY = os.environ.get("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_TIMEOUT = float(os.environ.get("OPENCODE_TIMEOUT", "120"))
# How long a fetched model list is trusted before it is refreshed.
OPENCODE_MODELS_TTL = float(os.environ.get("OPENCODE_MODELS_TTL", "300"))

# ─── CLI Providers (video review vision analysis) ────────────
_PROVIDERS_FILE = Path(__file__).parent / "providers.json"
with open(_PROVIDERS_FILE) as _pvf:
    CLI_PROVIDERS = json.load(_pvf)  # mutable dict, hot-reloaded like VIDEO_MODELS
REVIEW_CLI_TIMEOUT_S = float(os.environ.get("REVIEW_CLI_TIMEOUT_S", "120"))

# ─── Suno (Music Generation) — sunoapi.org ──────────────────
def _load_suno_key() -> str:
    """Load Suno API key: env var first, then channel_rules.json fallback."""
    key = os.environ.get("SUNO_API_KEY", "")
    if key:
        return key
    channels_dir = BASE_DIR / "youtube" / "channels"
    if channels_dir.exists():
        for rules_file in channels_dir.glob("*/channel_rules.json"):
            try:
                rules = json.loads(rules_file.read_text())
                key = rules.get("api_keys", {}).get("suno", "")
                if key:
                    return key
            except (json.JSONDecodeError, OSError):
                continue
    return ""

SUNO_API_KEY = _load_suno_key()
SUNO_BASE_URL = os.environ.get("SUNO_BASE_URL", "https://api.sunoapi.org")
SUNO_MODEL = os.environ.get("SUNO_MODEL", "V4")
SUNO_CALLBACK_URL = os.environ.get("SUNO_CALLBACK_URL", f"http://{API_HOST}:{API_PORT}/api/music/callback")
SUNO_POLL_INTERVAL = int(os.environ.get("SUNO_POLL_INTERVAL", "5"))
SUNO_POLL_TIMEOUT = int(os.environ.get("SUNO_POLL_TIMEOUT", "600"))

# ─── Header Randomization Pools ─────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
]

CHROME_VERSIONS = [
    '"Google Chrome";v="109", "Chromium";v="109"',
    '"Google Chrome";v="110", "Chromium";v="110"',
    '"Google Chrome";v="111", "Chromium";v="111"',
    '"Google Chrome";v="113", "Not-A.Brand";v="24"',
    '"Google Chrome";v="120", "Not-A.Brand";v="24"',
    '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
]

BROWSER_VALIDATIONS = [
    "SgDQo8mvrGRdD61Pwo8wyWVgYgs=",
]

CLIENT_DATA = [
    "CKi1yQEIh7bJAQiktskBCKmdygEIvorLAQiUocsBCIagzQEYv6nKARjRp88BGKqwzwE=",
]
