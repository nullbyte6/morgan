#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/bin:/bin:$PATH"

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
    root="$(cygpath -m "$root")"
fi
python="${ARLO_BUILD_PYTHON:-$root/.venv/Scripts/pythonw.exe}"
if [[ "${python##*/}" == "python.exe" ]]; then
    python="${python%/*}/pythonw.exe"
fi
output="${ARLO_BUILD_OUTPUT:-C:/}"
arlo="${ARLO:-${output%/}/Arlo}"
if command -v cygpath >/dev/null 2>&1; then
    arlo="$(cygpath -am "$arlo")"
else
    arlo="${arlo//\\//}"
fi
arlo="${arlo%/}"
output="${arlo%/*}/"
package="${arlo##*/}"
build="$root/build/packaging"

if [[ ! -x "$python" ]]; then
    printf 'Windowless Windows Python environment not found: %s\n' "$python" >&2
    exit 1
fi

cd -- "$root"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1
export MSYS_NO_PATHCONV=1
mkdir -p -- "$build"

run_python() {
    "$python" "$@" 2>&1 | cat
}

run_python -B - "$build/version-info" <<'PY'
import json
import re
import sys
from pathlib import Path
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
    VarStruct, VSVersionInfo)

version = json.loads(Path('dev/core.json').read_text(encoding='utf-8'))['version']
numbers = tuple((list(map(int, re.findall(r'\d+', version))) + [0] * 4)[:4])
strings = dict(FileDescription='Arlo', ProductName='Arlo', InternalName='Arlo',
               OriginalFilename='Arlo.exe', FileVersion=version, ProductVersion=version)
resource = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers, fileType=1),
    kids=[StringFileInfo([StringTable('040904B0', [StringStruct(k, v) for k, v in strings.items()])]),
          VarFileInfo([VarStruct('Translation', [1033, 1200])])])
Path(sys.argv[1]).write_text(str(resource), encoding='utf-8')
PY

hidden=()
while IFS= read -r module; do
    module="${module%$'\r'}"
    hidden+=(--hidden-import "$module")
done < <(run_python -B - <<'PY'
from pathlib import Path
for path in sorted(Path('src/init').rglob('*.py')):
    if path.stem in {'tts_server', 'voice_service'} or '__pycache__' in path.parts:
        continue
    parts = list(path.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    print('.'.join(parts))
PY
)

command=("$python" -B -m PyInstaller.utils.cliutils.makespec
    --onedir --windowed --noupx --name Arlo
    --icon "$root/assets/arlo.ico"
    --version-file "$build/version-info"
    --paths "$root"
    --specpath "$build"
    --add-data "$root/assets:assets"
    --add-data "$root/dev/core.json:dev"
    --add-data "$root/src/init:src/init"
    --add-data "$root/src/voices:src/voices"
    --collect-submodules winrt
    --collect-data pyfiglet
    --collect-data faster_whisper
    --recursive-copy-metadata pydantic-ai-slim
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2
    --exclude-module torch --exclude-module torchaudio --exclude-module transformers
    --exclude-module tensorflow --exclude-module src.init.voice_service
    --exclude-module src.init.tts_server
    "${hidden[@]}" "$root/entry/desktop.py")

printf 'Executing:'
printf ' %q' "${command[@]}"
printf '\n'
run_python "${command[@]:1}"
run_python -B - "$build/Arlo.spec" "$package" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
text = text.replace('    noarchive=False,',
    "    module_collection_mode={'scipy.stats._distn_infrastructure': 'py'},\n"
    "    noarchive=False,")
text = text.replace('pyz = PYZ(a.pure)',
    "a.binaries = [entry for entry in a.binaries if entry[0].lower() not in "
    "{'icuuc.dll', 'icuin.dll', 'icu.dll'}]\n"
    "import importlib.util\n"
    "for package in ('pydantic', 'logfire'):\n"
    "    directory = importlib.util.find_spec(package).submodule_search_locations[0]\n"
    "    a.datas += Tree(directory, prefix=package, excludes=['__pycache__', '*.pyc'])\n"
    "pyz = PYZ(a.pure)")
head, separator, collection = text.rpartition('coll = COLLECT(')
collection = collection.replace("name='Arlo',", f'name={sys.argv[2]!r},', 1)
text = head + separator + collection
path.write_text(text, encoding='utf-8')
PY
run_python -B -m PyInstaller --noconfirm --distpath "$output" --workpath "$build/work" "$build/Arlo.spec" "$@"
printf '\nExecutable: %s/Arlo.exe\n' "$arlo"
