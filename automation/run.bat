@echo off
REM ===========================================================================
REM  AutoShorts scheduled run wrapper.
REM
REM  Usage:   run.bat [runner options]
REM  Example: run.bat --source rss --url https://example.com/feed.xml --limit 1
REM
REM  Every run appends to storage\automation\logs\runner.log so that an
REM  unattended Task Scheduler run leaves a trail to inspect afterwards.
REM  Exit codes: 0 = ok, 1 = at least one task failed, 2 = could not start.
REM ===========================================================================
setlocal EnableExtensions

cd /d "%~dp0.." || exit /b 2

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "LOGDIR=storage\automation\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

set "LOGFILE=%LOGDIR%\runner.log"

echo.>> "%LOGFILE%"
echo ==================== run started ====================>> "%LOGFILE%"

"%PY%" -m automation.runner %* >> "%LOGFILE%" 2>&1
set "CODE=%ERRORLEVEL%"

echo exit code %CODE%>> "%LOGFILE%"

echo AutoShorts finished with exit code %CODE%.
echo Log: %LOGFILE%
exit /b %CODE%
