$python=Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$agent=Join-Path $PSScriptRoot "agent.py"

& $python $agent

Read-Host "Press Enter to exit"