# ARIA - Start Here!

## 🚀 Quick Start (30 seconds)

### Terminal 1: Webots Simulator
```bash
cd /Users/mayureshkhalane/Documents/ARIA
./scripts/run_webots.sh
```

Wait for Webots window to fully load (you'll see the house and robot).

### Terminal 2: UI Server
```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv run python -m src.ui.server
```

You'll see:
```
======= Serving on http://127.0.0.1:8080 =========
```

### Browser
Open: **http://127.0.0.1:8080**

You'll see the live robot camera feed!

## 🎯 What You Can Do

### Run a Goal
1. Change the goal text (e.g., "find cup and approach it")
2. Select policy: "vision" (default)
3. Click "Run" button

The robot will:
- Capture camera frames (15 FPS)
- Detect objects using YOLO
- Remember where it's been
- Build a spatial map
- Search for your target object
- Show all thinking in the log

### Watch the Dashboard
You'll see in real-time:
- 🎥 **Camera Feed** - Live 320x240 stream
- 🔍 **Detected Objects** - Cups, chairs, tables with confidence
- 🧠 **Memory** - How many observations stored
- 🗺️ **Graph** - How many locations mapped
- 📊 **Thinking** - Agent's reasoning: "sense: frame captured...", "plan: found cup...", "act: move forward"

## 🧪 Test the System

### Quick Camera Test
```bash
./scripts/test_camera_feed.py
```

Output shows:
```
✓ Camera: 240x320 @ 15.0 FPS
✓ Detector: Found N objects
✓ Memory: Stored observation
✓ Graph: Added node
```

### Run Integration Tests
```bash
uv run python tests/test_vision_integration.py
```

All 5 tests should pass ✓

## 📖 Example Goals

Try these in the UI:

| Goal | What It Does |
|------|-------------|
| `"find cup"` | Searches for cup, moves toward it |
| `"find chair"` | Looks for chair specifically |
| `"explore house"` | Wanders around, builds map |
| `"locate table"` | Finds table, approaches it |

## 🔧 If Something Doesn't Work

### Camera not showing
1. Check Webots window is open and showing "Running" (not "Paused")
2. Click Play button (▶️) in Webots if paused
3. Run test: `./scripts/test_camera_feed.py`

### UI not loading
1. Make sure server is running (see "Serving on..." message)
2. Try refreshing browser
3. Check http://127.0.0.1:8080 is correct

### No objects detected
- This is normal! The house may not have prominent objects
- Try moving the robot closer to objects
- Check object detector is working: `uv run python -c "from src.perception.object_detector import get_detector; print(get_detector())"`

### Port 8080 already in use
```bash
# Kill any existing server
pkill -f "ui.server"

# Wait a few seconds
sleep 2

# Try again
uv run python -m src.ui.server
```

## 📚 Documentation

- **This file**: Quick start
- `CAMERA_FIX_SUMMARY.md` - How camera streaming was fixed
- `VISION_QUICKSTART.md` - Detailed vision system setup
- `VISION_SYSTEM.md` - Complete architecture and API
- `ARCHITECTURE_VISION.md` - Design overview
- `README.md` - Full project description

## 🎬 What's Happening Behind the Scenes

```
1. SENSE
   Camera captures frame from Webots
   YOLO detects objects
   Store in visual memory
   
2. PLAN
   Check if target visible?
   Check if seen before (memory)?
   Check unexplored areas (graph)?
   Plan movement
   
3. ACT
   Execute action (move/turn/stop)
   Avoid obstacles
   
4. REPEAT
   Loop back to sense
   Update memory and graph
   Show progress in UI
```

## ⚡ Key Features

✨ **Real-time camera** - 15 FPS streaming to browser
✨ **Object detection** - YOLO-Nano finds cups, chairs, tables, etc.
✨ **Visual memory** - Remembers where it's been
✨ **Spatial reasoning** - Builds map of environment
✨ **Intelligent search** - Finds and approaches target objects
✨ **Live dashboard** - See everything happening in real-time

## 🔌 System Architecture

```
Browser UI (http://127.0.0.1:8080)
    ↓ (WebSocket)
Camera Stream (15 FPS JPEG)
    ↓
Object Detection (YOLO-Nano)
    ↓
Visual Memory + Graph Mapping
    ↓
Vision Agent Planning
    ↓
Robot Actions (via MCP)
    ↓
Webots Simulator
    ↓
Pioneer 3-DX Robot
```

## 🎮 Controls

- **Goal input**: Type natural language goal
- **Policy selector**: Choose vision/reactive/ollama
- **Model input**: LLM to use (for ollama policy)
- **Run button**: Start agent
- **Stop button**: Emergency stop

## 📊 Dashboard Shows

| Section | What It Shows |
|---------|--------------|
| Camera | Live feed + detected objects |
| Memory & Graph | Statistics (observations, nodes, objects) |
| Robot State | Position, orientation, sensors |
| Thinking | Agent's reasoning and actions |

## 🚨 Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| "Connecting to camera..." | Wait longer, or check Webots |
| No objects detected | Try moving robot, camera may be at blank wall |
| Robot doesn't move | Check Webots is not paused |
| Server crashes | Check port 8080 is free |
| Slow response | This is normal, YOLO takes ~100ms per frame |

## 🎯 Next Steps

1. ✅ Start Webots: `./scripts/run_webots.sh`
2. ✅ Start UI: `uv run python -m src.ui.server`
3. ✅ Open browser: http://127.0.0.1:8080
4. ✅ Type goal: "find cup"
5. ✅ Click "Run"
6. ✅ Watch the magic! 🎉

---

**Ready to go!** Your ARIA robot is ready to see, think, and navigate.

For detailed info see `CAMERA_FIX_SUMMARY.md` or `VISION_SYSTEM.md`
