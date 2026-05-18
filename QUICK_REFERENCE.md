# ARIA Smart Vision Agent - Quick Reference

## 🚀 Start in 3 Steps

```bash
# Terminal 1: Start Webots
./scripts/run_webots.sh

# Terminal 2: Start UI
uv run python -m src.ui.server

# Browser: Open dashboard
http://127.0.0.1:8080
```

## 🎯 How It Works

```
Camera captures frame
    ↓
Qwen3 analyzes: "What do I see?"
    ↓
Qwen3 decides: "Move forward? Turn left? Turn right?"
    ↓
Robot moves
    ↓
REPEAT
```

## 🖥️ UI Control

| Setting | Options | Notes |
|---------|---------|-------|
| Goal | "find cup", "locate chair", etc. | What robot should search for |
| Policy | smart_vision (default), vision, reactive, ollama | Agent strategy |
| Model | qwen3:8b (default) | LLM to use |
| Steps | 1-100 | Max exploration steps |

## 📊 Performance

- **Per step:** 3-6 seconds
- **Camera:** 15 FPS live feed
- **Model:** Qwen3:8b via Ollama

## 🔍 Key Features

✅ **Sees** - 15 FPS camera feed  
✅ **Understands** - Qwen3 scene analysis  
✅ **Decides** - LLM picks best action  
✅ **Remembers** - Stores observations  
✅ **Searches** - Finds target objects  

## 🎮 Example Goals

- "find cup"
- "locate chair"
- "find table"
- "find red object"
- "look for furniture"

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "No camera data" | Webots not running or paused |
| "Qwen error" | Ollama not running: `ollama serve` |
| "Connection refused" | Webots on wrong port - check `src/common/config.py` |
| Slow responses | Normal - Qwen takes 2-5s per step |

## 📁 Important Files

- **Agent:** `src/agent/smart_vision_agent.py`
- **Config:** `src/common/config.py`
- **Camera:** `src/perception/camera.py`
- **UI:** `src/ui/server.py`

## 💻 CLI Usage

```python
from src.agent.smart_vision_agent import run_smart_vision_agent

# Search for 15 steps
state = run_smart_vision_agent('find cup', max_steps=15)
print(f"Found: {state.success}")
```

## 🔧 Config Quick Edits

```python
# src/common/config.py
OLLAMA_BASE_URL = "http://localhost:11434"  # Ollama URL
OLLAMA_MODEL = "qwen3:8b"                   # Model to use
MAX_AGENT_STEPS = 100                       # Default max steps
```

## 📚 Full Docs

- **[SMART_VISION_GUIDE.md](./SMART_VISION_GUIDE.md)** - Complete guide
- **[SYSTEM_STATUS.md](./SYSTEM_STATUS.md)** - What's running
- **[README.md](./README.md)** - Project overview

## ✅ Checklist

- [ ] Webots installed (`brew install webots` on Mac)
- [ ] Python 3.10+ (`python --version`)
- [ ] Dependencies installed (`uv sync --group dev`)
- [ ] Ollama running with qwen3:8b (`ollama list`)
- [ ] Webots simulation loaded
- [ ] UI server running
- [ ] Browser open to http://127.0.0.1:8080

## 🎬 Try It Now

```bash
# Quick test (if Webots + Ollama running)
uv run python -c "
from src.agent.smart_vision_agent import SmartVisionAgent
agent = SmartVisionAgent('find cup', max_steps=3)
print('✓ Agent ready to search')
"
```

---

**Smart Vision Agent makes your robot truly intelligent!** 🤖

Questions? Check the full docs or run:
```bash
uv run python -m src.ui.server
```
