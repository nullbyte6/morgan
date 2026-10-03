@echo off
setlocal
cls
pwsh.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0morgan-run.ps1" -Mode Tui %*
set "MORGAN_EXIT_CODE=%errorlevel%"
if not "%MORGAN_EXIT_CODE%"=="0" pause
exit /b %MORGAN_EXIT_CODE%