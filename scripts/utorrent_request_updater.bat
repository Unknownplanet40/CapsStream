@echo off
REM ============================================================
REM  CapsStream uTorrent Request Updater Hook
REM  Automatically updates CapsStream media requests even when the app is closed.
REM ============================================================

setlocal enabledelayedexpansion
set "ROOT=%~dp0..\"
set "PYTHON=%ROOT%winpython\python\pythonw.exe"

if not exist "%PYTHON%" (
    set "PYTHON=pythonw.exe"
)

start "" /B "%PYTHON%" "%ROOT%backend\utorrent_hook.py" %*
exit /b 0
