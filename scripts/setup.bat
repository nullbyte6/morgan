@echo off
setlocal

for %%I in ("%~dp0..") do set "ROOT=%%~fI"
set "PYTHON=%ROOT%\.venv\Scripts\pythonw.exe"
set "WAKE=%ROOT%\entry\wake.py"

if not exist "%PYTHON%" exit /b 1
if not exist "%WAKE%" exit /b 1

schtasks /Create /F ^
    /TN "MORGAN_WAKE" ^
    /SC ONLOGON ^
    /TR "\"%PYTHON%\" \"%WAKE%\"" ^
    /RL LIMITED

if errorlevel 1 (
    exit /b 1
)
endlocal
