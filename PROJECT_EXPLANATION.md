# ARIA — Autonomous Robot Intelligence Architecture
## Complete Project Explanation Document

---

## 1. What is ARIA?

ARIA is an **autonomous indoor navigation robot** built on top of the **Webots** robotics simulator. It uses a **Vision-Language Model (VLM)** and **YOLO object detection** to navigate a simulated apartment, find specific objects, and stop when the target is reached.

The system runs in a **split environment**:
- **Webots** runs on **Windows** (robot simulation)
- **Python agent + web UI** runs in **WSL2** (Linux on Windows)

Communication between them happens over a **TCP socket** on port `19997`.

---

## 2. Hardware / Simulator

### Robot: Pioneer 3-DX (Differential Drive)
- Two wheels, controlled by independent motor velocities
- Wheel radius: **0.097 m**, half-track: **0.1564 m**
- Forward at velocity **4.0 rad/s** → ~**0.388 m/s** linear speed
- 90° turn at **1.5 rad/s** angular velocity takes ~**1.7 seconds**

### Sensors available on the robot:
| Sensor | Name in code | Purpose |
|--------|-------------|---------|
| Proximity sensors | `so0`–`so15` | 16 ultrasonic sensors around the robot |
| GPS | `gps` | Absolute position `(x, y, z)` in the world |
| Compass | `compass` | Orientation vector to compute heading |
| Camera | `camera` | 320×240 pixel RGB camera, BGRA encoded |

### World: Indoor Apartment
- File: `src/webots/indoor/worlds/complete_apartment.wbt`
- Multi-room apartment with kitchen, bedroom, bathroom, living room
- Contains objects: chairs, tables, cups, bottles, couches, clocks, plants, etc.

---

## 3. System Architecture (Layered)

```
┌─────────────────────────────────────┐
│         Browser UI (port 8080)      │  ← User gives goal (e.g. "find cup")
├─────────────────────────────────────┤
│        aiohttp Web Server           │  ← src/ui/server.py
│   WebSocket /ws  |  WebSocket /cam  │
├─────────────────────────────────────┤
│        ARIA Agent (main brain)      │  ← src/agent/aria_agent.py
│  SENSE → DETECT → VLM → ACT loop   │
├──────────────┬──────────────────────┤
│  YOLO        │  Ollama VLM          │
│  (local)     │  (Windows, llava-phi3│
│  YOLOv8n.pt  │  via HTTP REST API)  │
├──────────────┴──────────────────────┤
│       MCP Bridge (Tool Layer)       │  ← src/mcp_server/server.py
│  call_tool("get_state", ...)        │
│  call_tool("execute_action", ...)   │
├─────────────────────────────────────┤
│     TCP Socket (port 19997)         │  ← WSL2 → Windows gateway IP
├─────────────────────────────────────┤
│   Webots TCP Controller             │  ← src/webots/controllers/tcp_controller/
│   (runs INSIDE Webots on Windows)   │
├─────────────────────────────────────┤
│   Webots Simulator (Windows)        │
│   Pioneer 3-DX robot + apartment    │
└─────────────────────────────────────┘
```

---

## 4. Files and What They Do

### `src/webots/controllers/tcp_controller/tcp_controller.py`
**The Webots robot controller** — runs *inside* the simulator.

- Initializes motors, proximity sensors (so0–so15), GPS, Compass, Camera
- Opens a **TCP server on port 19997** bound to `0.0.0.0` (so WSL2 can reach it)
- Listens for JSON commands from the agent:
  - `{"cmd": "get_state", "include_camera": true}` → returns all sensor readings + camera image
  - `{"cmd": "execute", "action": {"type": "move", "params": {"velocity": 4.0}}}` → sets motor velocities
  - `{"cmd": "stop"}` → stops all motors
- After setting motor velocity, it calls `robot.step()` to actually apply the command in the physics engine (critical — without stepping, motors don't move)

### `src/mcp_server/server.py`
**The MCP (Model Context Protocol) Bridge** — Python layer that wraps TCP calls into clean function calls.

- `WebotsBridge` class manages the TCP socket connection (with auto-reconnect)
- Exposes named tools:
  - `call_tool("get_state", {"include_camera": True})` → sensor readings
  - `call_tool("execute_action", {"action_type": "move", "velocity": 4.0})` → move
  - `call_tool("stop", {})` → emergency stop
- Handles large responses (camera frames are ~327 KB base64-encoded)
- Thread-safe (uses a lock for concurrent access)

### `src/agent/aria_agent.py`
**The main ARIA agent** — the brain of the system.

Each step (every ~5 seconds) it runs this loop:

```
1. SENSE    → call get_state: get GPS position, compass heading, proximity sensors, camera
2. DECODE   → convert BGRA camera bytes → BGR numpy array (OpenCV format)
3. YOLO     → run YOLOv8n on the frame → list of detected objects with bounding boxes
4. VLM      → send camera image + context to llava-phi3 (Ollama) → get action as JSON
5. SAFETY   → override VLM action if front is blocked (obstacle avoidance)
6. STUCK    → detect if robot is spinning in circles; switch direction to escape
7. EXECUTE  → call execute_action with chosen motion command
8. GRAPH    → record position + detected objects in the environment graph
9. CHECK    → if YOLO confirms target found → stop and declare success
```

**Key constants:**
- `CYCLE_INTERVAL = 5.0` seconds per step
- `MOVE_DURATION = 2.5` seconds of driving per move command
- `MOVE_VELOCITY = 4.0` rad/s wheel speed
- `TURN_90_DUR = 1.7` seconds for a 90° turn
- `OBSTACLE_THRESH = 600` proximity sensor reading threshold (higher = closer)

**Target extraction:** `_extract_target("find fire extinguisher and approach it")` → `"fire extinguisher"`. Uses a keyword dictionary and a stopword filter to avoid returning pronouns like "it" as the target.

**Stuck detection:** If the safety override forces `turn_left_90` three times in a row with no right turns, it switches to `turn_right_90`. If total blocked turns ≥ 4, it does `turn_around`.

### `src/perception/object_detector.py`
**YOLO-based object detector.**

- Model: **YOLOv8n** (nano, ~3.3M parameters, fast)
- Trained on **COCO-80** classes (80 everyday objects)
- Detectable objects include: bottle, cup, chair, couch, bed, table, laptop, sink, toilet, plant, TV, fridge, etc.
- Returns `Detection` objects with: `class_name`, `confidence`, `bbox (x1,y1,x2,y2)`, `center (cx,cy)`
- Confidence threshold: **0.5** (50%), NMS IoU: **0.45**
- Note: **fire extinguisher is NOT in COCO-80** — the VLM (llava-phi3) must visually confirm it instead

### `src/perception/camera.py`
**Camera manager** — decodes and stores the latest camera frame.

- Receives BGRA-encoded bytes from Webots, converts to BGR (OpenCV native format)
- Shared globally so both the agent and UI can access the latest frame
- `get_frame(refresh=True)` fetches fresh frame; `get_frame()` returns cached

### `src/agent/environment_graph.py`
**Spatial memory as a graph** — tracks where the robot has been and what it has seen.

- Uses **NetworkX** (`nx.Graph`) as the graph data structure
- Each **node** = a robot position (merged if within 0.5m of existing node)
- Each **edge** = path between positions
- Stores detected objects per node (so you know "chair was seen at position (3.2, 1.1)")
- Supports shortest path finding (Dijkstra), loop closure detection, frontier exploration
- Statistics shown in the UI: total nodes, total edges, unique objects seen

### `src/common/config.py`
**Centralized configuration** — loads settings from `.env` or `.env.example`.

- Auto-detects WSL2 environment and uses the Windows gateway IP for Webots/Ollama
- Key settings: `WEBOTS_HOST`, `WEBOTS_PORT=19997`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL=llava-phi3`

### `src/ui/server.py` + `src/ui/static/index.html`
**Web dashboard** — browser-based control panel.

- Built with **aiohttp** (async Python web server)
- Serves the HTML UI at `http://localhost:8080`
- WebSocket `/ws` → streams agent events (step updates, reasoning, actions)
- WebSocket `/camera` → streams live annotated camera frames at ~15 FPS
- REST `POST /goal` → starts the agent with a goal
- REST `POST /stop` → cancels the current run
- UI shows: camera feed with YOLO bounding boxes, robot state (GPS, heading, sensors), memory/graph stats, step-by-step reasoning log

---

## 5. AI/ML Components Used

### YOLOv8n (You Only Look Once — Nano)
- **What it is:** Real-time object detection neural network
- **How it works:** Single forward pass through a CNN produces bounding boxes + class labels + confidence scores
- **Used for:** Detecting objects in the camera frame every step. When the target object is detected with confidence ≥ 50%, the robot stops.
- **Model file:** `yolov8n.pt` (3.3M parameters, ~6MB)
- **Library:** `ultralytics` Python package

### llava-phi3 (VLM — Vision Language Model)
- **What it is:** A multimodal LLM that accepts both an image and text prompt
- **How it works:** Takes the camera JPEG + a JSON context prompt, outputs a JSON action decision
- **Used for:** High-level reasoning — deciding whether to move forward, turn, or stop based on what it sees
- **Size:** 2.9 GB, runs on RTX 4050 Laptop (18/33 layers on GPU)
- **Runs via:** Ollama on Windows (`http://172.20.128.1:11434`)
- **API format:** Ollama's `/api/chat` REST endpoint (HTTP POST)
- **Timeout:** 90 seconds (allows for cold model load time ~33s)

### Prompt Engineering
The system prompt tells the VLM exactly what it is, what its constraints are, and what format to respond in:

```
You are ARIA, an autonomous indoor navigation robot.
Available actions: move_forward, turn_left_90, turn_right_90, turn_around, stop
Rules:
  1. Never move_forward if front_blocked is true
  2. Stop when target is visible and confirmed by yolo_detections
  3. Prefer unexplored directions
Respond ONLY with: {"action": "...", "reasoning": "...", "target_found": bool, "target_direction": "..."}
```

The user message is a JSON blob containing GPS position, heading, obstacle readings, YOLO results, visited positions, and the camera image.

---

## 6. Networking (WSL2 / Windows Split)

This is the trickiest part of the system. Two processes run on different network namespaces:

| Process | Where it runs | Address |
|---------|--------------|---------|
| Webots simulator | Windows | Listens on `0.0.0.0:19997` |
| Ollama LLM server | Windows | Listens on `0.0.0.0:11434` |
| Python agent + web UI | WSL2 (Linux) | `http://0.0.0.0:8080` |
| Browser | Windows | Connects to WSL2 at `localhost:8080` |

**The key insight:** In WSL2 NAT mode, `localhost` in WSL2 resolves to the Linux VM, not Windows. To reach Windows services from WSL2, you must use the **Windows gateway IP** (typically `172.20.128.1`).

The `config.py` auto-detects this by reading `/proc/sys/kernel/osrelease` and running `ip route show default` to find the gateway IP dynamically.

**Ollama must also be started with:**
```powershell
$env:OLLAMA_HOST = "0.0.0.0:11434"
ollama serve
```
Without this, Ollama only listens on `127.0.0.1` (Windows localhost) and WSL2 cannot reach it.

---

## 7. How to Run the System

### Step 1: Start Ollama on Windows (PowerShell)
```powershell
$env:OLLAMA_HOST = "0.0.0.0:11434"
ollama serve
```
(In a second terminal: `ollama pull llava-phi3` if not already downloaded)

### Step 2: Open Webots (Windows)
- Open `src/webots/indoor/worlds/complete_apartment.wbt`
- Press Play (the controller inside Webots connects on port 19997)

### Step 3: Start the Python server (WSL2 terminal)
```bash
cd /mnt/e/Leiden/Year-1/Sem-2/ENV/Robotics/Robotics_ARIA
python main.py
```

### Step 4: Open the browser
- Go to `http://localhost:8080`
- Type a goal (e.g. "find cup and approach it")
- Make sure policy is set to **ARIA (recommended)**
- Click **Run**

---

## 8. Data Flow — One Step in Detail

```
Browser: user types "find clock and approach it" → clicks Run
  ↓  POST /goal
aiohttp server → run_aria_agent("find clock and approach it", model="llava-phi3")
  ↓
aria_agent._extract_target() → "clock"
  ↓  (for each step)
call_tool("get_state", include_camera=True)
  ↓  TCP → Windows Webots controller
WebotsRobotServer.get_state() → GPS(x,y,z) + compass + so0..so15 + BGRA camera bytes
  ↓  JSON response over TCP back to WSL2
_decode_camera_frame() → BGR numpy array (240×320×3)
  ↓
YOLOv8n.detect(frame) → [Detection(class_name="clock", conf=0.72, bbox=...)]
  target_found_yolo = ("clock" in detected names) → True
  ↓
_query_vlm(model, system_prompt, context_json, jpeg_b64)
  ↓  HTTP POST to 172.20.128.1:11434/api/chat
llava-phi3 sees image + context → responds: {"action":"stop","reasoning":"clock visible center frame","target_found":true}
  ↓
Safety check: front_blocked? No → keep action = "stop"
  ↓
target_found_yolo = True → action overridden to "stop"
  ↓
call_tool("stop", {}) → robot halts
  ↓  WebSocket broadcast
Browser UI: log shows "SUCCESS at step N: clock found"
```

---

## 9. Key Libraries / Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| `ultralytics` | latest | YOLOv8 inference |
| `opencv-python` | ≥4.10 | Image decoding, JPEG encoding, drawing bounding boxes |
| `numpy` | ≥2.0 | Array operations on camera frames |
| `aiohttp` | 3.11 | Async web server + WebSocket |
| `networkx` | latest | Graph data structure for environment mapping |
| `python-dotenv` | 1.0 | Load config from `.env` files |
| `anthropic` | 0.38 | Anthropic API (available but Ollama used by default) |
| `langgraph` | 0.2.76 | Graph-based agent framework (available, not used in main ARIA agent) |
| `pillow` | ≥11.3 | Image utilities |
| `imagehash` | 4.3 | Perceptual image hashing for visual memory |

---

## 10. What Makes This System Interesting (For Presentation)

### 1. Grounded Language Understanding
The robot receives a plain English command ("find the fire extinguisher") and must translate it into physical robot actions. The system combines:
- **Symbolic keyword extraction** (fast, reliable for known objects)
- **Neural visual grounding** (VLM decides what to do when it sees the scene)

### 2. Sensor Fusion
The agent fuses multiple sensor modalities every step:
- **GPS** → absolute position in the world (knows where it is)
- **Compass** → heading direction (knows which way it faces)
- **Proximity sensors** → obstacle detection (knows what's immediately around it)
- **Camera + YOLO** → object detection (knows what objects are visible)
- **Camera + VLM** → scene understanding (knows what the whole scene means)

### 3. Safety Layer
The VLM's action is always checked against a safety rule before execution: if `front_blocked = true`, the move forward command is overridden. This prevents the LLM from crashing the robot into walls.

### 4. Stuck Detection / Escape Behavior
If the robot keeps turning left but never escapes a corner, the stuck detection flips to turn right, then tries a 180° turn. This is a simple but effective reactive behavior that prevents the robot from spinning forever.

### 5. Spatial Memory (Environment Graph)
Every position the robot visits is recorded as a node in a graph. Detected objects are stored at those nodes. This allows the system to know "I already visited position (3.2, 1.1) and saw a chair there" and avoid re-exploring the same areas.

### 6. Real-time Dashboard
The browser UI streams the live camera feed with YOLO bounding boxes drawn on it, along with the agent's step-by-step reasoning, so you can watch the robot "think" in real time.

---

## 11. Limitations to Be Aware Of

| Limitation | Details |
|-----------|---------|
| YOLO can't see fire extinguisher | Not in COCO-80 training data; relies solely on VLM visual confirmation |
| VLM cold start is slow | First Ollama call takes ~33 seconds to load the model into GPU memory |
| WSL2 networking complexity | Requires knowing the Windows gateway IP; breaks if IP changes |
| No path planning | Robot explores by trial and error, not by A* or similar planning |
| Single TCP connection | Only one agent can connect to Webots at a time |
| Simulation speed | `WEBOTS_SIM_SPEED=0.1` means simulation runs at 10% speed by default |

---

*This document was generated on 2026-05-19 to summarize the complete ARIA project.*
