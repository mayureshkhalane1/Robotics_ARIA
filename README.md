# ARIA: Agent Robotics Intelligence Architecture

A LangGraph-based robotic agent that reasons visually and acts on real-time sensor feedback. Combines local LLMs (Qwen via Ollama), Webots simulation, and a web UI for interactive goal setting.

## Quick Start

### Prerequisites

```bash
# Python 3.10+
python --version

# Webots simulator (download from https://cyberbotics.com)
# or install via homebrew: brew install webots
```

### 1. Install Dependencies

```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv sync --group dev
```

### 2. Start Webots Simulator

```bash
# In a new terminal
./scripts/run_webots.sh
```

**Wait for Webots to fully load** - you'll see:
- The simulation window open
- A robot in the arena
- The status bar showing "Running"

### 3. Start Ollama/Qwen (for LLM-based planning)

```bash
# In another new terminal
./scripts/start_ollama.sh
```

This downloads the Qwen 8B model (~5GB) on first run. Once running, Ollama listens on `http://localhost:11434`.

### 4. Run the Agent

Choose one of these:

**Option A: Web UI (Interactive)**
```bash
uv run python -m src.ui.server
```
Then open http://127.0.0.1:8080 and type goals in the chat box.

**Option B: CLI (Programmatic)**
```bash
uv run python -m src.agent.main \
  --policy ollama \
  --model qwen3:8b \
  --goal "explore the arena and avoid obstacles" \
  --steps 50
```

**Option C: Reactive Policy (No LLM)**
```bash
uv run python -m src.agent.main \
  --policy reactive \
  --goal "move forward and avoid obstacles" \
  --steps 20
```

## Troubleshooting

### "timed out" or "Failed to connect to Webots"

Run the diagnostic:
```bash
uv run python scripts/diagnose_webots.py
```

See [WEBOTS_TROUBLESHOOTING.md](./WEBOTS_TROUBLESHOOTING.md) for detailed fixes.

**Quick checks:**
1. Is Webots window open and showing "Running" (not "Paused")?
2. Is the robot visible in the simulation?
3. Try clicking the Play button (▶️) in Webots

### "Connection refused on localhost:19997"

Webots isn't running. Start it:
```bash
./scripts/run_webots.sh
```

### "No response from Webots after 5s"

Webots is paused. Click Play (▶️) in the Webots window or press SPACE.

## Architecture

```
┌─────────────┐
│   Web UI    │  (browser-based goal setting + live camera)
│ :8080       │
└──────┬──────┘
       │
    HTTP (POST /goal)
       │
       ▼
┌─────────────────────────────────────┐
│  Agent Server                       │
│  - LangGraph loop                   │
│  - Policy selection (reactive/      │
│    ollama/langgraph)                │
│  - State tracking & visualization   │
└──────┬──────────────────────────────┘
       │
    TCP (localhost:19997)
       │
       ▼
┌─────────────────────────────────────┐
│  Webots TCP Controller              │
│  - Robot state (GPS, compass,       │
│    distance sensors)                │
│  - Camera frames (base64)           │
│  - Motor control                    │
└──────────────────────────────────────┘
```

## Agent Policies

1. **reactive** - Simple obstacle avoidance, no LLM
2. **ollama** - Local Qwen LLM with zero-shot ReAct prompting
3. **langgraph** - Full multi-step reasoning with function calls (Claude only)

## Configuration

Edit `.env` to customize:
```bash
# Webots
WEBOTS_HOST=localhost
WEBOTS_PORT=19997
WEBOTS_TIMEOUT=5
WEBOTS_SIM_SPEED=0.1

# Agent
MAX_STEPS=50
STATE_CACHE_SIZE=10

# LLM
LLM_PROVIDER=ollama  # or 'anthropic'
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen3:8b
```

## Running Tests

```bash
uv run pytest tests -v
```

14 tests pass (7 Webots-specific tests skip if simulator not running).

## File Structure

```
src/
├── agent/           # LangGraph agent loop
│   ├── llm.py       # Ollama/Qwen LLM client
│   ├── graph.py     # LangGraph state machine
│   ├── nodes.py     # Agent nodes (sense, plan, act)
│   ├── prompts.py   # LLM prompt templates
│   └── main.py      # CLI entry point
├── ui/              # Web UI server
│   ├── server.py    # Flask app
│   └── static/      # HTML/CSS/JS
├── mcp_server/      # MCP tool server
│   └── server.py    # Webots bridge & tools
├── webots/
│   ├── controllers/ # Robot control script
│   └── worlds/      # .wbt simulation worlds
└── common/
    ├── config.py    # Configuration loader
    └── types.py     # Data types

tests/               # Unit & integration tests
scripts/            # Utility scripts
```

## Key Features

- **Local LLM**: Qwen 8B running via Ollama (no API calls)
- **Visual Reasoning**: Camera feed → base64 encoding → LLM analysis
- **Real-time Feedback**: Sensor data → agent loop every 100ms
- **Interactive Web UI**: Live camera, state log, natural-language goals
- **Safety Fallback**: Reverts to reactive policy if LLM fails
- **Multi-policy Agent**: Reactive, planning, or full reasoning

## Next Steps

- [ ] Implement object detection (YOLO on camera frames)
- [ ] Add multi-robot coordination
- [ ] Extend to real robot hardware (TurtleBot3, etc.)
- [ ] Fine-tune Qwen on domain-specific tasks
- [ ] Add sim-to-real transfer learning

## References

- Webots Docs: https://cyberbotics.com/doc
- LangGraph: https://langchain-ai.github.io/langgraph/
- Ollama: https://ollama.ai
- Qwen Models: https://huggingface.co/Qwen/

