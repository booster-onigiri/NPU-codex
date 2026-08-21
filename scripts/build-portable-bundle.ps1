[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.9",
    [string]$CodexVersion = "latest",
    [string]$OutputDirectory = "dist\NPUCodexPortable",
    [string]$ModelDirectory,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Output = [IO.Path]::GetFullPath((Join-Path $Root $OutputDirectory))
$ZipPath = "$Output.zip"
$Temp = Join-Path ([IO.Path]::GetTempPath()) ("npu-codex-" + [Guid]::NewGuid().ToString("N"))

if ((Test-Path $Output) -or (Test-Path $ZipPath)) {
    if (-not $Force) { throw "Output exists. Re-run with -Force after reviewing it: $Output" }
    if (Test-Path $Output) { Remove-Item -Recurse -Force $Output }
    if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
}

try {
    New-Item -ItemType Directory -Force -Path $Output, $Temp | Out-Null
    $PythonRuntime = Join-Path $Output "runtime\python"
    $CodexRuntime = Join-Path $Output "runtime\codex"
    New-Item -ItemType Directory -Force -Path $PythonRuntime, $CodexRuntime | Out-Null

    $PythonTag = $PythonVersion.Replace(".", "")
    $PythonUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    $PythonZip = Join-Path $Temp "python.zip"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $PythonZip
    Expand-Archive $PythonZip -DestinationPath $PythonRuntime
    $Pth = Get-ChildItem $PythonRuntime -Filter "python*._pth" | Select-Object -First 1
    if (-not $Pth) { throw "Embedded Python _pth file was not found." }
    (Get-Content $Pth.FullName) -replace '^#import site$', 'import site' |
        Set-Content $Pth.FullName -Encoding ASCII

    $SitePackages = Join-Path $PythonRuntime "Lib\site-packages"
    New-Item -ItemType Directory -Force -Path $SitePackages | Out-Null
    python -m pip install --disable-pip-version-check --target $SitePackages "${Root}[npu]"
    if ($LASTEXITCODE -ne 0) { throw "Failed to install portable Python dependencies." }

    $NpmPrefix = Join-Path $Temp "npm"
    npm install --prefix $NpmPrefix "@openai/codex@$CodexVersion"
    if ($LASTEXITCODE -ne 0) { throw "Failed to obtain Codex CLI." }
    $CodexExe = Get-ChildItem $NpmPrefix -Filter "codex.exe" -File -Recurse | Select-Object -First 1
    if (-not $CodexExe) { throw "codex.exe was not found in the installed @openai/codex package." }
    Copy-Item $CodexExe.FullName (Join-Path $CodexRuntime "codex.exe")

    foreach ($Name in @("README.md", "LICENSE", "SECURITY.md", "CHANGELOG.md", "config.example.toml")) {
        Copy-Item (Join-Path $Root $Name) (Join-Path $Output $Name)
    }
    Copy-Item (Join-Path $Root "scripts") (Join-Path $Output "scripts") -Recurse
    Copy-Item (Join-Path $Root "docs") (Join-Path $Output "docs") -Recurse
    New-Item -ItemType Directory -Force -Path (Join-Path $Output "models") | Out-Null

    if ($ModelDirectory) {
        $ResolvedModel = (Resolve-Path $ModelDirectory).Path
        Copy-Item $ResolvedModel (Join-Path $Output "models\local-coder") -Recurse
    }

    @(
        "python=$PythonVersion"
        "codex=$CodexVersion"
        "built_utc=$([DateTime]::UtcNow.ToString('o'))"
        "physical_npu_tested=false"
    ) | Set-Content (Join-Path $Output "BUNDLE-MANIFEST.txt") -Encoding ASCII

    $HashLines = Get-ChildItem $Output -File -Recurse | Sort-Object FullName | ForEach-Object {
        $Relative = $_.FullName.Substring($Output.Length).TrimStart('\')
        $Hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash  $Relative"
    }
    $HashLines | Set-Content (Join-Path $Output "SHA256SUMS.txt") -Encoding UTF8
    Compress-Archive -Path (Join-Path $Output "*") -DestinationPath $ZipPath -CompressionLevel Optimal
    (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLowerInvariant() |
        Set-Content "$ZipPath.sha256.txt" -Encoding ASCII
    Write-Host "Portable bundle: $ZipPath"
} finally {
    if (Test-Path $Temp) { Remove-Item -Recurse -Force $Temp }
}
