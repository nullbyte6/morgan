param([ValidateSet("Desktop", "Tui")] [string]$Mode = "Desktop")
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$services = Join-Path $PSScriptRoot "arlo-services.ps1"
$module = "entry.desktop"

foreach ($path in @($python, $services)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "ARLO required file not found: $path"
    }
}

$env:PYTHONPATH = @(
    $root
    (Join-Path $root "src")
    (Join-Path $root "src\third_party\Matcha-TTS")
) -join [IO.Path]::PathSeparator

$env:ARLO_EXTERNAL_CONSOLE = "1"

Set-Location -LiteralPath $root

if ($Mode -eq "Desktop") {
    & $services -NoConsole
}
else {
    & $services
}

if (-not $?) {
    throw "ARLO services failed to start."
}

Write-Host "Starting ARLO: $Mode"

if ($Mode -eq "Desktop") {
    Start-Process `
        -FilePath $python `
        -ArgumentList "-m", $module `
        -WorkingDirectory $root `
        -WindowStyle Hidden

    Write-Host "ARLO started independently in the background."
    exit 0
}

& $python -m $module

exit $LASTEXITCODE
