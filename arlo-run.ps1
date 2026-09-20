param(
    [ValidateSet("Desktop", "Tui")]
    [string]$Mode = "Desktop",
    [switch]$Run)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pythonExecutable = if ($Mode -eq "Tui") { "python.exe" } else { "pythonw.exe" }
$python = Join-Path $root ".venv\Scripts\$pythonExecutable"
$entryPoint = if ($Mode -eq "Tui") { "agent.py" } else { "desktop.py" }
$application = Join-Path $root $entryPoint
$services = Join-Path $root "arlo-services.ps1"

foreach ($path in @($python, $application, $services)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "ARLO required file not found: $path"
    }
}


if (-not $Run) {
    $pwsh = (Get-Command pwsh.exe -ErrorAction SilentlyContinue).Source
    if (-not $pwsh) {
        throw "PowerShell 7 (pwsh.exe) was not found. Install PowerShell 7 or add it to PATH."
    }

    $pwshArguments = @(
        '-NoLogo', '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', ('"{0}"' -f $PSCommandPath),
        '-Mode', $Mode, '-Run'
    ) -join ' '

    Start-Process -FilePath $pwsh -ArgumentList $pwshArguments -WorkingDirectory $root
    exit 0
}

$Host.UI.RawUI.WindowTitle = "ARLO"
$env:PYTHONPATH = "$root\src;$root\src\third_party\Matcha-TTS"
$env:ARLO_EXTERNAL_CONSOLE = "0"
Set-Location -LiteralPath $root

& $services
Start-Process -FilePath $python `
    -ArgumentList ('"{0}"' -f $application) `
    -WorkingDirectory $root
exit 0
