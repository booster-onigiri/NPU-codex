[CmdletBinding()]
param(
    [switch]$Mock,
    [switch]$ForceConfig
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime-paths.ps1")
$Python = Get-NpuCodexPython
$Config = Join-Path $Root "config.local.toml"

if ((-not (Test-Path $Config)) -or $ForceConfig) {
    $Arguments = @("-m", "npu_codex", "init", "--output", $Config)
    if ($Mock) { $Arguments += "--mock" }
    if ($ForceConfig) { $Arguments += "--force" }
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Configuration generation failed." }
}

Write-Host "Portable NPU Codex is ready."
Write-Host "Configuration: $Config"
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\scripts\doctor.ps1"
