## Critical Fix Needed: Restart Webots

The TCP controller code has been updated to handle large camera responses. **You must restart Webots** for the new code to take effect.

### Steps to Restart Webots:

1. **Close Webots completely**
   - Click the X button to close the Webots window
   - Or in terminal where Webots was launched, press `Ctrl+C`

2. **Restart Webots with the controller**
   ```bash
   ./scripts/run_webots.sh
   ```

3. **Wait for it to fully load**
   - You should see the robot in the arena
   - Status bar should show "Running"
   - Check the console at the bottom - should show `[Webots] Robot server initialized on port 19997`

4. **Test the connection**
   ```bash
   uv run python scripts/diagnose_webots.py
   ```
   It should now say `✓ WEBOTS CONNECTION IS WORKING CORRECTLY`

### What Changed?

- **Fixed large response handling**: Socket now reads up to 65536 bytes per chunk (was 4096)
- **Smart JSON parsing**: Waits for complete JSON object instead of breaking on partial UTF-8
- **Optional camera data**: Can request state without camera (2KB vs 327KB) to speed up agent loop
- **Better error recovery**: Handles decode errors gracefully

### After Restart, Run Agent:

```bash
# CLI
uv run python -m src.agent.main --policy ollama --model qwen3:8b --steps 50

# OR Web UI
uv run python -m src.ui.server
# Then open http://127.0.0.1:8080
```

The agent should now **successfully communicate** with Webots!
