@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1"
if errorlevel 1 (
  echo.
  echo Publish failed. Review the error above.
  pause
  exit /b 1
)
echo.
echo Publish finished.
pause
exit /b 0
