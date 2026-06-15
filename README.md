# ARIA - Autonomous Robot Intelligence Architecture

ARIA drives a Pioneer 3-DX in Webots R2025a to find an object described in plain
language (e.g. "find the dog and approach it"). It explores the room with its own
sensors - a Lidar-built occupancy grid and frontier search - and decides whether the
target is in view using an optional local vision-language model (VLM) with a YOLO
object detector as fallback. There is no SLAM, no ROS, and no cloud LLM in the loop.

- **Authors:** Mayuresh Khalane, Ntolgka Nalmpant, Pruthvish Mallikarjuna Shirur
- **Course:** Leiden University (LIACS), Robotics 2026
- **Repository:** <https://github.com/mayureshkhalane1/Robotics_ARIA>

## How it runs

The Python agent runs in **WSL2 (Ubuntu)**. Webots - and optionally Ollama - run on
**Windows**. The agent talks to a controller inside Webots over a TCP socket
(port 19997); the browser dashboard is served on port 8080.

```
WSL2:  ARIA agent  <--TCP 19997-->  Webots (Windows): Pioneer 3-DX + tcp_controller
  |                                  Lidar / Camera / GPS / Compass / sonar
  +-- browser dashboard :8080
  +-- Ollama (optional, Windows) for the VLM perception layer
```

## Entry points

```bash
# Browser UI (recommended) - open http://localhost:8080, type a goal, press Start
python -m src.ui.server

# Headless CLI - one run, prints the result
python main.py --goal "find the dog and approach it" --steps 50
python main.py --perception-mode yolo_vlm --goal "find the sports ball"
```

Use the **UI** for demos and live camera/detection view; use the **CLI** for scripted
or headless runs. Both share the same agent loop. `--perception-mode` selects how
perception works (below); `python main.py --validate-only` checks the tool registry
without Webots.

## Setup

1. **Windows:** install **Webots R2025a**.
2. **WSL2:** `git clone` the repo and `cd` into it.
3. Install dependencies (either works):

   ```bash
   pip install uv && uv sync          # from pyproject.toml
   # or:
   pip install -r requirements.txt    # CUDA/torch variant
   ```

4. *(Optional, for the VLM)* install **Ollama** on Windows and pull the model:
   `ollama pull qwen3-vl:4b-instruct-q4_K_M`. Bind it for WSL2 with
   `set OLLAMA_HOST=0.0.0.0` before `ollama serve`.
5. `cp .env.example .env` and edit if needed (defaults work for most setups).
6. In Webots, open `src/webots/worlds/Project/worlds/break_room.wbt` and press **Play**.
7. In WSL2, run `python -m src.ui.server`, open `http://localhost:8080`, type a goal,
   press **Start**.

> First run auto-downloads the YOLO weights (~67 MB). The Pioneer PROTO is fetched from
> GitHub on Webots' first load, so the initial open needs internet.

## Configuration

Set via `.env` or environment variables (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `ARIA_USE_LLM` | `1` (`.env.example` ships `0`) | `0` disables the VLM entirely - fastest, sensor + YOLO only |
| `PERCEPTION_MODE` | `vlm_first` | `vlm_first`, `yolo_vlm`, `vlm_only`, or `sensor_only` |
| `OLLAMA_VISION_MODEL` | `qwen3-vl:4b-instruct-q4_K_M` | local VLM for target visibility |
| `OLLAMA_REASONING_MODEL` | `qwen3:8b` | optional reasoning model |
| `YOLO_MODEL` | `yolo11m` | object detector (auto-downloads weights) |
| `YOLO_CONF` | `0.25` | detection confidence floor |
| `WEBOTS_PORT` | `19997` | agent <-> controller TCP port |
| `MAX_STEPS` | `50` | max sense-decide-act steps per run |

`WEBOTS_HOST` and `OLLAMA_BASE_URL` auto-detect the WSL2->Windows gateway; leave them unset.

## Worlds

| World | Use |
| --- | --- |
| `Project/worlds/break_room.wbt` | furnished room - recommended for demos |
| `Project/worlds/empt_room.wbt` | open room - used for the paper experiments |
| `worlds/worlds/hall.wbt` | larger space |

The controller reports which world Webots actually loaded, so the agent keys its map and
spatial memory to the real world rather than a config guess.

## Package structure

```
src/agent/       aria_agent.py (sense-decide-act loop), online_map.py (Lidar occupancy
                 grid + frontier planner), grid_explorer.py (heading->turn + 360 scan),
                 spatial_memory.py (record-only discovery store), environment_graph.py
                 (pose/observation graph), main.py (headless CLI)
src/perception/  camera.py (frame manager), object_detector.py (YOLO11m)
src/mcp_server/  server.py (TCP bridge to the Webots controller; NOT MCP protocol)
src/common/      config.py (settings + WSL2 gateway detection), types.py, log_retention.py
src/ui/          server.py (aiohttp dashboard + WebSocket camera stream), static/index.html
src/webots/      world files and controllers/tcp_controller/tcp_controller.py
tests/           unit + integration tests
```

## Results (from the report)

- **Find plant, `empt_room`:** 14.3 m path over 83 steps, then a correct "not found"
  termination once the reachable area was fully explored.
- **Find sports ball, `empt_room`:** success in 32 steps, with 3 target-reacquisition
  cycles during the approach.

## Architecture note

The original proposal used LangGraph, the Model Context Protocol, and GPT-4o-mini. The
final system instead uses a deterministic Python sense-decide-act loop, a raw TCP bridge
to the Webots controller, and a local Ollama VLM. This pivot was made for latency and
reliability (no cloud round-trips, no network dependency in the control loop) and is
discussed in the report's Discussion section.

## Tests

```bash
python -m pytest -q
```

The `tests/test_environment_graph.py` suite is **skipped** on purpose: the
`EnvironmentGraph` API was rewritten (new `add_observation` signature, renamed methods)
and those tests are stale - the skip is marked with that reason rather than deleted, so
the debt is visible. Several Webots/bridge tests **skip automatically** when no live
simulator is running. The remaining unit tests cover config, perception gating, frontier
scoring, and state extraction.

## Requirements

- Python 3.12 (tested; `>=3.9` declared)
- Webots R2025a on Windows (required)
- ~67 MB of YOLO weights (auto-downloaded on first run)
- Ollama (optional - only needed for the VLM perception layer)
