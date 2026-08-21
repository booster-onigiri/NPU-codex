[CmdletBinding()]
param(
    [string]$Config = "config.local.toml",
    [switch]$IncludeSmokeTest
)

$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "runtime-paths.ps1")
$Python = Get-NpuCodexPython
$ConfigPath = if ([IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $Root $Config }
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Output = Join-Path $Root "validation-$Stamp"
$Zip = "$Output.zip"
New-Item -ItemType Directory -Force -Path $Output | Out-Null

function Save-CommandOutput {
    param([string]$Name, [scriptblock]$Command)
    try {
        & $Command *>&1 | Out-String | Set-Content (Join-Path $Output "$Name.txt") -Encoding UTF8
    } catch {
        ($_ | Out-String) | Set-Content (Join-Path $Output "$Name.txt") -Encoding UTF8
    }
}

Save-CommandOutput "system" {
    Get-ComputerInfo | Select-Object WindowsProductName, WindowsVersion, OsBuildNumber,
        CsManufacturer, CsModel, CsProcessors, CsTotalPhysicalMemory
}
Save-CommandOutput "python" { & $Python --version }
Save-CommandOutput "codex" {
    $Codex = Get-NpuCodexCli
    & $Codex --version
}
Save-CommandOutput "doctor" { & $Python -m npu_codex doctor --config $ConfigPath --json }
Save-CommandOutput "npu-devices" {
    Get-PnpDevice | Where-Object {
        $_.FriendlyName -match "NPU|Neural|AI Boost" -or $_.InstanceId -match "NPU"
    } | Format-List Status, Class, FriendlyName, InstanceId
}
Save-CommandOutput "display-drivers" { Get-CimInstance Win32_PnPSignedDriver | Where-Object {
        $_.DeviceName -match "Intel.*(NPU|Graphics|AI Boost)"
    } | Select-Object DeviceName, DriverVersion, DriverDate, Manufacturer | Format-List }

if ($IncludeSmokeTest) {
    Save-CommandOutput "smoke-test" { & $Python -m npu_codex smoke-test --config $ConfigPath --json }
}

Compress-Archive -Path (Join-Path $Output "*") -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "Validation log: $Zip"
