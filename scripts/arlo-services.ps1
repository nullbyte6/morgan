param([switch]$NoConsole)

$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$ttsModule = "src.init.tts_server"

$ollamaUrl = "http://127.0.0.1:11434"
$ttsHost = "127.0.0.1"
$ttsPort = 18765

$logDir = Join-Path $env:TEMP "arlo"
$ttsLog = Join-Path $logDir "tts.log"
$agentLog = Join-Path $logDir "agent.log"
$consoleScript = Join-Path $logDir "console.ps1"

$env:PYTHONPATH = @(
    $root
    (Join-Path $root "src")
    (Join-Path $root "src\third_party\Matcha-TTS")
) -join [IO.Path]::PathSeparator

$env:TORCH_CPP_LOG_LEVEL = "ERROR"
$env:TORCH_LOGS = "-all"
$env:PYTHONUNBUFFERED = "1"

Set-Location -LiteralPath $root

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python"
}

New-Item -ItemType Directory -Path $logDir -Force |
    Out-Null

foreach ($file in @($ttsLog, $agentLog)) {
    if (-not (Test-Path -LiteralPath $file)) {
        New-Item -ItemType File -Path $file | Out-Null
    }
}

function Test-TcpPort {
    param(
        [string]$Address,
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()

    try {
        $result = $client.BeginConnect($Address, $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }

        $client.EndConnect($result)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Wait-TcpPort {
    param(
        [string]$Address,
        [int]$Port,
        [int]$TimeoutSeconds = 120
    )

    $timer = [Diagnostics.Stopwatch]::StartNew()

    while ($timer.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-TcpPort -Address $Address -Port $Port) {
            return $true
        }

        Start-Sleep -Milliseconds 500
    }

    return $false
}

Write-Host "ARLO SERVICES" -ForegroundColor Cyan
Write-Host "-------------"
Write-Host "[1/3] Checking Ollama..."
if (-not (Test-TcpPort -Address "127.0.0.1" -Port 11434)) {
    $ollama = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
    if (-not $ollama) {
        throw "Ollama was not found in PATH."
    }

    Write-Host "Starting Ollama..."
    Start-Process `
        -FilePath $ollama.Source `
        -ArgumentList "serve" `
        -WindowStyle Hidden

    if (-not (Wait-TcpPort `
        -Address "127.0.0.1" `
        -Port 11434 `
        -TimeoutSeconds 30)) {

        throw "Ollama did not start."
    }
}

Write-Host "Ollama ready." -ForegroundColor Green
$corePath = Join-Path $root "dev\core.json"
$modelName = $env:MODEL
$managedModel = [string]::IsNullOrWhiteSpace($modelName)
if ([string]::IsNullOrWhiteSpace($modelName)) {
    if (-not (Test-Path -LiteralPath $corePath -PathType Leaf)) {
        throw "ARLO model configuration not found: $corePath"
    }

    $core = Get-Content -LiteralPath $corePath -Raw -Encoding utf8 | ConvertFrom-Json
    $modelName = $core.model_name
}

if ($modelName -isnot [string] -or [string]::IsNullOrWhiteSpace($modelName)) {
    throw "Model name is missing or invalid in $corePath. Set model_name or MODEL."
}

if ($managedModel) {
    $baseModelName = $core.base_model_name
    $modelContext = $core.context_length
    if ($baseModelName -isnot [string] -or
        [string]::IsNullOrWhiteSpace($baseModelName) -or
        $modelContext -isnot [long] -or $modelContext -lt 4096) {
        throw "Managed model configuration is invalid in $corePath."
    }

    Write-Host "Configuring model context: $modelContext"
    $createPayload = @{
        model = $modelName
        from = $baseModelName
        parameters = @{num_ctx = $modelContext}
        stream = $false
    } | ConvertTo-Json -Compress
    try {
        $null = Invoke-RestMethod `
            -Uri "$ollamaUrl/api/create" `
            -Method Post `
            -ContentType "application/json" `
            -Body $createPayload `
            -TimeoutSec 300
    }
    catch {
        throw "Managed model configuration failed: $($_.Exception.Message)"
    }
}

$keepAlive = $env:KEEP_ALIVE
if (-not $keepAlive) {
    $keepAlive = "24h"
}

$modelReady = $false
try {
    $runningModels = Invoke-RestMethod `
        -Uri "$ollamaUrl/api/ps" `
        -Method Get `
        -TimeoutSec 5
    $modelAliases = @($modelName)
    if (-not $modelName.Contains(":")) {
        $modelAliases += "${modelName}:latest"
    }
    $modelReady = @($runningModels.models | Where-Object {
        $modelAliases -contains $_.name -or
        $modelAliases -contains $_.model
    }).Count -gt 0
}
catch {
    # Fall through to the normal preload request.
}

if ($modelReady) {
    Write-Host "Model already loaded; reusing it." -ForegroundColor Green
}
else {
    Write-Host "Preloading model: $modelName"
    $payload = @{
        model = $modelName
        prompt = ""
        keep_alive = $keepAlive
        stream = $false
    } | ConvertTo-Json -Compress

    try {
        $null = Invoke-RestMethod `
            -Uri "$ollamaUrl/api/generate" `
            -Method Post `
            -ContentType "application/json" `
            -Body $payload `
            -TimeoutSec 300

        Write-Host "Model ready." -ForegroundColor Green
    }
    catch {
        throw "Model preload failed: $($_.Exception.Message)"
    }
}

Write-Host "[2/3] Checking CosyVoice..."

$voiceSources = @(
    "src\init\tts_server.py", "src\init\voice_service.py",
    "src\init\voice_profiles.py", "src\init\voice_client.py"
)
$latestVoiceChange = ($voiceSources | ForEach-Object {
    (Get-Item -LiteralPath (Join-Path $root $_)).LastWriteTime
} | Sort-Object -Descending | Select-Object -First 1)
$pythonProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'")
$ownedTts = @($pythonProcesses | Where-Object {
    $_.ExecutablePath -eq $python -and
    $_.CommandLine -match '\s-m\s+src\.init\.tts_server(?:\s|$)' -and
    $_.CreationDate -lt $latestVoiceChange
})
foreach ($ttsOwner in $ownedTts) {
    Write-Host "Reloading the updated Arlo voice service..."
    $ttsChildren = @($pythonProcesses | Where-Object {
        $_.ParentProcessId -eq $ttsOwner.ProcessId -and
        $_.CommandLine -match '\s-m\s+src\.init\.tts_server(?:\s|$)'
    })
    foreach ($ttsChild in $ttsChildren) {
        Stop-Process -Id $ttsChild.ProcessId -ErrorAction SilentlyContinue
        Wait-Process -Id $ttsChild.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $ttsOwner.ProcessId -ErrorAction SilentlyContinue
    Wait-Process -Id $ttsOwner.ProcessId -Timeout 10 -ErrorAction SilentlyContinue
}

if (Test-TcpPort -Address $ttsHost -Port $ttsPort) {

    Write-Host "TTS port already in use." -ForegroundColor Yellow
    Write-Host "Reusing the existing service."

}
else {
    Write-Host "Starting CosyVoice..."
    $ttsCommand = @(
        "/d",
        "/s",
        "/c",
        ('""{0}" -u -m {1} >> "{2}" 2>&1"' -f `
            $python, $ttsModule, $ttsLog)
    )

    $ttsProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList $ttsCommand `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -PassThru

    Write-Host "Waiting for CosyVoice to load..."
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $ready = $false

    while ($timer.Elapsed.TotalSeconds -lt 180) {

        if (Test-TcpPort -Address $ttsHost -Port $ttsPort) {
            $ready = $true
            break
        }

        if ($ttsProcess.HasExited) {
            throw "TTS process exited. Check $ttsLog"
        }

        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        throw "CosyVoice startup timed out. Check $ttsLog"
    }

    Write-Host "CosyVoice ready." -ForegroundColor Green
}

Write-Host "[3/3] Preparing debug console..."

if (-not $NoConsole) {
    $consoleContent = @'
$Host.UI.RawUI.WindowTitle = "ARLO Console"

$logDir = Join-Path $env:TEMP "arlo"

$files = @(
    @{
        Name = "TTS"
        Path = Join-Path $logDir "tts.log"
    },
    @{
        Name = "AGENT"
        Path = Join-Path $logDir "agent.log"
    }
)

$positions = @{}

foreach ($file in $files) {
    $positions[$file.Name] = 0L
}

Write-Host "ARLO DEBUG CONSOLE" -ForegroundColor Cyan
Write-Host "------------------"

while ($true) {

    foreach ($file in $files) {

        $path = $file.Path
        $name = $file.Name

        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }

        try {
            $stream = [System.IO.FileStream]::new(
                $path,
                [System.IO.FileMode]::Open,
                [System.IO.FileAccess]::Read,
                [System.IO.FileShare]::ReadWrite
            )

            try {
                $position = [long]$positions[$name]

                if ($stream.Length -lt $position) {
                    $position = 0L
                }

                $stream.Seek(
                    $position,
                    [System.IO.SeekOrigin]::Begin
                ) | Out-Null

                $reader = [System.IO.StreamReader]::new(
                    $stream,
                    [System.Text.Encoding]::UTF8,
                    $true,
                    4096,
                    $true
                )

                try {
                    while ($null -ne ($line = $reader.ReadLine())) {

                        if ($line.Trim()) {
                            if ($name -eq "TTS") {
                                Write-Host "[$name] $line" `
                                    -ForegroundColor DarkCyan
                            }
                            else {
                                Write-Host "[$name] $line"
                            }
                        }
                    }

                    $positions[$name] = $stream.Position
                }
                finally {
                    $reader.Dispose()
                }
            }
            finally {
                $stream.Dispose()
            }
        }
        catch {
            # The next polling cycle will retry.
        }
    }
    Start-Sleep -Milliseconds 250
}
'@

    Set-Content `
        -LiteralPath $consoleScript `
        -Value $consoleContent `
        -Encoding utf8

    $existingConsole = Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "pwsh.exe" -and
            $_.CommandLine -like "*console.ps1*"
        } |
        Select-Object -First 1

    if (-not $existingConsole) {
        $pwsh = (Get-Command "pwsh.exe" -ErrorAction Stop).Source
        if (-not (Test-Path -LiteralPath $consoleScript -PathType Leaf)) {
            throw "Debug console script not found: $consoleScript"
        }

        $pwshArguments = @(
            "-NoLogo",
            "-NoProfile",
            "-File",
            "`"$consoleScript`""
        ) -join ' '

        Start-Process `
            -FilePath $pwsh `
            -ArgumentList $pwshArguments `
            -WorkingDirectory $root
        Write-Host "Debug console started." -ForegroundColor Green
    }
    else {
        Write-Host "Debug console already running."
    }
}

Write-Host "All services ready." -ForegroundColor Green
Write-Host "You can now launch Arlo normally."
