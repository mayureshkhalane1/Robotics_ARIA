# ARIA Project Status

**Last Updated:** 2026-04-10  
**Phase:** Scaffolding (Phase 1) ✓ Complete  
**Overall Progress:** 20% (Scaffolding + Basic Infrastructure)

---

## ✓ Phase 1: Project Scaffolding (COMPLETE)

### Completed:
- [x] Directory structure created
  - `src/{common,webots,mcp_server,agent}`
  - `tests/`, `benchmarks/`, `plans/`
  
- [x] Core data models (`src/common/types.py`)
  - `RobotState` — sensor readings
  - `Action` — robot actions + reasoning
  - `ActionType` — enum for action types
  - `AgentState` — persistent state across loop iterations

- [x] Centralized configuration (`src/common/config.py`)
  - Loads from `.env` with sensible defaults
  - Webots connection settings
  - LLM provider configuration
  - Agent parameters (MAX_STEPS, STATE_CACHE_SIZE, etc.)

- [x] Webots TCP Controller (`src/webots/controllers/tcp_controller.py`)
  - Fully implemented robot server
  - TCP socket listening on port 19997
  - Commands: `get_state`, `execute_action`, `stop`
  - Motor control: move, turn, stop
  - Sensor integration: proximity, GPS, compass
  - Error handling and connection management

- [x] MCP Server Bridge (`src/mcp_server/server.py`)
  - WebotsBridge class for TCP communication
  - 5 MCP tools:
    - `get_state()` — robot state retrieval
    - `execute_action()` — action execution
    - `stop()` — emergency stop
    - `get_objects()` — object detection (stub)
    - `validate_action()` — action validation
  - Proper error handling and logging

- [x] Test Framework (`tests/test_webots_connection.py`)
  - TCP connection tests
  - State retrieval tests
  - Action execution tests
  - Error handling tests

- [x] Documentation
  - `README.md` — comprehensive project guide
  - `.env.example` — configuration template
  - `STATUS.md` — this file

### Verified:
- ✓ All Python modules import successfully
- ✓ Configuration loads from environment
- ✓ Data models work correctly
- ✓ MCP server structure is sound

---

## ⏳ Phase 2: Webots Integration (Next)

### TODO:
- [ ] Create Webots world file (`.wbt`)
  - Import or create robot model
  - Add 8× distance sensors
  - Add GPS and compass
  - Add obstacles and targets
  - Add optional camera

- [ ] Place TCP controller in Webots
  - Create controller node
  - Copy tcp_controller.py content
  - Configure motor/sensor names to match world

- [ ] Test Webots connection
  - Run: `uv run pytest tests/test_webots_connection.py`
  - Verify TCP handshake works
  - Verify sensor reads work
  - Verify action execution works

### Timeline: Weeks 2–3

### Critical Steps:
1. **Create world file** in `src/webots/worlds/arena.wbt`
   - Use Webots native editor
   - Export as .wbt file
   
2. **Update controller names** in `tcp_controller.py` if needed
   - Match motor names: "left wheel motor", "right wheel motor"
   - Match sensor names: "distance sensor 0"–"distance sensor 7"
   - Match other devices: "gps", "compass", "camera"

3. **Run simulation and verify** port 19997 listens
   ```
   [Webots] Robot server initialized on port 19997
   ```

---

## ⏳ Phase 3: MCP Server (Weeks 3–4)

### TODO:
- [ ] Test MCP server against Webots
  - Run: `python src/mcp_server/server.py`
  - Verify tools are callable
  - Verify state retrieval works
  - Verify actions are executed

- [ ] Implement object detection (get_objects tool)
  - Use Webots world API or camera input
  - Return object positions and types

- [ ] Add retry logic and connection pooling
  - Handle dropped TCP connections
  - Auto-reconnect on failure

### Timeline: Weeks 3–4

---

## ⏳ Phase 4: LangGraph Agent (Weeks 4–6)

### TODO:
- [ ] Implement `src/agent/graph.py`
  - StateGraph for sense → plan → act → evaluate
  - Conditional edges for success/loop

- [ ] Implement `src/agent/nodes.py`
  - Sense node: read state via MCP
  - Plan node: LLM decides next action
  - Act node: execute action via MCP
  - Evaluate node: check success/stuck states

- [ ] Implement `src/agent/prompts.py`
  - Raw prompting strategy
  - Chain-of-thought (CoT) strategy
  - Structured output strategy

- [ ] Implement `src/agent/main.py`
  - CLI entry point for agent
  - Goal setting and step limit
  - Result reporting

### Timeline: Weeks 4–6

---

## ⏳ Phase 5: Integration & Benchmarking (Weeks 6–8)

### TODO:
- [ ] Create task definitions (`benchmarks/tasks.py`)
  - Navigate to target
  - Avoid obstacles
  - Fetch object
  - 2+ additional tasks

- [ ] Create benchmark runner (`benchmarks/run_benchmark.py`)
  - Run tasks multiple times
  - Measure success rates
  - Generate results CSV

- [ ] Full pipeline testing
  - Agent + MCP + Webots integration
  - End-to-end test with 5+ runs
  - Success rate measurement

### Timeline: Weeks 6–8

---

## ⏳ Phase 6: Experimentation & Ablation (Weeks 8–9)

### TODO:
- [ ] Prompt strategy ablation
  - Compare raw vs CoT vs structured
  - Measure success rate variance
  - Document findings

- [ ] LLM backend comparison
  - GPT-4o-mini (baseline)
  - Ollama Llama 3 (local)
  - Measure latency and quality gap

- [ ] Challenge mitigation testing
  - LLM latency: vary sim_speed
  - Spatial reasoning: test with/without context window
  - Prompt sensitivity: measure variance
  - Stuck states: test stagnation detector

### Timeline: Weeks 8–9

---

## 🎯 Demo Day Deliverables

### Minimum (REQUIRED)
- [ ] Working ARIA pipeline (Webots + MCP + LangGraph)
- [ ] Robot completes ≥3 distinct tasks
- [ ] Live demo: "type goal" → "robot acts"
- [ ] LLM reasoning displayed in real time
- [ ] Benchmark: success rate ≥50% on basic tasks
- [ ] Comparison: GPT-4o-mini vs Ollama results

### Stretch (NICE-TO-HAVE)
- [ ] Failure recovery (self-correction)
- [ ] Multi-step goal decomposition
- [ ] Prompt strategy ablation with statistics
- [ ] Interactive audience goal input
- [ ] Live reasoning trace panel

---

## Critical Path

```
Phase 1 (Scaffolding) ✓
        ↓
Phase 2 (Webots + TCP) 
        ↓
Phase 3 (MCP Server)
        ↓
Phase 4 (LangGraph Agent)
        ↓
Phase 5 (Integration)
        ↓
Phase 6 (Ablation + Demo)
```

**Critical blockers:**
1. Webots world must be created (Phase 2)
2. TCP connection must work (Phase 2 testing)
3. LLM API key must be set (Phase 4)
4. Full pipeline must integrate without errors (Phase 5)

---

## Configuration Checklist

- [ ] `.env` file created (copy from `.env.example`)
- [ ] `ANTHROPIC_API_KEY` set in `.env`
- [ ] `WEBOTS_HOST` = localhost (or your Webots IP)
- [ ] `WEBOTS_PORT` = 19997
- [ ] `WEBOTS_SIM_SPEED` = 0.1 (or adjust for your machine)
- [ ] Dependencies installed: `uv sync --group dev`

---

## Testing Checklist

### Phase 1 (Scaffolding)
- [x] Python modules import successfully
- [x] Config loads from environment

### Phase 2 (Webots)
- [ ] TCP connection to Webots works
- [ ] `get_state` returns valid robot state
- [ ] `execute_action` moves the robot
- [ ] Motor stops correctly

### Phase 3 (MCP)
- [ ] MCP tools callable and return results
- [ ] State retrieval via MCP works
- [ ] Action execution via MCP works

### Phase 4 (Agent)
- [ ] LangGraph graph compiles
- [ ] Sense node reads state
- [ ] Plan node generates action via LLM
- [ ] Act node executes action
- [ ] Evaluate node detects success

### Phase 5 (Integration)
- [ ] Full agent loop completes (50 steps)
- [ ] Robot state updates each step
- [ ] Success rate measurable
- [ ] No crashes or hangs

### Phase 6 (Ablation)
- [ ] Prompt ablation shows variance
- [ ] LLM comparison shows quality gap
- [ ] Challenge mitigations improve performance

---

## Key Files

| File | Purpose | Status |
|------|---------|--------|
| `src/common/types.py` | Data models | ✓ Done |
| `src/common/config.py` | Configuration | ✓ Done |
| `src/webots/controllers/tcp_controller.py` | Robot server | ✓ Done |
| `src/mcp_server/server.py` | MCP bridge | ✓ Done |
| `src/agent/graph.py` | LangGraph state machine | ⏳ Next |
| `src/agent/nodes.py` | Agent loop nodes | ⏳ Next |
| `src/agent/prompts.py` | System prompts | ⏳ Next |
| `src/agent/main.py` | Agent CLI | ⏳ Next |
| `benchmarks/tasks.py` | Task definitions | ⏳ Next |
| `benchmarks/run_benchmark.py` | Benchmark harness | ⏳ Next |

---

## Known Issues & Solutions

| Issue | Solution | Status |
|-------|----------|--------|
| LLM Latency | Slow sim to 0.1x speed, cache state | Design ✓ |
| Spatial Drift | Rolling context window (10 states) | Design ✓ |
| Prompt Sensitivity | 3-strategy ablation | Planned |
| TCP Sync Issues | Retry logic in MCP server | Planned |
| Stuck Loops | Stagnation detector in evaluate | Planned |
| Local LLM Gap | Ollama vs GPT comparison | Planned |

---

## Next Steps (Immediate)

1. **Create Webots world**
   - Open Webots
   - Add Pioneer 3-DX robot (or similar)
   - Add sensors (8× proximity, GPS, compass)
   - Save as `src/webots/worlds/arena.wbt`

2. **Place TCP controller in Webots**
   - Create controller node
   - Copy `tcp_controller.py` content
   - Run simulation and verify port 19997 is open

3. **Test Webots connection**
   - Ensure Webots is running with controller active
   - Run: `uv run pytest tests/test_webots_connection.py -v`
   - Fix any connection issues

4. **Then proceed to Phase 3** (MCP server testing)

---

## Team Coordination

- **Mayureshkhalane:** Leading all phases (solo effort)
- **Ntolgka, Pruthvish:** Parallel development (integrate code later)

Current focus: Getting Webots world and TCP connection working.

---

## References

- Plan: `/Users/mayureshkhalane/Documents/ARIA/plans/splendid-launching-dongarra.md`
- Presentation: `/Users/mayureshkhalane/Downloads/Robotics_Presentation_2026.pdf`
- README: `README.md` (in this directory)

---

**Last Build:** 2026-04-10 by Claude Code Agent  
**Next Review:** After Phase 2 (Webots Integration) completion
