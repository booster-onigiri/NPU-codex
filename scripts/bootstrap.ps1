[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Wheelhouse,
    [switch]$Mock,
    [switch]$ForceConfig
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Config = Join-Path $Root "config.local.toml"

if (-not (Test-Path $VenvPython)) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create Python virtual environment." }
}

if ($Wheelhouse) {
    $Wheelhouse = (Resolve-Path $Wheelhouse).Path
    $Package = if ($Mock) { "npu-codex" } else { "npu-codex[npu]" }
    & $VenvPython -m pip install --no-index --find-links $Wheelhouse $Package
} else {
    & $VenvPython -m pip install --upgrade pip
    $Target = if ($Mock) { $Root } else { "${Root}[npu]" }
    & $VenvPython -m pip install -e $Target
}
if ($LASTEXITCODE -ne 0) { throw "Package installation failed." }

if ((-not (Test-Path $Config)) -or $ForceConfig) {
    $InitArgs = @("-m", "npu_codex", "init", "--output", $Config)
    if ($Mock) { $InitArgs += "--mock" }
    if ($ForceConfig) { $InitArgs += "--force" }
    & $VenvPython @InitArgs
    if ($LASTEXITCODE -ne 0) { throw "Configuration generation failed." }
}

Write-Host "Installed NPU Codex in $Venv"
Write-Host "Configuration: $Config"
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1"
