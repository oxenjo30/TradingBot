@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Creating virtualenv...
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
echo.
echo Starting Trading Bot at http://localhost:8000
echo Press Ctrl+C to stop.
echo.
.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000
