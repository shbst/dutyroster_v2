param([switch]$Lan, [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$appPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $appPython)) {
    Write-Host 'Python 3.12+ で python -m venv .venv を実行し、.venv\Scripts\python.exe -m pip install -r requirements.txt を実行してください。'
    exit 1
}
$bindAddress = if ($Lan) { '0.0.0.0' } else { '127.0.0.1' }
Write-Host "当直ノート: http://localhost:$Port"
& $appPython -m uvicorn app.main:app --host $bindAddress --port $Port
