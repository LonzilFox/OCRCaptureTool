@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_release.ps1"
if errorlevel 1 (
  echo.
  echo Publish failed. Review the error above.
  pause
  exit /b 1
)
echo.
echo Publish finished.
pause
endlocal
