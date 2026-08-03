$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root '.venv-worker\Scripts\python.exe'
$processes = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $Python -or $_.CommandLine -like '*worker.py*'
}
if (-not $processes) { Write-Output "Worker is not running."; exit 0 }
$processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Output "Stopped worker: $($processes.ProcessId -join ', ')"
