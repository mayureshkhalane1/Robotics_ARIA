# Controller Update - Must Restart Webots

## What Changed

I've updated the TCP controller with **extensive debug logging**. This will help us see exactly what's happening when Webots runs it.

## What You Need to Do

### Step 1: Completely Close Webots
```bash
# Make sure no Webots process is running
pkill -9 webots

# Wait a few seconds
sleep 3

# Verify it's closed
ps aux | grep webots | grep -v grep
# (should show no results)
```

### Step 2: Start Webots Fresh
```bash
./scripts/run_webots.sh
```

### Step 3: **IMPORTANT** - Check the Webots Console

Once Webots loads:
1. Scroll to the **bottom** of the Webots window
2. Click the **Console** tab
3. **Copy everything you see** - especially any RED or YELLOW messages
4. Look for lines starting with `[INIT]`, `[OK]`, `[MOTOR]`, `[SENSOR]`, `[RUN]`

### Step 4: Tell Us What You See

**Send me:**
1. Screenshot of the Webots console output
2. Or paste the console text

**Look for:**
- `[OK] TCP server listening on port 19997` → Controller loaded ✓
- `[OK] Motors initialized` → Motors found ✓
- `[OK] Sensors: X proximity...` → Sensors found ✓
- `[RUN] Entering main loop...` → Server ready ✓
- Any RED error messages → What went wrong

### Step 5: Once Verified

Test with:
```bash
uv run python scripts/diagnose_webots.py
```

If that works, run the UI:
```bash
uv run python -m src.ui.server
```

---

**Why This Matters:**
The old controller was silent. If it crashed, you'd never know. The new one prints **every step** so we can see exactly where it fails (if at all).

