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
set "ARLO_SERVICES=%ARLO_ROOT%arlo-services.ps1"
set "ARLO_SCRIPT=%ARLO_ROOT%arlo-run.ps1"

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
schtasks /run /tn "ARLO" >nul 2>&1
if errorlevel 1 (
    echo [ARLO] Could not launch the scheduled task.
    pause
    exit /b 1
)

endlocal
