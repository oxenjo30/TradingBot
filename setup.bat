@echo off
title TradeBot Setup
color 0A
cls

echo ============================================================
echo         TRADEBOT - One-Click Setup
echo ============================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python not found. Downloading Python 3.13...
    echo.
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.13.3/python-3.13.3-amd64.exe' -OutFile '%TEMP%\python-installer.exe'"
    echo [*] Installing Python (this may take a minute)...
    "%TEMP%\python-installer.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
    if errorlevel 1 (
        echo [ERROR] Python installation failed. Please install Python 3.11+ manually from python.org
        pause
        exit /b 1
    )
    echo [OK] Python installed.
    echo.
) else (
    for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [OK] Python %%v found.
)

:: Create virtual environment if missing
if not exist ".venv\Scripts\python.exe" (
    echo [*] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: Install / upgrade dependencies
echo [*] Installing dependencies (first run may take 1-2 minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.
echo.

:: Initialize database
echo [*] Initializing database...
.venv\Scripts\python.exe -c "from server.db import init_db; init_db(); print('[OK] Database ready.')"
echo.

echo ============================================================
echo  Setup complete! Starting TradeBot...
echo  Dashboard will open in your browser automatically.
echo  Keep this window open while using the bot.
echo  Press Ctrl+C to stop the bot.
echo ============================================================
echo.

:: Wait 2 seconds then open browser
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

:: Start server
.venv\Scripts\python.exe -m uvicorn server.main:app --host 0.0.0.0 --port 8000

pause
