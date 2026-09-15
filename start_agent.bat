@echo off
REM FlowKit agent (RENDER server) starter — double-click this file.
REM Must run in your own session (not a sandbox): it serves 127.0.0.1:8100
REM plus the extension bridge (9223) and terminal WS. Keep this window open.
REM Restarting is safe: the Chrome extension re-dials 9223 by itself in ~6s.
set PYTHONHOME=
set PYTHONNOUSERSITE=
set VIRTUAL_ENV=
set PYTHONPATH=
cd /d "C:\Users\SATHYA TRADERS\Documents\Abi\Projects\AutoShorts\flowkit"
"C:\Users\SATHYA TRADERS\.workbuddy-ai\binaries\python\envs\flowkit\Scripts\python.exe" -u -m agent.main
pause
