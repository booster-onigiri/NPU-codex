[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }

Push-Location $Root
try {
    & $Python -m ruff check .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m compileall -q src tests
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python -m pytest -q
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
