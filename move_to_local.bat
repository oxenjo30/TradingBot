@echo off
setlocal
echo ============================================================
echo  TradeBot -- Move project OUT of OneDrive
echo  This fixes antivirus false-positives and DB locking issues
echo ============================================================
echo.

set SRC=C:\Users\johnr\OneDrive\Documents\ClaudeAi\Trading
set DST=C:\TradeBot

echo Source : %SRC%
echo Target : %DST%
echo.

if exist "%DST%" (
  echo [!] C:\TradeBot already exists. Delete it first if you want a fresh copy.
  pause
  exit /b 1
)

echo [1/3] Copying project files (excluding .venv)...
robocopy "%SRC%" "%DST%" /E /XD "%SRC%\.venv" /XD "%SRC%\__pycache__" /NP /NFL /NDL
echo Done.

echo [2/3] Creating fresh virtual environment in C:\TradeBot\.venv ...
REM Use -V:3.13 (standard, NOT the 3.13t free-threaded experimental build)
py -V:3.13 -m venv "%DST%\.venv"
"%DST%\.venv\Scripts\pip.exe" install -r "%DST%\requirements.txt" --quiet
echo Done.

echo [3/3] Copying database (trading.db) if it exists...
if exist "%SRC%\trading.db" (
  copy /Y "%SRC%\trading.db" "%DST%\trading.db"
  echo Database copied.
) else (
  echo No existing database found - will be created fresh.
)

echo.
echo ============================================================
echo  Done! Your TradeBot is now at C:\TradeBot
echo  Open C:\TradeBot and run start.bat from there.
echo.
echo  IMPORTANT: Add C:\TradeBot to Windows Defender exclusions:
echo    Windows Security -^> Virus Protection -^> Exclusions -^> Add Folder
echo ============================================================
pause
