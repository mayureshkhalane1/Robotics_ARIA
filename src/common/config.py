"""
Centralized configuration for ARIA system.
Loads from environment variables with sensible defaults.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load from .env file if it exists
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try to load from .env.example as fallback
    env_example_path = Path(__file__).parent.parent.parent / ".env.example"
    if env_example_path.exists():
        load_dotenv(env_example_path)

# Webots Connection Configuration
WEBOTS_HOST = os.getenv("WEBOTS_HOST", "localhost")
WEBOTS_PORT = int(os.getenv("WEBOTS_PORT", 19997))
WEBOTS_SIM_SPEED = float(os.getenv("WEBOTS_SIM_SPEED", 0.1))
WEBOTS_TIMEOUT = int(os.getenv("WEBOTS_TIMEOUT", 5))  # seconds

# Agent Configuration
MAX_STEPS = int(os.getenv("MAX_STEPS", 50))
STATE_CACHE_SIZE = int(os.getenv("STATE_CACHE_SIZE", 10))
STAGNATION_THRESHOLD = int(os.getenv("STAGNATION_THRESHOLD", 5))
STEP_TIMEOUT = int(os.getenv("STEP_TIMEOUT", 30))  # seconds per LLM call

# LLM Configuration
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # 'anthropic' or 'ollama'
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "gpt-4o-mini")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama2")

# Project Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
WEBOTS_WORLDS_PATH = PROJECT_ROOT / "src" / "webots" / "worlds"
WEBOTS_CONTROLLERS_PATH = PROJECT_ROOT / "src" / "webots" / "controllers"
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
print(f"  Agent: MAX_STEPS={MAX_STEPS}, STATE_CACHE={STATE_CACHE_SIZE}")
print(f"  LLM: {LLM_PROVIDER} ({ANTHROPIC_MODEL if LLM_PROVIDER == 'anthropic' else OLLAMA_MODEL})")
