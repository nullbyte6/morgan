#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    printf 'build-dmg.sh builds the macOS app and disk image and must run on macOS.\n' >&2
    exit 1
fi
if [[ "$(uname -m)" != "arm64" ]]; then
    printf 'build-dmg.sh needs Apple Silicon: the pinned PyTorch and ONNX Runtime have no Intel Mac builds.\n' >&2
    exit 1
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python="${ARLO_BUILD_PYTHON:-$root/.venv/bin/python}"
build="$root/build/packaging-macos"
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
    --onedir --windowed --noupx --name Arlo \
    --icon "$root/assets/arlo.png" \
    --osx-bundle-identifier com.xdg.arlo \
    --paths "$root" \
    --specpath "$build" \
    --add-data "$root/assets:assets" \
    --add-data "$root/dev/core.json:dev" \
    --add-data "$root/src/init:src/init" \
    --add-data "$root/src/voices:src/voices" \
    --collect-data pyfiglet \
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
    --exclude-module lingua --exclude-module babel --exclude-module num2words \
    "${hidden[@]}" "$root/entry/desktop.py"

"$python" -B - "$build/Arlo.spec" "$version" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = '.'.join(re.findall(r'\d+', sys.argv[2].partition('-')[0])[:3])
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
plist = {
    'CFBundleName': 'Arlo',
    'CFBundleDisplayName': 'Arlo',
    'CFBundleShortVersionString': version,
    'CFBundleVersion': version,
    'LSMinimumSystemVersion': '14.0',
    'NSHighResolutionCapable': True,
    'NSMicrophoneUsageDescription': 'Arlo listens for its wake phrase and records voice input.',
    'NSAppleEventsUsageDescription': 'Arlo controls Spotify, Music, Finder and System Events when you ask it to.',
}
text, count = re.subn(r"(    bundle_identifier=[^\n]*\n)",
                      lambda match: match.group(1) + f"    version={version!r},\n    info_plist={plist!r},\n",
                      text, count=1)
if count != 1:
    raise SystemExit('The generated spec has no BUNDLE section to configure.')
path.write_text(text, encoding='utf-8')
PY

"$python" -B -m PyInstaller --noconfirm --distpath "$dist" --workpath "$build/work" "$build/Arlo.spec" "$@"

staging="$build/dmg"
rm -rf -- "$staging"
mkdir -p -- "$staging"
cp -R -- "$dist/Arlo.app" "$staging/"
ln -s /Applications "$staging/Applications"
image="$installer/Arlo-$version.dmg"
rm -f -- "$image"
hdiutil create -volname "Arlo $version" -srcfolder "$staging" -fs HFS+ -format UDZO -ov "$image"
rm -rf -- "$staging"

printf '\nApplication: %s/Arlo.app\nDisk image: %s\n' "$dist" "$image"
