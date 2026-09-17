$env:PYTHONPATH = "$PSScriptRoot\src;$PSScriptRoot\src\third_party\Matcha-TTS"
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $python $agent