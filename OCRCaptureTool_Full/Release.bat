@echo off
setlocal
cd /d "%~dp0"
title OCR Capture Tool - Publish Offline Package
set "PYTHONUTF8=1"
set "OCR_CAPTURE_NO_PAUSE=1"

if not exist ".venv\Scripts\python.exe" (
  echo Local build environment was not found. Installing it now...
  call install_cpu.bat
  if errorlevel 1 goto :failed
)

set "PY=.venv\Scripts\python.exe"
echo Checking the launcher builder...
"%PY%" -c "import PyInstaller,sys; sys.exit(0 if PyInstaller.__version__=='6.21.0' else 1)" >nul 2>&1
if errorlevel 1 (
  echo Installing the launcher builder once...
  "%PY%" -m pip install pyinstaller==6.21.0 pyinstaller-hooks-contrib
  if errorlevel 1 goto :failed
) else (
  echo PyInstaller 6.21.0 is already ready.
)

echo.
echo Building OFFLINE release...
echo The publisher PC may need network access once to prepare/cache wheels and PP-OCRv6 Medium models.
echo The receiver will NOT need Internet.
echo Expanded Lib/site-packages will NOT be copied into the release ZIP.
"%PY%" build_release.py
if errorlevel 1 goto :failed

echo.
echo Publish completed.
for /f "tokens=2 delims==" %%V in ('findstr /b "APP_VERSION" version.py') do set "VER=%%~V"
set "VER=%VER: =%"
set "VER=%VER:"=%"
echo Send this file to your friends:
echo release\OCRCaptureTool_Full_v%VER%.zip
pause
exit /b 0

:failed
echo.
echo Publish failed. Review the error above.
pause
exit /b 1
