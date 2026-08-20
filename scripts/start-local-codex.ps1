[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Workspace,
    [string]$Config = "config.local.toml",
    [string]$CodexHome = ".codex-local",
    [switch]$Offline,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArguments
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }
$CodexHomePath = if ([IO.Path]::IsPathRooted($CodexHome)) { $CodexHome } else { Join-Path $Root $CodexHome }
$CodexConfig = Join-Path $CodexHomePath "config.toml"

if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }
if (-not (Test-Path $Workspace -PathType Container)) { throw "Workspace not found: $Workspace" }
if (-not (Test-Path $CodexConfig)) { throw "Run scripts\configure-codex.ps1 first." }
if (Test-Path (Join-Path $CodexHomePath "auth.json")) {
    throw "Dedicated CODEX_HOME must not contain auth.json: $CodexHomePath"
}
if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI was not found in PATH."
}

# Verify the bridge before starting Codex. Import the TOML through the project CLI
# rather than duplicating its parser in PowerShell.
$DoctorJson = & $Python -m npu_codex doctor --config $ConfigPath --json
if ($LASTEXITCODE -ne 0) { throw "NPU Codex doctor reported a critical failure." }
$Doctor = $DoctorJson | ConvertFrom-Json
$ListenCheck = $Doctor.checks | Where-Object { $_.name -eq "listen_port" }
if ($ListenCheck.ok) {
    throw "The bridge does not appear to be running; the configured port is still free. Start scripts\start-bridge.ps1 first."
}

$Headers = @{}
if ($env:NPU_CODEX_API_TOKEN) {
    $Headers["Authorization"] = "Bearer $($env:NPU_CODEX_API_TOKEN)"
}
$HealthUri = "http://$($ListenCheck.detail)/healthz"
try {
    $Health = Invoke-RestMethod -Method Get -Uri $HealthUri -Headers $Headers -TimeoutSec 10
} catch {
    throw "The configured port is occupied, but NPU Codex health check failed at $HealthUri. $($_.Exception.Message)"
}
if ($Health.status -ne "ok" -or -not $Health.version) {
    throw "Unexpected service response from $HealthUri"
}

$env:CODEX_HOME = $CodexHomePath
if ($Offline) {
    $env:HF_HUB_OFFLINE = "1"
    $env:TRANSFORMERS_OFFLINE = "1"
    $env:HF_DATASETS_OFFLINE = "1"
}

Push-Location (Resolve-Path $Workspace)
try {
    & codex @CodexArguments
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
