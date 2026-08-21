[CmdletBinding()]
param(
    [string]$Config = "config.local.toml"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime-paths.ps1")
$Python = Get-NpuCodexPython
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }

if (-not (Test-Path $ConfigPath)) { throw "Configuration not found: $ConfigPath" }

$env:PYTHONUTF8 = "1"
& $Python -m npu_codex serve --config $ConfigPath
exit $LASTEXITCODE
