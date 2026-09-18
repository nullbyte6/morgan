$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$agent = Join-Path $root "agent.py"

if (-not (Test-Path $python)) {
    throw "Arlo virtual environment not found: $python"
}

if (-not (Test-Path $agent)) {
    throw "Arlo agent not found: $agent"
}

$env:PYTHONPATH = "$root\src;$root\src\third_party\Matcha-TTS"

& wt.exe `
    -w new `
    new-tab `
    --title "Arlo" `
    --startingDirectory "$root" `
    pwsh.exe `
    -NoLogo `
    -NoProfile `
    -NoExit `
    -Command "& '$python' '$agent'"