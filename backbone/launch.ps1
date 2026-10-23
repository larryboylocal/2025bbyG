$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $Root
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }
if ($args -contains "--self-check") {
  & $Python -m terminals.kraken.kraken_runtime --self-check
  exit $LASTEXITCODE
}
& $Python -m terminals.kraken.kraken_runtime
