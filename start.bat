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

REM Check if CapsStream server is already running
"%PYTHON%" -c "import backend.settings as s, sys; sys.exit(0 if s.is_server_running() else 1)" 2>nul
if %ERRORLEVEL% equ 0 (
    echo  [!] CapsStream Server is ALREADY RUNNING!
    echo.
    echo  ============================================================
    echo   STATUS: CapsStream Server is already active and healthy.
    echo   Reusing running instance and focusing browser window...
    echo  ============================================================
    echo.
    "%PYTHON%" -c "import backend.settings as s; s.launch_browser()" 2>nul
    timeout /t 3 >nul
    exit /b 0
)

REM Install dependencies if needed
echo  [1/4] Checking dependencies...
"%PYTHON%" -m pip install -q -r "%ROOT%requirements.txt" 2>nul

REM Apply update files that were locked by the previous session
echo  [2/4] Applying pending update files...
"%PYTHON%" -c "from backend.updater import apply_pending_swaps; apply_pending_swaps()" 2>nul

REM Apply root directory system file hiding based on config.json
echo  [3/4] Checking system file visibility settings...
"%PYTHON%" -c "import backend.settings as s; s.apply_system_file_hiding()" 2>nul

REM Open browser in preferred mode from config.json
echo  [4/4] Launching web application in configured browser window...
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
