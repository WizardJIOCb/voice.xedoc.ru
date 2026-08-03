$processes = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '[\\/]worker[\\/]worker\.py' }
if (-not $processes) { Write-Output "Worker is not running."; exit 0 }
$processes | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Output "Stopped worker: $($processes.ProcessId -join ', ')"
