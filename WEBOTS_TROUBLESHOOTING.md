# Webots Connection Troubleshooting Guide

## The Error You're Seeing

```
Command failed on attempt 1/2: timed out
Not connected to Webots. Attempting reconnect...
Connection timeout after 5s - Webots may be paused or not responding
ERROR - Failed to connect to Webots: timed out
```

This means the agent **cannot communicate with Webots**. The issue is usually one of these:

## Quick Diagnostic

Run this to identify the exact problem:

```bash
cd /Users/mayureshkhalane/Documents/ARIA
uv run python scripts/diagnose_webots.py
```

This will tell you **exactly** where the problem is.

## Common Issues & Fixes

### 1. **Webots Simulator Not Running**

**Symptom:** `Port is CLOSED/FILTERED`

**Fix:**
```bash
./scripts/run_webots.sh
```

This script:
- Starts Webots
- Loads the correct world file (arena.wbt)
- Automatically assigns the TCP controller
- Runs at 0.1x speed for real-time agent control

### 2. **Webots Simulation is Paused**

**Symptom:** `No response from Webots after 5s - simulator may be paused`

**Fix:**
- Click the **Play ▶️** button in Webots to resume simulation
- Or in the Webots main window, press **SPACE** to toggle play/pause
- Watch the status bar - it should show "Running" not "Paused"

### 3. **TCP Controller Script Has Errors**

**Symptom:** `Connected` but then `No response`

**Fix:**
- Open Webots window and check the **Console** tab at bottom
- Look for red error messages about the controller
- If errors exist, they'll tell you what's wrong (e.g., missing sensors)
- The controller script is at: `src/webots/controllers/tcp_controller/tcp_controller.py`

### 4. **Robot Sensors Not Initialized**

**Symptom:** Connected, but get empty sensor responses

**Check:**
1. The robot in your .wbt world file **must have**:
   - `left wheel` or `left wheel motor` 
   - `right wheel` or `right wheel motor`
   - Optional: `gps`, `compass`, distance sensors
   
2. See `src/webots/worlds/arena.wbt` for a working example

### 5. **Wrong Port or Host**

**Check your .env file:**

```bash
cat .env
```

Should show:
```
WEBOTS_HOST=localhost
WEBOTS_PORT=19997
```

If different, update `src/common/config.py` to match your setup.

## Step-by-Step Fix

1. **Verify Webots is running:**
   ```bash
   ./scripts/run_webots.sh
   ```

2. **Check it's responsive:**
   ```bash
   uv run python scripts/diagnose_webots.py
   ```

3. **If diagnosis passes, start the agent:**
   ```bash
   uv run python -m src.agent.main --policy ollama --model qwen3:8b --steps 50
   ```

4. **If still fails, check the Webots console for errors**
   - In Webots, click **Console** tab at the bottom
   - Look for `[Webots]` error messages
   - Post those error messages for further debugging

## Timeout Configuration

The default timeout is **5 seconds**. If Webots is just slow:

```bash
# Increase timeout to 15 seconds
WEBOTS_TIMEOUT=15 uv run python -m src.agent.main --policy ollama --model qwen3:8b
```

## Testing Without Webots

To test just the agent without Webots:

```bash
# Use reactive policy (no Webots needed)
uv run python -m src.agent.main --policy reactive --goal "move forward"
```

## Still Stuck?

Run this and share the output:

```bash
echo "=== Config ===" && cat .env && echo -e "\n=== Diagnostic ===" && uv run python scripts/diagnose_webots.py && echo -e "\n=== Webots Process ===" && ps aux | grep webots
```

