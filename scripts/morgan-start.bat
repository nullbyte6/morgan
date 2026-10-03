@echo off
setlocal
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0arlo-run.ps1" -Mode Desktop
set "ARLO_EXIT_CODE=%errorlevel%"
if not "%ARLO_EXIT_CODE%"=="0" pause
exit /b %ARLO_EXIT_CODE%