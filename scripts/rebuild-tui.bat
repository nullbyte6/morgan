@echo off
"%ProgramFiles%\Git\bin\bash.exe" "%~dp0build-tui.sh"
if errorlevel 1 exit /b %errorlevel%
"C:\Inno Setup 7\ISCC.exe" "%~dp0..\ArloSetup.iss"
if errorlevel 1 exit /b %errorlevel%
start "" "%~dp0..\build\installer\ArloSetup.exe"
exit /b %errorlevel%
