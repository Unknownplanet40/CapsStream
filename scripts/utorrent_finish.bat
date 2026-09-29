@echo off
REM ============================================================
REM  CapsStream — uTorrent Finish Hook (Batch Launcher)
REM  Executes when a torrent finishes downloading.
REM  Automatically passes --finish so media request is marked completed.
REM ============================================================

setlocal enabledelayedexpansion
set "ROOT=%~dp0..\"
set "PYTHON=%ROOT%winpython\python\pythonw.exe"

if not exist "%PYTHON%" (
    set "PYTHON=pythonw.exe"
)

start "" /B "%PYTHON%" "%ROOT%backend\utorrent_hook.py" --finish %*
exit /b 0
