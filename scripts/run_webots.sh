#!/usr/bin/env bash
# ARIA Webots Launcher - Cross-platform (macOS/Linux/WSL2)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Detect OS and platform
OS_TYPE=$(uname -s)
IN_WSL=false

# Check if running in WSL2
if grep -qi microsoft /proc/version 2>/dev/null; then
  IN_WSL=true
fi

echo ""
echo "╔════════════════════════════════════════════════════════════╗"
echo "║              ARIA Webots Launcher                         ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

if [[ "$IN_WSL" == true ]]; then
  # WSL2 - Launch via PowerShell
  echo "Platform: WSL2 (Windows Subsystem for Linux)"
  echo ""
  PS1_WIN="$(wslpath -w "$ROOT/scripts/run_webots.ps1")"
  WINDOWS_HOST="$(ip route show default 2>/dev/null | awk '/via/{print $3; exit}' || echo '172.20.128.1')"
  
  echo "Launching Webots via Windows PowerShell..."
  powershell.exe -ExecutionPolicy Bypass -File "$PS1_WIN"
  
elif [[ "$OS_TYPE" == "Darwin" ]]; then
  # macOS
  echo "Platform: macOS"
  echo "Launching Webots..."
  
  WEBOTS_WORLD="${WEBOTS_WORLD:-$ROOT/src/webots/worlds/worlds/complete_apartment.wbt}"
  export WEBOTS_WORLD
  
  open -a Webots "$WEBOTS_WORLD" || {
    echo "Error: Webots not found. Install from https://cyberbotics.com"
    exit 1
  }
  
  echo ""
  echo "✓ Webots opened with: $WEBOTS_WORLD"
  echo ""
  echo "Next steps:"
  echo "  1. Wait for Webots to fully load (10 seconds)"
  echo "  2. Click the GREEN PLAY button ▶️ in the toolbar"
  echo "  3. In a new terminal:"
  echo "     cd $ROOT"
  echo "     uv run python -m src.ui.server"
  echo "  4. Open browser: http://localhost:8080"
  echo ""
  
elif [[ "$OS_TYPE" == "Linux" ]]; then
  # Linux (native)
  echo "Platform: Linux"
  echo "Launching Webots..."
  
  WEBOTS_WORLD="${WEBOTS_WORLD:-$ROOT/src/webots/worlds/worlds/complete_apartment.wbt}"
  export WEBOTS_WORLD
  
  webots "$WEBOTS_WORLD" > /tmp/webots.log 2>&1 &
  WEBOTS_PID=$!
  
  echo "✓ Webots started (PID: $WEBOTS_PID)"
  echo ""
  echo "Next steps:"
  echo "  1. Wait for Webots to fully load (10 seconds)"
  echo "  2. Click the GREEN PLAY button ▶️ in the toolbar"
  echo "  3. In a new terminal:"
  echo "     cd $ROOT"
  echo "     uv run python -m src.ui.server"
  echo "  4. Open browser: http://localhost:8080"
  echo ""
  
else
  echo "Error: Unsupported OS: $OS_TYPE"
  exit 1
fi
