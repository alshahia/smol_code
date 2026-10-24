# Create venv and install smolcode with dev extras on Windows PowerShell.
#
# Phase 8 (decision 0043): do NOT hardcode a Python minor version. The
# interpreter is resolved as: `py -3` (latest installed 3.x), then `python`,
# then `python3`; the first candidate reporting >= 3.10 wins. Previously this
# script ran `py -3.12` unconditionally, so a machine with only 3.11/3.13
# failed with a confusing launcher error instead of using the supported
# interpreter. Paths resolve from $PSScriptRoot so the script works from any
# working directory (matching scripts/quality.ps1).
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$candidates = @(
    @{ Exe = "py.exe";     Prefix = @("-3") },
    @{ Exe = "python.exe"; Prefix = @()    },
    @{ Exe = "python3.exe"; Prefix = @()   }
)
$chosen = $null
foreach ($c in $candidates) {
    $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    & $cmd.Source @($c.Prefix) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $chosen = @{ Exe = $cmd.Source; Prefix = $c.Prefix }; break }
}
if (-not $chosen) {
    Write-Error "no Python >= 3.10 found (looked for 'py -3', 'python', 'python3')"
    exit 1
}

$venv = Join-Path $root ".venv"
& $chosen.Exe @($chosen.Prefix) -m venv $venv
if ($LASTEXITCODE -ne 0) { Write-Error "failed to create venv at $venv"; exit 1 }
$py = Join-Path $venv "Scripts\python.exe"

Push-Location $root
try {
    & $py -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { Write-Error "failed to upgrade pip"; exit 1 }
    & $py -m pip install -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { Write-Error "failed to install smolcode[dev]"; exit 1 }
    & $py -c "import smolagents; print('OK smolagents ' + smolagents.__version__)"
    if ($LASTEXITCODE -ne 0) { Write-Error "smolagents import check failed"; exit 1 }
}
finally {
    Pop-Location
}
Write-Host "OK smolcode installed in $venv"
