param([switch]$NoConsole, [switch]$NoVoice)

$ErrorActionPreference = "Stop"

$env:Path = ((@("Machine", "User") | ForEach-Object {
    [Environment]::GetEnvironmentVariable("Path", $_)
}) + $env:Path) -join ";"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root ".venv\Scripts\python.exe"
$ttsModule = "src.init.tts_server"
$gatewayModule = "src.init.omni_gateway"

$gatewayHost = "127.0.0.1"
$gatewayPort = 18767
$ttsHost = "127.0.0.1"
$ttsPort = 18765

$env:PYTHONPATH = @(
    $root
    (Join-Path $root "src")
) -join [IO.Path]::PathSeparator

$env:TORCH_CPP_LOG_LEVEL = "ERROR"
$env:TORCH_LOGS = "-all"
$env:PYTHONUNBUFFERED = "1"

Set-Location -LiteralPath $root

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found: $python. The runtime setup did not finish; run the installer again to complete it."
}

$assistantMetadata = & $python -X utf8 -B -c "import json; from src.init.identity import get_assistant_identifier, get_assistant_name; from src.init.lang import tr; print(json.dumps(dict(identifier=get_assistant_identifier(), name=get_assistant_name(), console_title=tr('console.console_title'))))"
if ($LASTEXITCODE -ne 0 -or -not $assistantMetadata) {
    throw "Could not resolve the assistant service namespace."
}
$assistantMetadata = $assistantMetadata | ConvertFrom-Json
$assistantName = $assistantMetadata.name
$env:ASSISTANT_NAME = $assistantName
$env:ASSISTANT_CONSOLE_TITLE = $assistantMetadata.console_title
$env:ASSISTANT_LOG_DIR = Join-Path $env:TEMP $assistantMetadata.identifier
$logDir = $env:ASSISTANT_LOG_DIR
$ttsLog = Join-Path $logDir "tts.log"
$gatewayLog = Join-Path $logDir "model.log"
$agentLog = Join-Path $logDir "agent.log"
$consoleScript = Join-Path $logDir "console.ps1"

New-Item -ItemType Directory -Path $logDir -Force |
    Out-Null

foreach ($file in @($ttsLog, $gatewayLog, $agentLog)) {
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

function Write-LogTail {
    param(
        [string]$Path,
        [int]$Lines = 12
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return
    }

    $tail = (Get-Content -LiteralPath $Path -Tail $Lines -Encoding utf8 -ErrorAction SilentlyContinue) -join "`n"
    if ($tail.Length -gt 1200) {
        $tail = $tail.Substring($tail.Length - 1200)
    }

    if ($tail.Trim()) {
        Write-Host "Last lines of ${Path}:"
        Write-Host $tail
    }
}

Write-Host "$($assistantName.ToUpper()) SERVICES" -ForegroundColor Cyan
Write-Host "-------------"

Write-Host "[1/3] Checking the model service..."
$gatewayProcess = $null
if (Test-TcpPort -Address $gatewayHost -Port $gatewayPort) {
    Write-Host "Model service already running; reusing it." -ForegroundColor Green
}
else {
    Write-Host "Starting the model service..."
    $gatewayCommand = @(
        "/d",
        "/s",
        "/c",
        ('""{0}" -u -m {1} >> "{2}" 2>&1"' -f `
            $python, $gatewayModule, $gatewayLog)
    )

    $gatewayProcess = Start-Process `
        -FilePath "cmd.exe" `
        -ArgumentList $gatewayCommand `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -PassThru
}

$ttsProcess = $null
if (-not $NoVoice) {
    Write-Host "[2/3] Checking the voice service..."

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
        Write-Host "Reloading the updated $assistantName voice service..."
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
        Write-Host "Starting the voice service..."
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
    }
}

if ($gatewayProcess) {
    Write-Host "Waiting for the model to load..."
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $ready = $false

    while ($timer.Elapsed.TotalSeconds -lt 300) {

        if (Test-TcpPort -Address $gatewayHost -Port $gatewayPort) {
            $ready = $true
            break
        }

        if ($gatewayProcess.HasExited) {
            Write-LogTail -Path $gatewayLog
            throw "Model service exited. Check $gatewayLog"
        }

        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        Write-LogTail -Path $gatewayLog
        throw "Model service startup timed out. Check $gatewayLog"
    }

    Write-Host "Model ready." -ForegroundColor Green
}

if ($NoVoice) {
    Write-Host "Voice service skipped."
    exit 0
}

if ($ttsProcess) {
    Write-Host "Waiting for the voice service to load..."
    $timer = [Diagnostics.Stopwatch]::StartNew()
    $ready = $false

    while ($timer.Elapsed.TotalSeconds -lt 180) {

        if (Test-TcpPort -Address $ttsHost -Port $ttsPort) {
            $ready = $true
            break
        }

        if ($ttsProcess.HasExited) {
            Write-LogTail -Path $ttsLog
            throw "TTS process exited. Check $ttsLog"
        }

        Start-Sleep -Milliseconds 500
    }

    if (-not $ready) {
        Write-LogTail -Path $ttsLog
        throw "Voice service startup timed out. Check $ttsLog"
    }

    Write-Host "Voice service ready." -ForegroundColor Green
}

Write-Host "[3/3] Preparing debug console..."

if (-not $NoConsole) {
    $consoleContent = @'
$Host.UI.RawUI.WindowTitle = $env:ASSISTANT_CONSOLE_TITLE

$logDir = $env:ASSISTANT_LOG_DIR

$files = @(
    @{
        Name = "MODEL"
        Path = Join-Path $logDir "model.log"
    },
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

Write-Host "$env:ASSISTANT_NAME DEBUG CONSOLE" -ForegroundColor Cyan
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
Write-Host "You can now launch $assistantName normally."
