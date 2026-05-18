#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORLD="${WEBOTS_WORLD:-$ROOT/src/webots/worlds/house.wbt}"
WEBOTS_BIN="/Applications/Webots.app/Contents/MacOS/webots"
PORT="${WEBOTS_PORT_UI:-1236}"

if [[ ! -x "$WEBOTS_BIN" ]]; then
  echo "Webots binary not found at: $WEBOTS_BIN" >&2
  echo "Open Webots manually and load: $WORLD" >&2
  exit 1
fi

if pgrep -f "/Applications/Webots.app/Contents/MacOS/webots" >/dev/null; then
  echo "WARNING: Another Webots instance is already running."
  echo "Recommended: quit it first with: osascript -e 'quit app \"Webots\"'"
  echo "Continuing on UI/extern-controller port $PORT..."
fi

echo "Opening ARIA Webots world: $WORLD"
echo "Using Webots UI/extern-controller port: $PORT"
echo "ARIA robot TCP port remains: 19997"
echo ""
echo "NOTE: Webots will run in the background."
echo "To kill it later, run: pkill -f 'Webots'"
echo ""

# Run in background and disown so it survives terminal closure
"$WEBOTS_BIN" --port="$PORT" --stdout --stderr "$WORLD" > /tmp/webots.log 2>&1 &
PID=$!
echo "✓ Webots started with PID $PID"
echo "✓ Log file: /tmp/webots.log"
sleep 3
echo "✓ Webots initialized"
disown
