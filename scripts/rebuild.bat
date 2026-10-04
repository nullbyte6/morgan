@echo off
set "bash=%ProgramFiles%\Git\bin\bash.exe"
"%bash%" "%~dp0build-exe.sh"
if errorlevel 1 exit /b %errorlevel%
"C:\Inno Setup 7\ISCC.exe" "%~dp0..\MorganSetup.iss"
if errorlevel 1 exit /b %errorlevel%
start "" "%~dp0..\build\installer\MorganSetup.exe"
exit /b %errorlevel%
