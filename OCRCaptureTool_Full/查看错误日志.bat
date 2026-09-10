@echo off
setlocal
set "LOGDIR=%LOCALAPPDATA%\OCRCaptureTool\logs"
if not exist "%LOGDIR%" (
  echo No error log directory was found.
  pause
  exit /b 0
)
start "" explorer "%LOGDIR%"
exit /b 0
