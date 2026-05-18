# Launch Webots with the ARIA world file.
# Run this from Windows PowerShell — NOT from WSL.
# Usage:  .\scripts\run_webots.ps1

$ErrorActionPreference = "Stop"

# Resolve the world file path relative to this script's location
$ROOT     = (Resolve-Path "$PSScriptRoot\..").Path
$WORLD    = if ($env:WEBOTS_WORLD) { $env:WEBOTS_WORLD } `
            else { Join-Path $ROOT "src\webots\worlds\house.wbt" }
$PORT     = if ($env:WEBOTS_PORT_UI) { $env:WEBOTS_PORT_UI } else { "1234" }

# Webots R2025a default install path
$WEBOTS   = if ($env:WEBOTS_BIN) { $env:WEBOTS_BIN } `
            else { "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" }

if (-not (Test-Path $WEBOTS)) {
    Write-Error "Webots not found at: $WEBOTS`nSet `$env:WEBOTS_BIN to the correct path."
    exit 1
}

if (Get-Process -Name "webots" -ErrorAction SilentlyContinue) {
    Write-Warning "Webots is already running. Stop it first:  Stop-Process -Name webots"
}

Write-Host "World:      $WORLD"
Write-Host "Webots port: $PORT  (robot TCP stays on 19997)"
Write-Host "Starting Webots in background..."

Start-Process -FilePath $WEBOTS -ArgumentList "--port=$PORT", "`"$WORLD`"" -WindowStyle Normal

Write-Host "Webots launched. Switch to it in the taskbar."
Write-Host "To stop it:  Stop-Process -Name webots"
