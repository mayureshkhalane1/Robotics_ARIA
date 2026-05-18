# ARIA Vision System - Quick Start

## 60-Second Setup

### 1. Start Webots (Terminal 1)
```bash
cd /Users/mayureshkhalane/Documents/ARIA
./scripts/run_webots.sh
```

Expected output:
```
Opening ARIA Webots world: .../src/webots/worlds/house.wbt
✓ Webots started with PID 12345
✓ Log file: /tmp/webots.log
```

### 2. Start UI Server (Terminal 2)
```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv run python -m src.ui.server
```

Expected output:
```
======= Serving on http://127.0.0.1:8080 =========
```

### 3. Open Browser
```
http://127.0.0.1:8080
```

## What You'll See

1. **Camera Feed** - Real-time 320x240 stream from robot
2. **Detected Objects** - List of cups, chairs, tables, etc.
3. **Memory & Graph Stats** - Environment knowledge accumulating
4. **Robot State** - Position, sensor readings
5. **Agent Log** - Reasoning ("found cup, turning towards it", etc.)

## How It Works

### Goal: "find cup and approach it"

1. **Sense Phase:**
   - Camera captures frame
   - YOLO-Nano detects objects
   - Observations stored in visual memory
   - Environment graph updated

2. **Plan Phase:**
   - If cup visible → move toward it
   - If cup seen before → navigate to memory location
   - If unknown area → explore frontier

3. **Act Phase:**
   - Execute movement command
   - Avoid obstacles with proximity sensors
   - Loop back to sense

### Memory & Graph

**Visual Memory:**
- Stores frames with timestamps and poses
- Detects loop closures (revisiting same place)
- Similarity matching using perceptual hashing
- Query past observations by location

**Environment Graph:**
- Nodes = locations visited
- Edges = connectivity
- Auto-merges observations <0.5m apart
- Tracks object detections per location
- Enables spatial reasoning

## Example Goals

Try changing the goal text:

| Goal | Behavior |
|------|----------|
| "find cup and approach it" | Searches for cup, remembers location, navigates |
| "find chair" | Searches for chair using object detection |
| "explore the house" | Wanders around building spatial map |
| "find and approach table" | Detects table, moves toward it |

## Policy Selection

- **vision** (default) - Uses memory + graph for object search
- **reactive** - Just obstacle avoidance, no LLM
- **ollama** - LLM-based planning (slower but smart)
- **langgraph** - LangChain integration

For finding objects → **use vision policy**

## Monitoring

### Camera Status
- "320x240 @ 15FPS" = streaming normally
- "Connecting to camera..." = waiting for frames

### Memory Stats
- **Observations:** Number of frames stored (max 100)
- **Memory (MB):** RAM usage

### Graph Stats
- **Nodes:** Unique locations visited
- **Objects Seen:** Unique object types detected
- **Memory Full:** Warning if at capacity

## Troubleshooting

### No camera feed

```bash
# Check Webots is running
ps aux | grep Webots

# Check MCP server
uv run python -c "from src.mcp_server.server import call_tool; print(call_tool('get_state', {}))"

# Check Webots log
tail -50 /tmp/webots.log
```

### Objects not detected

- Move robot to get better view of objects
- Check lighting/angle in Webots
- Some objects may not be in YOLO's 80 classes

### Agent not moving

- Click "Run" button
- Check policy is "vision"
- Check Webots is still running

### UI disconnects

- Refresh page
- Check server is still running
- Look for errors in UI server terminal

## Full Documentation

See `VISION_SYSTEM.md` for detailed architecture and API reference.

## Architecture at a Glance

```
Camera (Webots)
    ↓ (MCP)
Camera Manager
    ├→ YOLO-Nano Detection
    ├→ Visual Memory (Loop Closure)
    └→ Environment Graph
         ↓
    Vision Agent Planning
         ↓
    Actions (move/turn/stop)
         ↓
    Browser UI (WebSocket)
```

## Commands

### CLI Mode (Alternative to UI)

```bash
# Search for objects
uv run python -m src.agent.main \
  --goal "find cup" \
  --policy vision \
  --steps 50

# Vision agent with custom memory
uv run python -c "
from src.agent.vision_agent import run_vision_aware_agent
state = run_vision_aware_agent('find chair', max_steps=100)
print(f'Success: {state.success}')
"
```

### Check Components

```bash
# Test camera
uv run python -c "
from src.perception.camera import get_camera_manager
camera = get_camera_manager()
frame = camera.get_frame()
print(f'Frame: {frame.shape if frame else \"None\"}')"

# Test detector
uv run python -c "
from src.perception.object_detector import get_detector
detector = get_detector()
print('Detector loaded:', detector.model is not None)"

# Check memory
uv run python -c "
from src.agent.visual_memory import get_visual_memory
memory = get_visual_memory()
print('Memory:', memory.get_stats())"

# Check graph
uv run python -c "
from src.agent.environment_graph import get_environment_graph
graph = get_environment_graph()
print('Graph:', graph.get_stats())"
```

## Performance

- Camera streaming: ~15 FPS
- Object detection: ~100ms per frame
- Memory/graph updates: <5ms
- Total cycle: ~200ms (sense + plan + act)

## Next Steps

1. **Experiment with Different Goals:** Try "find table", "find chair", etc.
2. **Monitor Memory Growth:** Watch graph nodes increase as robot explores
3. **Test Loop Closures:** Make robot revisit area → watch memory recognize it
4. **Extend Detector:** Add more objects to detection system
5. **Save/Load Maps:** Implement persistent memory between runs

## More Info

- **Vision System Details:** `VISION_SYSTEM.md`
- **Architecture:** `ARCHITECTURE_VISION.md`
- **Original Guide:** `WORKING_GUIDE.md`

---

**Status:** Ready to use!  
**Last Updated:** 2026-05-18
