# ARIA: Agentic Robot Intelligence Architecture — Implementation Plan

## Context

**Problem:** Building autonomous robot control systems traditionally requires extensive task-specific training. ARIA tests whether a zero-shot LLM can reason about robot actions (navigate, fetch, avoid) in real-time using only natural language prompts and sensor readings—no training data needed.

**Solution:** A fully decoupled system where:
- **Webots** simulates the robot and physics
- **MCP Server** exposes robot state/actions as callable tools
- **LangGraph** orchestrates the sense → plan → act → evaluate loop
- **Zero-shot LLM** (GPT-4o-mini or Ollama) decides actions from natural language

**Key Innovation:** This design separates concerns cleanly—you can swap the LLM, robot, or state machine without rewriting the entire system.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     LangGraph Agent Loop                         │
│  (State Management + Node Orchestration)                        │
│  ├─ Sense Node: Read robot state via MCP                       │
│  ├─ Plan Node: LLM decides next action                         │
│  ├─ Act Node: Execute action via MCP tools                     │
│  └─ Evaluate Node: Check success, detect stuck states          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ (tool calls)
┌───────────────────────────▼─────────────────────────────────────┐
│                    MCP Server (Custom Bridge)                    │
│  Tools: get_state | execute_action | get_objects | validate     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ (TCP socket)
┌───────────────────────────▼─────────────────────────────────────┐
│                    Webots Simulator + TCP Server                 │
│  ├─ Robot: Sensors (camera, proximity, GPS)                     │
│  ├─ World: Obstacles, objects, navigation targets               │
│  └─ Controller: Listens for actions, applies physics            │
└─────────────────────────────────────────────────────────────────┘
```

**File Organization:**
```
/Users/mayureshkhalane/Documents/ARIA/
├── src/
│   ├── webots/
│   │   ├── worlds/
│   │   │   └── arena.wbt               # Webots world file (task scenes)
│   │   └── controllers/
│   │       └── tcp_controller.py       # Robot controller + TCP server
│   ├── mcp_server/
│   │   ├── server.py                   # MCP server implementation
│   │   └── tools.py                    # Tool definitions (get_state, execute_action, etc)
│   ├── agent/
│   │   ├── graph.py                    # LangGraph state machine
│   │   ├── nodes.py                    # Individual nodes (Sense/Plan/Act/Evaluate)
│   │   ├── prompts.py                  # System prompts, chain-of-thought strategies
│   │   └── main.py                     # Agent entry point + demo runner
│   └── common/
│       ├── config.py                   # Shared constants (TCP host/port, sim speed, etc)
│       └── types.py                    # Shared data models (RobotState, Action, etc)
├── tests/
│   ├── test_webots_connection.py       # TCP handshake + sensor read/write
│   ├── test_mcp_tools.py               # MCP tool validation
│   └── test_agent_integration.py       # End-to-end agent + simulator
├── benchmarks/
│   ├── tasks.py                        # 5+ task scenarios (navigate, fetch, avoid)
│   └── run_benchmark.py                # Test harness + success rate measurement
├── requirements.txt                    # All Python dependencies
├── .env.example                        # Config template (LLM API keys, sim params)
└── README.md                           # Setup & usage guide
```

---

## Phase 1: Project Scaffolding (Weeks 1)

### 1.1 Directory Structure & Dependencies

**Created directory structure:**
```bash
cd /Users/mayureshkhalane/Documents/ARIA
mkdir -p src/{webots/{worlds,controllers},mcp_server,agent,common} tests benchmarks
```

**Created `requirements.txt`:**
```
langgraph==0.2.76
langgraph-checkpoint==2.1.2
anthropic==0.38.0
pydantic==2.10.0
python-dotenv==1.0.1
aiohttp==3.11.0
pyyaml==6.0.2
```

**Created `.env.example`:**
```
# LLM Configuration
LLM_PROVIDER=anthropic  # or 'ollama'
ANTHROPIC_API_KEY=sk-...
OLLAMA_BASE_URL=http://localhost:11434

# Webots Connection
WEBOTS_HOST=localhost
WEBOTS_PORT=19997
WEBOTS_SIM_SPEED=0.1  # Slow down simulation to ~0.1x for LLM latency

# Agent Configuration
MAX_STEPS=50
STATE_CACHE_SIZE=10  # Rolling context window for spatial reasoning
STAGNATION_THRESHOLD=5  # Steps before "stuck state" detection
```

### 1.2 Shared Data Models (`src/common/types.py`)

Defined structures used across all components:
```python
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class RobotState:
    """Current sensor readings from the robot."""
    position: tuple  # (x, y, z)
    orientation: tuple  # (roll, pitch, yaw)
    proximity_sensors: Dict[str, float]  # sensor_name -> distance
    camera_frame: Optional[bytes]  # encoded image if available
    wheel_velocities: tuple  # (left, right)
    timestamp: float

@dataclass
class Action:
    """Action the robot will execute."""
    type: str  # 'move', 'turn', 'stop', 'grab'
    params: Dict[str, float]  # velocity, angle, duration, etc
    reasoning: str  # LLM's explanation
```

### 1.3 Configuration (`src/common/config.py`)

```python
import os
from dotenv import load_dotenv

load_dotenv()

# Webots
WEBOTS_HOST = os.getenv("WEBOTS_HOST", "localhost")
WEBOTS_PORT = int(os.getenv("WEBOTS_PORT", 19997))
WEBOTS_SIM_SPEED = float(os.getenv("WEBOTS_SIM_SPEED", 0.1))

# Agent
MAX_STEPS = int(os.getenv("MAX_STEPS", 50))
STATE_CACHE_SIZE = int(os.getenv("STATE_CACHE_SIZE", 10))
STAGNATION_THRESHOLD = int(os.getenv("STAGNATION_THRESHOLD", 5))

# LLM
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
```

---

## Phase 2: Webots Integration (Weeks 2–3)

### 2.1 Webots World Setup

**Webots file:** `src/webots/worlds/arena.wbt`
- Import or create a simple world with:
  - A mobile robot (e.g., Pioneer 3-DX or custom)
  - Proximity/distance sensors (front, left, right)
  - A navigation target (sphere or marker)
  - Obstacles (boxes, walls)
  - Optional: camera, GPS

**Note:** Webots has native Python controller support. We'll use a custom controller script to expose a TCP server.

### 2.2 TCP Controller Script (`src/webots/controllers/tcp_controller.py`)

This script runs **inside** Webots and listens for commands over TCP:

```python
"""
Runs inside Webots as a robot controller.
Listens on TCP port, executes commands, streams sensor data.
"""
import socket
import json
from controller import Robot, Motor, DistanceSensor, GPS, Compass

# Webots setup
robot = Robot()
timestep = int(robot.getBasicTimeStep())
sim_speed = 0.1  # From config

# Get motors
left_motor = robot.getDevice("left wheel motor")
right_motor = robot.getDevice("right wheel motor")
left_motor.setPosition(float('inf'))
right_motor.setPosition(float('inf'))

# Get sensors
proximity_sensors = {}
for i in range(8):  # Adjust based on your robot
    sensor = robot.getDevice(f"distance sensor {i}")
    sensor.enable(timestep)
    proximity_sensors[f"dist_{i}"] = sensor

gps = robot.getDevice("gps")
gps.enable(timestep)

compass = robot.getDevice("compass")
compass.enable(timestep)

# TCP Server
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(("127.0.0.1", 19997))
server_socket.listen(1)
server_socket.setblocking(False)

print("[Webots] TCP server listening on port 19997")

client_socket = None

def get_robot_state():
    """Return current sensor readings as dict."""
    return {
        "position": list(gps.getValues()),
        "compass": list(compass.getValues()),
        "proximity": {k: v.getValue() for k, v in proximity_sensors.items()},
        "wheel_velocities": [left_motor.getVelocity(), right_motor.getVelocity()],
    }

def execute_action(action_dict):
    """Execute an action: {type, params}."""
    action_type = action_dict.get("type")
    params = action_dict.get("params", {})
    
    if action_type == "move":
        velocity = params.get("velocity", 1.0)
        left_motor.setVelocity(velocity)
        right_motor.setVelocity(velocity)
    elif action_type == "turn":
        angular_vel = params.get("angular_velocity", 0.5)
        left_motor.setVelocity(-angular_vel)
        right_motor.setVelocity(angular_vel)
    elif action_type == "stop":
        left_motor.setVelocity(0)
        right_motor.setVelocity(0)
    
    return {"status": "ok"}

# Main loop
while robot.step(timestep) != -1:
    # Try to accept a connection
    try:
        if client_socket is None:
            client_socket, addr = server_socket.accept()
            print(f"[Webots] Client connected: {addr}")
    except BlockingIOError:
        pass
    
    # Handle incoming commands
    if client_socket:
        try:
            data = client_socket.recv(1024).decode('utf-8')
            if data:
                msg = json.loads(data)
                if msg["cmd"] == "get_state":
                    response = get_robot_state()
                    client_socket.sendall((json.dumps(response) + "\n").encode('utf-8'))
                elif msg["cmd"] == "execute":
                    result = execute_action(msg["action"])
                    client_socket.sendall((json.dumps(result) + "\n").encode('utf-8'))
        except (json.JSONDecodeError, socket.error) as e:
            print(f"[Webots] Error: {e}")
            client_socket = None
```

**Integration Steps:**
1. Open Webots, create a new world or import one
2. Add a mobile robot (Pioneer 3-DX available in library)
3. Add proximity sensors, GPS, compass to the robot
4. Create a custom controller and place this TCP script there
5. Run the simulation and verify TCP server starts on port 19997

**Testing:** `tests/test_webots_connection.py`
```python
import socket
import json

def test_webots_tcp():
    """Connect to Webots controller and test commands."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect(("localhost", 19997))
    
    # Get state
    s.sendall(b'{"cmd": "get_state"}\n')
    response = json.loads(s.recv(1024).decode('utf-8'))
    assert "position" in response
    assert "proximity" in response
    
    # Execute action
    s.sendall(b'{"cmd": "execute", "action": {"type": "move", "params": {"velocity": 1.0}}}\n')
    result = json.loads(s.recv(1024).decode('utf-8'))
    assert result["status"] == "ok"
    
    s.close()
    print("✓ Webots TCP tests passed")

if __name__ == "__main__":
    test_webots_tcp()
```

---

## Phase 3: MCP Server (Weeks 3–4)

### 3.1 MCP Server Implementation (`src/mcp_server/server.py`)

The MCP server is a bridge that exposes Webots as tool-callable resources:

```python
"""
MCP Server: Exposes Webots robot as callable tools.
Tools: get_state, execute_action, get_objects, validate_action
"""
from mcp.server import Server, Request
from mcp.types import Tool, TextContent
import socket
import json
from src.common.types import RobotState, Action
from src.common.config import WEBOTS_HOST, WEBOTS_PORT

server = Server("aria-webots-mcp")

class WebotsBridge:
    """Manages TCP connection to Webots controller."""
    
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None
    
    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
    
    def send_command(self, cmd):
        """Send command and receive response."""
        self.socket.sendall((json.dumps(cmd) + "\n").encode('utf-8'))
        response = self.socket.recv(4096).decode('utf-8')
        return json.loads(response)
    
    def get_state(self):
        """Fetch current robot state."""
        return self.send_command({"cmd": "get_state"})
    
    def execute_action(self, action: Action):
        """Execute an action on the robot."""
        return self.send_command({
            "cmd": "execute",
            "action": {
                "type": action.type,
                "params": action.params
            }
        })

# Initialize bridge
bridge = WebotsBridge(WEBOTS_HOST, WEBOTS_PORT)

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return available tools for the agent."""
    return [
        Tool(
            name="get_state",
            description="Get current robot state: position, orientation, sensor readings",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="execute_action",
            description="Execute action: move, turn, stop, grab",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_type": {"type": "string", "enum": ["move", "turn", "stop", "grab"]},
                    "velocity": {"type": "number"},
                    "angular_velocity": {"type": "number"},
                    "duration": {"type": "number"}
                }
            }
        ),
        Tool(
            name="get_objects",
            description="Get list of objects in world and their positions",
            inputSchema={"type": "object", "properties": {}}
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> str:
    """Handle tool calls from the agent."""
    if name == "get_state":
        state = bridge.get_state()
        return json.dumps(state)
    
    elif name == "execute_action":
        action = Action(
            type=arguments.get("action_type", "move"),
            params={k: v for k, v in arguments.items() if k != "action_type"},
            reasoning=""
        )
        result = bridge.execute_action(action)
        return json.dumps(result)
    
    elif name == "get_objects":
        # TODO: Implement object detection from camera/world state
        return json.dumps({"objects": []})

if __name__ == "__main__":
    bridge.connect()
    server.run()
```

### 3.2 Tool Definitions (`src/mcp_server/tools.py`)

Centralize tool definitions for reuse:

```python
TOOLS = {
    "get_state": {
        "description": "Get current robot state: position, orientation, sensor readings",
        "params": {}
    },
    "execute_action": {
        "description": "Execute action: move, turn, stop, grab",
        "params": {
            "action_type": {"type": "string", "enum": ["move", "turn", "stop"]},
            "velocity": {"type": "number", "description": "Linear velocity (m/s)"},
            "angular_velocity": {"type": "number", "description": "Rotational velocity (rad/s)"}
        }
    },
    "get_objects": {
        "description": "Get list of objects in world",
        "params": {}
    }
}
```

**Testing:** `tests/test_mcp_tools.py`
```python
async def test_mcp_tools():
    """Test MCP tool definitions and calls."""
    tools = await list_tools()
    assert len(tools) >= 3
    
    # Test get_state
    result = await call_tool("get_state", {})
    state = json.loads(result)
    assert "position" in state
    
    print("✓ MCP tool tests passed")
```

---

## Phase 4: LangGraph Agent (Weeks 4–6)

### 4.1 Agent State Machine (`src/agent/graph.py`)

```python
"""
LangGraph state machine: Sense → Plan → Act → Evaluate → Loop
"""
from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from src.agent.nodes import sense_node, plan_node, act_node, evaluate_node
from src.common.config import MAX_STEPS, STATE_CACHE_SIZE

class AgentState(TypedDict):
    """State persisted across agent loop iterations."""
    goal: str  # Natural language goal
    robot_state: dict  # Current sensor readings
    state_history: list  # Rolling window of past states
    plan: str  # LLM's current plan
    action: dict  # Last executed action
    step_count: int
    success: bool
    error: str

def build_agent_graph():
    """Construct the LangGraph state machine."""
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("sense", sense_node)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("evaluate", evaluate_node)
    
    # Add edges
    graph.add_edge(START, "sense")
    graph.add_edge("sense", "plan")
    graph.add_edge("plan", "act")
    graph.add_edge("act", "evaluate")
    
    # Conditional edge: success or continue loop
    def should_continue(state):
        if state["success"] or state["step_count"] >= MAX_STEPS:
            return END
        return "sense"
    
    graph.add_conditional_edges("evaluate", should_continue)
    
    return graph.compile()

# Export compiled agent
agent = build_agent_graph()
```

### 4.2 Node Implementations (`src/agent/nodes.py`)

```python
"""
Individual LangGraph nodes implementing the sense-plan-act-evaluate loop.
"""
from anthropic import Anthropic
from src.common.config import ANTHROPIC_API_KEY
from src.mcp_server.server import bridge
import json

client = Anthropic(api_key=ANTHROPIC_API_KEY)

def sense_node(state):
    """
    Read robot state and update history.
    """
    robot_state = bridge.get_state()
    
    # Maintain rolling context window
    history = state.get("state_history", [])
    history.append(robot_state)
    if len(history) > 10:  # Keep last 10 states
        history.pop(0)
    
    return {
        **state,
        "robot_state": robot_state,
        "state_history": history,
        "step_count": state.get("step_count", 0) + 1
    }

def plan_node(state):
    """
    Use LLM to decide next action based on goal and current state.
    """
    system_prompt = """You are a robot controller. Given the robot's current state and goal:
1. Analyze what you observe
2. Explain your reasoning
3. Decide the next action: move, turn, stop, or grab
4. Return JSON: {"action": {...}, "reasoning": "..."}
"""
    
    user_message = f"""
Goal: {state['goal']}

Current Robot State:
- Position: {state['robot_state'].get('position')}
- Orientation: {state['robot_state'].get('compass')}
- Proximity sensors: {state['robot_state'].get('proximity')}
- Step: {state['step_count']} / 50

What should the robot do next?
"""
    
    response = client.messages.create(
        model="gpt-4o-mini",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}]
    )
    
    # Parse LLM response
    try:
        plan = json.loads(response.content[0].text)
    except:
        plan = {"action": {"type": "stop"}, "reasoning": "Error parsing LLM response"}
    
    return {**state, "plan": plan}

def act_node(state):
    """
    Execute the planned action.
    """
    plan = state.get("plan", {})
    action = plan.get("action", {"type": "stop"})
    
    try:
        result = bridge.execute_action(action)
        state["action"] = action
        return state
    except Exception as e:
        return {**state, "error": str(e)}

def evaluate_node(state):
    """
    Check if goal is achieved or if robot is stuck.
    """
    # TODO: Implement goal-specific success detection
    # For now, just check for stagnation
    
    success = False  # Replace with actual goal check
    
    return {
        **state,
        "success": success
    }
```

### 4.3 System Prompts (`src/agent/prompts.py`)

Support multiple prompting strategies for ablation:

```python
PROMPTS = {
    "raw": {
        "system": "You are a robot controller. Analyze state and decide actions.",
        "strategy": "Direct instruction"
    },
    "cot": {
        "system": """You are a robot controller. For each step:
1. Observe the world
2. Reason about the goal
3. Plan next action
4. Explain your decision
Then output JSON.""",
        "strategy": "Chain-of-thought"
    },
    "structured": {
        "system": """You are a robot controller. Respond with:
{
  "observation": "What do you see?",
  "reasoning": "Why do you choose this action?",
  "action": {"type": "...", "params": {...}},
  "confidence": 0.0-1.0
}""",
        "strategy": "Structured output"
    }
}
```

**Testing:** `tests/test_agent_integration.py`
```python
async def test_agent_e2e():
    """Test full agent loop with Webots."""
    from src.agent.graph import agent
    
    initial_state = {
        "goal": "Move forward 2 meters",
        "robot_state": {},
        "state_history": [],
        "plan": "",
        "action": {},
        "step_count": 0,
        "success": False,
        "error": ""
    }
    
    final_state = await agent.ainvoke(initial_state)
    print(f"Agent completed in {final_state['step_count']} steps")
    print(f"Success: {final_state['success']}")
```

---

## Phase 5: Integration & Benchmarking (Weeks 6–8)

### 5.1 Task Benchmark (`benchmarks/tasks.py`)

Define 5+ standardized scenarios:

```python
TASKS = {
    "navigate_target": {
        "description": "Navigate to a marked target location",
        "world": "arena.wbt",
        "goal": "Move to the green sphere at position (5, 0, 0)",
        "success_criteria": "Distance to target < 0.5m",
        "timeout_steps": 50
    },
    "obstacle_avoidance": {
        "description": "Navigate around obstacles",
        "goal": "Reach the far side of the arena without hitting walls",
        "success_criteria": "Reached far side AND no collision",
        "timeout_steps": 100
    },
    "fetch_object": {
        "description": "Fetch and return an object",
        "goal": "Pick up the red cube and bring it to the start",
        "success_criteria": "Robot holding object and at start position",
        "timeout_steps": 150
    },
    # ... more tasks
}
```

### 5.2 Benchmark Runner (`benchmarks/run_benchmark.py`)

```python
"""
Run agent on task suite and measure success rates.
"""
import asyncio
from src.agent.graph import agent
from benchmarks.tasks import TASKS

async def run_task(task_name, num_runs=5):
    """Run a task multiple times and report success rate."""
    task = TASKS[task_name]
    successes = 0
    
    for run in range(num_runs):
        initial_state = {
            "goal": task["goal"],
            "robot_state": {},
            "state_history": [],
            "plan": "",
            "action": {},
            "step_count": 0,
            "success": False,
            "error": ""
        }
        
        final_state = await agent.ainvoke(initial_state)
        if final_state["success"]:
            successes += 1
        
        print(f"  Run {run+1}: {'✓' if final_state['success'] else '✗'}")
    
    success_rate = successes / num_runs
    print(f"{task_name}: {success_rate*100:.1f}% success rate ({successes}/{num_runs})")
    return success_rate

async def main():
    """Run full benchmark suite."""
    results = {}
    for task_name in TASKS.keys():
        print(f"\nBenchmarking: {task_name}")
        results[task_name] = await run_task(task_name, num_runs=5)
    
    print("\n" + "="*50)
    print("Summary:")
    for task, rate in results.items():
        print(f"  {task}: {rate*100:.1f}%")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Phase 6: Experimentation & Ablation (Weeks 8–9)

### 6.1 Prompt Strategy Comparison

Run each task with:
1. **Raw:** Direct "move forward" instructions
2. **CoT (Chain-of-Thought):** Structured reasoning steps
3. **Structured:** Enforced JSON output format

### 6.2 LLM Backend Comparison

Compare:
- **GPT-4o-mini** (cloud, baseline)
- **Ollama Llama 3** (local, latency/cost tradeoff)

### 6.3 Critical Challenges to Address

From the presentation, you'll encounter:

| Challenge | Mitigation Strategy |
|-----------|-------------------|
| **LLM Latency (0.5–2s)** | Slow sim speed (0.1x), cache state descriptions, pipeline multiple steps |
| **Spatial Reasoning Drift** | Rolling context window (last 10 states), absolute coordinates, waypoint decomposition |
| **Prompt Sensitivity** | Systematic ablation (3 prompt formats), measure variance |
| **MCP-Webots Sync** | Retry logic, connection pooling, graceful degradation |
| **Stuck State Loop** | Stagnation detector in evaluate node, force re-plan after N identical states |
| **Local LLM Gap** | Benchmark Ollama vs GPT-4o-mini, measure quality delta |

---

## Critical Files & References

**Start Here:**
- `src/common/config.py` — All centralized configuration
- `src/webots/controllers/tcp_controller.py` — Robot-simulator bridge
- `src/agent/graph.py` — Agent orchestration

**Core Integration:**
- `src/mcp_server/server.py` — Tool exposure to agent
- `src/agent/nodes.py` — Sense/Plan/Act/Evaluate logic

**Testing & Benchmarking:**
- `tests/test_webots_connection.py` — TCP handshake validation
- `benchmarks/run_benchmark.py` — Task success measurement

**Research Foundation:**
- Paper: "Leveraging Large Language Models for Autonomous Robotic Mapping and Navigation" (Pascual Espada et al., 2025)

---

## Implementation Order (Dependency Graph)

```
1. Phase 1 (Scaffolding)
   ├─ Create directory structure
   ├─ Write requirements.txt
   └─ Define src/common/ types & config

2. Phase 2 (Webots)
   ├─ Create .wbt world file in Webots
   ├─ Write tcp_controller.py
   └─ Test with test_webots_connection.py ✓

3. Phase 3 (MCP)
   ├─ Implement src/mcp_server/server.py
   ├─ Define tools.py
   └─ Test with test_mcp_tools.py ✓

4. Phase 4 (Agent)
   ├─ Build src/agent/graph.py
   ├─ Implement nodes.py
   ├─ Add prompts.py
   └─ Test with test_agent_integration.py ✓

5. Phase 5 (Integration)
   ├─ Run full pipeline with agent + simulator
   └─ Debug connections (TCP, MCP, LLM)

6. Phase 6 (Benchmarking & Ablation)
   ├─ Run benchmarks/run_benchmark.py
   ├─ Compare prompt strategies
   └─ Compare LLM backends
```

---

## Verification Strategy

**Unit Tests (verify each component works in isolation):**
- ✓ TCP socket connection to Webots
- ✓ MCP tool calls and responses
- ✓ LangGraph state transitions
- ✓ LLM prompt formatting

**Integration Tests (verify components talk to each other):**
- ✓ Agent→MCP→Webots→Agent loop (1 full cycle)
- ✓ State consistency across agent steps
- ✓ Error recovery (dropped TCP, invalid LLM response)

**End-to-End Tests (verify system accomplishes goals):**
- ✓ Robot completes ≥3 distinct tasks
- ✓ Success rate ≥50% for basic tasks
- ✓ Reasoning trace visible and coherent
- ✓ Live demo: "type goal" → "robot acts"

**Ablation Studies (measure what matters):**
- Success rate: raw vs CoT vs structured prompts
- Latency impact: sim speed at 0.05x, 0.1x, 0.5x
- LLM quality: GPT-4o-mini vs Ollama on same 10 runs

---

## Next Steps

1. **Copy this plan** and create `src/common/types.py` + `src/common/config.py` first
2. **Set up Webots world** and verify the TCP controller works
3. **Build the MCP server** to expose Webots as callable tools
4. **Implement the LangGraph agent** step by step (Sense → Plan → Act → Evaluate)
5. **Test each component** as you go (don't integrate all at once)
6. **Run benchmarks** to see where performance breaks down
7. **Iterate on prompts** once the pipeline is working

**You have LangGraph installed already.** Next, install anthropic SDK:
```bash
pip install -r requirements.txt
```

This plan is designed to be **modular**—each phase builds on the previous one without dependencies on your teammates. You can test Webots independently, test MCP independently, test the agent independently, then wire them together.
