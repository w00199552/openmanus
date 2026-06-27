@echo off
REM Stop all deepmanus services (kill processes on 8000/4000/5173).

echo [deepmanus] stopping services...

for %%P in (8000 4000 5173) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P" ^| findstr "LISTENING"') do (
        echo   killing port %%P  (PID %%A)
        taskkill /F /PID %%A >nul 2>&1
    )
)

echo [deepmanus] stopped.
pause
