#!/usr/bin/env bash
set -euo pipefail
export PATH="/usr/bin:/bin:$PATH"

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
    root="$(cygpath -m "$root")"
fi
python="${MORGAN_BUILD_PYTHON:-$root/.venv/Scripts/pythonw.exe}"
if [[ "${python##*/}" == "python.exe" ]]; then
    python="${python%/*}/pythonw.exe"
fi
output="${MORGAN_BUILD_OUTPUT:-C:/}"
morgan="${MORGAN:-${output%/}/Morgan}"
if command -v cygpath >/dev/null 2>&1; then
    morgan="$(cygpath -am "$morgan")"
else
    morgan="${morgan//\\//}"
fi
morgan="${morgan%/}"
build="$root/build/packaging-tui"

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
strings = dict(FileDescription='Morgan Terminal', ProductName='Morgan', InternalName='MorganTUI',
               OriginalFilename='MorganTUI.exe', FileVersion=version, ProductVersion=version)
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
    if path.stem in {'tts_server', 'voice_service', 'speech_text'} or '__pycache__' in path.parts:
        continue
    source = path.read_text(encoding='utf-8', errors='replace')
    if 'PySide6' in source or 'shiboken6' in source:
        continue
    parts = list(path.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    print('.'.join(parts))
PY
)

command=("$python" -B -m PyInstaller.utils.cliutils.makespec
    --onedir --console --noupx --name MorganTUI
    --icon "$root/assets/morgan.ico"
    --version-file "$build/version-info"
    --paths "$root"
    --specpath "$build"
    --add-data "$root/assets:assets"
    --add-data "$root/dev/core.json:dev"
    --add-data "$root/src/init:src/init"
    --add-data "$root/src/voices:src/voices"
    --collect-submodules winrt
    --collect-submodules pygments.lexers
    --collect-submodules pygments.styles
    --collect-data pyfiglet
    --collect-data faster_whisper
    --recursive-copy-metadata pydantic-ai-slim
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2
    --exclude-module PySide6 --exclude-module shiboken6
    --exclude-module torch --exclude-module torchaudio --exclude-module transformers
    --exclude-module tensorflow --exclude-module numba --exclude-module llvmlite
    --exclude-module pandas --exclude-module pyarrow --exclude-module matplotlib
    --exclude-module src.init.voice_service
    --exclude-module src.init.tts_server
    --exclude-module src.init.speech_text
    --exclude-module lingua --exclude-module babel --exclude-module num2words
    "${hidden[@]}" "$root/entry/tui.py")

printf 'Executing:'
printf ' %q' "${command[@]}"
printf '\n'
run_python "${command[@]:1}"
run_python -B - "$build/MorganTUI.spec" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')
text = text.replace('    noarchive=False,',
    "    module_collection_mode={'scipy.stats._distn_infrastructure': 'py'},\n"
    "    noarchive=False,")
text = text.replace('pyz = PYZ(a.pure)',
    "import importlib.util\n"
    "for package in ('pydantic', 'logfire'):\n"
    "    directory = importlib.util.find_spec(package).submodule_search_locations[0]\n"
    "    a.datas += Tree(directory, prefix=package, excludes=['__pycache__', '*.pyc'])\n"
    "a.datas = [entry for entry in a.datas if not entry[0].replace('\\\\', '/').startswith('timezonefinder_data/data/')]\n"
    "pyz = PYZ(a.pure)")
head, separator, collection = text.rpartition('coll = COLLECT(')
collection = collection.replace("name='MorganTUI',", "name='tui',", 1)
text = head + separator + collection
path.write_text(text, encoding='utf-8')
PY
rm -rf -- "$build/dist"
run_python -B -m PyInstaller --noconfirm --distpath "$build/dist" --workpath "$build/work" "$build/MorganTUI.spec" "$@"

mkdir -p -- "$morgan/_internal"
cp -f -- "$build/dist/tui/MorganTUI.exe" "$morgan/MorganTUI.exe"
cp -rn -- "$build/dist/tui/_internal/." "$morgan/_internal/"

system32="${SYSTEMROOT:-C:\\Windows}"
system32="${system32//\\//}/System32"
for runtime in vcruntime140 vcruntime140_1 msvcp140 msvcp140_1 msvcp140_2 \
        msvcp140_atomic_wait msvcp140_codecvt_ids concrt140 vcomp140; do
    if [[ -f "$system32/$runtime.dll" ]]; then
        cp -f -- "$system32/$runtime.dll" "$morgan/_internal/"
    fi
done
printf '\nExecutable: %s/MorganTUI.exe\n' "$morgan"
