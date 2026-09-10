@echo off
setlocal
cd /d "%~dp0"
title OCR Capture Tool - Install
set "PYTHONUTF8=1"

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher was not found.
  echo Install 64-bit Python 3.12 and enable the Python launcher.
  goto :failed
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating Python 3.12 virtual environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :failed
)

set "PY=.venv\Scripts\python.exe"
echo Updating basic packaging tools...
"%PY%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :failed

echo Installing the stable CPU runtime...
"%PY%" -m pip uninstall -y paddlepaddle paddlepaddle-gpu >nul 2>nul
"%PY%" -m pip install --no-cache-dir "numpy>=1.26.4,<2.0"
if errorlevel 1 goto :failed
"%PY%" -m pip install --no-cache-dir paddlepaddle==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
if errorlevel 1 goto :failed

echo Installing OCR and interface dependencies...
"%PY%" -m pip install --prefer-binary -r requirements.txt
if errorlevel 1 goto :failed

"%PY%" -c "import paddle, paddleocr, PySide6, PIL, pynput; print('PaddlePaddle', paddle.__version__); print('PaddleOCR', paddleocr.__version__); print('Environment check OK')"
if errorlevel 1 goto :failed

echo.
echo Installation completed.
echo Use run.bat to start, or use the publish BAT to build a package for friends.
if defined OCR_CAPTURE_NO_PAUSE exit /b 0
pause
exit /b 0

:failed
echo.
echo Installation failed. Review the error above.
if defined OCR_CAPTURE_NO_PAUSE exit /b 1
pause
exit /b 1
