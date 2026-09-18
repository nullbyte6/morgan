param([switch]$Run)

$ErrorActionPreference = "Stop"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Start-Process `
        -FilePath "pwsh.exe" `
        -Verb RunAs `
        -ArgumentList @(
            "-NoLogo",
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$PSCommandPath`"")
    exit
}

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

    sudo cmd.exe /c start "" wt.exe -w new `
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