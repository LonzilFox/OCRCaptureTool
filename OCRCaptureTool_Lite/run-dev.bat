@echo off
setlocal
cd /d "%~dp0"
if /I "%~1"=="debug" goto debug
if /I "%~1"=="--debug" goto debug
if not exist "%~dp0run_hidden.vbs" goto missing
wscript.exe //B "%~dp0run_hidden.vbs"
exit /b %ERRORLEVEL%

:debug
chcp 65001 >nul
title OCRCaptureTool Lite - Developer Debug
echo OCRCaptureTool Lite v0.2.1 - developer debug mode
echo This window will stay open after the launcher exits.
echo.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" -DebugMode
set "ERR=%ERRORLEVEL%"
echo.
echo Launcher exit code: %ERR%
echo Run log: %~dp0logs\run.log
echo Build log: %~dp0logs\build.log
pause
exit /b %ERR%

:missing
echo ERROR: run_hidden.vbs is missing. Re-extract the complete project.
pause
exit /b 1
