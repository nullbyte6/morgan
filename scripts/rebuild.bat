@echo off
.\build-exe.sh
.\build-tui.sh
"C:\Inno Setup 7\ISCC.exe" ..\ArloSetup.iss
& "D:\arlo\build\installer\ArloSetup.exe"
exit /b %errorLevel%