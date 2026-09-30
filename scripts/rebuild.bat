@echo off
.\build-exe.sh
"C:\Inno Setup 7\ISCC.exe" ..\ArloSetup.iss
& "D:\arlo\build\installer\ArloSetup.exe"
exit /b %errorLevel%