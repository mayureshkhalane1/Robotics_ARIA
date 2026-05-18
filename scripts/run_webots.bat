@echo off
:: Launch Webots with the ARIA apartment world.
:: Double-click this file from Windows Explorer, or run from cmd/PowerShell.
:: No execution-policy restrictions apply to .bat files.

set WEBOTS=C:\Program Files\Webots\msys64\mingw64\bin\webots.exe
set WORLD=%~dp0..\src\webots\indoor\worlds\complete_apartment.wbt

if not exist "%WEBOTS%" (
    echo ERROR: Webots not found at "%WEBOTS%"
    echo Edit this file and set the correct WEBOTS path.
    pause
    exit /b 1
)

echo Starting Webots...
echo World: %WORLD%
echo.
echo After Webots opens, press Play to start the simulation.
echo The robot TCP controller starts automatically when you press Play.
echo.

start "" "%WEBOTS%" "%WORLD%"
