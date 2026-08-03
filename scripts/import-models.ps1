$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Legacy = "C:\Projects\video-compose\projects\russian-audiobook-tts-test"
if (-not (Test-Path $Legacy)) { throw "Original model folder is missing: $Legacy" }
New-Item -ItemType Directory -Force -Path "$Root\models" | Out-Null
robocopy "$Legacy\models\f5" "$Root\models\f5" /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) { throw "F5 copy failed: $LASTEXITCODE" }
robocopy "$Legacy\models\ruaccent" "$Root\models\ruaccent" /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) { throw "RUAccent copy failed: $LASTEXITCODE" }
robocopy "$Legacy\models\silero" "$Root\models\silero" /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) { throw "Silero copy failed: $LASTEXITCODE" }
robocopy "$Legacy\models\hf-cache" "$Root\models\hf-cache" /E /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -gt 7) { throw "F5 cache copy failed: $LASTEXITCODE" }
New-Item -ItemType Directory -Force -Path "$Root\models\reference" | Out-Null
Copy-Item "$Legacy\outputs\silero_v5_5_xenia_reference.wav" "$Root\models\reference\xenia.wav" -Force
