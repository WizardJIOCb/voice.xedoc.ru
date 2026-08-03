$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv-worker\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts/bootstrap-worker.ps1 first." }
if (-not (Test-Path "$Root\.runtime\worker.token")) { throw "Worker token is missing." }
$existing = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $Python }
if ($existing) { Write-Output "Worker is already running: $($existing.ProcessId -join ', ')"; exit 0 }
Start-Process -FilePath $Python -ArgumentList "worker\worker.py" -WorkingDirectory $Root -WindowStyle Hidden
Write-Output "Worker started; log: $Root\.runtime\worker.log"
