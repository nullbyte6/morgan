param(
    [Parameter(Mandatory = $false)]
    [string]$InstallDir = "C:\Morgan",

    [Parameter(Mandatory = $false)]
    [string]$AssistantName = "Morgan",

    [Parameter(Mandatory = $false)]
    [switch]$SkipVoiceRuntime
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$MainModel = "qwen3.5:4b"
$CodingModel = "qwen3.5:9b"

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
    $AssistantName = "Morgan"
}

$LegacyDir = Join-Path $env:USERPROFILE ".morgan"
$DataDir = Join-Path $env:USERPROFILE ("." + (Get-AssistantIdentifier $AssistantName))

$ConfigFile = Join-Path $DataDir "json\config.json"
$ModelsDir = Join-Path $DataDir "models"
$CosyVoiceDir = Join-Path $ModelsDir "Fun-CosyVoice3-0.5B"
$CosyVoiceRepo = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
$TimezoneDataVersion = "1.2026.3"
$TimezoneDataDir = Join-Path $ModelsDir "timezonefinder-data"
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

$VenvDir = Join-Path $InstallDir ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$TorchVersion = "2.8.0"
$TorchCudaIndex = "https://download.pytorch.org/whl/cu128"
$TorchRocmVersion = "2.12.0+rocm7.14.1"
$TorchaudioRocmVersion = "2.11.0+rocm7.14.1"
$TorchRocmIndex = "https://repo.amd.com/rocm/whl-multi-arch/"
$TorchcodecRocmVersion = "0.16.0"
$TorchcodecProbe = "import io, wave; b = io.BytesIO(); w = wave.open(b, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(3200)); w.close(); from torchcodec.decoders import AudioDecoder; AudioDecoder(b.getvalue()).get_all_samples()"
$VoicePackages = @(
    "antlr4-python3-runtime==4.9.3",
    "attrs==26.1.0",
    "babel==2.18.0",
    "beautifulsoup4==4.15.0",
    "certifi==2026.7.22",
    "charset-normalizer==3.5.1",
    "cloudpickle==3.1.2",
    "colorama==0.4.6",
    "conformer==0.3.2",
    "cryptography==50.0.1",
    "cycler==0.12.1",
    "decorator==5.3.1",
    "diffusers==0.29.2",
    "einops==0.8.2",
    "einx==0.4.3",
    "filelock==4.0.0",
    "fonttools==4.65.0",
    "frozendict==2.4.7",
    "fsspec==2026.7.0",
    "gdown==6.4.0",
    "huggingface_hub==0.36.2",
    "hydra-core==1.3.7",
    "HyperPyYAML==1.2.3",
    "idna==3.20",
    "inflect==7.5.0",
    "Jinja2==3.1.6",
    "joblib==1.6.0",
    "kiwisolver==1.5.1",
    "lazy-loader==0.5",
    "librosa==0.10.2.post1",
    "lightning==2.6.6",
    "lightning-utilities==0.15.3",
    "lingua-language-detector==2.2.0",
    "llvmlite==0.49.0",
    "loguru==0.7.3",
    "lxml==6.1.3",
    "MarkupSafe==3.0.3",
    "matplotlib==3.11.2",
    "modelscope==1.40.1",
    "modelscope-hub==0.4.3",
    "more-itertools==11.1.0",
    "mpmath==1.3.0",
    "msgpack==1.2.2",
    "narwhals==2.26.0",
    "num2words==0.5.14",
    "numba==0.67.0",
    "numpy==2.2.6",
    "omegaconf==2.3.1",
    "onnxruntime-directml==1.24.4",
    "openai-whisper==20250625",
    "packaging==26.3",
    "pandas==3.0.5",
    "pillow==12.3.0",
    "protobuf==5.29.6",
    "psutil==7.2.2",
    "pyarrow==21.0.0",
    "pydub==0.25.1",
    "Pygments==2.21.0",
    "pyparsing==3.3.2",
    "PySocks==1.7.1",
    "python-dateutil==2.9.0.post0",
    "pywin32==312",
    "pyworld==0.3.5",
    "PyYAML==6.0.3",
    "regex==2026.9.10",
    "requests==2.34.2",
    "rich==14.3.4",
    "ruamel.yaml==0.18.17",
    "safetensors==0.8.0",
    "scikit-learn==1.9.1",
    "scipy==1.15.3",
    "six==1.17.0",
    "sounddevice==0.5.6",
    "soundfile==0.14.0",
    "soupsieve==2.9.2",
    "sympy==1.14.0",
    "threadpoolctl==3.7.0",
    "tiktoken==0.14.0",
    "tokenizers==0.21.4",
    "torch-einops-utils==0.1.27",
    "torchmetrics==1.9.0",
    "tqdm==4.70.1",
    "transformers==4.51.3",
    "typeguard==4.6.0",
    "typing_extensions==4.16.0",
    "urllib3==2.8.0",
    "wetext==0.1.8",
    "wget==3.2",
    "win32_setctime==1.2.0",
    "x-transformers==2.28.8"
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

function Ensure-TimezoneData {
    Write-Step "Checking timezone data..."

    if (Test-Path (Join-Path $TimezoneDataDir "data_version.txt") -PathType Leaf) {
        Write-Host "Timezone data found:"
        Write-Host "  $TimezoneDataDir"
        return
    }

    $Curl = Get-Command "curl.exe" -ErrorAction SilentlyContinue

    if (-not $Curl) {
        throw "curl.exe is required to download the timezone data."
    }

    Write-Host "Timezone data is missing. Downloading..."

    $Release = Invoke-RestMethod -Uri "https://pypi.org/pypi/timezonefinder-data/$TimezoneDataVersion/json"
    $Wheel = @($Release.urls | Where-Object { $_.packagetype -eq "bdist_wheel" })[0]

    if (-not $Wheel) {
        throw "timezonefinder-data $TimezoneDataVersion has no wheel on PyPI."
    }

    $Archive = Join-Path ([IO.Path]::GetTempPath()) $Wheel.filename

    Write-Host "Source: $($Wheel.url)"
    Write-Host "Size: $([math]::Round($Wheel.size / 1MB, 1)) MB"

    & $Curl.Source `
        --location `
        --fail `
        --retry 5 `
        --retry-delay 3 `
        --output $Archive `
        $Wheel.url

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download the timezone data (curl exit code $LASTEXITCODE)."
    }

    try {
        if ((Get-FileHash $Archive -Algorithm SHA256).Hash -ne $Wheel.digests.sha256.ToUpperInvariant()) {
            throw "The timezone data download is corrupt."
        }

        $Staging = "$TimezoneDataDir.part"
        $Prefix = "timezonefinder_data/data/"

        if (Test-Path $Staging) {
            Remove-Item $Staging -Recurse -Force
        }

        Add-Type -AssemblyName System.IO.Compression.FileSystem

        $Zip = [IO.Compression.ZipFile]::OpenRead($Archive)

        try {
            foreach ($Entry in $Zip.Entries) {
                if ((-not $Entry.FullName.StartsWith($Prefix)) -or (-not $Entry.Name)) {
                    continue
                }

                $Target = Join-Path $Staging ($Entry.FullName.Substring($Prefix.Length) -replace "/", "\")

                New-Item `
                    -ItemType Directory `
                    -Path (Split-Path $Target) `
                    -Force | Out-Null

                [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Target, $true)
            }
        }
        finally {
            $Zip.Dispose()
        }

        if (Test-Path $TimezoneDataDir) {
            Remove-Item $TimezoneDataDir -Recurse -Force
        }

        Move-Item -Path $Staging -Destination $TimezoneDataDir
    }
    finally {
        Remove-Item $Archive -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path (Join-Path $TimezoneDataDir "data_version.txt") -PathType Leaf)) {
        throw "The timezone data was downloaded but could not be verified."
    }

    Write-Host "Timezone data installed successfully."
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$File,

        [Parameter(Mandatory = $false)]
        [string[]]$Arguments = @()
    )

    $Previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    try {
        & $File @Arguments 2>&1 | ForEach-Object { Write-Host "$_" }

        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $Previous
    }
}

function Install-WinGetPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,

        [Parameter(Mandatory = $false)]
        [string[]]$Extra = @()
    )

    $Winget = Get-Command "winget.exe" -ErrorAction SilentlyContinue

    if (-not $Winget) {
        throw "WinGet is required to install $Id automatically."
    }

    $ExitCode = Invoke-Native -File $Winget.Source -Arguments (@(
        "install",
        "--id", $Id,
        "--exact",
        "--source", "winget",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity"
    ) + $Extra)

    if (($ExitCode -ne 0) -and ($ExitCode -ne -1978335189)) {
        throw "Installation of $Id failed with exit code $ExitCode."
    }
}

function Update-SessionPath {
    $Paths = @("Machine", "User") | ForEach-Object {
        [Environment]::GetEnvironmentVariable("Path", $_)
    }

    $env:Path = (($Paths + $env:Path) -join ";")
}

function Find-Python {
    $Candidates = @()
    $Launcher = Get-Command "py.exe" -ErrorAction SilentlyContinue

    if ($Launcher) {
        try {
            $Candidates += @(& $Launcher.Source -3.12 -c "import sys; print(sys.executable)" 2>$null)
        }
        catch {
        }
    }

    $Candidates += @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
        (Join-Path $env:ProgramFiles "Python312\python.exe")
    )

    $Command = Get-Command "python.exe" -ErrorAction SilentlyContinue

    if ($Command) {
        $Candidates += $Command.Source
    }

    foreach ($Candidate in $Candidates) {
        if (-not $Candidate -or -not (Test-Path $Candidate -PathType Leaf)) {
            continue
        }

        try {
            $Version = & $Candidate -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null

            if ($Version -eq "3.12") {
                return $Candidate
            }
        }
        catch {
        }
    }

    return $null
}

function Test-VoiceRuntime {
    if (-not (Test-Path $VenvPython -PathType Leaf)) {
        return $false
    }

    try {
        & $VenvPython -c "import torch, torchaudio, onnxruntime, transformers, hyperpyyaml, whisper, modelscope, sounddevice, librosa, wetext, pyworld, x_transformers, lingua" *> $null

        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Get-TorchBackend {
    $Adapters = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Name })

    if ($Adapters -match "NVIDIA") {
        return @{ Name = "cuda"; Target = $null }
    }

    if ($Adapters -match "Radeon.*RX\s*907\d") {
        return @{ Name = "rocm"; Target = "gfx1201" }
    }

    if ($Adapters -match "Radeon.*RX\s*906\d") {
        return @{ Name = "rocm"; Target = "gfx1200" }
    }

    return @{ Name = "cpu"; Target = $null }
}

function Get-TorchInstallArguments {
    param([hashtable]$Backend)

    switch ($Backend.Name) {
        "cuda" {
            Write-Host "NVIDIA GPU detected. Using CUDA PyTorch."

            return @("torch==$TorchVersion", "torchaudio==$TorchVersion", "--index-url", $TorchCudaIndex)
        }
        "rocm" {
            Write-Host "AMD Radeon GPU detected ($($Backend.Target)). Using ROCm PyTorch."

            return @("torch[device-$($Backend.Target)]==$TorchRocmVersion", "torchaudio==$TorchaudioRocmVersion", "--index-url", $TorchRocmIndex)
        }
    }

    Write-Host "No supported GPU detected. Using CPU PyTorch."

    return @("torch==$TorchVersion", "torchaudio==$TorchVersion")
}

function Test-TorchBackend {
    param([hashtable]$Backend)

    if ($Backend.Name -eq "cpu") {
        return $true
    }

    $Attribute = if ($Backend.Name -eq "rocm") { "hip" } else { "cuda" }
    $Check = "import sys, torch; sys.exit(0 if torch.version.$Attribute else 1)"

    try {
        & $VenvPython -c $Check *> $null

        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Test-TorchCodec {
    try {
        & $VenvPython -c $TorchcodecProbe *> $null

        return ($LASTEXITCODE -eq 0)
    }
    catch {
        return $false
    }
}

function Ensure-TorchCodec {
    param(
        [hashtable]$Backend,
        [string[]]$Pip
    )

    if (($Backend.Name -ne "rocm") -or (Test-TorchCodec)) {
        return
    }

    Write-Host "Installing TorchCodec for the ROCm torchaudio..."

    if ((Invoke-Native -File $VenvPython -Arguments ($Pip + @("torchcodec==$TorchcodecRocmVersion"))) -ne 0) {
        throw "Failed to install TorchCodec."
    }

    if (Test-TorchCodec) {
        return
    }

    Write-Host "TorchCodec needs the shared FFmpeg libraries. Installing..."

    Install-WinGetPackage -Id "Gyan.FFmpeg.Shared"

    Update-SessionPath

    if (-not (Test-TorchCodec)) {
        throw "TorchCodec was installed but could not load the shared FFmpeg libraries."
    }
}

function Ensure-Ffmpeg {
    Write-Step "Checking FFmpeg..."

    Update-SessionPath

    if (Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue) {
        Write-Host "FFmpeg found."
        return
    }

    Write-Host "FFmpeg is missing. Installing..."

    Install-WinGetPackage -Id "Gyan.FFmpeg"

    Update-SessionPath

    if (-not (Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue)) {
        throw "FFmpeg was installed but ffmpeg.exe could not be found."
    }
}

function Ensure-VoiceRuntime {
    Write-Step "Checking the voice runtime..."

    $Backend = Get-TorchBackend
    $Pip = @("-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--progress-bar", "off")

    if (Test-VoiceRuntime) {
        if (Test-TorchBackend $Backend) {
            Write-Host "Voice runtime found:"
            Write-Host "  $VenvDir"
            Ensure-TorchCodec $Backend $Pip
            return
        }

        Write-Host "Voice runtime found, but PyTorch does not match the GPU. Reinstalling PyTorch..."

        $Reinstall = $Pip

        if ($Backend.Name -eq "cuda") {
            $Reinstall += "--force-reinstall"
        }

        if ((Invoke-Native -File $VenvPython -Arguments ($Reinstall + (Get-TorchInstallArguments $Backend))) -ne 0) {
            throw "Failed to install PyTorch."
        }

        if (-not (Test-TorchBackend $Backend)) {
            throw "PyTorch was reinstalled but does not support the GPU."
        }

        Write-Host "PyTorch updated successfully."
        Ensure-TorchCodec $Backend $Pip
        return
    }

    $Python = Find-Python

    if (-not $Python) {
        Write-Host "Python 3.12 is missing. Installing..."

        Install-WinGetPackage -Id "Python.Python.3.12" -Extra @("--scope", "user")

        $Python = Find-Python
    }

    if (-not $Python) {
        throw "Python 3.12 was installed but could not be found."
    }

    Write-Host "Python found:"
    Write-Host "  $Python"

    if (-not (Test-Path $VenvPython -PathType Leaf)) {
        Write-Host "Creating $VenvDir..."

        if ((Invoke-Native -File $Python -Arguments @("-m", "venv", $VenvDir)) -ne 0) {
            throw "Could not create the voice runtime environment."
        }
    }

    Write-Host "Installing PyTorch..."

    $Arguments = $Pip + (Get-TorchInstallArguments $Backend)

    if ((Invoke-Native -File $VenvPython -Arguments $Arguments) -ne 0) {
        throw "Failed to install PyTorch."
    }

    Write-Host "Installing voice dependencies..."

    if ((Invoke-Native -File $VenvPython -Arguments ($Pip + $VoicePackages)) -ne 0) {
        throw "Failed to install the voice dependencies."
    }

    Ensure-TorchCodec $Backend $Pip

    if (-not (Test-VoiceRuntime)) {
        throw "The voice runtime was installed but could not be verified."
    }

    Write-Host "Voice runtime installed successfully."
}

function Move-LegacyDataDirectory {
    if (-not (Test-Path $LegacyDir)) {
        return
    }

    $Legacy = Get-Item $LegacyDir -Force
    $IsLink = [bool]$Legacy.LinkType
    $Source = $LegacyDir

    if ($IsLink) {
        $Source = @($Legacy.Target)[0]
    }

    $SameFolder = [string]::Equals(
        [IO.Path]::GetFullPath($Source).TrimEnd("\"),
        [IO.Path]::GetFullPath($DataDir).TrimEnd("\"),
        [StringComparison]::OrdinalIgnoreCase)

    if ((-not $SameFolder) -and (-not (Test-Path $DataDir)) -and (Test-Path $Source)) {
        Write-Host "Moving $Source to $DataDir..."
        Move-Item -LiteralPath $Source -Destination $DataDir
        $SameFolder = $true
    }

    if ($IsLink -and $SameFolder) {
        [IO.Directory]::Delete($LegacyDir)
    }
}

function Format-Json {
    param([string]$Json)

    $Depth = 0
    $Lines = foreach ($Line in ($Json -split "\r?\n")) {
        $Line = $Line.Trim()
        if (-not $Line) { continue }
        if ($Line -match '^[\}\]]') { $Depth-- }
        $Line = $Line -replace '^("(?:[^"\\]|\\.)*"):\s+', '$1: '
        ("  " * [Math]::Max($Depth, 0)) + $Line
        if ($Line -match '[\{\[]$') { $Depth++ }
    }

    (($Lines -join "`n") -replace '([\{\[])\n\s*([\}\]])', '$1$2') + "`n"
}

function Set-AssistantConfig {
    New-Item `
        -ItemType Directory `
        -Path (Split-Path $ConfigFile) `
        -Force | Out-Null

    $Config = $null

    if (Test-Path $ConfigFile -PathType Leaf) {
        try {
            $Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
        }
        catch {
            Write-Host "Existing config.json is not valid JSON and will be replaced."
        }
    }

    if (-not $Config) {
        $Config = [pscustomobject]@{}
    }

    if (-not $Config.PSObject.Properties["assistant"] -or -not $Config.assistant) {
        $Config | Add-Member -NotePropertyName "assistant" -NotePropertyValue ([pscustomobject]@{}) -Force
    }

    $Config.assistant | Add-Member -NotePropertyName "name" -NotePropertyValue $AssistantName -Force

    [IO.File]::WriteAllText(
        $ConfigFile,
        (Format-Json ($Config | ConvertTo-Json -Depth 20)),
        (New-Object Text.UTF8Encoding $false))
}

function Ensure-Directories {
    Write-Step "Preparing $AssistantName data directories..."

    Move-LegacyDataDirectory

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

    Set-AssistantConfig
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

    Ensure-OllamaModel `
        -Ollama $Ollama `
        -Model $CodingModel

    Ensure-CosyVoice

    try {
        Ensure-TimezoneData
    }
    catch {
        Write-Warning "Timezone data was not installed: $($_.Exception.Message)"
    }

    if (-not $SkipVoiceRuntime) {
        Ensure-Ffmpeg

        Ensure-VoiceRuntime
    }

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