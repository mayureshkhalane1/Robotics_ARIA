#!/usr/bin/env bash
# Helper to remind WSL users how to start Webots (which is a Windows GUI app).
#
# Webots must be launched from Windows PowerShell — not from WSL — because
# WSL cannot create a process in the Windows interactive desktop session.
#
# Usage (from this WSL shell):
#   powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w "$( cd "$(dirname "$0")/.." && pwd )/scripts/run_webots.ps1")"
#
# Or open a Windows PowerShell window and run:
#   cd E:\Leiden\Year-1\Sem-2\ENV\Robotics\Robotics_ARIA
#   .\scripts\run_webots.ps1

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PS1_WIN="$(wslpath -w "$ROOT/scripts/run_webots.ps1")"

# Determine the Windows host IP so the user knows what to put in .env
WINDOWS_HOST="$(ip route show default 2>/dev/null | awk '/via/{print $3; exit}')"
WINDOWS_HOST="${WINDOWS_HOST:-172.20.128.1}"

echo ""
echo "=== Webots must be launched from Windows PowerShell, not WSL ==="
echo ""
echo "Option 1 — run from THIS WSL terminal (launches PowerShell for you):"
echo "  powershell.exe -ExecutionPolicy Bypass -File \"$PS1_WIN\""
echo ""
echo "Option 2 — open a Windows PowerShell window and run:"
echo "  cd $(wslpath -w "$ROOT")"
echo "  .\\scripts\\run_webots.ps1"
echo ""
echo "After Webots opens, make sure your .env contains:"
echo "  WEBOTS_HOST=$WINDOWS_HOST"
echo ""

# Offer to launch PowerShell automatically
read -rp "Launch Webots now via powershell.exe? [Y/n] " REPLY
REPLY="${REPLY:-Y}"
if [[ "$REPLY" =~ ^[Yy]$ ]]; then
  echo "Launching..."
  powershell.exe -ExecutionPolicy Bypass -File "$PS1_WIN"
fi
