@echo off
setlocal
cls
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0arlo-run.ps1" -Mode Tui %*
set "ARLO_EXIT_CODE=%errorlevel%"
if not "%ARLO_EXIT_CODE%"=="0" pause
exit /b %ARLO_EXIT_CODE%