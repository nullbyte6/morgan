#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
    printf 'build-linux.sh builds the Linux application and archive and must run on Linux.\n' >&2
    exit 1
fi

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
    --exclude-module grpc_tools --exclude-module hf_xet \
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
unused_binaries = r'''import re
unused = re.compile(r'^(onnxruntime/capi/libonnxruntime_providers_(cuda|tensorrt)\.so|PySide6/(qml/|plugins/qmltooling/|Qt6?(3D|Charts|DataVisualization|Graphs|Location|MultimediaQuick|Quick3D|QuickShapes|QuickTest|QuickVectorImage|RemoteObjects|Scxml|Sensors|SpatialAudio|Test)[^/]*$|resources/.*\\.debug\\.|translations/))')
a.binaries = [entry for entry in a.binaries if not unused.match(entry[0])]
a.datas = [entry for entry in a.datas if not unused.match(entry[0])]
'''
text = text.replace('pyz = PYZ(a.pure)', unused_binaries + 'pyz = PYZ(a.pure)')
path.write_text(text, encoding='utf-8')
PY

"$python" -B -m PyInstaller --noconfirm --distpath "$dist" --workpath "$build/work" "$build/Morgan.spec" "$@"

internal="$dist/Morgan/_internal"
qt="$internal/PySide6/Qt"
rm -rf -- "$qt/translations" "$qt/plugins/egldeviceintegrations"
rm -f -- "$qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so" \
    "$qt/plugins/platformthemes/libqgtk3.so" \
    "$qt"/plugins/platforms/libq{eglfs,linuxfb,minimalegl,vnc,vkkhrdisplay}.so \
    "$qt"/lib/libQt6{Quick,Qml,VirtualKeyboard,EglFS,EglFsKms}*
for library in libgtk-3 libgdk-3 libgdk_pixbuf libglycin libcairo libpango libatk libatspi libepoxy \
    libcloudproviders libtinysparql libjson-glib libharfbuzz libgraphite2 libfribidi libthai libdatrie \
    libpixman libseccomp libicudata.so.78 libicuuc.so.78 libicui18n.so.78 libxml2 libXi libXrandr \
    libXcursor libXrender libXext liblcms2; do
    rm -f -- "$internal/$library"*
done
find "$internal" -name RECORD -delete
find "$internal" -type f \( -name '*.so' -o -name '*.so.*' \) -exec strip --strip-unneeded {} + 2>/dev/null || true

payload="$build/payload"
rm -rf -- "$payload"
mkdir -p -- "$payload"
cp -R -- "$dist/Morgan" "$payload/Morgan"
mkdir -p -- "$payload/Morgan/scripts"
cp -- "$root/assets/morgan.png" "$payload/morgan.png"
cp -- "$root/LICENSE" "$payload/LICENSE"
cp -R -- "$root/licenses" "$payload/licenses"
cp -- "$root/scripts/morgan-services.sh" "$payload/Morgan/scripts/morgan-services.sh"
cp -- "$root/scripts/setup-runtime.sh" "$payload/Morgan/scripts/setup-runtime.sh"
chmod +x "$payload/Morgan/Morgan" "$payload/Morgan/scripts/morgan-services.sh" "$payload/Morgan/scripts/setup-runtime.sh"
mkdir -p -- "$payload/Morgan/dev" "$payload/Morgan/src/init" "$payload/Morgan/src/platforms/linuxx64" \
    "$payload/Morgan/src/third_party"
cp -- "$root/dev/core.json" "$payload/Morgan/dev/core.json"
cp -- "$root/src/__init__.py" "$payload/Morgan/src/__init__.py"
cp -- "$root/src/init"/*.py "$payload/Morgan/src/init/"
cp -R -- "$root/src/init/locales" "$payload/Morgan/src/init/locales"
cp -- "$root/src/platforms/__init__.py" "$root/src/platforms/base.py" "$payload/Morgan/src/platforms/"
cp -- "$root/src/platforms/linuxx64"/*.py "$payload/Morgan/src/platforms/linuxx64/"
cp -R -- "$root/src/cosyvoice" "$payload/Morgan/src/cosyvoice"
cp -R -- "$root/src/third_party/Matcha-TTS" "$payload/Morgan/src/third_party/Matcha-TTS"
cp -R -- "$root/src/voices" "$payload/Morgan/src/voices"
find "$payload/Morgan/src" -name __pycache__ -type d -prune -exec rm -rf {} +

archive="$build/payload.tar.xz"
tar -C "$payload" -cf - . | xz -T1 --x86 --lzma2=preset=9e,dict=256MiB,lc=4,lp=0,pb=0 > "$archive"
rm -rf -- "$payload"
mkdir -p -- "$payload"

stub="$build/stub.sh"
cat > "$stub" <<'STUB'
#!/bin/sh
set -eu
prefix="${MORGAN_PREFIX:-$HOME/.local/opt/Morgan}"
applications="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
command_link="$HOME/.local/bin/morgan"
uninstall=0
runtime=1

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) prefix="${2:?--prefix needs a folder}"; shift 2 ;;
        --uninstall) uninstall=1; shift ;;
        --no-runtime) runtime=0; shift ;;
        -h|--help)
            printf 'Usage: %s [--prefix FOLDER] [--no-runtime] [--uninstall]\n' "$0"
            exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

if [ "$uninstall" = 1 ]; then
    rm -rf -- "$prefix"
    rm -f -- "$applications/morgan.desktop"
    [ -L "$command_link" ] && rm -f -- "$command_link"
    printf 'Morgan removed from %s\n' "$prefix"
    exit 0
fi

for tool in xz tar awk; do
    command -v "$tool" >/dev/null 2>&1 || { printf '%s is required to install Morgan.\n' "$tool" >&2; exit 1; }
done

skip="$(awk '/^__ARCHIVE_BELOW__$/ { print NR + 1; exit }' "$0")"
mkdir -p -- "$prefix" "$applications" "$HOME/.local/bin"
if [ -d "$prefix/Morgan/.venv" ]; then
    rm -rf -- "$prefix/.venv.keep"
    mv -- "$prefix/Morgan/.venv" "$prefix/.venv.keep"
fi
rm -rf -- "$prefix/Morgan" "$prefix/licenses"
printf 'Installing Morgan in %s...\n' "$prefix"
tail -n +"$skip" "$0" | xz -dc | tar -x -C "$prefix"
if [ -d "$prefix/.venv.keep" ]; then
    mv -- "$prefix/.venv.keep" "$prefix/Morgan/.venv"
fi

cat > "$applications/morgan.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Morgan
Comment=Personal assistant
Exec=$prefix/Morgan/Morgan
Icon=$prefix/morgan.png
Terminal=false
Categories=Utility;
StartupWMClass=morgan
DESKTOP
ln -sf -- "$prefix/Morgan/Morgan" "$command_link"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$applications" || true
printf 'Morgan installed. Start it from the application menu or with the morgan command.\nTo remove it, run: %s --uninstall\n' "$0"
if [ "$runtime" = 1 ]; then
    "$prefix/Morgan/scripts/setup-runtime.sh" || {
        printf '\nThe Morgan runtime could not be prepared. Run %s/Morgan/scripts/setup-runtime.sh to retry.\n' "$prefix" >&2
        exit 1
    }
fi
exit 0
__ARCHIVE_BELOW__
STUB

setup="$installer/MorganSetup.run"
rm -f -- "$setup"
cat "$stub" "$archive" > "$setup"
chmod +x "$setup"
rm -f -- "$stub" "$archive"

printf '\nApplication: %s/Morgan/Morgan\nInstaller: %s (%s)\n' "$dist" "$setup" "$(du -h "$setup" | cut -f1)"
