$Root = Split-Path -Parent $PSScriptRoot
$PortablePython = Join-Path $Root "runtime\python\python.exe"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$PortableCodex = Join-Path $Root "runtime\codex\codex.exe"

function Get-NpuCodexPython {
    if (Test-Path $PortablePython -PathType Leaf) { return $PortablePython }
    if (Test-Path $VenvPython -PathType Leaf) { return $VenvPython }
    throw "Python runtime was not found. Use the portable bundle or run scripts\bootstrap.ps1."
}

function Get-NpuCodexCli {
    if (Test-Path $PortableCodex -PathType Leaf) { return $PortableCodex }
    $Command = Get-Command codex -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }
    throw "Codex CLI was not found. Use the portable bundle or install Codex CLI."
}
