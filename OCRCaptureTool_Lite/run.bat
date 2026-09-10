@echo off
setlocal
cd /d "%~dp0"
wscript.exe //B "%~dp0run_hidden.vbs"
exit /b 0
