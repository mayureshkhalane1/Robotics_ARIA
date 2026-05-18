# ✅ Quick Action Checklist

## Your Webots Timeout Issue - FIXED

The diagnostic revealed the **real problem**: Webots sends 327 KB JSON responses with camera images, but the socket receiver was breaking on large payloads.

### What You Need to Do Now:

- [ ] **Step 1:** Close Webots completely
  ```bash
  # Kill any running Webots process
  pkill -9 webots
  # Or just close the window
  ```

- [ ] **Step 2:** Restart Webots with updated controller
  ```bash
  cd /Users/mayureshkhalane/Documents/ARIA
  ./scripts/run_webots.sh
  ```
  Wait for:
  - Robot visible in simulation
  - Status bar shows "Running"
  - Bottom console shows `[Webots] Robot server initialized on port 19997`

- [ ] **Step 3:** Verify the fix works
  ```bash
  uv run python scripts/diagnose_webots.py
  ```
  Should end with: `✓ WEBOTS CONNECTION IS WORKING CORRECTLY`

- [ ] **Step 4:** Run the agent!
  ```bash
  # Option A: CLI (batch mode)
  uv run python -m src.agent.main --policy ollama --model qwen3:8b --steps 50
  
  # Option B: Web UI (interactive)
  uv run python -m src.ui.server
  # Then open http://127.0.0.1:8080 in browser
  ```

### If You Get Issues:

**"timed out" error still appears?**
- Is Webots window open and showing "Running" (not "Paused")?
- Did you fully close the old Webots before restarting?
- Run diagnostic again: `uv run python scripts/diagnose_webots.py`

**Want to understand what was fixed?**
- Read [TCP_FIX_SUMMARY.md](./TCP_FIX_SUMMARY.md)

**Need more help?**
- See [WEBOTS_TROUBLESHOOTING.md](./WEBOTS_TROUBLESHOOTING.md)
- See [RESTART_WEBOTS.md](./RESTART_WEBOTS.md)

---

**TL;DR:** Restart Webots → test with diagnostic → run agent. That's it!

