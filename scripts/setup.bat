@echo off
setlocal

set "ROOT=%~dp0"
set "PYTHON=%ROOT%.venv\Scripts\pythonw.exe"
set "WAKE=%ROOT%entry\wake.py"

schtasks /Create /F ^
    /TN "ARLO_WAKE" ^
    /SC ONLOGON ^
    /TR "\"%PYTHON%\" \"%WAKE%\"" ^
    /RL LIMITED

if errorlevel 1 (
    exit /b 1
)
endlocal
