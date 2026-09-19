@echo off
setlocal
if not defined ARLO_HOME (
    for /f "usebackq delims=" %%I in (`
        powershell.exe -NoProfile -Command ^
        "[Environment]::GetEnvironmentVariable('ARLO_HOME','User')"`) do set "ARLO_HOME=%%I"
)

if not defined ARLO_HOME (
    echo [ARLO] ARLO_HOME is not configured.
    echo [ARLO] Run install.sh first.
    pause
    exit /b 1
)

set "ARLO_ROOT=%ARLO_HOME%"
set "ARLO_SERVICES=%ARLO_ROOT%\arlo-services.ps1"
set "ARLO_SCRIPT=%ARLO_ROOT%\arlo.ps1"

if not exist "%ARLO_SERVICES%" (
    echo [ARLO] Missing: %ARLO_SERVICES%
    pause
    exit /b 1
)

if not exist "%ARLO_SCRIPT%" (
    echo [ARLO] Missing: %ARLO_SCRIPT%
    pause
    exit /b 1
)

cd /d "%ARLO_ROOT%"

powershell.exe -NoProfile -Command ^
  "$ports = 11434,18765; foreach ($port in $ports) { $c = [Net.Sockets.TcpClient]::new(); try { $r = $c.BeginConnect('127.0.0.1',$port,$null,$null); if (-not $r.AsyncWaitHandle.WaitOne(500)) { exit 1 }; $c.EndConnect($r) } catch { exit 1 } finally { $c.Dispose() } }"

if errorlevel 1 (
    echo [ARLO] Starting services...

    pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass ^
        -File "%ARLO_SERVICES%"

    if errorlevel 1 (
        echo [ARLO] Services failed to start.
        pause
        exit /b 1
    )
) else (
    echo [ARLO] Services already running.
)

schtasks /query /tn "ARLO" >nul 2>&1

if errorlevel 1 (
    echo [ARLO] Creating scheduled task...

    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
      "$root = $env:ARLO_ROOT; $script = Join-Path $root 'arlo.ps1'; $arguments = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File ' + [char]34 + $script + [char]34; $action = New-ScheduledTaskAction -Execute 'pwsh.exe' -Argument $arguments -WorkingDirectory $root; $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest; Register-ScheduledTask -TaskName 'ARLO' -Action $action -Principal $principal -Force | Out-Null"

    if errorlevel 1 (
        echo [ARLO] Could not create the scheduled task.
        echo [ARLO] Administrator approval may be required.
        pause
        exit /b 1
    )
)

schtasks /run /tn "ARLO" >nul 2>&1
if errorlevel 1 (
    echo [ARLO] Could not launch the scheduled task.
    pause
    exit /b 1
)

endlocal
