@echo off
REM deepmanus Windows launcher — starts backend, runtime, frontend.
REM Usage: double-click dev.bat  (or run in cmd). Ctrl+C each window to stop.

setlocal
set ROOT=%~dp0
set LOGDIR=%ROOT%.logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [deepmanus] starting services...
echo.

REM --- 1. backend (Python, :8000) ---
echo [deepmanus] starting backend  (logs: .logs\backend.log)
start "deepmanus-backend" /D "%ROOT%backend" cmd /c "uv run uvicorn deepopen.main:app --port 8000 > %LOGDIR%\backend.log 2>&1"

REM --- 2. runtime (Express, :4000) ---
timeout /t 2 /nobreak >nul
echo [deepmanus] starting runtime  (logs: .logs\runtime.log)
start "deepmanus-runtime" /D "%ROOT%runtime" cmd /c "node src\index.js > %LOGDIR%\runtime.log 2>&1"

REM --- 3. frontend (vite, :5173) ---
timeout /t 2 /nobreak >nul
echo [deepmanus] starting frontend (logs: .logs\frontend.log)
start "deepmanus-frontend" /D "%ROOT%frontend" cmd /c "yarn dev > %LOGDIR%\frontend.log 2>&1"

echo.
echo [deepmanus] all services starting.
echo    frontend: http://localhost:5173
echo    runtime:  http://localhost:4000/api/copilotkit/info
echo    backend:  http://localhost:8000/agents/main/health
echo    (close the 3 popup windows to stop each service)
echo.

REM keep this window open so you can see the message
pause
endlocal
