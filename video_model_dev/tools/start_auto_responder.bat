@echo off
set AGENT=%1
if "%AGENT%"=="" set AGENT=Pi-Agent
echo =======================================================
echo   Starting Autonomous Auto-Responder for @%AGENT%
echo =======================================================
python tools\auto_responder.py --agent %AGENT% --interval 5
pause
