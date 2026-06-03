# ARIA: Autonomous Robot Intelligence Architecture

A Pioneer 3-DX in Webots R2025a that **explores a room on its own** — it builds a live map from its **Lidar** (it is never given the floor plan), drives toward unexplored space, and looks for a target with YOLO. What it finds is saved to a spatial memory so later runs can go straight to a known object. The Python agent runs in WSL2; Webots (and optionally Ollama) run on Windows.

---

## How it works

```
┌─────────────────── Browser UI (http://localhost:8080) ───────────────────┐
│  live camera · YOLO detections · map stats · spatial memory summary      │
└───────────────────────────────┬──────────────────────────────────────────┘
                                 │ WebSocket
              ┌──────────────────▼─────────────────┐
              │            ARIA Agent               │
              │  ┌─────────────┐  ┌──────────────┐  │
              │  │ OnlineMap    │  │ SpatialMemory│  │
              │  │ (Lidar grid +│  │ (JSON on disk)│ │
              │  │  frontiers)  │  └──────┬───────┘  │
              │  └──────┬───────┘   recall │         │
              │   carrot │                 │         │
              │  ┌───────▼─────────────────▼──────┐  │
              │  │  Sense → Explore → Act          │  │
              │  │  Lidar · YOLO · Compass · GPS   │  │
              │  │         · Sonar (safety)        │  │
              │  └─────────────────────────────────┘  │
              │  (LLM via Ollama — optional layer)    │
              └──────────────────┬────────────────────┘
                                 │ TCP 19997
              ┌──────────────────▼─────────────────┐
              │   Webots  (Windows)                 │
              │   Pioneer 3-DX  ·  break_room.wbt   │
              └─────────────────────────────────────┘
```

**First run** — the robot starts knowing nothing about the walls. Every step it ray-casts its 360° Lidar into an occupancy grid (free / occupied / unknown) and drives toward the nearest **frontier** (the edge of the unknown). Frontiers sit at openings, so it flows through gaps into unexplored areas and around obstacles, discovering the layout. YOLO runs on every frame; every detection + GPS position is saved to `logs/spatial_memory.json`.

**Subsequent runs** — the agent loads `spatial_memory.json` and, if the requested target was seen before, routes straight to its nearest known position through the discovered free space.

Nothing in the navigation reads wall positions from the `.wbt` or relies on wall colour — obstacles are discovered with sensors. The live sonar ring is the collision backstop; the Lidar is for mapping.

---

## Quick start

### Prerequisites

| Tool    | Version | Notes                                     |
| ------- | ------- | ----------------------------------------- |
| Python  | 3.10+   | run in WSL2                               |
| Webots  | R2025a  | run on Windows                            |
| Ollama  | any     | run on Windows — optional                 |

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

Press **Play (▶)**. The TCP controller starts automatically and listens on port 19997. On start it prints the sensors it found, including `Lidar=True`.

### 3. Start the ARIA agent (WSL2)

```bash
python -m src.ui.server
```

Open `http://localhost:8080`, type a goal (e.g. `find the dog`), click **Run**.

### 4. Ollama — optional, make it reachable from WSL2 (Windows PowerShell)

The LLM is an optional "describe the scene" layer; navigation works fully without it. By default Ollama binds only to `127.0.0.1` and WSL2 cannot reach it. Run this **before** `ollama serve`:

```powershell
$env:OLLAMA_HOST = "0.0.0.0"
ollama serve
```

You may also need to allow **port 11434 through Windows Defender Firewall** for WSL. If you are not using the LLM, set `OLLAMA_VISION_TIMEOUT=5` in `.env` so an unreachable Ollama can't stall a step for the full 35 s timeout.

---

## Configuration

Copy `.env.example` to `.env` and edit if needed:

```bash
cp .env.example .env
```

| Variable                     | Default              | Notes                                   |
| ---------------------------- | -------------------- | --------------------------------------- |
| `WEBOTS_HOST`                | auto-detected        | WSL2 gateway or `localhost`             |
| `OLLAMA_BASE_URL`            | auto-detected        | WSL2 gateway or `localhost`             |
| `OLLAMA_VISION_MODEL`        | `llava-phi3:latest`  | image description                       |
| `OLLAMA_REASONING_MODEL`     | `qwen3:8b`           | action suggestions (optional)           |
| `OLLAMA_VISION_TIMEOUT`      | 35                   | per-LLM-call timeout (s); lower if no LLM |
| `OLLAMA_VISION_SAMPLE_INTERVAL` | 10                | min seconds between LLM calls           |
| `WEBOTS_WORLD_FILE`          | `break_room.wbt`     | path to active world                    |
| `MAX_STEPS`                  | 50                   | UI run limit                            |

---

## Project structure

```
src/
├── agent/
│   ├── aria_agent.py          # main loop: sense → frontier explore → act
│   ├── online_map.py          # live Lidar occupancy grid + frontier planner
│   ├── grid_explorer.py       # heading→turn helper + 360° scan state machine
│   ├── spatial_memory.py      # persistent discovery store (logs/*.json)
│   ├── environment_graph.py   # lightweight pose/observation graph
│   └── main.py                # headless CLI entry (python -m src.agent.main)
├── common/
│   ├── config.py              # all settings; auto-detects WSL2 gateway
│   └── types.py               # shared dataclasses
├── mcp_server/
│   └── server.py              # bridge → Webots TCP commands
├── perception/
│   ├── object_detector.py     # YOLOv8n (conf=0.5)
│   └── camera.py              # frame manager
└── ui/
    └── server.py              # aiohttp dashboard (aria policy)

src/webots/worlds/Project/
├── worlds/break_room.wbt      # active world (Pioneer + Camera/Compass/GPS/Lidar)
└── controllers/tcp_controller/
    └── tcp_controller.py       # Webots-side TCP server; closed-loop motion

logs/
└── spatial_memory.json         # persists object locations between sessions
```

---

## Navigation behaviour

### Autonomous exploration (no prior memory)

Built entirely from the robot's own sensors — the `.wbt` floor plan is never read for obstacles.

1. **Map** — each step, fuse the 360° Lidar scan into an occupancy grid (free / occupied / unknown) using the GPS+compass pose.
2. **Frontier** — pick the nearest reachable *frontier* (a free cell touching the unknown). BFS over discovered free space gives a path; the robot steers toward a "carrot" ~0.7 m along it.
3. **Look around** — on reaching a frontier, do a 360° turn so YOLO sees every direction and the map fills in.
4. **Give up gracefully** — if it can't get closer to a frontier for several steps (furniture the Lidar missed), it blacklists it and picks another.
5. **Done** — when no reachable frontier remains, the reachable area is fully explored.

### Recall navigation (object seen before)

On startup `SpatialMemory` loads prior detections. If the requested target is known, the agent routes to its nearest known position through the live free-space map.

### Motion & heading

- Turns/moves are **closed-loop**: the controller spins until the compass has rotated the requested angle (or GPS shows the requested distance), then stops the wheels itself — deterministic regardless of the Webots speed slider.
- World is **Z-up (ENU)**; heading = `atan2(compass.x, compass.y)` (`0°` = +X/east, `90°` = +Y/north).

### Sensor safety (always active)

- Sonar value `> 800` ≈ obstacle within ~0.5 m → if moving forward, turn to the clearer side.
- Critical proximity (`> 970`) → back up + turn. This is the real collision backstop; the map only guides exploration.

---

## Troubleshooting

### First step takes a long time

On step 1 the agent makes its first (optional) Ollama call before the fail-fast logic engages; if Ollama is unreachable that is up to two 35 s timeouts (~70 s), plus the first YOLO weight load. Fix Ollama (step 4) or set `OLLAMA_VISION_TIMEOUT=5` in `.env`.

### The live map looks mirrored / rotated (robot drives ~90° or 180° off)

The Lidar range-image index→angle convention can differ between Webots builds. Flip the single marked line in `update_lidar` (`online_map.py`): negate `rel`. Likewise, if the robot turns the *wrong way* toward targets, flip `_heading_from_orientation` (`aria_agent.py`) from `atan2(bx, by)` to `atan2(by, bx)`.

### Webots won't load the world (Lidar field error)

Some builds dislike a full-circle (2π) fixed Lidar. In `break_room.wbt` change the Lidar `fieldOfView` from `6.2831853` to `3.14159` (180° forward) — the robot will turn to map behind it.

### `URLError: timed out`

That is only the optional Ollama LLM, not a navigation error. Test from WSL2: `curl http://172.20.128.1:11434/api/tags`. If it hangs, it's the firewall/binding (step 4).

### "Connection refused" on port 19997

Webots is not running or is paused. Click **Play (▶)**.

### Spatial memory has wrong positions

Delete `logs/spatial_memory.json`, or from Python:

```python
from src.agent.spatial_memory import SpatialMemory
SpatialMemory().clear_world()
```

### Webots world not loading / missing sensors

The Pioneer3dx in `break_room.wbt` needs `controller "tcp_controller"` plus Camera, Compass, GPS, **and Lidar** in `extensionSlot`. Do not revert to the Webots default controller.
