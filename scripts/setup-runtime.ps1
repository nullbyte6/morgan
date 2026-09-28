param(
    [Parameter(Mandatory = $false)]
    [string]$InstallDir = "C:\Arlo",

    [Parameter(Mandatory = $false)]
    [string]$AssistantName = "Arlo"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$MainModel = "qwen3.5:9b"

$DataDir = Join-Path $env:USERPROFILE ".arlo"
$ModelsDir = Join-Path $DataDir "models"
$CosyVoiceDir = Join-Path $ModelsDir "Fun-CosyVoice3-0.5B"

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message"
}

function Find-Ollama {
    $Command = Get-Command "ollama.exe" -ErrorAction SilentlyContinue

    if ($Command) {
        return $Command.Source
    }

    $Candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        (Join-Path $env:LOCALAPPDATA "Ollama\ollama.exe"),
        (Join-Path $env:ProgramFiles "Ollama\ollama.exe")
    )

    foreach ($Candidate in $Candidates) {
        if (Test-Path $Candidate -PathType Leaf) {
            return $Candidate
        }
    }

    return $null
}

function Install-Ollama {
    Write-Step "Ollama is not installed. Installing..."

    $Winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue

    if (-not $Winget) {
        throw "WinGet is required to install Ollama automatically."
    }

    & $Winget.Source `
        install `
        --id Ollama.Ollama `
        --exact `
        --source winget `
        --silent `
        --accept-package-agreements `
        --accept-source-agreements `
        --disable-interactivity

    if ($LASTEXITCODE -ne 0) {
        throw "Ollama installation failed with exit code $LASTEXITCODE."
    }

    $Ollama = Find-Ollama

    if (-not $Ollama) {
        throw "Ollama was installed but ollama.exe could not be found."
    }

    return $Ollama
}

function Wait-Ollama {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Ollama
    )

    Write-Step "Checking Ollama service..."

    try {
        & $Ollama list *> $null

        if ($LASTEXITCODE -eq 0) {
            return
        }
    }
    catch {
    }

    Write-Host "Starting Ollama..."

    Start-Process `
        -FilePath $Ollama `
        -ArgumentList "serve" `
        -WindowStyle Hidden

    for ($Attempt = 0; $Attempt -lt 30; $Attempt++) {
        Start-Sleep -Seconds 1

        try {
            & $Ollama list *> $null

            if ($LASTEXITCODE -eq 0) {
                Write-Host "Ollama is ready."
                return
            }
        }
        catch {
        }
    }

    throw "Ollama did not become ready within 30 seconds."
}

function Test-OllamaModel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Ollama,

        [Parameter(Mandatory = $true)]
        [string]$Model
    )

    $Models = & $Ollama list 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "Could not query installed Ollama models."
    }

    foreach ($Line in $Models) {
        if ($Line -match "^\s*$([regex]::Escape($Model))\s") {
            return $true
        }
    }

    return $false
}

function Ensure-OllamaModel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Ollama,

        [Parameter(Mandatory = $true)]
        [string]$Model
    )

    Write-Step "Checking $Model..."

    if (Test-OllamaModel -Ollama $Ollama -Model $Model) {
        Write-Host "$Model is already installed."
        return
    }

    Write-Host "$Model is missing. Downloading..."

    & $Ollama pull $Model

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download $Model."
    }

    if (-not (Test-OllamaModel -Ollama $Ollama -Model $Model)) {
        throw "$Model was downloaded but could not be verified."
    }

    Write-Host "$Model installed successfully."
}

function Test-CosyVoice {
    if (-not (Test-Path $CosyVoiceDir -PathType Container)) {
        return $false
    }

    $Contents = Get-ChildItem `
        -Path $CosyVoiceDir `
        -Force `
        -ErrorAction SilentlyContinue

    return $null -ne $Contents
}

function Ensure-CosyVoice {
    Write-Step "Checking CosyVoice..."

    if (Test-CosyVoice) {
        Write-Host "CosyVoice model found:"
        Write-Host "  $CosyVoiceDir"
        return
    }

    Write-Warning "CosyVoice model is not installed."
    Write-Warning "Expected location:"
    Write-Warning "  $CosyVoiceDir"
    Write-Warning "Automatic CosyVoice installation has not been configured yet."
}

function Ensure-Directories {
    Write-Step "Preparing $AssistantName data directories..."

    $Directories = @(
        $DataDir,
        $ModelsDir
    )

    foreach ($Directory in $Directories) {
        if (-not (Test-Path $Directory)) {
            New-Item `
                -ItemType Directory `
                -Path $Directory `
                -Force | Out-Null
        }
    }
}

try {
    Write-Host ""
    Write-Host "$AssistantName runtime setup"
    Write-Host "Installation: $InstallDir"
    Write-Host ""

    Ensure-Directories

    Write-Step "Checking Ollama..."

    $Ollama = Find-Ollama

    if ($Ollama) {
        Write-Host "Ollama found:"
        Write-Host "  $Ollama"
    }
    else {
        $Ollama = Install-Ollama
    }

    Wait-Ollama -Ollama $Ollama

    Ensure-OllamaModel `
        -Ollama $Ollama `
        -Model $MainModel

    Ensure-CosyVoice

    Write-Host ""
    Write-Host "========================================"
    Write-Host "$AssistantName runtime setup completed."
    Write-Host "========================================"
    Write-Host ""

    exit 0
}
catch {
    Write-Host ""
    Write-Error "$AssistantName runtime setup failed: $($_.Exception.Message)"
    exit 1
}