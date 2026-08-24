@echo off
REM ============================================================
REM  CapsStream Manual Updater (fallback)
REM  Pulls and installs the latest release from GitHub Releases.
REM ============================================================

set "ROOT=%~dp0"
set "PYTHON=%ROOT%winpython\python\python.exe"

title CapsStream Updater

echo.
echo  ============================================================
echo   CapsStream Update
echo  ============================================================
echo.

if not exist "%PYTHON%" (
    echo ERROR: Python not found at %PYTHON%
    echo Edit the PYTHON path in update.bat first.
    pause
    exit /b 1
)

echo  Checking for updates...
"%PYTHON%" -c "import json; from backend.updater import check_for_update; print(json.dumps(check_for_update(), indent=2))"

echo.
echo  Installing update...
"%PYTHON%" -c "import json; from backend.updater import apply_update; print(json.dumps(apply_update(), indent=2))"

echo.
echo  Done. If a restart was required, close this window and
echo  run start.bat again.
pause
