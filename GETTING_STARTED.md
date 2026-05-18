# ARIA Smart Vision Agent - Getting Started Guide

Welcome! You now have a **fully intelligent robot vision system** that can see, understand, and navigate.

## 🎯 What You Have

A robotic agent that:
- **Sees** via real-time 15 FPS camera
- **Understands** via Qwen3 LLM scene analysis
- **Decides** based on intelligent reasoning
- **Remembers** observations and locations
- **Searches** for target objects smartly

**Note:** The original `apartment.wbt` used deprecated EXTERNPROTO links and an older header, causing loading failures in Webots R2025a. The new pure‑VRML version (R2023b) works across all current Webots releases. If you see a conversion prompt, you can safely accept it or just continue using the VRML file.



```bash
# Terminal 1
./scripts/run_webots.sh

# Terminal 2 (wait for Webots to fully load)
uv run python -m src.ui.server

# Browser
http://127.0.0.1:8080
```

**Then:**
1. Set goal: `find cup`
2. Click **Run**
3. Watch the agent reason in real-time!

## 📋 Prerequisites Checklist

Before you start, verify you have:

- [ ] **Webots** installed
  ```bash
  brew install webots  # macOS
  # or download from https://cyberbotics.com
  ```

- [ ] **Python 3.10+**
  ```bash
  python --version
  ```

- [ ] **Dependencies installed**
  ```bash
  cd /Users/mayureshkhalane/Documents/ARIA
  uv sync --group dev
  ```

- [ ] **Ollama running with Qwen3**
  ```bash
  ollama pull qwen3:8b
  ollama serve  # In a separate terminal
  ```

## 🚀 Step-by-Step Startup

### Step 1: Start Webots (2 minutes)

```bash
./scripts/run_webots.sh
```

**Wait for:**
- Webots window to appear
- Simulation to show "Running" status (not "Paused")
- See the robot in the house environment

**If stuck:**
- Click Play button (▶️) in Webots if paused
- Check [WEBOTS_TROUBLESHOOTING.md](./WEBOTS_TROUBLESHOOTING.md)

### Step 2: Start Ollama (30 seconds)

In a **separate terminal**:

```bash
ollama serve
```

You should see something like:
```
Listening on 127.0.0.1:11434
```

If Qwen3 isn't installed yet:
```bash
ollama pull qwen3:8b  # Downloads ~4.5GB, first time only
```

### Step 3: Start UI Server (10 seconds)

In **another new terminal**:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv run python -m src.ui.server
```

You should see:
```
[UI] Starting dashboard on http://127.0.0.1:8080
```

### Step 4: Open Browser (5 seconds)

Open: **http://127.0.0.1:8080**

You should see:
- Live camera feed from the robot
- Interface with controls
- Console showing agent reasoning

## 🎮 Using the Interface

### Main Controls

| Element | Purpose | Example |
|---------|---------|---------|
| **Goal** | What robot should find | "find cup", "locate chair" |
| **Policy** | Agent strategy | "smart vision (VLM)" [default] |
| **Model** | Which LLM to use | "qwen3:8b" [default] |
| **Steps** | Max exploration steps | "20" or "100" |
| **Run** | Start the agent | Click when ready |
| **Stop** | Cancel current run | Stops immediately |

### Example Queries

**Simple Object Search:**
- "find cup"
- "locate chair"
- "find table"

**Descriptive Search:**
- "find red object"
- "look for furniture"
- "find something to sit on"

**Complex Goals:**
- "find cup and move towards it"
- "explore the room"
- "look for kitchen items"

## 📊 What You're Seeing

### Console Output During Run

```
============================================================
[Step 1/20] Position: (0.0, 0.0), Rotation: 0°
============================================================
[SENSE] Capturing camera frame...
✓ Frame: (240, 320, 3)

[PERCEIVE] Analyzing what robot sees...
  Image analysis: Image (320x240). Color avg: R127,G120,B115...

[UNDERSTAND] Asking Qwen: What do you see? Is the target here?
  Understanding: The robot sees a beige/tan colored room...

[PLAN] Qwen deciding next action...
  Decision: 1. Move forward to explore further...

[ACT] Executing action...
  → Moving forward...

✓ Step 1 complete
```

**Key things to notice:**
- Image analysis (colors, edges)
- What Qwen understands
- What Qwen decides to do
- Progress through steps

### Browser Dashboard

**Camera Feed:**
- Real-time 15 FPS video
- Shows what robot sees
- YOLO detection boxes (if enabled)

**Controls:**
- Goal text field
- Policy dropdown
- Run/Stop buttons

**Stats:**
- Current step count
- Memory observations
- Graph nodes
- Agent state

## ⚙️ Configuration

### Default Settings

These are already configured - just start using it!

```python
# Webots connection
WEBOTS_HOST = "localhost"
WEBOTS_PORT = 19997

# LLM (Ollama)
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"

# Agent
MAX_AGENT_STEPS = 100
```

### Customize (Optional)

Edit `src/common/config.py` to change:
- Webots host/port
- Different Ollama model (e.g., "qwen3:14b", "mistral:7b")
- Agent step limits
- Other parameters

## 🆘 Troubleshooting

### "Connection refused" or "Cannot connect to Webots"

**Problem:** Webots isn't running

**Solution:**
```bash
./scripts/run_webots.sh  # In Terminal 1
```

**Still not working?**
```bash
uv run python scripts/diagnose_webots.py
```

### "Qwen error" or "No response from LLM"

**Problem:** Ollama not running or Qwen3 not installed

**Solution:**
```bash
# Terminal 1 - Check/install Qwen3
ollama list  # Should show "qwen3:8b"

# If not there, install:
ollama pull qwen3:8b  # ~4.5GB download

# Then start Ollama
ollama serve
```

### Robot doesn't move

**Problem:** Motor control issue

**Solution:**
- Check Webots window - is simulation paused? (click Play ▶️)
- Check console for error messages
- Try different policy: "vision" or "reactive"

### Very slow responses

**Expected behavior!** Qwen takes 2-5 seconds per step. This is normal.

If you want faster feedback:
- Change policy to "vision" (faster, less intelligent)
- Or "reactive" (very fast, obstacle avoidance only)

## 📚 Documentation Roadmap

**Just Getting Started?**
- You're reading it! 👈 This is the right place

**Want Quick Overview?**
- Read: [QUICK_REFERENCE.md](./QUICK_REFERENCE.md) (2 min read)

**Want Complete Details?**
- Read: [SMART_VISION_GUIDE.md](./SMART_VISION_GUIDE.md) (15 min read)

**Need System Overview?**
- Read: [SYSTEM_STATUS.md](./SYSTEM_STATUS.md) (5 min read)

**Interested in Architecture?**
- Read: [README.md](./README.md) (10 min read)

**Troubleshooting Webots?**
- Read: [WEBOTS_TROUBLESHOOTING.md](./WEBOTS_TROUBLESHOOTING.md)

## 🎯 Next Steps

### Try Basic Search (5 minutes)
```
1. Open http://127.0.0.1:8080
2. Goal: "find cup"
3. Steps: "10"
4. Click Run
5. Watch console output
```

### Try Different Goals (10 minutes)
- "find chair"
- "find table"
- "explore the room"

### Change Agent Policy (5 minutes)
In UI dropdown:
- Try "vision" (faster)
- Try "reactive" (very fast)
- Notice differences

### Read Smart Vision Guide (15 minutes)
- Understand how it works
- Learn about architecture
- See example runs

## 💡 Key Concepts

### Smart Vision Agent Pipeline

```
See (camera) → Understand (Qwen) → Decide (Qwen) → Act (motor) → Repeat
```

### Scene Understanding

Agent asks Qwen: *"What do you see? Is the target here?"*

Qwen responds with semantic understanding, not just object lists.

### Smart Decision Making

Agent asks Qwen: *"What should robot do?"*

Qwen chooses next action based on scene and goal.

### Spatial Memory

Robot remembers:
- What it saw at each location
- Whether target was found
- What actions led where

## 🎓 Learning Path

**Day 1:** Get it running
- Start Webots and UI
- Make robot find a cup
- Read QUICK_REFERENCE.md

**Day 2:** Explore features
- Try different goals
- Try different policies
- Read SMART_VISION_GUIDE.md

**Day 3:** Deep dive
- Understand architecture
- Customize prompts
- Experiment with parameters

**Day 4+:** Integration & extension
- Integrate with your own systems
- Extend with new capabilities
- Build on the framework

## 🚀 Common Commands

```bash
# Start everything (in 3 terminals)
./scripts/run_webots.sh
ollama serve
uv run python -m src.ui.server

# Test without UI (CLI)
uv run python -c "
from src.agent.smart_vision_agent import run_smart_vision_agent
state = run_smart_vision_agent('find cup', max_steps=20)
print(f'Success: {state.success}')
"

# Test camera feed
uv run python scripts/test_camera_feed.py

# Diagnose Webots issues
uv run python scripts/diagnose_webots.py
```

## ❓ FAQ

**Q: Why is each step slow (3-6 seconds)?**  
A: Qwen LLM inference takes time. This is the trade-off for intelligent reasoning. Use "vision" or "reactive" policy for faster exploration.

**Q: Will it always find the object?**  
A: Not guaranteed - depends on object visibility, exploration strategy, and step limit. Increase steps or try different goals.

**Q: Can I use a different LLM?**  
A: Yes! Edit `src/common/config.py` and change `OLLAMA_MODEL` to any Ollama model like "mistral:7b", "llama2:13b", etc.

**Q: Is Webots required?**  
A: For this demo, yes. The code is designed for Webots simulation.

**Q: Can I run without a GPU?**  
A: Qwen3:8b runs on CPU but slower. With GPU it's much faster.

## 📞 Support

**Agent not starting?**
```bash
uv run python scripts/diagnose_webots.py
```

**Webots troubleshooting?**
```
See: WEBOTS_TROUBLESHOOTING.md
```

**Want to dive deeper?**
```
See: SMART_VISION_GUIDE.md (complete documentation)
```

## 🎉 You're All Set!

Everything is ready to go. Your intelligent robot vision system is functional and waiting to explore!

**Start now:**
1. Open 3 terminals
2. Run the 3 startup commands
3. Open browser to http://127.0.0.1:8080
4. Set goal and click Run
5. Watch it think and explore!

Enjoy! 🤖✨

---

**Questions?** Check the [SMART_VISION_GUIDE.md](./SMART_VISION_GUIDE.md) or relevant troubleshooting doc.

**Ready to explore?** Start Webots and the UI, then search for "find cup"!
