# ARIA: Autonomous Robot Intelligence Architecture

A Pioneer 3-DX in Webots R2025a that **explores a room on its own** - it builds a live map from its **Lidar** (it is never given the floor plan), drives toward unexplored space, and looks for a target with YOLO. What it finds is saved to a spatial memory so later runs can go straight to a known object. The Python agent runs in WSL2; Webots (and optionally Ollama) run on Windows.

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
              │  └──────┬───────┘   record │         │
              │   carrot │                 │         │
              │  ┌───────▼─────────────────▼──────┐  │
              │  │  Sense → Explore → Act          │  │
              │  │  Lidar · YOLO · Compass · GPS   │  │
              │  │         · Sonar (safety)        │  │
              │  └─────────────────────────────────┘  │
              │  (LLM via Ollama - optional layer)    │
              └──────────────────┬────────────────────┘
                                 │ TCP 19997
              ┌──────────────────▼─────────────────┐
              │   Webots  (Windows)                 │
              │   Pioneer 3-DX  ·  break_room.wbt   │
              └─────────────────────────────────────┘
```

**Each run** - the robot starts knowing nothing about the walls. Every step it ray-casts its 360° Lidar into an occupancy grid (free / occupied / unknown) and drives toward the nearest **frontier** (the edge of the unknown). Frontiers sit at openings, so it flows through gaps into unexplored areas and around obstacles, discovering the layout. YOLO runs on every frame; every detection + GPS position is saved to `logs/spatial_memory.json`. The target is acted on when YOLO actually sees it (see "find" vs "approach" below).

**Memory** - `spatial_memory.json` is loaded for reference/UI only; it does **not** drive navigation. Recall-driving was removed because it overrode exploration and, being keyed to the world file, could chase a stale coordinate from another world.

Nothing in the navigation reads wall positions from the `.wbt` or relies on wall colour - obstacles are discovered with sensors. The live sonar ring is the collision backstop; the Lidar is for mapping.

---

## Quick start

### Prerequisites

| Tool    | Version | Notes                                     |
| ------- | ------- | ----------------------------------------- |
| Python  | 3.10+   | run in WSL2                               |
| Webots  | R2025a  | run on Windows                            |
| Ollama  | any     | run on Windows - optional                 |

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

### 4. Ollama - optional, make it reachable from WSL2 (Windows PowerShell)

The LLM is an optional "describe the scene" layer; navigation works fully without it. By default Ollama binds only to `127.0.0.1` and WSL2 cannot reach it. Run this **before** `ollama serve`:

```powershell
$env:OLLAMA_HOST = "0.0.0.0"
ollama serve
```

Two env vars matter for Ollama (set them in the **same** PowerShell before `ollama serve`):

```powershell
$env:OLLAMA_HOST = "0.0.0.0"        # bind all interfaces so WSL2 can reach it
$env:OLLAMA_KEEP_ALIVE = "30m"      # keep the model warm (avoids ~60s cold-start per call)
ollama serve
```

`$env:` vars last only for that PowerShell window, so you set them **every time** - unless you make them permanent once with:

```powershell
setx OLLAMA_HOST "0.0.0.0"
setx OLLAMA_KEEP_ALIVE "30m"
```

(then just `ollama serve`; restart the terminal once for `setx` to take effect). You may also need to allow **port 11434 through Windows Defender Firewall** for WSL.

**Don't want the LLM?** It's optional - set `ARIA_USE_LLM=0` in `.env` and the agent never calls Ollama (navigation + YOLO detection are unaffected and startup is fastest).

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
| `ARIA_USE_LLM`               | `1`                  | set `0` to skip Ollama entirely         |
| `YOLO_MODEL`                 | `yolov8s`            | COCO detector; `yolov8s-world.pt` for open-vocab |
| `YOLO_CONF`                  | `0.35`               | detection confidence floor; lower (e.g. `0.25`) to catch faint/flickering targets |
| `WEBOTS_WORLD_FILE`          | `break_room.wbt`     | fallback only - the loaded world is auto-detected from Webots (see below) |
| `ARIA_LOG_KEEP`              | `5`                  | how many newest run logs stay git-tracked |
| `MAX_STEPS`                  | 50                   | UI run limit                            |

**Run logs.** Every run is captured to `logs/run_<timestamp>.log` with a wall-clock timestamp per line, a per-step timing line (`dt sense+yolo=… plan=… llm=… move=…`), and a motion-feedback line (`MOVED dist=… turned=… reached=…`) showing how far the robot actually translated/rotated. The `logs/` folder is git-ignored **except** the latest `ARIA_LOG_KEEP` run logs: when you stop `python -m src.ui.server`, [`src/common/log_retention.py`](src/common/log_retention.py) rewrites the whitelist in `.gitignore` so only the newest few logs are committable (run it manually with `python -m src.common.log_retention [N]`).

**World auto-detection.** The TCP controller reports the world Webots actually loaded (`get_state → "world"`); the agent keys spatial memory and floor bounds to it, so you don't have to keep `WEBOTS_WORLD_FILE` in sync when you switch worlds.

---

## Project structure

```
src/
├── agent/
│   ├── aria_agent.py          # main loop: sense → frontier explore → act → pursue
│   ├── online_map.py          # live Lidar occupancy grid + frontier planner
│   ├── grid_explorer.py       # heading→turn helper + 360° scan state machine
│   ├── spatial_memory.py      # record-only discovery store (logs/*.json)
│   ├── environment_graph.py   # lightweight pose/observation graph
│   └── main.py                # headless CLI entry (python -m src.agent.main)
├── common/
│   ├── config.py              # all settings; auto-detects WSL2 gateway
│   ├── log_retention.py       # trims .gitignore to the newest N run logs
│   └── types.py               # shared dataclasses
├── mcp_server/
│   └── server.py              # bridge → Webots TCP commands
├── perception/
│   ├── object_detector.py     # YOLOv8s (conf=0.35); YOLO-World if model has "world"
│   └── camera.py              # frame manager
└── ui/
    └── server.py              # aiohttp dashboard (aria policy)

src/webots/worlds/Project/
├── worlds/break_room.wbt      # active world (Pioneer + Camera/Compass/GPS/Lidar)
└── controllers/tcp_controller/
    └── tcp_controller.py       # Webots-side TCP server; closed-loop motion; reports world

logs/
└── spatial_memory.json         # persists object locations between sessions
```

---

## Navigation behaviour

### Finding a target: "find" vs "approach"

The goal text decides what happens when YOLO sees the target:

- **`find the dog`** → the robot **stops and looks at it** the moment it's detected (success).
- **`find the dog and approach it`** (or "go to / navigate to / reach …") → the robot **drives to it** using visual servoing (centre the target in the camera, move forward) until it fills the frame, then stops (success).

Target pursuit overrides exploration and the scan, so once the target is seen the robot commits to it instead of wandering off.

**Detectable objects:** standard YOLO only knows the 80 **COCO** classes - `dog`, `cat`, `sports ball`, `bottle`, `chair`, `person`, etc. work. A **`duck`** or **`wooden box`** are *not* COCO classes, so the default model can't find them by name. To find arbitrary objects, set an **open-vocabulary** model in `.env`: `YOLO_MODEL=yolov8s-world.pt` - the agent then tells it the target words (YOLO-World detects them by text).

**Quadruped aliasing:** YOLO frequently flips a single rendered animal between COCO quadrupeds (the Webots dog reads as `horse` up close, `dog`/`sheep` at range). So `find the dog` also accepts `cat/horse/sheep/cow/bear/…` as the target - pragmatic for these single-animal test worlds. If a detection is faint, lowering `YOLO_CONF` (e.g. to `0.25`) lets it through. See [`ARIA_STATUS.md`](ARIA_STATUS.md) for the validation notes behind this.

### Autonomous exploration (no prior memory)

Built entirely from the robot's own sensors - the `.wbt` floor plan is never read for obstacles.

Deliberate **look-around → drive** cycle (the robot rotates, identifies, then acts - it does not spin reactively):

1. **Look around** - a 360° scan in **45° steps** (8 orientations); YOLO + Lidar run at each, building the occupancy grid and checking every direction for the target.
2. **Frontier** - from the freshly-scanned map, pick the nearest reachable *frontier* (a free cell touching the unknown). BFS over discovered free space gives a path; the robot steers toward a "carrot" ~0.7 m along it.
3. **Drive** - head to the frontier with fine **45° aiming turns** (a 25° deadband means it converges on a heading instead of oscillating between two 90°-apart ones).
4. **Repeat / give up** - on arrival, look around again; if it can't get closer for several steps (furniture the Lidar missed), it blacklists that frontier and re-scans.
5. **Done** - when no reachable frontier remains, the reachable area is fully explored.

### Spatial memory (record-only)

Every YOLO detection is saved to `logs/spatial_memory.json` for analysis and the UI.
Memory does **not** drive navigation: the robot always explores from its own sensors and
lets YOLO pursuit handle the target when it is actually seen. (Blind-driving to a stored
coordinate was removed - it overrode exploration and, because memory is keyed by the
configured world file rather than the world Webots actually loaded, could chase a stale
coordinate from another world and spin in place. See `ARIA_STATUS.md`.)

### Motion & heading

- Turns/moves are **closed-loop**: the controller spins until the compass has rotated the requested angle (or GPS shows the requested distance), then stops the wheels itself - deterministic regardless of the Webots speed slider.
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

Some builds dislike a full-circle (2π) fixed Lidar. In `break_room.wbt` change the Lidar `fieldOfView` from `6.2831853` to `3.14159` (180° forward) - the robot will turn to map behind it.

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
