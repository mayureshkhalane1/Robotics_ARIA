# ARIA — Agentic Robot Intelligence Architecture

Progress Report — Week 1

---

## What This Project Is

Building system where AI agent controls simulated robot in Webots without task-specific training. Zero-shot learning. Natural language goals → robot executes.

**Why it matters:** Tests whether LLMs can reason about real-time robot control. No training data needed. Fully swappable components (LLM, robot, simulator).

**Team:** Mayureshkhalane (solo, all components), Ntolgka, Pruthvish (parallel work)

**Course:** Robotics 2026, Leiden University LIACS

**Deadline:** Demo day, end of semester

---

## Architecture (Three Layers)

```
LangGraph Agent
  (sense → plan → act → evaluate loop)
        ↓ calls
MCP Server
  (5 callable tools exposing Webots)
        ↓ TCP socket
Webots Simulator + TCP Controller
  (robot, physics, sensors)
```

**Key innovation:** Modular. Swap LLM (GPT-4o-mini ↔ Ollama). Swap robot. Swap simulator. Touch nothing else.

---

## What We Finished This Week (Phase 1: Scaffolding)

### Project structure
- 20 Python files
- 600+ lines core code
- 6 test cases ready
- 4 documentation files
- All dependencies installed

### Code built

**Data models** (`src/common/types.py`):
- `RobotState` — sensors (position, orientation, proximity, wheel speeds)
- `Action` — what robot does + reasoning
- `ActionType` — enum (move, turn, stop, grab)
- `AgentState` — persistent state across loop

**Configuration** (`src/common/config.py`):
- Loads from `.env` file
- No hardcoded values
- 12 parameters (Webots host/port, LLM provider, agent settings)

**Webots TCP controller** (`src/webots/controllers/tcp_controller.py`):
- 290 lines
- Listens on port 19997
- Commands: `get_state`, `execute_action`, `stop`
- Handles 8 distance sensors, GPS, compass, optional camera
- Motor control (left/right wheels)

**MCP Server bridge** (`src/mcp_server/server.py`):
- 400+ lines
- 5 tools: get_state, execute_action, stop, get_objects, validate_action
- WebotsBridge class manages TCP connection
- Singleton pattern (one connection per process)

**Test suite** (`tests/test_webots_connection.py`):
- 6 test cases
- TCP connection validation
- State retrieval tests
- Action execution tests
- Error handling tests
- Skip gracefully if Webots not running

### Documentation

- `README.md` — full architecture guide + setup
- `WEBOTS_SETUP.md` — step-by-step Webots integration (9 steps)
- `CODE_STRUCTURE.md` — codebase explanation, dependencies, design decisions
- `STATUS.md` — progress tracker with all phases mapped
- Implementation plan (`plans/splendid-launching-dongarra.md`) — 10-page spec

### Verified

- All modules import without errors ✓
- Config loads from environment ✓
- Data models work with type checking ✓
- MCP server structure is sound ✓
- TCP controller handles errors gracefully ✓
- No dependency issues ✓

---

## Robot Selected

**Pioneer 3-DX** — wheeled mobile robot

**Why:** Industry standard. Two wheels. 8 distance sensors. GPS. Compass. Perfect for testing navigation, obstacle avoidance, waypoint following.

**Status:** All 3 team members have Webots installed, environment configured

---

## The Full Plan (6 Phases, 10 Weeks)

### Phase 1: Scaffolding (Week 1) ✓ DONE
- ✓ Directory structure
- ✓ Data models
- ✓ Configuration system
- ✓ TCP controller implementation
- ✓ MCP server implementation
- ✓ Test framework
- ✓ Documentation

### Phase 2: Webots Integration (Weeks 2–3)
**Goal:** TCP connection working end-to-end

**Tasks:**
- Create Webots world file (arena.wbt)
- Add Pioneer 3-DX robot
- Add 8 distance sensors, GPS, compass
- Add obstacles and navigation target
- Place TCP controller in Webots
- Run simulation and verify port 19997 listens
- Run tests: `pytest tests/test_webots_connection.py`

**Success criteria:**
- TCP handshake works
- get_state returns valid sensor readings
- execute_action moves the robot
- Motor stops correctly

**Effort:** ~2 hours this weekend + debugging

### Phase 3: MCP Server Validation (Weeks 3–4)
**Goal:** All 5 MCP tools work against live Webots

**Tasks:**
- Test `get_state()` tool against live robot
- Test `execute_action()` tool (move, turn, stop)
- Test `validate_action()` tool
- Test `get_objects()` tool (stub, will enhance later)
- Test error recovery (dropped TCP, invalid commands)

**Success criteria:**
- Tool calls return correct shapes
- State is accurate
- Actions execute consistently
- Errors handled gracefully

### Phase 4: LangGraph Agent (Weeks 4–6)
**Goal:** Full sense → plan → act → evaluate loop implemented

**Tasks:**
- Implement `src/agent/graph.py` — LangGraph state machine
- Implement `src/agent/nodes.py` — 4 nodes:
  - **Sense:** Read robot state via MCP, maintain rolling history
  - **Plan:** Call LLM (Claude) to decide next action
  - **Act:** Execute action via MCP tools
  - **Evaluate:** Check goal success, detect stuck states
- Implement `src/agent/prompts.py` — 3 prompting strategies (raw, CoT, structured)
- Implement `src/agent/main.py` — CLI entry point
- Wire LLM + MCP client integration

**Success criteria:**
- Agent loop completes (50 steps)
- Robot state updates each iteration
- LLM is called correctly
- Actions execute from LLM decisions
- Loop terminates on success or MAX_STEPS

### Phase 5: Integration & Benchmarking (Weeks 6–8)
**Goal:** Measure agent performance on real tasks

**Tasks:**
- Create task definitions (`benchmarks/tasks.py`):
  - Navigate to target (position X, Y, Z)
  - Obstacle avoidance (reach far side without collision)
  - Fetch object (pick up, return to start)
  - +2 more tasks (total 5+)
- Create benchmark harness (`benchmarks/run_benchmark.py`)
  - Run each task N times
  - Measure success rate
  - Track step count, execution time
- Full pipeline integration test
- Debug any issues (latency, TCP sync, LLM timeouts)

**Success criteria:**
- Robot completes ≥3 tasks
- Success rate ≥50% on basic tasks
- No hangs or crashes
- Benchmark results reproducible

### Phase 6: Experimentation & Ablation (Weeks 8–9)
**Goal:** Measure impact of design decisions

**Tasks:**
- **Prompt strategy ablation:**
  - Run each task with "raw" prompting → measure success rate
  - Run with "CoT" prompting → measure success rate
  - Run with "structured" prompting → measure success rate
  - Compare results, document variance

- **LLM backend comparison:**
  - Benchmark on GPT-4o-mini (cloud baseline)
  - Benchmark on Ollama Llama 3 (local)
  - Measure latency, quality, success rate delta

- **Challenge mitigation testing:**
  - LLM latency: vary sim_speed (0.05x, 0.1x, 0.5x), measure impact
  - Spatial reasoning: test with/without rolling context window
  - Prompt sensitivity: measure variance across 10+ runs
  - Stuck-state detection: verify stagnation detector works

- **Demo preparation:**
  - Polish agent (clean up logs, error messages)
  - Prepare 5 live demo scenarios
  - Create reasoning trace visualization (show LLM thinking)
  - Test end-to-end demo run

**Success criteria:**
- All experiments complete with data
- Clear findings on what works/doesn't work
- Demo is polished and reproducible

---

## Critical Challenges We Identified (All Have Solutions)

### 1. LLM Latency (0.5–2s per step)
**Problem:** API calls slow. Robot can't respond in real-time.

**Solution:** Slow simulation to 0.1x speed. Gives LLM time to think. Cache repeated state descriptions to reduce tokens.

### 2. Spatial Reasoning Drift
**Problem:** LLM misjudges coordinates over many steps. Robot gets lost.

**Solution:** Rolling context window (keep last 10 states). LLM can reference recent history. Absolute coordinates instead of relative movements.

### 3. Prompt Sensitivity
**Problem:** Small wording changes shift success by 10–20%.

**Solution:** Systematic ablation. Test 3 prompting strategies. Measure variance. Document which works best.

### 4. MCP-Webots TCP Sync
**Problem:** Dropped packets, timing mismatches, Webots crashes corrupt agent state.

**Solution:** Retry logic. Connection pooling. Graceful error handling. Agent state doesn't corrupt.

### 5. Stuck-State Loops
**Problem:** Vanilla LLM planner loops indefinitely without progress.

**Solution:** Stagnation detector in evaluate node. If robot state doesn't change for N steps, force re-plan. Detect and break loops.

### 6. Local LLM Quality Gap
**Problem:** Ollama models (Llama 3) underperform GPT-4o-mini on planning.

**Solution:** Benchmark both. Measure quality delta. Document gap size as research finding.

---

## This Weekend (Phase 2 Kickoff)

**Create Webots world:**
- Open Webots, new world
- Add Pioneer 3-DX robot
- Add 8 distance sensors (names: distance_sensor_0–7)
- Add GPS, compass
- Add 1 target (green sphere)
- Add 3–5 obstacles (boxes/walls)
- ~1 hour

**Integrate TCP controller:**
- Create controller node in Webots
- Paste tcp_controller.py content
- Save, verify no syntax errors
- ~15 min

**Test connection:**
- Run simulation (play button)
- Verify: `[Webots] Robot server initialized on port 19997`
- Run: `pytest tests/test_webots_connection.py -v`
- All tests should pass
- ~30 min + debugging

**Total:** ~2 hours. No blockers.

---

## Timeline at a Glance

| Phase | What | Timeline | Status |
|-------|------|----------|--------|
| 1 | Scaffolding | Week 1 | ✓ DONE |
| 2 | Webots + TCP | Weeks 2–3 | ⏳ This weekend |
| 3 | MCP validation | Weeks 3–4 | ⏳ Next week |
| 4 | Agent logic | Weeks 4–6 | ⏳ Start week 4 |
| 5 | Integration | Weeks 6–8 | ⏳ Mid-project |
| 6 | Ablation + demo | Weeks 8–9 | ⏳ Final sprint |

---

## Demo Day Deliverables

### Minimum (Required)
- ✓ Working ARIA pipeline (Webots + MCP + LangGraph)
- ✓ Robot completes ≥3 distinct tasks (navigate, fetch, avoid obstacles)
- ✓ Live demo: type goal → watch robot execute in real-time
- ✓ LLM reasoning displayed alongside simulation
- ✓ Benchmark results: success rate across 10+ runs per task
- ✓ GPT-4o-mini vs Ollama comparison with metrics

### Stretch (Nice-to-Have)
- Failure recovery: robot detects stuck state, re-plans
- Multi-step goal decomposition with sub-goal verification
- Prompt strategy ablation (raw vs CoT vs structured) with statistics
- Interactive audience goal input during demo ("Make the robot fetch that object")
- Live reasoning trace panel (show LLM thinking step-by-step)

---

## Resources & Documentation

**Core implementation:**
- `/src/` — All code
- `/tests/` — Test suite
- `/benchmarks/` — Tasks + benchmark harness
- `/plans/` — Detailed specs

**Reference:**
- `README.md` — Architecture overview
- `CODE_STRUCTURE.md` — Every file explained
- `WEBOTS_SETUP.md` — Integration guide (9 steps)
- `STATUS.md` — Progress tracker with checklists

**Key files:**
- `src/common/types.py` — Data models
- `src/common/config.py` — Configuration
- `src/webots/controllers/tcp_controller.py` — Robot server
- `src/mcp_server/server.py` — MCP bridge
- `plans/splendid-launching-dongarra.md` — Full implementation plan

---

## Why This Approach Works

1. **Modular:** Each layer (agent, MCP, TCP) is independent. Test separately.
2. **Type-safe:** Data models catch errors early. Dataclasses are serializable.
3. **No hardcoded values:** Everything in `.env`. Easy to configure.
4. **Error-resilient:** TCP retry logic, graceful degradation, clear error messages.
5. **Research-grade:** Designed for systematic ablation studies. Measure everything.

---

## Next Step: This Weekend

1. Create Webots world
2. Place TCP controller
3. Run simulation
4. Run tests

Once tests pass, everything downstream unblocks.

**No blockers. Ready to go.**
