param([string]$PythonVersion = "3.11")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not (Test-Path ".venv-worker")) { uv venv --python $PythonVersion .venv-worker }
uv pip install --python .venv-worker\Scripts\python.exe torch==2.8.0+cu128 torchaudio==2.8.0+cu128 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv-worker\Scripts\python.exe -r worker\requirements.txt
& .venv-worker\Scripts\python.exe -c "import torch; assert torch.cuda.is_available(), 'CUDA is unavailable'; print(torch.cuda.get_device_name(0))"

