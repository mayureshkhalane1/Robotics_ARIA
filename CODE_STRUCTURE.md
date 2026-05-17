# ARIA Code Structure & Architecture

## Directory Layout

```
ARIA/
├── src/                          # All application code
│   ├── common/                   # Shared utilities (types, config)
│   │   ├── __init__.py
│   │   ├── types.py             # Data models (RobotState, Action, etc)
│   │   └── config.py            # Configuration management
│   │
│   ├── webots/                  # Webots simulator integration
│   │   ├── controllers/         # Robot controllers (runs inside Webots)
│   │   │   ├── __init__.py
│   │   │   └── tcp_controller.py # Main robot server
│   │   └── worlds/              # Webots world files (.wbt)
│   │
│   ├── mcp_server/              # MCP bridge (agent ↔ Webots)
│   │   ├── __init__.py
│   │   └── server.py            # MCP server + tool implementations
│   │
│   └── agent/                   # LangGraph agent (Phase 4+)
│       ├── __init__.py
│       ├── graph.py             # State machine orchestrator
│       ├── nodes.py             # Sense/Plan/Act/Evaluate nodes
│       ├── prompts.py           # System prompts (ablation)
│       └── main.py              # CLI entry point
│
├── tests/                        # Test suite
│   ├── __init__.py
│   ├── test_webots_connection.py # TCP connection tests
│   ├── test_mcp_tools.py        # MCP tool validation
│   └── test_agent_integration.py # End-to-end tests
│
├── benchmarks/                   # Task definitions & benchmarking
│   ├── __init__.py
│   ├── tasks.py                 # Task scenarios (navigate, fetch, avoid)
│   └── run_benchmark.py         # Benchmark harness
│
├── plans/                        # Planning & documentation
│   ├── splendid-launching-dongarra.md  # Full implementation plan
│   └── (other planning docs)
│
├── logs/                         # Runtime logs (auto-created)
│
├── README.md                     # Project overview
├── WEBOTS_SETUP.md              # Webots integration guide
├── CODE_STRUCTURE.md            # This file
├── STATUS.md                     # Progress tracker
├── PROGRESS_REPORT_WEEK1.md     # Weekly update
├── requirements.txt             # Python dependencies
├── .env.example                 # Config template
└── .env                         # Live config (git-ignored)
```

---

## Core Files Explained

### `src/common/types.py` — Data Models

**Purpose:** Define all data structures used across components.

**Key classes:**

```python
class ActionType(Enum):
    """Robot actions the agent can execute."""
    MOVE = "move"      # Linear motion
    TURN = "turn"      # Rotation in place
    STOP = "stop"      # Emergency halt
    GRAB = "grab"      # Gripper (future)
```

```python
@dataclass
class RobotState:
    """Current sensor readings from the robot."""
    position: Tuple[float, float, float]      # (x, y, z) coordinates
    orientation: Tuple[float, float, float]   # (roll, pitch, yaw) angles
    proximity_sensors: Dict[str, float]       # 8 distance sensors
    wheel_velocities: Tuple[float, float]     # (left, right) speeds
    timestamp: float                          # Sim time
    gps_reading: Optional[Tuple[...]]         # Raw GPS (optional)
```

```python
@dataclass
class Action:
    """Action to execute + reasoning."""
    type: ActionType                  # Which action?
    params: Dict[str, float]          # Velocity, angle, etc
    reasoning: str                    # Why this action?
```

```python
@dataclass
class AgentState:
    """Persistent state across agent loop iterations."""
    goal: str                         # User-given goal
    robot_state: RobotState          # Current sensors
    state_history: List[RobotState]  # Last 10 states (context window)
    plan: str                        # LLM's current plan
    action: Optional[Action]         # Last executed action
    step_count: int                  # How many iterations done?
    success: bool                    # Goal achieved?
    error: str                       # Error message if failed
    reasoning_trace: List[str]       # Debug trail
```

**Why it's here:** Central source of truth for all data flowing through the system. Type hints catch errors early. Dataclasses are serializable (important for saving/loading state).

---

### `src/common/config.py` — Configuration Management

**Purpose:** Load and expose all configuration from environment + defaults.

**What it does:**

```python
# Loads from .env file or environment variables
WEBOTS_HOST = os.getenv("WEBOTS_HOST", "localhost")
WEBOTS_PORT = int(os.getenv("WEBOTS_PORT", 19997))
WEBOTS_SIM_SPEED = float(os.getenv("WEBOTS_SIM_SPEED", 0.1))

# LLM provider (anthropic or ollama)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Agent parameters
MAX_STEPS = int(os.getenv("MAX_STEPS", 50))
STATE_CACHE_SIZE = int(os.getenv("STATE_CACHE_SIZE", 10))
STAGNATION_THRESHOLD = int(os.getenv("STAGNATION_THRESHOLD", 5))

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
WEBOTS_WORLDS_PATH = PROJECT_ROOT / "src" / "webots" / "worlds"
LOGS_PATH = PROJECT_ROOT / "logs"
```

**Why it's here:** No hardcoded values. Everything configurable. Single import point—if config changes, you import from here and it's consistent everywhere.

---

### `src/webots/controllers/tcp_controller.py` — Robot Server

**Purpose:** Runs INSIDE Webots. Listens on TCP port 19997 for commands and streams sensor data.

**Architecture:**

```
┌─────────────────────────────────────┐
│   WebotsRobotServer (Main Class)   │
├─────────────────────────────────────┤
│ __init__()                          │
│  └─ Setup motors (left, right)      │
│  └─ Setup sensors (8× distance,     │
│      GPS, compass, camera)          │
│  └─ Start TCP server on :19997      │
│                                     │
│ run()                               │
│  └─ Main loop (while robot.step()): │
│      ├─ Accept TCP connections      │
│      ├─ Receive JSON commands       │
│      ├─ Dispatch to handlers        │
│      └─ Send JSON responses         │
│                                     │
│ get_robot_state()                   │
│  └─ Read all sensors, return dict   │
│                                     │
│ execute_action(action)              │
│  └─ Set motor velocities based on   │
│      action.type + params           │
│                                     │
│ handle_command(cmd)                 │
│  └─ Parse and route commands        │
│      (get_state, execute, stop)     │
└─────────────────────────────────────┘
```

**Protocol (JSON over TCP):**

Request:
```json
{"cmd": "get_state"}
```

Response:
```json
{
  "timestamp": 12.34,
  "position": [1.5, 2.3, 0.0],
  "orientation": [0.0, 0.0, 0.785],
  "proximity": {
    "distance_0": 0.45,
    "distance_1": 1.2,
    ...
  },
  "wheel_velocities": [1.0, 1.0]
}
```

**Why it's here:** This is the direct interface to the simulator. Webots controller scripts have access to the `robot` object, sensors, and motors—only place that can read/write them. Everything else talks to this via TCP.

---

### `src/mcp_server/server.py` — MCP Bridge

**Purpose:** Expose Webots as callable MCP tools. The LLM agent calls these tools instead of talking directly to Webots.

**Architecture:**

```
┌──────────────────────────────────────┐
│   WebotsBridge (TCP Client)         │
├──────────────────────────────────────┤
│ Manages connection to tcp_controller │
│ Sends commands, receives responses   │
│ Handles reconnection logic           │
└──────────────────────────────────────┘
            ↓ (uses)
┌──────────────────────────────────────┐
│   MCP_TOOLS Registry                │
├──────────────────────────────────────┤
│ tool_get_state()                    │
│ tool_execute_action(...)            │
│ tool_stop()                         │
│ tool_get_objects()                  │
│ tool_validate_action(...)           │
└──────────────────────────────────────┘
            ↑ (consumed by)
┌──────────────────────────────────────┐
│   LangGraph Agent (Phase 4)         │
│   Calls tools via tool_calling API  │
└──────────────────────────────────────┘
```

**Key functions:**

```python
def tool_get_state() -> Dict[str, Any]:
    """Get robot state."""
    bridge = get_bridge()
    state = bridge.get_state()
    return {"success": True, "state": state}

def tool_execute_action(action_type: str, velocity: float = None, 
                        angular_velocity: float = None) -> Dict[str, Any]:
    """Execute action: move, turn, stop, grab."""
    bridge = get_bridge()
    action = Action(type=ActionType(action_type), params={...})
    result = bridge.execute_action(action)
    return {"success": True, "action": action_type}

def tool_validate_action(action_type: str, **params) -> Dict[str, Any]:
    """Validate action without executing."""
    if action_type not in ["move", "turn", "stop", "grab"]:
        return {"valid": False, "message": "..."}
    return {"valid": True}
```

**MCP_TOOLS registry:**

```python
MCP_TOOLS = {
    "get_state": {
        "function": tool_get_state,
        "description": "Get robot state: position, orientation, sensors",
        "input_schema": {...}
    },
    "execute_action": {
        "function": tool_execute_action,
        "description": "Execute action: move, turn, stop, grab",
        "input_schema": {
            "properties": {
                "action_type": {"enum": ["move", "turn", "stop", "grab"]},
                "velocity": {"type": "number"},
                "angular_velocity": {"type": "number"}
            }
        }
    },
    ...
}
```

**Why it's here:** Decouples agent from Webots. Agent doesn't know or care about TCP sockets—it just calls tools. If we swap the simulator later, we only update this file.

---

### `src/agent/graph.py` — State Machine Orchestrator (Phase 4)

**Purpose:** LangGraph state machine that orchestrates sense → plan → act → evaluate loop.

**Structure:**

```python
class AgentState(TypedDict):
    goal: str
    robot_state: dict
    state_history: list
    plan: str
    action: dict
    step_count: int
    success: bool
    error: str

def build_agent_graph():
    graph = StateGraph(AgentState)
    
    # Add nodes (functions that run sequentially)
    graph.add_node("sense", sense_node)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("evaluate", evaluate_node)
    
    # Add edges (flow)
    graph.add_edge(START, "sense")           # Entry point
    graph.add_edge("sense", "plan")          # sense → plan
    graph.add_edge("plan", "act")            # plan → act
    graph.add_edge("act", "evaluate")        # act → evaluate
    
    # Conditional edge (loop or exit)
    def should_continue(state):
        if state["success"] or state["step_count"] >= MAX_STEPS:
            return END
        return "sense"
    
    graph.add_conditional_edges("evaluate", should_continue)
    
    return graph.compile()
```

**Execution flow:**

```
START
  ↓
sense_node: Read robot state via MCP
  ↓
plan_node: LLM decides next action (via MCP tools)
  ↓
act_node: Execute action via MCP
  ↓
evaluate_node: Check success or detect stuck
  ↓
[Did goal succeed?] ──YES→ END
       ↓
       NO
       ↓
  [Loop back to sense]
```

**Why it's here:** LangGraph handles state persistence, loop control, and tool-calling integration. We don't write the loop manually—we declare the structure and LangGraph executes it.

---

### `src/agent/nodes.py` — Loop Nodes (Phase 4)

**Purpose:** Implement each step of the sense-plan-act-evaluate loop.

```python
def sense_node(state):
    """Read robot state via MCP."""
    robot_state = bridge.get_state()
    
    # Maintain rolling context window
    history = state.get("state_history", [])
    history.append(robot_state)
    if len(history) > STATE_CACHE_SIZE:
        history.pop(0)
    
    return {
        **state,
        "robot_state": robot_state,
        "state_history": history,
        "step_count": state.get("step_count", 0) + 1
    }

def plan_node(state):
    """LLM decides next action."""
    system_prompt = """You are a robot controller. Given goal and state:
1. Analyze what you observe
2. Explain reasoning
3. Decide action: move, turn, stop, grab
4. Return JSON: {"action": {...}, "reasoning": "..."}"""
    
    user_message = f"""
Goal: {state['goal']}
Position: {state['robot_state'].get('position')}
Proximity: {state['robot_state'].get('proximity')}
Step: {state['step_count']} / 50

What next?
"""
    
    response = client.messages.create(
        model="gpt-4o-mini",
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    
    plan = json.loads(response.content[0].text)
    return {**state, "plan": plan}

def act_node(state):
    """Execute action via MCP."""
    plan = state.get("plan", {})
    action = plan.get("action", {"type": "stop"})
    
    result = bridge.execute_action(action)
    return {**state, "action": action}

def evaluate_node(state):
    """Check success or stuck state."""
    # TODO: Goal-specific success detection
    success = check_if_goal_achieved(state)
    
    # Check for stagnation
    if is_stagnant(state, STAGNATION_THRESHOLD):
        return {**state, "error": "Stuck state detected"}
    
    return {**state, "success": success}
```

**Why it's here:** Each node is a logical step. Separating them makes testing and debugging easier. You can test sense_node independently, test plan_node with mock state, etc.

---

### `src/agent/prompts.py` — Prompting Strategies (Phase 4)

**Purpose:** Support multiple prompting approaches for ablation study.

```python
PROMPTS = {
    "raw": {
        "system": "You are a robot controller. Analyze state and decide actions.",
        "strategy": "Direct instruction"
    },
    "cot": {  # Chain-of-thought
        "system": """You are a robot controller. For each step:
1. Observe the world
2. Reason about the goal
3. Plan next action
4. Explain your decision
Then output JSON.""",
        "strategy": "Chain-of-thought"
    },
    "structured": {  # Enforced format
        "system": """You are a robot controller. Respond with:
{
  "observation": "What do you see?",
  "reasoning": "Why this action?",
  "action": {"type": "...", "params": {...}},
  "confidence": 0.0-1.0
}""",
        "strategy": "Structured output"
    }
}
```

**Usage:**

```python
# In plan_node, select which strategy to use
prompt_key = "cot"  # or "raw", "structured"
system_prompt = PROMPTS[prompt_key]["system"]
```

**Why it's here:** Measure impact of prompting style. Run benchmark with "raw", measure success rate. Run with "cot", measure again. Data-driven comparison.

---

### `tests/test_webots_connection.py` — TCP Tests

**Purpose:** Validate TCP connection to Webots works.

```python
def test_webots_tcp_connection():
    """Basic TCP connection."""
    s = socket.socket()
    s.connect(("localhost", 19997))
    s.close()
    assert True

def test_get_state():
    """Retrieve robot state."""
    s = socket.socket()
    s.connect(("localhost", 19997))
    s.sendall(b'{"cmd": "get_state"}\n')
    response = json.loads(s.recv(1024).decode())
    assert "position" in response
    assert "proximity" in response

def test_execute_move():
    """Execute move action."""
    s = socket.socket()
    s.connect(("localhost", 19997))
    s.sendall(b'{"cmd": "execute", "action": {"type": "move", "params": {"velocity": 1.0}}}\n')
    result = json.loads(s.recv(1024).decode())
    assert result["status"] == "ok"
```

**Why it's here:** Verify the lowest level (TCP handshake) works before testing higher layers (MCP, agent).

---

### `benchmarks/tasks.py` — Task Definitions

**Purpose:** Define standardized tasks to measure agent success.

```python
TASKS = {
    "navigate_target": {
        "description": "Navigate to a marked target",
        "goal": "Move to the green sphere at (5, 0, 0)",
        "success_criteria": "Distance to target < 0.5m",
        "timeout_steps": 50
    },
    "obstacle_avoidance": {
        "description": "Navigate around obstacles",
        "goal": "Reach the far side without hitting walls",
        "success_criteria": "At far side AND no collision",
        "timeout_steps": 100
    },
    "fetch_object": {
        "description": "Fetch and return object",
        "goal": "Pick up red cube, bring to start",
        "success_criteria": "Holding object AND at start",
        "timeout_steps": 150
    }
}
```

**Why it's here:** Reproducible, objective measurement of agent performance.

---

## Data Flow

```
User: "Navigate to target"
  ↓
agent.ainvoke({"goal": "Navigate to target", ...})
  ↓
sense_node: bridge.get_state() → MCP → tcp_controller
            (reads GPS, sensors from Webots)
  ↓
plan_node: LLM.create(goal=..., state=...)
           (LLM decides "move with velocity 1.0")
  ↓
act_node: bridge.execute_action(Action(type="move", params={"velocity": 1.0}))
          → MCP → tcp_controller → Webots motors
          (robot actually moves)
  ↓
evaluate_node: check_success(state)
               ("Did we reach target?")
  ↓
[Loop back or exit based on success]
```

---

## Dependency Chain

```
Agent (graph.py, nodes.py)
  ↓ calls
MCP Server (server.py)
  ↓ talks to (TCP)
TCP Controller (tcp_controller.py, runs inside Webots)
  ↓ controls
Webots Simulator
```

Each layer is independent:
- **Agent** doesn't know about TCP or Webots details
- **MCP** doesn't know about LangGraph or agent logic
- **TCP Controller** doesn't know about MCP or agent
- **Webots** is completely isolated

---

## Key Design Decisions

### 1. **TCP vs gRPC/RPC**
- **Why TCP:** Simple, reliable, works with Webots native Python
- **Trade-off:** Synchronous (not async). Fine for ~1 Hz control loop

### 2. **MCP as the Interface**
- **Why:** Decouples agent from simulator. Swap robots/simulators without touching agent code
- **Trade-off:** One extra layer. Worth it for modularity

### 3. **Dataclasses for State**
- **Why:** Type-safe, serializable, clean API
- **Trade-off:** Not as flexible as dicts. Worth it for safety

### 4. **Rolling Context Window (last 10 states)**
- **Why:** Combat spatial reasoning drift. LLM can reference recent history
- **Trade-off:** More tokens per LLM call. Necessary to prevent accumulation errors

### 5. **Separate Agent/MCP/Controller Repos**
- **Why:** Each component can be tested independently
- **Trade-off:** More code, more imports. Worth it for clarity

---

## Adding New Features

**New robot action (e.g., gripper)?**
1. Add to `ActionType` enum in `types.py`
2. Add handler in `tcp_controller.py` execute_action()
3. Add tool in `mcp_server.py` (if exposing to agent)

**New sensor (e.g., camera)?**
1. Add to `RobotState` dataclass in `types.py`
2. Read from Webots in `tcp_controller.py` get_robot_state()
3. Include in MCP `get_state()` response

**New MCP tool?**
1. Write function in `mcp_server.py` tool_xyz()
2. Add to `MCP_TOOLS` registry
3. Use in agent via tool-calling

**New prompting strategy?**
1. Add to `PROMPTS` dict in `prompts.py`
2. Update `plan_node` to select it
3. Run benchmark with new strategy

---

## Testing Layers

```
Layer 1: TCP (test_webots_connection.py)
         └─ Verify Webots listens, responds

Layer 2: MCP (test_mcp_tools.py, TBD)
         └─ Verify tools callable, return correct shapes

Layer 3: Agent (test_agent_integration.py, TBD)
         └─ Verify full loop completes, state progresses

Layer 4: Benchmark (benchmarks/run_benchmark.py, TBD)
         └─ Measure task success rates across runs
```

Each layer tested independently before moving up.

---

## Summary

**Phase 1 (now):** types.py, config.py, tcp_controller.py, mcp_server.py, tests
**Phase 4:** graph.py, nodes.py, prompts.py, main.py
**Phase 5:** Integrate layers, run benchmarks

Total ~1000 LOC core code. Clean separation. Modular.
