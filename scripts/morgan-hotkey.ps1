param(
    [string]$InstallDir = "",
    [string]$AssistantName = "",
    [string]$Hotkey = "CTRL+ALT+M",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($AssistantName)) { $AssistantName = $env:ASSISTANT_NAME }
if ([string]::IsNullOrWhiteSpace($AssistantName)) { $AssistantName = "Morgan" }

if ([string]::IsNullOrWhiteSpace($InstallDir)) {
    $InstallDir = [Environment]::GetEnvironmentVariable($AssistantName.ToUpperInvariant())
}
if ([string]::IsNullOrWhiteSpace($InstallDir)) { $InstallDir = "C:\Morgan" }

$exe = Join-Path $InstallDir "Morgan.exe"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "$AssistantName.lnk"

if ($Remove) {
    if (Test-Path -LiteralPath $shortcut -PathType Leaf) {
        $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
        $link.Hotkey = ""
        $link.Save()
        Write-Host "Hotkey removed from $shortcut"
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    Write-Host "$exe was not found. Run MorganSetup.exe first, then run this script again."
    exit 1
}

$link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
$link.TargetPath = $exe
$link.WorkingDirectory = $InstallDir
$link.Description = $AssistantName
$link.Hotkey = $Hotkey
$link.Save()

Write-Host "$Hotkey now launches $AssistantName ($exe)."
exit 0
