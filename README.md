**NORA** is an Native Operational Reasoning Assistant, made for the 
local PC and meant to be running alongside your software. It is **100% open source and using Ollama local API**

## Instalación

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Entrada de voz

Ejecuta Nora normalmente y escribe `/voz` o `/voice`. Habla cuando aparezca
el indicador `[MIC]`; la grabación termina automáticamente después del
silencio. El modelo Whisper se descarga la primera vez y después la
transcripción se ejecuta localmente.
