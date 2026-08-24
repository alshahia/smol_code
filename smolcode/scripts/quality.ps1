# Run the same quality gate as 'make quality' on Windows PowerShell.
$ErrorActionPreference = "Stop"
$venv = Join-Path $PSScriptRoot ".." ".venv"
$ruff = Join-Path $venv "Scripts\ruff.exe"
if (-not (Test-Path $ruff)) {
  Write-Error ".venv missing or ruff not installed. Run scripts/install.ps1 first."
  exit 1
}
& $ruff check src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $ruff format --check src
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "OK quality"
