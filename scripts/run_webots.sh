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
exec "$WEBOTS_BIN" --port="$PORT" --stdout --stderr "$WORLD"
