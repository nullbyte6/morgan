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

$command = @"
`$env:PYTHONPATH = '$root\src;$root\src\third_party\Matcha-TTS'
Set-Location -LiteralPath '$root'
& '$python' '$agent'
"@

Start-Process `
    -FilePath "wt.exe" `
    -ArgumentList @(
        "-w", "new",
        "new-tab",
        "--title", "Arlo",
        "pwsh.exe",
        "-NoLogo",
        "-NoProfile",
        "-NoExit",
        "-Command",
        $command
    )