# Create venv and install smolcode with dev extras on Windows PowerShell.
$ErrorActionPreference = "Stop"
$py = (Get-Command "py.exe" -ErrorAction SilentlyContinue)?.Source
if (-not $py) { $py = "python" }
& $py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pip show smolagents | Out-Null
Write-Host "OK smolagents installed"
