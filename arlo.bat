@echo off
cd /d "%~dp0"
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop.py"
exit /b