@echo off
rem ── ZoneMiner launcher ──────────────────────────────────────────
rem Double-click this file to start the app. A black window will open —
rem KEEP IT OPEN while you use the app (closing it stops the server).
rem Your browser opens automatically after a few seconds.
rem ─────────────────────────────────────────────────────────────────────
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  The Python environment is missing. One-time setup:
  echo    1^) install Python 3.12+ from python.org
  echo    2^) run:  python -m venv .venv
  echo    3^) run:  .venv\Scripts\pip install -r requirements.txt
  echo  Then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo.
echo  Starting ZoneMiner ...
echo  Your browser will open at http://127.0.0.1:8765 in a moment.
echo  KEEP THIS WINDOW OPEN while using the app. Close it to stop.
echo.

rem Port 8765 on purpose: Docker Desktop and other tools often occupy 8000.
start "" cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --port 8765
pause
