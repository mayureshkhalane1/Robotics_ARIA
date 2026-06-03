"""
Centralized configuration for ARIA system.
Loads from environment variables with sensible defaults.
"""

import os
import subprocess
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _wsl2_gateway() -> Optional[str]:
    """Return the Windows gateway IP when running inside WSL2, else None."""
    try:
        osrelease = Path("/proc/sys/kernel/osrelease").read_text().lower()
        if "microsoft" not in osrelease:
            return None
        out = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=2,
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if "via" in parts:
                return parts[parts.index("via") + 1]
    except Exception:
        pass
    return None


def _default_webots_host() -> str:
    """Return the right host for the Webots TCP connection.

    When running inside WSL2 (NAT networking mode), Webots runs as a Windows
    process and its TCP server is NOT reachable at 'localhost' — we must use
    the Windows gateway IP instead (e.g. 172.20.128.1).
    An explicit WEBOTS_HOST env var always takes priority.
    """
    if env_val := os.getenv("WEBOTS_HOST"):
        return env_val
    gw = _wsl2_gateway()
    return gw if gw else "127.0.0.1"


def _default_ollama_base_url() -> str:
    """Return the right Ollama base URL for the current environment.

    Ollama running on Windows is reachable from WSL2 via the Windows gateway
    IP, not via localhost.  An explicit OLLAMA_BASE_URL env var always wins.
    """
    if env_val := os.getenv("OLLAMA_BASE_URL"):
        return env_val
    gw = _wsl2_gateway()
    return f"http://{gw}:11434" if gw else "http://localhost:11434"


# Step 1: load user's real .env (explicit overrides, if it exists)
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)

# Step 2: resolve WEBOTS_HOST and OLLAMA_BASE_URL *before* loading .env.example,
# which contains dummy 'localhost' defaults that would block WSL2 auto-detection.
WEBOTS_HOST = _default_webots_host()
os.environ.setdefault("WEBOTS_HOST", WEBOTS_HOST)
_ollama_url = _default_ollama_base_url()
os.environ.setdefault("OLLAMA_BASE_URL", _ollama_url)

# Step 3: load .env.example for all other settings (load_dotenv skips already-set vars)
if not _env_path.exists():
    _example_path = PROJECT_ROOT / ".env.example"
    if _example_path.exists():
        load_dotenv(_example_path)

# Webots Connection Configuration
WEBOTS_PORT = int(os.getenv("WEBOTS_PORT", 19997))
WEBOTS_SIM_SPEED = float(os.getenv("WEBOTS_SIM_SPEED", 0.1))
WEBOTS_TIMEOUT = int(os.getenv("WEBOTS_TIMEOUT", 30))  # seconds

# Agent Configuration
MAX_STEPS = int(os.getenv("MAX_STEPS", 50))
STATE_CACHE_SIZE = int(os.getenv("STATE_CACHE_SIZE", 10))
STAGNATION_THRESHOLD = int(os.getenv("STAGNATION_THRESHOLD", 5))
STEP_TIMEOUT = int(os.getenv("STEP_TIMEOUT", 30))  # seconds per LLM call

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # 'anthropic' or 'ollama'
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-latest")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
# Vision model: used ONLY for image description (every 10s)
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava-phi3:latest")
# Reasoning model: used by agent for fast decision-making
OLLAMA_REASONING_MODEL = os.getenv("OLLAMA_REASONING_MODEL", "qwen3:8b")
# Legacy: OLLAMA_MODEL now maps to reasoning model for backward compatibility
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", OLLAMA_REASONING_MODEL)
OLLAMA_VISION_TIMEOUT = int(os.getenv("OLLAMA_VISION_TIMEOUT", 35))
OLLAMA_VISION_NUM_PREDICT = int(os.getenv("OLLAMA_VISION_NUM_PREDICT", 160))
OLLAMA_VISION_IMAGE_MAX_DIM = int(os.getenv("OLLAMA_VISION_IMAGE_MAX_DIM", 640))
OLLAMA_VISION_SAMPLE_INTERVAL = float(os.getenv("OLLAMA_VISION_SAMPLE_INTERVAL", 10.0))

# Project Paths
WEBOTS_WORLDS_PATH = PROJECT_ROOT / "src" / "webots" / "worlds"
WEBOTS_CONTROLLERS_PATH = PROJECT_ROOT / "src" / "webots" / "controllers"
WEBOTS_WORLD_FILE = os.getenv(
    "WEBOTS_WORLD_FILE",
    str(PROJECT_ROOT / "src" / "webots" / "worlds" / "Project" / "worlds" / "break_room.wbt"),
)
LOGS_PATH = PROJECT_ROOT / "logs"
LOGS_PATH.mkdir(exist_ok=True)

# Logging
LOGLEVEL = os.getenv("LOGLEVEL", "INFO")

# Validation
if LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
    print("WARNING: ANTHROPIC_API_KEY not set. Agent will fail to make API calls.")

if LLM_PROVIDER not in ("anthropic", "ollama"):
    raise ValueError(f"Invalid LLM_PROVIDER: {LLM_PROVIDER}. Must be 'anthropic' or 'ollama'.")

print(f"[Config] Loaded configuration:")
print(f"  Webots: {WEBOTS_HOST}:{WEBOTS_PORT} (sim_speed={WEBOTS_SIM_SPEED}x)")
print(f"  Ollama: {OLLAMA_BASE_URL}  vision={OLLAMA_VISION_MODEL}  reasoning={OLLAMA_REASONING_MODEL}")
print(f"  Agent: MAX_STEPS={MAX_STEPS}, STATE_CACHE={STATE_CACHE_SIZE}")
print(f"  LLM: {LLM_PROVIDER} ({ANTHROPIC_MODEL if LLM_PROVIDER == 'anthropic' else OLLAMA_MODEL})")
