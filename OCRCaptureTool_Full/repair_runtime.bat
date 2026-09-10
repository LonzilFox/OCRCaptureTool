@echo off
setlocal
cd /d "%~dp0"
title OCR Capture Tool - Repair Runtime
set "PYTHONUTF8=1"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment was not found.
  echo Run install_cpu.bat first.
  pause
  exit /b 1
)

set "PY=.venv\Scripts\python.exe"
echo Reinstalling the stable PaddlePaddle runtime...
"%PY%" -m pip uninstall -y paddlepaddle paddlepaddle-gpu
if errorlevel 1 goto :failed
"%PY%" -m pip install --no-cache-dir --force-reinstall "numpy>=1.26.4,<2.0"
if errorlevel 1 goto :failed
"%PY%" -m pip install --no-cache-dir --force-reinstall paddlepaddle==3.2.2 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
if errorlevel 1 goto :failed
"%PY%" -c "import paddle; print('PaddlePaddle', paddle.__version__); paddle.utils.run_check()"
if errorlevel 1 goto :failed

echo.
echo Runtime repair completed.
pause
exit /b 0

:failed
echo.
echo Runtime repair failed. Review the error above.
pause
exit /b 1
