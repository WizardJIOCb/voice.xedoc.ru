@echo off
setlocal
cd /d "%~dp0"

if not exist ".runtime\worker.token" (
  echo Worker token is missing. Configure this computer first.
  pause
  exit /b 1
)

if not exist ".venv-worker\Scripts\python.exe" (
  echo Preparing the local GPU worker. This may take a few minutes on first launch.
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap-worker.ps1"
  if errorlevel 1 goto :error
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-worker.ps1"
if errorlevel 1 goto :error

echo.
echo Local GPU worker is ready. You can close this window and use https://voice.xedoc.ru
exit /b 0

:error
echo.
echo The local GPU worker could not be started. See the message above.
pause
exit /b 1
