# ARIA: Agentic Robot Intelligence Architecture

A fully decoupled AI system for autonomous robot control using LangGraph, MCP, and zero-shot LLMs. The robot reasons about its environment and decides actions without task-specific training.

## Project Structure

```
ARIA/
├── src/
│   ├── common/
│   │   ├── config.py       # Centralized configuration
│   │   └── types.py        # Shared data models
│   ├── webots/
│   │   ├── worlds/         # Webots .wbt simulation files
│   │   └── controllers/
│   │       └── tcp_controller.py  # Robot controller + TCP server
│   ├── mcp_server/
│   │   ├── server.py       # MCP bridge to Webots
│   │   └── tools.py        # Tool definitions
│   └── agent/
│       ├── graph.py        # LangGraph state machine
│       ├── nodes.py        # Sense/Plan/Act/Evaluate nodes
│       ├── prompts.py      # System prompts for ablation
│       └── main.py         # Agent CLI entry point
├── tests/
│   ├── test_webots_connection.py
│   ├── test_mcp_tools.py
│   └── test_agent_integration.py
├── benchmarks/
│   ├── tasks.py            # Task definitions
│   └── run_benchmark.py    # Benchmark harness
├── requirements.txt        # Python dependencies
├── .env.example            # Configuration template
└── plans/                  # Project planning docs
```

## Quick Start

### 1. Install Dependencies with uv

```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv sync --group dev
```

This project uses `pyproject.toml` plus tracked `uv.lock` as the dependency source of truth. `requirements.txt` is kept only as a legacy/reference file.

### 2. Set Up Configuration

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-...
```

### 3. Set Up Webots

1. **Open Webots** and create a new world or use an existing one
2. **Add a robot** (Pioneer 3-DX is recommended)
3. **Add sensors:**
   - 8× Distance Sensors (named: `distance sensor 0`, `distance sensor 1`, etc.)
   - GPS
   - Compass
4. **Create a controller** and paste the contents of `src/webots/controllers/tcp_controller.py`
5. **Run the simulation** — you should see:
   ```
   [Webots] Robot server initialized on port 19997
   ```

### 4. Test Webots Connection

```bash
uv run pytest tests/test_webots_connection.py -v
```

(Requires Webots simulator running with tcp_controller.py as controller)

### 5. Build MCP Server

The MCP server bridges the agent to Webots. Start with:

```bash
uv run python src/mcp_server/server.py
```

### 6. Run the Agent

```bash
uv run python -m src.agent.main --goal "Navigate to the target" --steps 50
```

## System Architecture

### Sense → Plan → Act → Evaluate Loop

```
┌────────────────────────────────────────────────────────────────┐
│                  LangGraph Agent                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ SENSE NODE   │→ │ PLAN NODE    │→ │  ACT NODE    │→ ...    │
│  │ Read state   │  │ LLM decides  │  │ Execute via  │         │
│  │ via MCP      │  │ next action  │  │ MCP tools    │         │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└────────────────────────────────────────────────────────────────┘
           ↓                                        ↑
┌────────────────────────────────────────────────────────────────┐
│              MCP Server (Tool Bridge)                          │
│  Tools: get_state | execute_action | get_objects | validate   │
└────────────────────────────────────────────────────────────────┘
           ↓                                        ↑
┌────────────────────────────────────────────────────────────────┐
│           Webots Simulator (TCP Server)                        │
│  ├─ Robot: Wheels, sensors (proximity, GPS, compass)          │
│  ├─ World: Obstacles, targets                                 │
│  └─ Physics Engine: Accurate motion simulation                │
└────────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Webots TCP Controller (`src/webots/controllers/tcp_controller.py`)

Runs **inside** Webots. Listens for commands on TCP port 19997:

**Commands:**
- `{"cmd": "get_state"}` → Current sensor readings
- `{"cmd": "execute", "action": {...}}` → Execute action
- `{"cmd": "stop"}` → Stop all motors

### 2. MCP Server (`src/mcp_server/server.py`)

Exposes Webots as callable tools to the agent:

**Tools:**
- `get_state()` → Robot state (position, orientation, sensors)
- `execute_action(action)` → Move, turn, stop, grab
- `get_objects()` → Object detection (not yet implemented)

### 3. LangGraph Agent (`src/agent/graph.py`)

State machine orchestrating the agent loop:

- **Sense:** Read robot state via MCP
- **Plan:** Use LLM to decide next action
- **Act:** Execute action via MCP
- **Evaluate:** Check goal success or stuck states

### 4. Data Models (`src/common/types.py`)

Shared structures:
- `RobotState` — Sensor readings
- `Action` — Robot action + reasoning
- `AgentState` — Persistent agent state across loop

## Configuration

Edit `.env` to customize:

```bash
# LLM Backend
LLM_PROVIDER=anthropic          # 'anthropic' or 'ollama'
ANTHROPIC_API_KEY=sk-...
ANTHROPIC_MODEL=gpt-4o-mini

# Webots Connection
WEBOTS_HOST=localhost
WEBOTS_PORT=19997
WEBOTS_SIM_SPEED=0.1            # Sim speed factor for LLM latency

# Agent Behavior
MAX_STEPS=50                    # Max planning steps
STATE_CACHE_SIZE=10             # Rolling context window
STAGNATION_THRESHOLD=5          # Steps before "stuck" detection
```

## Testing

### Unit Tests

Test individual components in isolation:

```bash
# Test Webots connection
uv run pytest tests/test_webots_connection.py -v

# Test MCP tools
uv run pytest tests/test_mcp_tools.py -v

# Test agent integration
uv run pytest tests/test_agent_integration.py -v
```

### Integration Tests

Test the full pipeline:

```bash
python src/agent/main.py --goal "Move forward 2 meters" --demo
```

### Benchmarking

Run task suite and measure success rates:

```bash
python benchmarks/run_benchmark.py --tasks navigate,avoid --runs 5
```

## Challenges & Mitigations

### 1. LLM Latency (0.5–2s per step)
- **Mitigation:** Slow simulation speed (0.1x), cache state descriptions

### 2. Spatial Reasoning Drift
- **Mitigation:** Rolling context window (last 10 states), absolute coordinates

### 3. Prompt Sensitivity
- **Mitigation:** Systematic ablation (raw vs CoT vs structured)

### 4. Stuck State Loops
- **Mitigation:** Stagnation detector, force re-plan after N identical states

### 5. Local LLM Quality Gap
- **Mitigation:** Benchmark Ollama vs GPT-4o-mini

## Prompting Strategies

The system supports multiple prompting approaches for ablation:

1. **Raw** — Direct instruction ("Move forward")
2. **CoT (Chain-of-Thought)** — Structured reasoning steps
3. **Structured** — Enforced JSON output format

Switch via `src/agent/prompts.py`.

## Research Foundation

Based on: **"Leveraging Large Language Models for Autonomous Robotic Mapping and Navigation"** (Pascual Espada et al., 2025)

Key insight: Zero-shot LLM-based robot planning is feasible with proper state representation and action abstraction.

## Development Timeline

- **Weeks 1–3:** Webots + TCP controller (Phase 2)
- **Weeks 3–4:** MCP server (Phase 3)
- **Weeks 4–6:** LangGraph agent (Phase 4)
- **Weeks 6–8:** Integration + benchmarking (Phase 5)
- **Weeks 8–9:** Ablation studies + demo (Phase 6)

## Demo Day Deliverables

**Minimum:**
- ✓ Working pipeline (Webots + MCP + LangGraph)
- ✓ Robot completes ≥3 distinct tasks (navigate, fetch, avoid)
- ✓ Live demo with real-time reasoning display
- ✓ Benchmark: success rate across 10+ task runs
- ✓ Comparison: GPT-4o-mini vs Ollama

**Stretch:**
- Failure recovery (self-correction)
- Multi-step goal decomposition
- Prompt strategy ablation with statistics
- Interactive audience goal input during demo
- Live reasoning trace panel

## Debugging

### Check Webots Connection

```bash
python -c "
import socket, json
s = socket.socket()
s.connect(('localhost', 19997))
s.sendall(b'{\"cmd\": \"get_state\"}\n')
print(s.recv(1024).decode())
"
```

### View Agent Logs

```bash
tail -f logs/agent.log
```

### Enable Debug Mode

```bash
LOGLEVEL=DEBUG python src/agent/main.py
```

## Contributing

- **Webots world design** → `src/webots/worlds/`
- **Sensor/actuator interface** → `src/webots/controllers/tcp_controller.py`
- **LLM tool exposure** → `src/mcp_server/`
- **Agent logic** → `src/agent/nodes.py`
- **Task benchmarks** → `benchmarks/tasks.py`

## References

- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [MCP Spec](https://modelcontextprotocol.io/)
- [Webots Docs](https://cyberbotics.com/doc/guide/index.html)
- [Anthropic Claude API](https://docs.anthropic.com/)

---

**Team:** Mayureshkhalane (Webots/MCP/Agent), Ntolgka (MCP Architect), Pruthvish (Agent Developer)  
**Course:** Robotics 2026, Leiden University LIACS  
**Project:** ARIA — Agentic Robot Intelligence Architecture
