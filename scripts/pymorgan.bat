@echo off
set "MORGAN_ROOT=%~dp0.."
"%MORGAN_ROOT%\.venv\Scripts\pythonw.exe" "%MORGAN_ROOT%\entry\desktop.py"
exit /b 0
