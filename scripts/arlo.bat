@echo off
setlocal
cd /d "%~dp0"
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0arlo-run.ps1"
-Mode Desktop
exit /b %errorlevel%
