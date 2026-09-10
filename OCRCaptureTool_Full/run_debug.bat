@echo off
setlocal
cd /d "%~dp0"
title OCR Capture Tool - Debug
set "PYTHONUTF8=1"
set "PADDLE_PDX_MODEL_SOURCE=BOS"

if not exist ".venv\Scripts\python.exe" (
  echo The local environment is not installed.
  echo Run install_cpu.bat first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "app.py"
echo.
echo Program exit code: %errorlevel%
pause
