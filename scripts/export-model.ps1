[CmdletBinding()]
param(
    [string]$ModelId = "Qwen/Qwen2.5-Coder-1.5B-Instruct",
    [string]$OutputDirectory = "models/local-coder",
    [ValidateSet("128", "-1")]
    [string]$GroupSize = "128",
    [switch]$InstallDependencies,
    [switch]$TrustRemoteCode,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Optimum = Join-Path $Root ".venv\Scripts\optimum-cli.exe"
$Output = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    $OutputDirectory
} else {
    Join-Path $Root $OutputDirectory
}

if (-not (Test-Path $Python)) { throw "Run scripts\bootstrap.ps1 first." }
if ((Test-Path $Output) -and (Get-ChildItem $Output -Force | Select-Object -First 1) -and -not $Force) {
    throw "Output directory is not empty. Use -Force only after reviewing it: $Output"
}
if ($InstallDependencies) {
    & $Python -m pip install -e "${Root}[export]"
    if ($LASTEXITCODE -ne 0) { throw "Model exporter dependency installation failed." }
}
if (-not (Test-Path $Optimum)) {
    throw "optimum-cli was not found. Re-run with -InstallDependencies on a connected preparation PC."
}

New-Item -ItemType Directory -Force -Path $Output | Out-Null
$Arguments = @(
    "export", "openvino",
    "-m", $ModelId,
    "--weight-format", "int4",
    "--sym",
    "--ratio", "1.0",
    "--group-size", $GroupSize
)
if ($TrustRemoteCode) { $Arguments += "--trust-remote-code" }
$Arguments += $Output

Write-Warning "Review and accept the model license before downloading or converting it."
& $Optimum @Arguments
if ($LASTEXITCODE -ne 0) { throw "Model export failed." }
Write-Host "OpenVINO model exported to $Output"
