# ARIA Execution Plan

Generated: 2026-05-17

## Current Reality

ARIA is currently a scaffolded robotics project, not a finished runnable robot agent.

Working/in-place:
- `src/common/types.py`: shared data classes for robot state, actions, agent state.
- `src/common/config.py`: environment config loader.
- `src/webots/controllers/tcp_controller.py`: Webots-side TCP robot controller.
- `src/mcp_server/server.py`: Python bridge/tool registry that talks to Webots over TCP.
- `tests/test_webots_connection.py`: integration tests that run only when Webots controller is live.

Missing or empty:
- `src/agent/main.py`
- `src/agent/graph.py`
- `src/agent/nodes.py`
- `src/agent/prompts.py`
- `src/webots/worlds/arena.wbt`
- `benchmarks/tasks.py`
- `benchmarks/run_benchmark.py`
- real MCP protocol server transport, currently `server.py` is a callable Python tool registry/test harness.

Also found:
- A nested `Robotics_ARIA/` clone exists inside `/Users/mayureshkhalane/Documents/ARIA`. This was likely created accidentally during earlier terminal testing. Keep it only if you need it, otherwise remove it after confirming.

## Goal

Build a complete local demo pipeline:

```text
Webots world + robot controller
        ↓ TCP JSON
MCP/Webots bridge tools
        ↓ Python tool calls
LangGraph-like agent loop
        ↓ actions
Robot navigates while avoiding obstacles
```

## Phase 0: Clean workspace

Commands:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
git status --short
```

If the nested clone is accidental:

```bash
rm -rf Robotics_ARIA
```

Only do this after confirming there is nothing unique in that folder.

## Phase 1: Environment setup

Use Python 3.10+ if possible. macOS system Python 3.9 works for basic imports but some packages may be happier on 3.10/3.11.

Commands:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pytest
cp .env.example .env
```

Edit `.env`:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your_key_here
WEBOTS_HOST=localhost
WEBOTS_PORT=19997
MAX_STEPS=50
```

Validation:

```bash
python - <<'PY'
from src.common.types import AgentState
from src.mcp_server.server import list_tools, call_tool
print('imports ok')
print([t['name'] for t in list_tools()])
print(call_tool('validate_action', {'action_type': 'move', 'velocity': 1.0}))
PY
```

## Phase 2: Build or add Webots world

Needed file:

```text
src/webots/worlds/arena.wbt
```

Minimum world requirements:
- Differential-drive robot, recommended Pioneer 3-DX.
- Wheel motors named:
  - `left wheel motor`
  - `right wheel motor`
- Distance sensors named:
  - `distance sensor 0` through `distance sensor 7`
- GPS named `gps`.
- Compass named `compass`.
- Optional camera named `camera`.
- Static obstacles.
- A visible target object.

Manual Webots workflow:

```bash
open -a Webots
```

Then in Webots:
1. Create/save world as `src/webots/worlds/arena.wbt`.
2. Add robot.
3. Attach sensors.
4. Set controller to `tcp_controller` or paste/use `src/webots/controllers/tcp_controller.py`.
5. Press Play.
6. Confirm console prints:

```text
[Webots] Robot server initialized on port 19997
```

Possible CLI launch on macOS once world exists:

```bash
/Applications/Webots.app/Contents/MacOS/webots src/webots/worlds/arena.wbt
```

## Phase 3: Test Webots TCP controller

With Webots running and simulation playing:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
source .venv/bin/activate
python -m pytest tests/test_webots_connection.py -v
```

Manual TCP test:

```bash
python - <<'PY'
import socket, json
s = socket.socket()
s.settimeout(3)
s.connect(('localhost', 19997))
s.sendall(b'{"cmd":"get_state"}\n')
print(json.loads(s.recv(4096).decode()))
s.close()
PY
```

Expected:
- pytest tests pass, not skip.
- `get_state` returns timestamp, proximity, wheel velocities, position if GPS works.

## Phase 4: Implement runnable agent CLI

Create these files:

```text
src/agent/prompts.py
src/agent/nodes.py
src/agent/graph.py
src/agent/main.py
```

Recommended first implementation: deterministic safety agent before LLM.

Why: This proves the robot-control loop works without API latency or prompt instability.

Minimal agent behavior:
1. Sense: call `tool_get_state()`.
2. Plan:
   - If front proximity means obstacle near, turn.
   - Else move forward.
3. Act: call `tool_execute_action(...)`.
4. Stop after `--steps` or on error.

Command after implementation:

```bash
python -m src.agent.main --goal "avoid obstacles and explore" --steps 50 --policy reactive
```

Then add LLM policy:

```bash
python -m src.agent.main --goal "navigate to the green target while avoiding obstacles" --steps 50 --policy llm
```

## Phase 5: Make MCP server real or rename it honestly

Current `src/mcp_server/server.py` is not a full MCP stdio/http server. It is a Python module exposing a tool registry.

Two options:

### Option A, fastest for project demo
Keep it as a Python bridge and rename docs from “MCP server” to “MCP-style tool bridge”.

### Option B, more correct
Add real MCP SDK/server transport so external agents can call tools.

Likely dependencies:

```bash
pip install mcp
```

Then expose tools over stdio:

```bash
python -m src.mcp_server.server
```

## Phase 6: Benchmarks

Create:

```text
benchmarks/tasks.py
benchmarks/run_benchmark.py
```

Tasks:
- `avoid_obstacles_30s`
- `drive_forward_5m`
- `turn_in_place`
- `navigate_to_target`
- `recover_from_blocked`

Metrics:
- success/failure
- collision count if detectable
- final distance to target
- steps used
- average action latency
- LLM calls used

Command:

```bash
python -m benchmarks.run_benchmark --task avoid_obstacles_30s --runs 5 --policy reactive
python -m benchmarks.run_benchmark --task navigate_to_target --runs 5 --policy llm
```

## Phase 7: Git workflow

After each completed phase:

```bash
git add .
git commit -m "Implement <phase name>"
git push origin main
```

## Immediate Next Coding Tasks

Priority order:

1. Remove/ignore accidental nested `Robotics_ARIA/` clone.
2. Add `.gitignore` for `.venv/`, logs, cache, nested clones, Webots generated files.
3. Implement `src/agent/main.py` with reactive policy.
4. Add `src/agent/nodes.py` and `graph.py` with a simple loop.
5. Add unit tests for agent planning that do not require Webots.
6. Create Webots `arena.wbt` manually or through a generated starter world.
7. Run TCP tests against live Webots.
8. Add LLM policy and structured prompts.
9. Add benchmark runner.

## Known Current Commands

Run current bridge validation without Webots:

```bash
python - <<'PY'
from src.mcp_server.server import list_tools, call_tool
print([t['name'] for t in list_tools()])
print(call_tool('validate_action', {'action_type': 'move', 'velocity': 1.0}))
PY
```

Run Webots integration tests:

```bash
python -m pytest tests/test_webots_connection.py -v
```

Run MCP bridge test, requires Webots live:

```bash
python src/mcp_server/server.py
```

Future agent command after implementation:

```bash
python -m src.agent.main --goal "navigate to target" --steps 50 --policy reactive
```
