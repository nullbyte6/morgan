param(
    [Parameter(Mandatory = $false)]
    [string]$InstallDir = "C:\Arlo",

    [Parameter(Mandatory = $false)]
    [string]$AssistantName = "Arlo"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$MainModel = "qwen3.5:9b"

function Get-AssistantIdentifier {
    param([string]$Name)

    $Identifier = ($Name.Normalize([Text.NormalizationForm]::FormKC).ToLowerInvariant() -replace "[^\w-]+", "-").Trim("-", "_")
    $Reserved = @("con", "prn", "aux", "nul") + (1..9 | ForEach-Object { "com$_"; "lpt$_" })

    if ($Reserved -contains $Identifier) {
        $Identifier = "_" + $Identifier
    }

    return $Identifier
}

$AssistantName = $AssistantName.Trim()

if (-not $AssistantName) {
    $AssistantName = "Arlo"
}

$AnchorDir = Join-Path $env:USERPROFILE ".arlo"
$DataDir = Join-Path $env:USERPROFILE ("." + (Get-AssistantIdentifier $AssistantName))

if (($DataDir -ne $AnchorDir) -and (Test-Path $AnchorDir) -and -not (Test-Path $DataDir)) {
    $DataDir = $AnchorDir
}

$ConfigFile = Join-Path $DataDir "json\config.json"
$ModelsDir = Join-Path $DataDir "models"
$CosyVoiceDir = Join-Path $ModelsDir "Fun-CosyVoice3-0.5B"
$CosyVoiceRepo = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
$CosyVoiceRequired = @(
    "cosyvoice3.yaml",
    "campplus.onnx",
    "speech_tokenizer_v3.onnx",
    "flow.pt",
    "flow.decoder.estimator.fp32.onnx",
    "hift.pt",
    "llm.pt",
    "CosyVoice-BlankEN/config.json",
    "CosyVoice-BlankEN/merges.txt",
    "CosyVoice-BlankEN/model.safetensors",
    "CosyVoice-BlankEN/tokenizer_config.json",
    "CosyVoice-BlankEN/vocab.json"
)
$CosyVoiceSkipped = @(
    ".gitattributes",
    "README.md",
    "llm.rl.pt",
    "speech_tokenizer_v3.batch.onnx"
)

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
    foreach ($Relative in $CosyVoiceRequired) {
        $File = Join-Path $CosyVoiceDir ($Relative -replace "/", "\")

        if (-not (Test-Path $File -PathType Leaf)) {
            return $false
        }

        if ((Get-Item $File).Length -le 0) {
            return $false
        }
    }

    return $true
}

function Get-CosyVoiceFiles {
    $Uri = "https://huggingface.co/api/models/$CosyVoiceRepo/tree/main?recursive=true"

    try {
        $Entries = Invoke-RestMethod -Uri $Uri -UseBasicParsing
    }
    catch {
        throw "Could not list the CosyVoice model files: $($_.Exception.Message)"
    }

    $Files = @($Entries | Where-Object {
        ($_.type -eq "file") -and
        ($CosyVoiceSkipped -notcontains $_.path) -and
        (-not $_.path.StartsWith("asset/"))
    })

    foreach ($Relative in $CosyVoiceRequired) {
        if (-not ($Files | Where-Object { $_.path -eq $Relative })) {
            throw "CosyVoice repository is missing $Relative."
        }
    }

    return $Files
}

function Save-CosyVoiceFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Curl,

        [Parameter(Mandatory = $true)]
        [string]$Relative,

        [Parameter(Mandatory = $true)]
        [long]$Size
    )

    $Target = Join-Path $CosyVoiceDir ($Relative -replace "/", "\")

    if ((Test-Path $Target -PathType Leaf) -and ((Get-Item $Target).Length -eq $Size)) {
        Write-Host "$Relative is already downloaded."
        return
    }

    New-Item `
        -ItemType Directory `
        -Path (Split-Path $Target) `
        -Force | Out-Null

    $Part = "$Target.part"
    $Url = "https://huggingface.co/$CosyVoiceRepo/resolve/main/$Relative"

    Write-Host "Downloading $Relative ($([math]::Round($Size / 1MB, 1)) MB)..."

    $Partial = 0

    if (Test-Path $Part -PathType Leaf) {
        $Partial = (Get-Item $Part).Length
    }

    if ($Partial -ne $Size) {
        & $Curl `
            --location `
            --fail `
            --retry 5 `
            --retry-delay 3 `
            --continue-at - `
            --output $Part `
            $Url

        if ($LASTEXITCODE -ne 0) {
            throw "Failed to download $Relative (curl exit code $LASTEXITCODE)."
        }
    }

    if ((Get-Item $Part).Length -ne $Size) {
        Remove-Item $Part -Force
        throw "$Relative was downloaded incompletely."
    }

    Move-Item -Path $Part -Destination $Target -Force
}

function Ensure-CosyVoice {
    Write-Step "Checking CosyVoice..."

    if (Test-CosyVoice) {
        Write-Host "CosyVoice model found:"
        Write-Host "  $CosyVoiceDir"
        return
    }

    $Curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue

    if (-not $Curl) {
        throw "curl.exe is required to download the CosyVoice model."
    }

    Write-Host "CosyVoice model is missing. Downloading..."

    $Files = Get-CosyVoiceFiles
    $Total = ($Files | Measure-Object -Property size -Sum).Sum

    Write-Host "Source: https://huggingface.co/$CosyVoiceRepo"
    Write-Host "Destination: $CosyVoiceDir"
    Write-Host "Total size: $([math]::Round($Total / 1GB, 1)) GB"

    foreach ($File in $Files) {
        Save-CosyVoiceFile `
            -Curl $Curl.Source `
            -Relative $File.path `
            -Size ([long]$File.size)
    }

    if (-not (Test-CosyVoice)) {
        throw "CosyVoice model was downloaded but could not be verified."
    }

    Write-Host "CosyVoice model installed successfully."
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

    if (-not (Test-Path $AnchorDir)) {
        New-Item `
            -ItemType Junction `
            -Path $AnchorDir `
            -Target $DataDir | Out-Null
    }

    if (-not (Test-Path $ConfigFile)) {
        New-Item `
            -ItemType Directory `
            -Path (Split-Path $ConfigFile) `
            -Force | Out-Null

        $Config = @{ assistant = @{ name = $AssistantName } } | ConvertTo-Json
        [IO.File]::WriteAllText($ConfigFile, $Config, (New-Object Text.UTF8Encoding $false))
    }
}

try {
    Write-Host ""
    Write-Host "$AssistantName runtime setup"
    Write-Host "Installation: $InstallDir"
    Write-Host "Data: $DataDir"
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