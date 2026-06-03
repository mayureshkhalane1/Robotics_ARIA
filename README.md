# ARIA: Autonomous Robot Intelligence Architecture

Pioneer 3-DX robot in Webots R2025a that systematically explores a room, builds a spatial memory of what it finds, and on subsequent runs navigates directly to previously-seen objects.  Runs entirely in WSL2 (Python agent) + Windows (Webots + Ollama).

---

## How it works

```
┌─────────────────── Browser UI (http://localhost:8080) ───────────────────┐
│  live camera · YOLO detections · grid progress · spatial memory summary  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ WebSocket
              ┌─────────────────▼──────────────────┐
              │           ARIA Agent               │
              │  ┌───────────┐  ┌────────────────┐ │
              │  │GridExplor │  │ SpatialMemory  │ │   ← NEW
              │  │ (vacuum)  │  │ (JSON on disk) │ │
              │  └─────┬─────┘  └───────┬────────┘ │
              │        │  nav_action     │ recall   │
              │  ┌─────▼─────────────── ▼────────┐ │
              │  │  Sense → Navigate → Act        │ │
              │  │  YOLO · Compass · GPS · Sonar  │ │
              │  └────────────────────────────────┘ │
              │  (LLM via Ollama — optional layer)  │
              └─────────────────┬──────────────────┘
                                │ TCP 19997
              ┌─────────────────▼──────────────────┐
              │   Webots  (Windows)                │
              │   Pioneer 3-DX  ·  break_room.wbt  │
              └────────────────────────────────────┘
```

**First run** — robot has no prior knowledge, visits 32 waypoints in a lawnmower grid (every 1.5 m), does a 360° YOLO scan at each stop, and records every detection + GPS position to `logs/spatial_memory.json`.

**Subsequent runs** — agent loads `spatial_memory.json` and navigates straight to the nearest known position of the requested object.

---

## Quick start

### Prerequisites

| Tool    | Version | Notes                                     |
| ------- | ------- | ----------------------------------------- |
| Python  | 3.10+   | run in WSL2                               |
| Webots  | R2025a  | run on Windows                            |
| Ollama  | any     | run on Windows — optional but recommended |

### 1. Install Python dependencies (WSL2)

```bash
cd /mnt/e/Leiden/Year-1/Sem-2/ENV/Robotics/Robotics_ARIA
pip install -r requirements.txt   # or: uv sync --group dev
```

### 2. Open the world in Webots (Windows)

Open Webots → **File → Open World**:
```
src/webots/worlds/Project/worlds/break_room.wbt
```
Press **Play (▶)**.  The TCP controller starts automatically and listens on port 19997.

### 3. Start the ARIA agent (WSL2)

```bash
python -m src.ui.server
```

Open `http://localhost:8080`, type a goal (e.g. `find the dog`), click **Run**.

### 4. Ollama — make it reachable from WSL2 (Windows PowerShell)

By default Ollama binds only to `127.0.0.1` on Windows and WSL2 cannot reach it.  Run this **before** starting `ollama serve`:

```powershell
$env:OLLAMA_HOST = "0.0.0.0"
ollama serve
```

The agent auto-detects the WSL2 gateway IP and uses `http://172.20.x.x:11434`.  Without Ollama the grid navigation still works — the LLM layer is optional.

---

## Configuration

Copy `.env.example` to `.env` and edit if needed:

```bash
cp .env.example .env
```

| Variable                | Default              | Notes                          |
| ----------------------- | -------------------- | ------------------------------ |
| `WEBOTS_HOST`           | auto-detected        | WSL2 gateway or `localhost`    |
| `OLLAMA_BASE_URL`       | auto-detected        | WSL2 gateway or `localhost`    |
| `OLLAMA_VISION_MODEL`   | `llava-phi3:latest`  | image description              |
| `OLLAMA_REASONING_MODEL`| `llava-phi3:latest`  | action decisions               |
| `WEBOTS_WORLD_FILE`     | `break_room.wbt`     | path to active world           |
| `MAX_STEPS`             | 50                   | UI run limit                   |

---

## Project structure

```
src/
├── agent/
│   ├── aria_agent.py          # main agent loop (grid nav + spatial mem + LLM)
│   ├── grid_explorer.py       # boustrophedon waypoint grid from .wbt floor
│   ├── spatial_memory.py      # persistent discovery store (logs/spatial_memory.json)
│   ├── world_knowledge.py     # .wbt parser → room/object positions
│   ├── graph.py               # simple reactive agent (python main.py)
│   └── nodes.py               # reactive agent nodes
├── common/
│   └── config.py              # all settings; auto-detects WSL2 gateway
├── mcp_server/
│   └── server.py              # MCP bridge → Webots TCP commands
├── perception/
│   ├── object_detector.py     # YOLOv8n (conf=0.5)
│   └── camera.py              # frame manager
└── ui/
    └── server.py              # aiohttp dashboard (default policy: aria)

src/webots/worlds/Project/
├── worlds/break_room.wbt      # active Webots world
└── controllers/tcp_controller/
    └── tcp_controller.py      # Webots-side TCP server (step-based motion)

logs/
└── spatial_memory.json        # persists object locations between sessions
```

---

## Navigation behaviour

### Grid exploration (no prior memory)

The room floor (`Floor` node in the `.wbt`) is parsed to extract bounds (12.9 × 7.7 m navigable area).  32 waypoints at 1.5 m spacing are generated in a **boustrophedon** (vacuum-cleaner) pattern.

At each waypoint:

1. Navigate using compass heading + GPS bearing
2. On arrival: do a **360° scan** (4 × 90° turns, YOLO at each orientation)
3. Record every detection to `spatial_memory.json`
4. Move to nearest unvisited waypoint

### Recall navigation (object seen before)

On startup, `SpatialMemory` loads prior detections.  If the requested target is in memory, the agent skips the grid and navigates straight to the nearest known position.

### Sensor safety (always active, cannot be overridden)

- `OBSTACLE_THRESH = 800` — Pioneer 3DX sonar value above which something is within ≈0.5 m
- Front blocked → turn toward clearer side
- Critical proximity (>970) → back up + turn

---

## Troubleshooting

### Robot spins in place / goes wrong direction

Bearing calculation uses `heading = atan2(compass.bx, compass.bz)` where `heading=0°` = east, `heading=90°` = north.  The grid_explorer uses `atan2(dy, dx)` to compute target bearing.  If anything looks inverted, check these two conventions match.

### Steps take 45–60 seconds

Ollama is not reachable — each LLM call waits for a timeout.  Start Ollama with `$env:OLLAMA_HOST = "0.0.0.0"` (see step 4 above).  The agent detects the failure and skips LLM calls for 10 steps before retrying.

### "Connection refused" on port 19997

Webots is not running or the simulation is paused.  Click **Play (▶)** in Webots.

### Spatial memory has wrong positions

Delete `logs/spatial_memory.json` to start fresh.  Or from Python:

```python
from src.agent.spatial_memory import SpatialMemory
SpatialMemory().clear_world()
```

### Webots world not loading / missing sensors

The Pioneer3dx in `break_room.wbt` needs `controller "tcp_controller"` plus Camera, Compass, and GPS in `extensionSlot`.  These are already in place — do not revert to the Webots default controller.
