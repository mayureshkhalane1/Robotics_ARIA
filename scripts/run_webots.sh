#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORLD="${WEBOTS_WORLD:-$ROOT/src/webots/worlds/house.wbt}"
PORT="${WEBOTS_PORT_UI:-1236}"

# Default Webots install location on Windows, accessed from WSL.
# Override by setting WEBOTS_BIN before running this script, e.g.:
#   export WEBOTS_BIN='/mnt/c/Program Files/Webots/webots.exe'
WEBOTS_BIN="${WEBOTS_BIN:-/mnt/c/Program Files/Webots/webots.exe}"

if [[ ! -f "$WEBOTS_BIN" ]]; then
  echo "Webots binary not found at: $WEBOTS_BIN" >&2
  echo "Set WEBOTS_BIN to the correct WSL path, e.g.:" >&2
  echo "  export WEBOTS_BIN='/mnt/c/Program Files/Webots/webots.exe'" >&2
  echo "Or open Webots manually and load the world file." >&2
  exit 1
fi

# Webots is a Windows process; use tasklist.exe to detect it from WSL.
if tasklist.exe 2>/dev/null | grep -qi "webots.exe"; then
  echo "WARNING: Another Webots instance is already running."
  echo "Recommended: stop it first with:  taskkill.exe /IM webots.exe /F"
  echo "Continuing on UI/extern-controller port $PORT..."
fi

# Convert the WSL world-file path to a Windows path (e.g. E:\...)
# so the Windows Webots binary can open it.
WORLD_WIN="$(wslpath -w "$WORLD")"

# Determine the Windows host IP used to reach Webots TCP from WSL2.
WINDOWS_HOST="$(ip route show default 2>/dev/null | awk '/via/{print $3; exit}')"
WINDOWS_HOST="${WINDOWS_HOST:-172.20.128.1}"

echo "Opening ARIA Webots world: $WORLD_WIN"
echo "Using Webots UI/extern-controller port: $PORT"
echo "ARIA robot TCP port:       19997"
echo "Windows host IP (for WSL2 TCP connection): $WINDOWS_HOST"
echo ""
echo "Make sure your .env sets:  WEBOTS_HOST=$WINDOWS_HOST"
echo "NOTE: Webots will run in the background."
echo "To kill it later, run:  taskkill.exe /IM webots.exe /F"
echo ""

"$WEBOTS_BIN" --port="$PORT" "$WORLD_WIN" > /tmp/webots.log 2>&1 &
PID=$!
disown
echo "Webots started with PID $PID"
echo "Log file: /tmp/webots.log"
sleep 3
echo "Webots initialized"
