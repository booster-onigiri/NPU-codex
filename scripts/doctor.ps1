[CmdletBinding()]
param(
    [string]$Config = "config.local.toml",
    [switch]$Json
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime-paths.ps1")
$Python = Get-NpuCodexPython
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }

$Arguments = @("-m", "npu_codex", "doctor", "--config", $ConfigPath)
if ($Json) { $Arguments += "--json" }
& $Python @Arguments
exit $LASTEXITCODE
