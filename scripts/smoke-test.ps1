[CmdletBinding()]
param(
    [string]$Config = "config.local.toml",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }

if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }
$Arguments = @("-m", "npu_codex", "smoke-test", "--config", $ConfigPath)
if ($Json) { $Arguments += "--json" }
& $Python @Arguments
exit $LASTEXITCODE
