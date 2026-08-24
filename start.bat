@echo off
REM ============================================================
REM  CapsStream Launcher
REM  Double-click this file to start CapsStream
REM ============================================================

set "ROOT=%~dp0"
set "PYTHON=%ROOT%winpython\python\python.exe"
set "SCRIPT=%ROOT%app.py"

title CapsStream Server

echo.
echo  ============================================================
echo   CapsStream Media Server
echo  ============================================================
echo.

REM Check if Python exists
if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    echo Please update the PYTHON path in start.bat
    pause
    exit /b 1
)

REM Install dependencies if needed
echo  [1/3] Checking dependencies...
"%PYTHON%" -m pip install -q -r "%ROOT%requirements.txt" 2>nul

REM Apply root directory system file hiding based on config.json
echo  [2/3] Checking system file visibility settings...
"%PYTHON%" -c "import backend.settings as s; s.apply_system_file_hiding()" 2>nul

REM Open browser in preferred mode from config.json
echo  [3/3] Launching web application in configured browser window...
"%PYTHON%" -c "import backend.settings as s; s.launch_browser()" 2>nul

echo.
echo  ============================================================
echo   STATUS: CapsStream Server is Live!
echo   ADDRESS: http://127.0.0.1:8000
echo.
echo   TO STOP THE SERVER: Press Ctrl+C or close this window.
echo  ============================================================
echo.

"%PYTHON%" "%SCRIPT%"
