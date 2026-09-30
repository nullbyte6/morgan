@echo off
set "ARLO_ROOT=%~dp0.."
"%ARLO_ROOT%\.venv\Scripts\pythonw.exe" "%ARLO_ROOT%\entry\desktop.py"
exit /b 0
