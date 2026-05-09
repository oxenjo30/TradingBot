@echo off
title TradeBot
color 0A
cls

echo ============================================================
echo   TRADEBOT - Starting...
echo   Dashboard: http://localhost:8000
echo   Keep this window open. Press Ctrl+C to stop.
echo ============================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [!] First time? Run setup.bat first.
    pause
    exit /b 1
)

REM Check if port 8000 is already in use
netstat -an | find ":8000 " | find "LISTENING" >nul
if %errorlevel%==0 (
    echo [!] Port 8000 is already in use.
    echo     Another TradeBot may already be running.
    echo     Close the other window and try again, or open:
    echo     http://localhost:8000
    echo.
    pause
    exit /b 1
)

echo [TIP] If Windows Defender blocks this app, add this folder to exclusions:
echo   Windows Security -^> Virus Protection -^> Exclusions -^> Add Folder
echo   Then add: %CD%
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"
.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
pause
