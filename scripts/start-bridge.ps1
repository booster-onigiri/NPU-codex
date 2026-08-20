[CmdletBinding()]
param(
    [string]$Config = "config.local.toml"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }

if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }
if (-not (Test-Path $ConfigPath)) { throw "Configuration not found: $ConfigPath" }

$env:PYTHONUTF8 = "1"
& $Python -m npu_codex serve --config $ConfigPath
exit $LASTEXITCODE
