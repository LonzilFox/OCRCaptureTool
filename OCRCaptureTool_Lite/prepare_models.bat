@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title OCRCaptureTool Lite - Prepare Models
echo Verifying or reusing PP-OCRv6 Small models...
echo Existing ScreenAssistant models are reused first; network is only a fallback.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_models.ps1" -CalledByRunner
set "ERR=%ERRORLEVEL%"
echo.
if not "%ERR%"=="0" (
  echo Model preparation failed. Review the popup and log.
  echo Log: %~dp0logs\prepare_models.log
) else (
  echo Model preparation completed successfully.
)
echo.
pause
exit /b %ERR%
