@echo off
REM ============================================================
REM  CapsStream — uTorrent State Change Hook (Batch Launcher)
REM  Executes on any torrent state change.
REM ============================================================

setlocal enabledelayedexpansion
set "ROOT=%~dp0..\"
set "PYTHON=%ROOT%winpython\python\pythonw.exe"

if not exist "%PYTHON%" (
    set "PYTHON=pythonw.exe"
)

start "" /B "%PYTHON%" "%ROOT%backend\utorrent_hook.py" %*
exit /b 0
