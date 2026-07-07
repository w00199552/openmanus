@echo off
REM openmanus restart — kills old processes, then starts in order:
REM   1. backend (:8999)  — wait for health check
REM   2. frontend (:5173) — wait for vite ready
REM   3. electron          — desktop client (dev mode)
REM Usage: double-click restart.bat

setlocal
set ROOT=%~dp0
set LOGDIR=%ROOT%.logs
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

echo [openmanus] stopping old services...
taskkill /F /IM electron.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM node.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [openmanus] starting services fresh...
echo.

REM --- 1. backend (Python, :8999) ---
echo [openmanus] starting backend...
start "openmanus-backend" /D "%ROOT%backend" cmd /c "uv run uvicorn openmanus.main:app --port 8999"

REM Wait for backend health check (max 30 retries = 30 seconds)
set RETRIES=0
:WAIT_BACKEND
timeout /t 1 /nobreak >nul
curl -s -o nul http://127.0.0.1:8999/health 2>nul
if %ERRORLEVEL% neq 0 (
    set /a RETRIES+=1
    if %RETRIES% lss 30 (
        goto :WAIT_BACKEND
    )
    echo [openmanus] ERROR: backend health check failed after 30s
    pause
    exit /b 1
)
echo [openmanus] backend ready (health OK)

REM --- 2. frontend (vite, :5173) ---
echo [openmanus] starting frontend...
start "openmanus-frontend" /D "%ROOT%frontend" cmd /c "yarn dev"

REM Wait for frontend (max 30 retries)
set RETRIES=0
:WAIT_FRONTEND
timeout /t 1 /nobreak >nul
curl -s -o nul http://localhost:5173 2>nul
if %ERRORLEVEL% neq 0 (
    set /a RETRIES+=1
    if %RETRIES% lss 30 (
        goto :WAIT_FRONTEND
    )
    echo [openmanus] ERROR: frontend not ready after 30s
    pause
    exit /b 1
)
echo [openmanus] frontend ready (http://localhost:5173)

REM --- 3. electron (desktop client, dev mode) ---
echo [openmanus] starting electron desktop client...
start "openmanus-electron" /D "%ROOT%electron" cmd /c "npm run dev"

echo.
echo [openmanus] all services started:
echo    backend:  http://127.0.0.1:8999/health
echo    frontend: http://localhost:5173
echo    electron: desktop window (dev mode)
echo    (close the popup windows to stop each service)
echo.

pause
endlocal
