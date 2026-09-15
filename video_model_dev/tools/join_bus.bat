@echo off
set AGENT=%1
if "%AGENT%"=="" set AGENT=Pi-Agent
echo ===================================================
echo   Joining Multi-Agent Conversation Bus as: @%AGENT%
echo ===================================================
python tools\agent_bus.py live --agent %AGENT%
pause
