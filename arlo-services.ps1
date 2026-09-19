param([switch]$NoConsole)
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$ttsModule = "src.init.tts_server"

$ollamaUrl = "http://127.0.0.1:11434"
$ttsHost = "127.0.0.1"
$ttsPort = 18765

$logDir = Join-Path $env:TEMP "arlo"
$ttsLog = Join-Path $logDir "tts.log"
$agentLog = Join-Path $logDir "agent.log"
$consoleScript = Join-Path $logDir "console.ps1"

$env:PYTHONPATH = (
    (Join-Path $root "src") + ";" +
    (Join-Path $root "src\third_party\Matcha-TTS")
)

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
$modelName = $env:MODEL
if (-not $modelName) {
    $configPath = $env:ARLO_CONFIG_FILE
    $corePath = $env:ARLO_CORE_FILE
    if (-not $configPath) {
        $configPath = Join-Path $env:USERPROFILE ".arlo\json\config.json"
    }

    if (-not $corePath) {
        $arloHome = $env:ARLO_HOME

        if (-not $arloHome) {
            $arloHome = $root
        }

        $corePath = Join-Path $arloHome "dev\core.json"
    }

    if (Test-Path -LiteralPath $corePath) {
        $core = Get-Content -LiteralPath $corePath -Raw | ConvertFrom-Json
        $modelName = $core.model_name
    }
}

if (-not $modelName) {
    throw "Model name not found. Set MODEL or ARLO_CONFIG_FILE."
}

$keepAlive = $env:KEEP_ALIVE
if (-not $keepAlive) {
    $keepAlive = "24h"
}

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

Write-Host "[2/3] Checking CosyVoice..."

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
        $wt = (Get-Command "wt.exe" -ErrorAction Stop).Source
        if (-not (Test-Path -LiteralPath $consoleScript -PathType Leaf)) {
            throw "Debug console script not found: $consoleScript"
        }

        $wtArguments = @(
            "-w", "new",
            "new-tab",
            "--title", "ARLO Console",
            "--suppressApplicationTitle",
            "`"$pwsh`"",
            "-NoLogo",
            "-NoProfile",
            "-NoExit",
            "-File",
            "`"$consoleScript`""
        ) -join ' '

        Start-Process `
            -FilePath $wt `
            -ArgumentList $wtArguments
        Write-Host "Debug console started." -ForegroundColor Green
        Write-Host "Debug console started." -ForegroundColor Green
    }
    else {
        Write-Host "Debug console already running."
    }
}

Write-Host "All services ready." -ForegroundColor Green
Write-Host "You can now launch Arlo normally."
