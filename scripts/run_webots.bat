@echo off
:: Launch Webots with the ARIA apartment world.
:: Double-click this file or run from cmd/PowerShell.

set WEBOTS=C:\Program Files\Webots\msys64\mingw64\bin\webots.exe
set WORLD=%~dp0..\src\webots\indoor\worlds\complete_apartment.wbt
set LOG=%TEMP%\webots_controller.log

if not exist "%WEBOTS%" (
    echo ERROR: Webots not found at "%WEBOTS%"
    pause
    exit /b 1
)

echo World : %WORLD%
echo Log   : %LOG%
echo.
echo Webots will open PAUSED. Press Play to start.
echo Controller output (stdout+stderr) goes to: %LOG%
echo After it closes, open that file to see what happened.
echo.

:: --stdout and --stderr redirect controller output to this console/log
"%WEBOTS%" --mode=pause --stdout --stderr "%WORLD%" > "%LOG%" 2>&1

echo.
echo Webots exited. Controller log:
echo ----------------------------------------
type "%LOG%"
echo ----------------------------------------
pause
