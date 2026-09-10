@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
title OCRCaptureTool Lite - Prepare Models
echo Verifying PP-OCRv6 Small models...
echo A progress window shows validation/download status.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0prepare_models.ps1"
set "ERR=%ERRORLEVEL%"
if not "%ERR%"=="0" (
  echo.
  echo Model preparation failed.
  echo Log: %~dp0logs\prepare_models.log
  pause
)
exit /b %ERR%
