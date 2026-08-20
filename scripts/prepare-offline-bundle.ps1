[CmdletBinding()]
param(
    [string]$Python = "python",
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [switch]$IncludeExporter,
    [string]$ModelDirectory,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Output = [IO.Path]::GetFullPath($OutputDirectory)
$ZipPath = "$Output.zip"

if ((Test-Path $Output) -and -not $Force) {
    throw "Output directory already exists. Use -Force after reviewing it: $Output"
}
if (Test-Path $Output) { Remove-Item -Recurse -Force $Output }
if (Test-Path $ZipPath) {
    if (-not $Force) { throw "ZIP already exists: $ZipPath" }
    Remove-Item -Force $ZipPath
}

$Wheelhouse = Join-Path $Output "wheelhouse"
New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null

& $Python -m pip wheel --wheel-dir $Wheelhouse "${Root}[npu]"
if ($LASTEXITCODE -ne 0) { throw "Failed to build the runtime wheelhouse." }
if ($IncludeExporter) {
    & $Python -m pip wheel --wheel-dir $Wheelhouse "${Root}[export]"
    if ($LASTEXITCODE -ne 0) { throw "Failed to add exporter dependencies." }
}

foreach ($Name in @("README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md", "config.example.toml")) {
    Copy-Item (Join-Path $Root $Name) (Join-Path $Output $Name)
}
Copy-Item (Join-Path $Root "scripts") (Join-Path $Output "scripts") -Recurse
Copy-Item (Join-Path $Root "docs") (Join-Path $Output "docs") -Recurse

if ($ModelDirectory) {
    $ResolvedModel = (Resolve-Path $ModelDirectory).Path
    $ModelTarget = Join-Path $Output "models\local-coder"
    New-Item -ItemType Directory -Force -Path $ModelTarget | Out-Null
    Copy-Item (Join-Path $ResolvedModel "*") $ModelTarget -Recurse -Force
}

$HashLines = Get-ChildItem $Output -File -Recurse | Sort-Object FullName | ForEach-Object {
    $Relative = $_.FullName.Substring($Output.Length).TrimStart('\')
    $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  $Relative"
}
$HashLines | Set-Content (Join-Path $Output "SHA256SUMS.txt") -Encoding UTF8

Compress-Archive -Path (Join-Path $Output "*") -DestinationPath $ZipPath -CompressionLevel Optimal
$ZipHash = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$ZipHash  $([IO.Path]::GetFileName($ZipPath))" | Set-Content "$ZipPath.sha256.txt" -Encoding ASCII

Write-Host "Offline bundle: $ZipPath"
Write-Host "SHA-256: $ZipHash"
