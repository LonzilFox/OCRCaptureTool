@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PADDLE_PDX_MODEL_SOURCE=BOS"

if not exist ".venv\Scripts\pythonw.exe" (
  echo The local environment is not installed.
  echo Run install_cpu.bat first.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "app.py"
exit /b 0
