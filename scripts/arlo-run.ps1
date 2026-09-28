param([ValidateSet("Desktop", "Tui")] [string]$Mode = "Desktop")
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$services = Join-Path $PSScriptRoot "arlo-services.ps1"
$module = "entry.desktop"

foreach ($path in @($python, $services)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Assistant required file not found: $path"
    }
}

$env:PYTHONPATH = @(
    $root
    (Join-Path $root "src")
    (Join-Path $root "src\third_party\Matcha-TTS")
) -join [IO.Path]::PathSeparator

$env:ASSISTANT_EXTERNAL_CONSOLE = "1"

Set-Location -LiteralPath $root

if ($Mode -eq "Desktop") {
    & $services -NoConsole
}
else {
    & $services
}

if (-not $?) {
    throw "Assistant services failed to start."
}

Write-Host "Starting $env:ASSISTANT_NAME`: $Mode"

if ($Mode -eq "Desktop") {
    $desktopDir = [Environment]::GetEnvironmentVariable($env:ASSISTANT_NAME.ToUpperInvariant())
    if ([string]::IsNullOrWhiteSpace($desktopDir)) { $desktopDir = "C:\Arlo" }
    $desktopExe = Join-Path $desktopDir "Arlo.exe"
    if (Test-Path -LiteralPath $desktopExe -PathType Leaf) {
        Start-Process -FilePath $desktopExe -WorkingDirectory $root -WindowStyle Hidden
    }
    else {
        Start-Process `
            -FilePath $python `
            -ArgumentList "-m", $module `
            -WorkingDirectory $root `
            -WindowStyle Hidden
    }

    Write-Host "$env:ASSISTANT_NAME started independently in the background."
    exit 0
}

& $python -m $module

exit $LASTEXITCODE
