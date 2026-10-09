#!/usr/bin/env bash
set -euo pipefail

install_dir=""
skip_voice=0
assume_yes=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir) install_dir="${2:?--install-dir needs a folder}"; shift 2 ;;
        --skip-voice-runtime) skip_voice=1; shift ;;
        --yes) assume_yes=1; shift ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
done

scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
install_dir="$(cd -- "${install_dir:-$scripts/..}" && pwd)"
export PATH="$HOME/.local/bin:$PATH"

assistant_name="Morgan"
main_model="qwen3.5:4b"
coding_model="qwen3.5:9b"
data_dir="$HOME/.morgan"
models_dir="$data_dir/models"
cosyvoice_dir="$models_dir/Fun-CosyVoice3-0.5B"
cosyvoice_repo="FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
timezone_version="1.2026.3"
timezone_dir="$models_dir/timezonefinder-data"
venv="$install_dir/.venv"
venv_python="$venv/bin/python"
torch_version="2.8.0"
torch_rocm_version="2.12.0+rocm7.14.1"
torchaudio_rocm_version="2.11.0+rocm7.14.1"
torch_rocm_index="https://repo.amd.com/rocm/whl-multi-arch/"
torchcodec_rocm_version="0.16.0"
torchcodec_probe="import io, wave; b = io.BytesIO(); w = wave.open(b, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(bytes(3200)); w.close(); from torchcodec.decoders import AudioDecoder; AudioDecoder(b.getvalue()).get_all_samples()"
cosyvoice_required=(
    cosyvoice3.yaml campplus.onnx speech_tokenizer_v3.onnx flow.pt flow.decoder.estimator.fp32.onnx
    hift.pt llm.pt CosyVoice-BlankEN/config.json CosyVoice-BlankEN/merges.txt
    CosyVoice-BlankEN/model.safetensors CosyVoice-BlankEN/tokenizer_config.json CosyVoice-BlankEN/vocab.json
)
cosyvoice_skipped=(.gitattributes README.md llm.rl.pt speech_tokenizer_v3.batch.onnx)
voice_packages=(
    antlr4-python3-runtime==4.9.3 attrs==26.1.0 babel==2.18.0 beautifulsoup4==4.15.0 certifi==2026.7.22
    charset-normalizer==3.5.1 cloudpickle==3.1.2 colorama==0.4.6 conformer==0.3.2 cryptography==50.0.1
    cycler==0.12.1 decorator==5.3.1 diffusers==0.29.2 einops==0.8.2 einx==0.4.3 filelock==4.0.0
    fonttools==4.65.0 frozendict==2.4.7 fsspec==2026.7.0 gdown==6.4.0 huggingface_hub==0.36.2
    hydra-core==1.3.7 HyperPyYAML==1.2.3 idna==3.20 inflect==7.5.0 Jinja2==3.1.6 joblib==1.6.0
    kiwisolver==1.5.1 lazy-loader==0.5 librosa==0.10.2.post1 lightning==2.6.6 lightning-utilities==0.15.3
    lingua-language-detector==2.2.0 llvmlite==0.49.0 loguru==0.7.3 lxml==6.1.3 MarkupSafe==3.0.3
    matplotlib==3.11.2 modelscope==1.40.1 modelscope-hub==0.4.3 more-itertools==11.1.0 mpmath==1.3.0
    msgpack==1.2.2 narwhals==2.26.0 num2words==0.5.14 numba==0.67.0 numpy==2.2.6 omegaconf==2.3.1
    onnxruntime==1.24.4 openai-whisper==20250625 packaging==26.3 pandas==3.0.5 pillow==12.3.0
    protobuf==5.29.6 psutil==7.2.2 pyarrow==21.0.0 pydub==0.25.1 Pygments==2.21.0 pyparsing==3.3.2
    PySocks==1.7.1 python-dateutil==2.9.0.post0 pyworld==0.3.5 PyYAML==6.0.3 regex==2026.9.10
    requests==2.34.2 rich==14.3.4 ruamel.yaml==0.18.17 safetensors==0.8.0 scikit-learn==1.9.1
    scipy==1.15.3 setuptools==80.9.0 six==1.17.0 sounddevice==0.5.6 soundfile==0.14.0 soupsieve==2.9.2 sympy==1.14.0
    threadpoolctl==3.7.0 tiktoken==0.14.0 tokenizers==0.21.4 torch-einops-utils==0.1.27
    torchmetrics==1.9.0 tqdm==4.70.1 transformers==4.51.3 typeguard==4.6.0 typing_extensions==4.16.0
    urllib3==2.8.0 wetext==0.1.8 wget==3.2 x-transformers==2.28.8
)

step() {
    printf '\n==> %s\n' "$1"
}

die() {
    printf '\n%s runtime setup failed: %s\n' "$assistant_name" "$1" >&2
    exit 1
}

confirm() {
    if (( assume_yes )); then
        return 0
    fi
    if { : < /dev/tty; } 2>/dev/null; then
        local answer
        read -r -p "$1 [Y/n] " answer < /dev/tty || return 1
        [[ -z "$answer" || "$answer" =~ ^[Yy] ]]
        return
    fi
    return 1
}

package_hint() {
    if command -v pacman >/dev/null 2>&1; then
        printf 'sudo pacman -S %s' "$1"
    elif command -v apt >/dev/null 2>&1; then
        printf 'sudo apt install %s' "${2:-$1}"
    elif command -v dnf >/dev/null 2>&1; then
        printf 'sudo dnf install %s' "${2:-$1}"
    else
        printf 'install %s with your package manager' "$1"
    fi
}

ollama_ready() {
    ollama list >/dev/null 2>&1
}

ensure_ollama() {
    step "Checking Ollama..."
    if ! command -v ollama >/dev/null 2>&1; then
        if confirm "Ollama is not installed. Install it with the official script (needs sudo)?"; then
            curl -fsSL https://ollama.com/install.sh | sh
        else
            die "Ollama is required. Install it from https://ollama.com and run this setup again."
        fi
    fi
    command -v ollama >/dev/null 2>&1 || die "Ollama was installed but could not be found."
    printf 'Ollama found: %s\n' "$(command -v ollama)"
    if ollama_ready; then
        return
    fi
    printf 'Starting Ollama...\n'
    nohup ollama serve >/dev/null 2>&1 &
    for _ in $(seq 30); do
        sleep 1
        if ollama_ready; then
            printf 'Ollama is ready.\n'
            return
        fi
    done
    die "Ollama did not become ready within 30 seconds."
}

ensure_model() {
    step "Checking $1..."
    if ollama list | awk 'NR > 1 { print $1 }' | grep -Fxq "$1"; then
        printf '%s is already installed.\n' "$1"
        return
    fi
    printf '%s is missing. Downloading...\n' "$1"
    ollama pull "$1" || die "Failed to download $1."
    printf '%s installed successfully.\n' "$1"
}

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then
        return
    fi
    printf 'Installing uv...\n'
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null || die "Could not install uv."
    command -v uv >/dev/null 2>&1 || die "uv was installed but could not be found."
}

torch_backend() {
    local adapters
    adapters="$(lspci 2>/dev/null | grep -Ei 'vga|3d|display' || true)"
    if grep -qi nvidia <<< "$adapters"; then
        printf 'cuda'
    elif grep -Eqi 'amd|ati|radeon' <<< "$adapters"; then
        printf 'rocm'
    else
        printf 'cpu'
    fi
}

torch_index() {
    case "$1" in
        cuda) printf 'https://download.pytorch.org/whl/cu128' ;;
        rocm) printf 'https://download.pytorch.org/whl/rocm6.4' ;;
        *) printf 'https://download.pytorch.org/whl/cpu' ;;
    esac
}

voice_probe="import torch, torchaudio, onnxruntime, transformers, hyperpyyaml, whisper, modelscope, sounddevice, librosa, wetext, pyworld, x_transformers, lingua"

test_voice_runtime() {
    [[ -x "$venv_python" ]] && "$venv_python" -c "$voice_probe" >/dev/null 2>&1
}

test_torch_backend() {
    case "$1" in
        rocm) "$venv_python" -c "import sys, torch; sys.exit(0 if torch.version.hip else 1)" >/dev/null 2>&1 ;;
        cuda) "$venv_python" -c "import sys, torch; sys.exit(0 if torch.version.cuda else 1)" >/dev/null 2>&1 ;;
        *) return 0 ;;
    esac
}

rocm_target() {
    local adapters
    adapters="$(lspci 2>/dev/null | grep -Ei 'vga|3d|display' || true)"
    if grep -Eqi 'radeon.*rx *907[0-9]|rx 907[0-9]' <<< "$adapters"; then
        printf 'gfx1201'
    elif grep -Eqi 'radeon.*rx *906[0-9]|rx 906[0-9]' <<< "$adapters"; then
        printf 'gfx1200'
    fi
}

test_torchcodec() {
    "$venv_python" -c "$torchcodec_probe" >/dev/null 2>&1
}

ensure_torchcodec() {
    [[ "$1" == rocm && -n "$(rocm_target)" ]] || return 0
    test_torchcodec && return 0
    printf 'Installing TorchCodec for the ROCm torchaudio...\n'
    uv pip install --python "$venv_python" --no-deps --index-url "$(torch_index cpu)" \
        "torchcodec==$torchcodec_rocm_version" || die "Failed to install TorchCodec."
    test_torchcodec || die "TorchCodec was installed but could not load the shared FFmpeg libraries. Install them with: $(package_hint ffmpeg)"
}

install_torch() {
    local backend="$1" target
    target="$(rocm_target)"
    if [[ "$backend" == rocm && -n "$target" ]]; then
        printf 'Installing PyTorch (ROCm, %s)...\n' "$target"
        uv pip install --python "$venv_python" --index-strategy unsafe-best-match \
            --index-url "$torch_rocm_index" --extra-index-url https://pypi.org/simple \
            "torch[device-$target]==$torch_rocm_version" "torchaudio==$torchaudio_rocm_version" \
            || die "Failed to install PyTorch."
    else
        printf 'Installing PyTorch (%s)...\n' "$backend"
        uv pip install --python "$venv_python" --index-strategy unsafe-best-match \
            --index-url "$(torch_index "$backend")" --extra-index-url https://pypi.org/simple \
            "torch==$torch_version" "torchaudio==$torch_version" || die "Failed to install PyTorch."
    fi
    test_torch_backend "$backend" || die "PyTorch was installed but does not support the GPU."
}

ensure_ffmpeg() {
    step "Checking FFmpeg..."
    if command -v ffmpeg >/dev/null 2>&1; then
        printf 'FFmpeg found.\n'
    else
        printf 'FFmpeg is missing. Install it with: %s\n' "$(package_hint ffmpeg)"
    fi
}

portaudio_present() {
    { ldconfig -p || /sbin/ldconfig -p; } 2>/dev/null | grep -q 'libportaudio\.so'
}

ensure_portaudio() {
    step "Checking PortAudio..."
    if portaudio_present; then
        printf 'PortAudio found.\n'
        return
    fi
    local install
    if command -v pacman >/dev/null 2>&1; then
        install=(sudo pacman -S --needed portaudio)
    elif command -v apt >/dev/null 2>&1; then
        install=(sudo apt install -y libportaudio2)
    elif command -v dnf >/dev/null 2>&1; then
        install=(sudo dnf install -y portaudio)
    else
        die "PortAudio is required by sounddevice. Install it with your package manager and run this setup again."
    fi
    if confirm "PortAudio is missing and sounddevice needs it. Install it with '${install[*]}'?"; then
        "${install[@]}" || die "Failed to install PortAudio."
        portaudio_present || die "PortAudio was installed but could not be found."
    else
        die "PortAudio is required by sounddevice. Install it with: $(package_hint portaudio libportaudio2)"
    fi
}

ensure_voice_runtime() {
    step "Checking the voice runtime..."
    local backend
    backend="$(torch_backend)"
    ensure_uv
    ensure_portaudio
    if test_voice_runtime; then
        if test_torch_backend "$backend"; then
            ensure_torchcodec "$backend"
            printf 'Voice runtime found: %s\n' "$venv"
            return
        fi
        printf 'Voice runtime found, but PyTorch does not match the GPU. Reinstalling PyTorch...\n'
        install_torch "$backend"
        ensure_torchcodec "$backend"
        return
    fi
    command -v g++ >/dev/null 2>&1 || die "A C++ compiler is required to build pyworld. Install it with: $(package_hint base-devel build-essential)"
    if [[ ! -x "$venv_python" ]]; then
        printf 'Creating %s with Python 3.12...\n' "$venv"
        uv python install 3.12 || die "Could not install Python 3.12."
        uv venv --python 3.12 "$venv" || die "Could not create the voice runtime environment."
    fi
    install_torch "$backend"
    printf 'Installing voice dependencies...\n'
    uv pip install --python "$venv_python" --index-strategy unsafe-best-match "${voice_packages[@]}" \
        || die "Failed to install the voice dependencies."
    ensure_torchcodec "$backend"
    test_voice_runtime || die "The voice runtime was installed but could not be verified: $("$venv_python" -c "$voice_probe" 2>&1 | tail -1)"
    printf 'Voice runtime installed successfully.\n'
}

test_cosyvoice() {
    local relative
    for relative in "${cosyvoice_required[@]}"; do
        [[ -s "$cosyvoice_dir/$relative" ]] || return 1
    done
}

ensure_cosyvoice() {
    step "Checking CosyVoice..."
    if test_cosyvoice; then
        printf 'CosyVoice model found: %s\n' "$cosyvoice_dir"
        return
    fi
    [[ -x "$venv_python" ]] || die "The voice runtime is required to list the CosyVoice model files."
    printf 'CosyVoice model is missing. Downloading...\n'
    local listing
    listing="$("$venv_python" - "$cosyvoice_repo" "${cosyvoice_skipped[*]}" <<'PY'
import json
import sys
import urllib.request

repo, skipped = sys.argv[1], sys.argv[2].split()
url = f"https://huggingface.co/api/models/{repo}/tree/main?recursive=true"
with urllib.request.urlopen(url, timeout=60) as response:
    entries = json.load(response)
for entry in entries:
    path = entry["path"]
    if entry["type"] == "file" and path not in skipped and not path.startswith("asset/"):
        print(path, entry["size"])
PY
    )" || die "Could not list the CosyVoice model files."
    local relative size target part
    while read -r relative size; do
        target="$cosyvoice_dir/$relative"
        if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]]; then
            printf '%s is already downloaded.\n' "$relative"
            continue
        fi
        mkdir -p -- "$(dirname -- "$target")"
        part="$target.part"
        printf 'Downloading %s (%s MB)...\n' "$relative" "$(( size / 1048576 ))"
        if [[ ! -f "$part" || "$(stat -c %s "$part")" != "$size" ]]; then
            curl --location --fail --retry 5 --retry-delay 3 --continue-at - --output "$part" \
                "https://huggingface.co/$cosyvoice_repo/resolve/main/$relative" \
                || die "Failed to download $relative."
        fi
        if [[ "$(stat -c %s "$part")" != "$size" ]]; then
            rm -f -- "$part"
            die "$relative was downloaded incompletely."
        fi
        mv -f -- "$part" "$target"
    done <<< "$listing"
    test_cosyvoice || die "CosyVoice model was downloaded but could not be verified."
    printf 'CosyVoice model installed successfully.\n'
}

ensure_timezone_data() {
    step "Checking timezone data..."
    if [[ -f "$timezone_dir/data_version.txt" ]]; then
        printf 'Timezone data found: %s\n' "$timezone_dir"
        return
    fi
    printf 'Timezone data is missing. Downloading...\n'
    "$venv_python" - "$timezone_version" "$timezone_dir" <<'PY' || return 1
import hashlib
import json
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

version, target = sys.argv[1], Path(sys.argv[2])
with urllib.request.urlopen(f"https://pypi.org/pypi/timezonefinder-data/{version}/json", timeout=60) as response:
    release = json.load(response)
wheel = next(item for item in release["urls"] if item["packagetype"] == "bdist_wheel")
with tempfile.TemporaryDirectory() as folder:
    archive = Path(folder) / wheel["filename"]
    with urllib.request.urlopen(wheel["url"], timeout=120) as response:
        archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != wheel["digests"]["sha256"]:
        raise SystemExit("The timezone data download is corrupt.")
    staging = target.with_name(target.name + ".part")
    shutil.rmtree(staging, ignore_errors=True)
    prefix = "timezonefinder_data/data/"
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            if entry.filename.startswith(prefix) and not entry.is_dir():
                destination = staging / entry.filename[len(prefix):]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(bundle.read(entry))
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
PY
    [[ -f "$timezone_dir/data_version.txt" ]] || return 1
    printf 'Timezone data installed successfully.\n'
}

printf '\n%s runtime setup\nInstallation: %s\nData: %s\n' "$assistant_name" "$install_dir" "$data_dir"
mkdir -p -- "$models_dir"

ensure_ollama
ensure_model "$main_model"
ensure_model "$coding_model"

if (( ! skip_voice )); then
    ensure_ffmpeg
    ensure_voice_runtime
    ensure_cosyvoice
    ensure_timezone_data || printf 'Timezone data was not installed.\n' >&2
fi

printf '\n========================================\n%s runtime setup completed.\n========================================\n\n' "$assistant_name"
