[CmdletBinding()]
param(
    [string]$Config = "config.local.toml",
    [string]$CodexHome = ".codex-local",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "runtime-paths.ps1")
$Python = Get-NpuCodexPython
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }
$CodexHomePath = if ([IO.Path]::IsPathRooted($CodexHome)) { $CodexHome } else { Join-Path $Root $CodexHome }
$Output = Join-Path $CodexHomePath "config.toml"
$AuthFile = Join-Path $CodexHomePath "auth.json"

if (Test-Path $AuthFile) {
    throw "Dedicated CODEX_HOME contains auth.json. Remove it manually after confirming it is not needed: $AuthFile"
}

$Arguments = @(
    "-m", "npu_codex", "write-codex-config",
    "--config", $ConfigPath,
    "--output", $Output
)
if ($Force) { $Arguments += "--force" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Dedicated CODEX_HOME: $CodexHomePath"
Write-Host "Do not copy ChatGPT/OpenAI auth.json into this directory."
