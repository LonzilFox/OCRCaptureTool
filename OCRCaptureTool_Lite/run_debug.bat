@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title OCRCaptureTool Lite - Debug Launcher
echo OCRCaptureTool Lite v0.2.1 debug launcher
echo This console stays open if startup fails.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -DebugMode
set "ERR=%ERRORLEVEL%"
echo.
echo Launcher exit code: %ERR%
if not "%ERR%"=="0" (
  echo Run log: %~dp0logs\run.log
  echo Build log: %~dp0logs\build.log
)
pause
exit /b %ERR%
