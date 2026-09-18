param([switch]$Run)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$agent = Join-Path $root "agent.py"

if (-not (Test-Path $python)) {
    throw "ARLO virtual environment (.venv) not found: $python"
}

if (-not (Test-Path $agent)) {
    throw "ARLO agent not found: $agent"
}

if (-not $Run) {
    $self = $PSCommandPath

    cmd.exe /c start "" wt.exe -w new `
        new-tab `
        --title "ARLO" `
        --suppressApplicationTitle `
        --startingDirectory "$root" `
        pwsh.exe -NoLogo -NoProfile -NoExit -File "$self" -Run

    exit
}

$Host.UI.RawUI.WindowTitle = "ARLO"
$env:PYTHONPATH = "$root\src;$root\src\third_party\Matcha-TTS"
Set-Location -LiteralPath $root
& $python $agent