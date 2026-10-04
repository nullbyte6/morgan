@echo off
set "MORGAN_ROOT=%~dp0.."
powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -Command "Start-Process -WindowStyle Hidden -FilePath '%MORGAN_ROOT%\.venv\Scripts\pythonw.exe' -ArgumentList '\"%MORGAN_ROOT%\entry\desktop.py\"'"
exit /b 0
