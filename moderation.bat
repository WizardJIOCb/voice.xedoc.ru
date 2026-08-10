@echo off
setlocal
cd /d "%~dp0"

if not exist ".runtime\moderation.key" (
  echo Moderation key is not configured on this computer.
  pause
  exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$key = [uri]::EscapeDataString((Get-Content -Raw '.runtime\moderation.key').Trim()); Start-Process ('https://voice.xedoc.ru/#moderation=' + $key)"
exit /b 0
