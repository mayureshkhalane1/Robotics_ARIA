# ARIA System Status

**Last Updated:** May 18, 2026  
**Status:** ✅ **Smart Vision Agent Ready for Use**

## 🎯 What's Running

### Smart Vision Language Agent (NEW)
- **Status:** ✅ Active and tested
- **Features:** 
  - LLM-powered scene understanding (Qwen3)
  - Intelligent navigation based on vision
  - Spatial memory of observations
  - Strategic object search
- **Integration:** Integrated into UI as default policy
- **Testing:** All 5 integration tests passing

### Components
| Component | Status | Details |
|-----------|--------|---------|
| **Camera Manager** | ✅ Working | 15 FPS BGRA8 frames, JPEG encoded |
| **YOLO Detector** | ✅ Working | Detects 80 COCO classes, ~100ms/frame |
| **Visual Memory** | ✅ Working | Stores observations, loop closure detection |
| **Environment Graph** | ✅ Working | Spatial mapping with node merging |
| **Qwen3 via Ollama** | ✅ Working | Scene understanding & decision making |
| **Webots Simulator** | ⚙️ Requires manual start | Robot simulation environment |
| **Web UI** | ✅ Working | Real-time camera feed & agent control |

## 🚀 Quick Start

### 1. Start Webots
```bash
./scripts/run_webots.sh
```
Wait for the simulation window to show "Running" status.

### 2. Start UI Server
```bash
uv run python -m src.ui.server
```

### 3. Open Browser
```
http://127.0.0.1:8080
```

### 4. Set Goal and Run
- Goal: `find cup` or any target object
- Policy: `smart vision (VLM)` (default)
- Click **Run**

Watch the console for real-time agent reasoning!

## 📊 Performance Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Camera FPS | 15 FPS | 320×240 resolution |
| Frame size | ~9 KB | JPEG encoded |
| Image analysis | <50ms | Local processing |
| Qwen query | 2-5s | LLM inference time |
| **Per-step total** | **3-6s** | Full sense→plan→act cycle |
| **Exploration rate** | **10-20 steps/min** | Depends on response time |

## 🏗️ Architecture Overview

```
Camera Frame (15 FPS)
    ↓
Local Image Analysis (colors, brightness, edges)
    ↓
Qwen3-VL LLM: "What do you see?"
    ↓
Visual Memory + Observation Tracking
    ↓
Qwen3 LLM: "What should robot do?"
    ↓
Decision (move forward / turn / backup)
    ↓
Webots Motor Control
    ↓
Repeat
```

## 📁 Key Files

### Agent System
- `src/agent/smart_vision_agent.py` - NEW: Main VLM-based agent
- `src/agent/vision_agent.py` - Vision-aware agent (memory + graph)
- `src/agent/graph.py` - Reactive/LangGraph agent
- `src/agent/environment_graph.py` - Spatial mapping
- `src/agent/visual_memory.py` - Observation storage

### Vision System
- `src/perception/camera.py` - Camera capture & encoding
- `src/perception/object_detector.py` - YOLO-Nano detection

### Integration
- `src/mcp_server/server.py` - Webots connection
- `src/ui/server.py` - WebSocket server for UI
- `src/ui/static/index.html` - Web dashboard

## 📋 Agent Policies

| Policy | Speed | Intelligence | Use Case |
|--------|-------|--------------|----------|
| **smart_vision** (NEW) | Medium (3-6s/step) | High (VLM reasoning) | General exploration |
| **vision** | Fast (200ms/step) | Medium (memory+graph) | Quick searches |
| **reactive** | Very fast (50ms/step) | Low (obstacle avoid) | Tight spaces |
| **ollama** | Slow (5-10s/step) | High (LLM+sensors) | Complex reasoning |
| **langgraph** | Fast (200ms/step) | Medium (tool use) | Multi-step planning |

## 🧪 Testing

All systems passing integration tests:

```bash
✓ TEST 1: Initialization
✓ TEST 2: Image Analysis  
✓ TEST 3: Qwen Query
✓ TEST 4: Component Availability
✓ TEST 5: Run Functions

5/5 tests passed ✅
```

Run tests:
```bash
uv run python -m pytest tests/
```

## 🔍 Debugging

### Check Webots Connection
```bash
uv run python scripts/diagnose_webots.py
```

### Test Camera Feed
```bash
uv run python scripts/test_camera_feed.py
```

### Monitor Agent Reasoning
Run UI server and watch console output - you'll see:
- Image analysis output
- Qwen understanding
- Decision reasoning
- Movement commands

### Qwen Connection
```bash
ollama list  # Check Qwen3 is installed
ollama serve  # Start Ollama if not running
```

## 📚 Documentation

- **[SMART_VISION_GUIDE.md](./SMART_VISION_GUIDE.md)** - Complete smart vision agent documentation
- **[README.md](./README.md)** - Project overview
- **[VISION_QUICKSTART.md](./VISION_QUICKSTART.md)** - 60-second setup guide
- **[WEBOTS_TROUBLESHOOTING.md](./WEBOTS_TROUBLESHOOTING.md)** - Common issues & fixes

## ✅ What Works

- ✅ Robot sees live camera feed
- ✅ Qwen3 understands scenes
- ✅ LLM makes intelligent decisions
- ✅ Robot navigates based on understanding
- ✅ Memory tracks observations
- ✅ UI shows real-time progress
- ✅ Multiple policy options available
- ✅ Integration tests passing

## 🚧 What's Coming

- [ ] Multi-angle exploration (rotate before moving)
- [ ] Persistent memory across runs
- [ ] More sophisticated scene understanding
- [ ] Object tracking across frames
- [ ] Semantic map visualization
- [ ] Natural language feedback to user

## 🛠️ Configuration

Edit `src/common/config.py` to adjust:
- Webots host/port
- LLM model and URL
- Agent max steps
- State cache size

Default: Local Ollama with Qwen3:8b on localhost:11434

## 💡 Example Commands

### Find Cup
```bash
uv run python -c "
from src.agent.smart_vision_agent import run_smart_vision_agent
state = run_smart_vision_agent('find cup', max_steps=20)
"
```

### Interactive UI
```bash
uv run python -m src.ui.server
# Then open http://127.0.0.1:8080
```

### Use Different Agent
```bash
# UI policy dropdown or programmatically:
from src.agent.vision_agent import run_vision_aware_agent
state = run_vision_aware_agent('find chair', max_steps=50)
```

---

**Smart Vision Agent is the new default.** It combines real-time vision perception with LLM reasoning for truly intelligent robot navigation!
