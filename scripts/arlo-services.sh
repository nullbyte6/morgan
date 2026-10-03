#!/usr/bin/env bash
set -euo pipefail

no_console=0
no_voice=0
for argument in "$@"; do
    case "$argument" in
        --no-console) no_console=1 ;;
        --no-voice) no_voice=1 ;;
        *) printf 'Unknown option: %s\n' "$argument" >&2; exit 2 ;;
    esac
done

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="$root/.venv/bin/python"
tts_module="src.init.tts_server"
ollama_url="http://127.0.0.1:11434"
tts_host="127.0.0.1"
tts_port=18765

export PATH="/opt/homebrew/bin:/usr/local/bin:/Applications/Ollama.app/Contents/Resources:$PATH"
export PYTHONPATH="$root:$root/src:$root/src/third_party/Matcha-TTS"
export TORCH_CPP_LOG_LEVEL="ERROR"
export TORCH_LOGS="-all"
export PYTHONUNBUFFERED="1"

cd -- "$root"

if [[ ! -x "$python" ]]; then
    printf 'Python environment not found: %s. Create .venv and install requirements.txt first.\n' "$python" >&2
    exit 1
fi

metadata="$("$python" -X utf8 -B -c "from src.init.config import load_config; from src.init.identity import get_assistant_identifier, get_assistant_name; from src.init.lang import tr; print(get_assistant_identifier()); print(get_assistant_name()); print(tr('console.console_title')); print(load_config()['context_length'])")" || {
    printf 'Could not resolve the assistant service namespace.\n' >&2
    exit 1
}
{
    IFS= read -r identifier
    IFS= read -r assistant_name
    IFS= read -r console_title
    IFS= read -r model_context
} <<< "$metadata"

export ASSISTANT_NAME="$assistant_name"
export ASSISTANT_CONSOLE_TITLE="$console_title"
export ASSISTANT_LOG_DIR="${TMPDIR:-/tmp}"
ASSISTANT_LOG_DIR="${ASSISTANT_LOG_DIR%/}/$identifier"
log_dir="$ASSISTANT_LOG_DIR"
tts_log="$log_dir/tts.log"
agent_log="$log_dir/agent.log"
mkdir -p -- "$log_dir"
touch -- "$tts_log" "$agent_log"

port_open() {
    (exec 3<>"/dev/tcp/$1/$2") 2>/dev/null
}

wait_port() {
    local deadline=$((SECONDS + $3))
    while (( SECONDS < deadline )); do
        if port_open "$1" "$2"; then
            return 0
        fi
        sleep 0.5
    done
    return 1
}

log_tail() {
    if [[ -s "$1" ]]; then
        printf 'Last lines of %s:\n' "$1"
        tail -n 12 -- "$1" | tail -c 1200
    fi
}

printf '%s SERVICES\n-------------\n' "$(printf '%s' "$assistant_name" | tr '[:lower:]' '[:upper:]')"

core_path="$root/dev/core.json"
if [[ ! -f "$core_path" ]]; then
    printf '%s model configuration not found: %s\n' "$assistant_name" "$core_path" >&2
    exit 1
fi
if ! [[ "$model_context" =~ ^[0-9]+$ ]] || (( model_context < 4096 )); then
    printf 'Model context is invalid in %s.\n' "$core_path" >&2
    exit 1
fi

printf '[1/3] Checking Ollama...\n'
export OLLAMA_CONTEXT_LENGTH="$model_context"
if ! port_open 127.0.0.1 11434; then
    if ! command -v ollama >/dev/null 2>&1; then
        printf 'Ollama was not found. Install it from https://ollama.com or with brew install ollama.\n' >&2
        exit 1
    fi
    printf 'Starting Ollama...\n'
    nohup ollama serve >/dev/null 2>&1 &
    if ! wait_port 127.0.0.1 11434 30; then
        printf 'Ollama did not start.\n' >&2
        exit 1
    fi
fi
printf 'Ollama ready.\n'

model_name="${MODEL:-}"
if [[ -z "${model_name// }" ]]; then
    model_name="$("$python" -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8')).get('base_model_name') or '')" "$core_path")"
fi
if [[ -z "${model_name// }" ]]; then
    printf 'Model name is missing or invalid in %s. Set base_model_name or MODEL.\n' "$core_path" >&2
    exit 1
fi
keep_alive="${KEEP_ALIVE:-24h}"

tts_pid=""
if (( ! no_voice )); then
    printf '[2/3] Checking CosyVoice...\n'
    "$python" -B - "$root" "$python" "$tts_module" <<'PY'
import os
import sys
from pathlib import Path

import psutil

root, python, module = Path(sys.argv[1]), os.path.realpath(sys.argv[2]), sys.argv[3]
sources = ["src/init/tts_server.py", "src/init/voice_service.py", "src/init/voice_profiles.py",
           "src/init/voice_client.py", "src/cosyvoice/cli/cosyvoice.py", "src/cosyvoice/cli/frontend.py",
           "src/cosyvoice/cli/model.py"]
latest = max((root / source).stat().st_mtime for source in sources)
for process in psutil.process_iter(["cmdline", "create_time"]):
    command = process.info["cmdline"] or []
    try:
        owned = (command[:1] and os.path.realpath(command[0]) == python
                 and "-m" in command and module in command)
    except OSError:
        owned = False
    if owned and process.info["create_time"] < latest:
        print("Reloading the updated voice service...")
        children = process.children(recursive=True)
        for target in (*children, process):
            try:
                target.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs((*children, process), timeout=10)
PY
    if port_open "$tts_host" "$tts_port"; then
        printf 'TTS port already in use.\nReusing the existing service.\n'
    else
        printf 'Starting CosyVoice...\n'
        nohup "$python" -u -m "$tts_module" >> "$tts_log" 2>&1 &
        tts_pid=$!
    fi
fi

model_ready=0
if running="$(curl -fsS --max-time 5 "$ollama_url/api/ps" 2>/dev/null)"; then
    if MODEL_NAME="$model_name" "$python" -c "
import json, os, sys
name = os.environ['MODEL_NAME']
aliases = {name} | ({name + ':latest'} if ':' not in name else set())
models = json.loads(sys.stdin.read() or '{}').get('models') or []
sys.exit(0 if any(m.get('name') in aliases or m.get('model') in aliases for m in models) else 1)
" <<< "$running"; then
        model_ready=1
    fi
fi

if (( model_ready )); then
    printf 'Model already loaded; reusing it.\n'
else
    printf 'Preloading model: %s\n' "$model_name"
    payload="$(MODEL_NAME="$model_name" KEEP_ALIVE_VALUE="$keep_alive" "$python" -c "import json, os; print(json.dumps(dict(model=os.environ['MODEL_NAME'], prompt='', keep_alive=os.environ['KEEP_ALIVE_VALUE'], stream=False)))")"
    if ! curl -fsS --max-time 300 -H "Content-Type: application/json" -d "$payload" "$ollama_url/api/generate" >/dev/null; then
        printf 'Model preload failed.\n' >&2
        exit 1
    fi
    printf 'Model ready.\n'
fi

if (( no_voice )); then
    printf 'Voice service skipped.\n'
    exit 0
fi

if [[ -n "$tts_pid" ]]; then
    printf 'Waiting for CosyVoice to load...\n'
    deadline=$((SECONDS + 180))
    ready=0
    while (( SECONDS < deadline )); do
        if port_open "$tts_host" "$tts_port"; then
            ready=1
            break
        fi
        if ! kill -0 "$tts_pid" 2>/dev/null; then
            log_tail "$tts_log"
            printf 'TTS process exited. Check %s\n' "$tts_log" >&2
            exit 1
        fi
        sleep 0.5
    done
    if (( ! ready )); then
        log_tail "$tts_log"
        printf 'CosyVoice startup timed out. Check %s\n' "$tts_log" >&2
        exit 1
    fi
    printf 'CosyVoice ready.\n'
fi

printf '[3/3] Preparing debug console...\n'
if (( ! no_console )); then
    if pgrep -f "tail -n 0 -F $tts_log" >/dev/null 2>&1; then
        printf 'Debug console already running.\n'
    else
        console_command="printf '\\033]0;%s\\007' $(printf '%q' "$console_title"); tail -n 0 -F $(printf '%q' "$tts_log") $(printf '%q' "$agent_log")"
        osascript -e 'on run argv' -e 'tell application "Terminal" to do script (item 1 of argv)' -e 'end run' "$console_command" >/dev/null
        printf 'Debug console started.\n'
    fi
fi

printf 'All services ready.\nYou can now launch %s normally.\n' "$assistant_name"
