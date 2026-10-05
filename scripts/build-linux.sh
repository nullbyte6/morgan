#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    printf 'build-linux.sh builds the Linux application and archive and must run on Linux.\n' >&2
    exit 1
fi
architecture="$(uname -m)"

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="${MORGAN_BUILD_PYTHON:-$root/.venv/bin/python}"
build="$root/build/packaging-linux"
dist="$build/dist"
installer="$root/build/installer"

if [[ ! -x "$python" ]]; then
    printf 'Python environment not found: %s\n' "$python" >&2
    exit 1
fi

cd -- "$root"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1
mkdir -p -- "$build" "$installer"

version="$("$python" -c "import json; print(json.load(open('dev/core.json', encoding='utf-8'))['version'])")"

hidden=()
while IFS= read -r module; do
    hidden+=(--hidden-import "$module")
done < <("$python" -B - <<'PY'
from pathlib import Path
for path in sorted(Path('src/init').rglob('*.py')):
    if path.stem in {'tts_server', 'voice_service', 'speech_text'} or '__pycache__' in path.parts:
        continue
    parts = list(path.with_suffix('').parts)
    if parts[-1] == '__init__':
        parts.pop()
    print('.'.join(parts))
PY
)

"$python" -B -m PyInstaller.utils.cliutils.makespec \
    --onedir --windowed --noupx --name Morgan \
    --icon "$root/assets/morgan.png" \
    --paths "$root" \
    --specpath "$build" \
    --add-data "$root/assets:assets" \
    --add-data "$root/dev/core.json:dev" \
    --add-data "$root/src/init:src/init" \
    --add-data "$root/src/voices:src/voices" \
    --collect-submodules uvicorn \
    --collect-submodules websockets \
    --collect-data faster_whisper \
    --recursive-copy-metadata pydantic-ai-slim \
    --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 \
    --exclude-module torch --exclude-module torchaudio --exclude-module transformers \
    --exclude-module tensorflow --exclude-module numba --exclude-module llvmlite \
    --exclude-module pandas --exclude-module pyarrow --exclude-module matplotlib \
    --exclude-module src.init.voice_service \
    --exclude-module src.init.tts_server \
    --exclude-module src.init.speech_text \
    --exclude-module src.platforms.winx64 \
    --exclude-module src.platforms.macx64 \
    --exclude-module lingua --exclude-module babel --exclude-module num2words \
    "${hidden[@]}" "$root/entry/desktop.py"

"$python" -B - "$build/Morgan.spec" <<'PY'
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
    "a.datas = [entry for entry in a.datas if not entry[0].startswith('timezonefinder_data/data/')]\n"
    "pyz = PYZ(a.pure)")
path.write_text(text, encoding='utf-8')
PY

"$python" -B -m PyInstaller --noconfirm --distpath "$dist" --workpath "$build/work" "$build/Morgan.spec" "$@"

staging="$build/archive/Morgan-$version-linux-$architecture"
rm -rf -- "$build/archive"
mkdir -p -- "$staging"
cp -R -- "$dist/Morgan" "$staging/Morgan"
cp -- "$root/assets/morgan.png" "$staging/morgan.png"

cat > "$staging/morgan.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Morgan
Comment=Personal assistant
Exec=@PREFIX@/Morgan/Morgan
Icon=@PREFIX@/morgan.png
Terminal=false
Categories=Utility;
StartupWMClass=morgan
DESKTOP

cat > "$staging/install.sh" <<'INSTALL'
#!/usr/bin/env bash
set -euo pipefail
source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
prefix="${MORGAN_PREFIX:-$HOME/.local/opt/Morgan}"
applications="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p -- "$prefix" "$applications" "$HOME/.local/bin"
rm -rf -- "$prefix/Morgan"
cp -R -- "$source_dir/Morgan" "$prefix/Morgan"
cp -- "$source_dir/morgan.png" "$prefix/morgan.png"
sed "s|@PREFIX@|$prefix|g" "$source_dir/morgan.desktop" > "$applications/morgan.desktop"
ln -sf -- "$prefix/Morgan/Morgan" "$HOME/.local/bin/morgan"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$applications" || true
printf 'Morgan installed in %s\n' "$prefix"
INSTALL
chmod +x "$staging/install.sh" "$staging/Morgan/Morgan"

archive="$installer/Morgan-$version-linux-$architecture.tar.gz"
rm -f -- "$archive"
tar -C "$build/archive" -czf "$archive" "$(basename -- "$staging")"
rm -rf -- "$build/archive"

printf '\nApplication: %s/Morgan/Morgan\nArchive: %s\n' "$dist" "$archive"
