#!/usr/bin/env bash

set -Eeuo pipefail

readonly NORA_MODEL="${NORA_MODEL:-qwen3:14b}"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

info() {
    printf '\n[Nora] %s\n' "$1"
}

fail() {
    printf '\n[Nora] ERROR: %s\n' "$1" >&2
    exit 1
}

to_unix_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -u "$1"
    elif command -v wslpath >/dev/null 2>&1; then
        wslpath -u "$1"
    else
        printf '%s\n' "$1"
    fi
}

to_windows_path() {
    if command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    elif command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$1"
    else
        printf '%s\n' "$1"
    fi
}

find_powershell() {
    if command -v pwsh.exe >/dev/null 2>&1; then
        POWERSHELL_BIN="$(command -v pwsh.exe)"
    elif command -v powershell.exe >/dev/null 2>&1; then
        POWERSHELL_BIN="$(command -v powershell.exe)"
    else
        fail "PowerShell is unavailable. This installer is designed for Windows."
    fi
}

get_windows_folder() {
    "$POWERSHELL_BIN" -NoProfile -Command \
        "[Environment]::GetFolderPath('$1')" | tr -d '\r'
}

find_winget() {
    if command -v winget.exe >/dev/null 2>&1; then
        WINGET_BIN="$(command -v winget.exe)"
        return 0
    fi

    local candidate="${LOCAL_APP_DATA_UNIX}/Microsoft/WindowsApps/winget.exe"
    if [[ -x "$candidate" ]]; then
        WINGET_BIN="$candidate"
        return 0
    fi
    return 1
}

winget_install() {
    local package_id="$1"
    "$WINGET_BIN" install \
        --id "$package_id" \
        --exact \
        --source winget \
        --scope user \
        --silent \
        --accept-package-agreements \
        --accept-source-agreements \
        --disable-interactivity
}

download_file() {
    local url="$1"
    local destination="$2"
    command -v curl >/dev/null 2>&1 || fail \
        "curl is required to download an installer when WinGet is unavailable."
    curl --fail --location --retry 3 --output "$destination" "$url"
}

verify_authenticode_signature() {
    local installer_windows
    installer_windows="$(to_windows_path "$1")"
    NORA_INSTALLER_TO_VERIFY="$installer_windows" \
        "$POWERSHELL_BIN" -NoProfile -Command \
        '$Signature = Get-AuthenticodeSignature -LiteralPath $env:NORA_INSTALLER_TO_VERIFY;
        if ($Signature.Status -ne "Valid") { Write-Error "Invalid installer signature: $($Signature.Status)"; exit 1 }'
}

install_python_directly() {
    local installer="${TMPDIR:-/tmp}/nora-python-3.12.10-$RANDOM.exe"
    TEMP_INSTALLERS+=("$installer")
    info "Downloading the official Python 3.12.10 installer..."
    download_file \
        "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe" \
        "$installer"

    local actual_hash
    actual_hash="$(sha256sum "$installer" | awk '{ print toupper($1) }')"
    [[ "$actual_hash" == "67B5635E80EA51072B87941312D00EC8927C4DB9BA18938F7AD2D27B328B95FB" ]] \
        || fail "The downloaded Python installer failed SHA-256 verification."

    MSYS2_ARG_CONV_EXCL='*' "$installer" \
        /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
}

install_ollama_directly() {
    local installer="${TMPDIR:-/tmp}/nora-ollama-setup-$RANDOM.exe"
    TEMP_INSTALLERS+=("$installer")
    info "Downloading the official Ollama installer..."
    download_file "https://ollama.com/download/OllamaSetup.exe" "$installer"
    verify_authenticode_signature "$installer"
    MSYS2_ARG_CONV_EXCL='*' "$installer" /VERYSILENT /NORESTART
}

cleanup_installers() {
    local installer
    for installer in "${TEMP_INSTALLERS[@]:-}"; do
        [[ -n "$installer" ]] && rm -f -- "$installer"
    done
}

python_works() {
    "$@" -c \
        'import sys, struct; raise SystemExit(0 if sys.platform == "win32" and (3, 12) <= sys.version_info < (3, 13) and struct.calcsize("P") == 8 else 1)' \
        >/dev/null 2>&1
}

find_python() {
    PYTHON_CMD=()

    if command -v py.exe >/dev/null 2>&1 && python_works py.exe -3.12; then
        PYTHON_CMD=(py.exe -3.12)
        return 0
    fi

    local command_name
    for command_name in python.exe python3.exe python3 python; do
        if command -v "$command_name" >/dev/null 2>&1 \
                && python_works "$(command -v "$command_name")"; then
            PYTHON_CMD=("$(command -v "$command_name")")
            return 0
        fi
    done

    local candidate
    for candidate in \
        "${LOCAL_APP_DATA_UNIX}/Programs/Python/Python312/python.exe" \
        "${USER_PROFILE_UNIX}/.python/python.exe" \
        "${PROGRAM_FILES_UNIX}/Python312/python.exe"; do
        if [[ -x "$candidate" ]] && python_works "$candidate"; then
            PYTHON_CMD=("$candidate")
            return 0
        fi
    done
    return 1
}

find_ollama() {
    if command -v ollama.exe >/dev/null 2>&1; then
        OLLAMA_BIN="$(command -v ollama.exe)"
        return 0
    fi

    local candidate
    for candidate in \
        "${LOCAL_APP_DATA_UNIX}/Programs/Ollama/ollama.exe" \
        "${PROGRAM_FILES_UNIX}/Ollama/ollama.exe"; do
        if [[ -x "$candidate" ]]; then
            OLLAMA_BIN="$candidate"
            return 0
        fi
    done
    return 1
}

ensure_ollama_server() {
    if "$OLLAMA_BIN" list >/dev/null 2>&1; then
        return 0
    fi

    info "Starting the local Ollama service..."
    local log_file="${TMPDIR:-/tmp}/nora-ollama.log"
    nohup "$OLLAMA_BIN" serve >"$log_file" 2>&1 &

    local attempt
    for attempt in {1..30}; do
        if "$OLLAMA_BIN" list >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    fail "Ollama did not respond within 30 seconds. Check ${log_file}."
}

find_powershell

[[ -f "${SCRIPT_DIR}/requirements.txt" ]] || fail \
    "${SCRIPT_DIR}/requirements.txt was not found."
[[ -f "${SCRIPT_DIR}/nora.ps1" ]] || fail \
    "${SCRIPT_DIR}/nora.ps1 was not found."

readonly LOCAL_APP_DATA_WINDOWS="${LOCALAPPDATA:-$(get_windows_folder LocalApplicationData)}"
readonly USER_PROFILE_WINDOWS="${USERPROFILE:-$(get_windows_folder UserProfile)}"
readonly PROGRAM_FILES_WINDOWS="${PROGRAMFILES:-$(get_windows_folder ProgramFiles)}"

[[ -n "$LOCAL_APP_DATA_WINDOWS" ]] || fail "Windows LocalAppData could not be located."
[[ -n "$USER_PROFILE_WINDOWS" ]] || fail "The Windows user profile could not be located."
[[ -n "$PROGRAM_FILES_WINDOWS" ]] || fail "Windows Program Files could not be located."

readonly LOCAL_APP_DATA_UNIX="$(to_unix_path "$LOCAL_APP_DATA_WINDOWS")"
readonly USER_PROFILE_UNIX="$(to_unix_path "$USER_PROFILE_WINDOWS")"
readonly PROGRAM_FILES_UNIX="$(to_unix_path "$PROGRAM_FILES_WINDOWS")"

TEMP_INSTALLERS=()
trap cleanup_installers EXIT

WINGET_BIN=""
find_winget || true

info "Checking for Python 3.12..."
PYTHON_CMD=()
if ! find_python; then
    info "No compatible Python installation found; installing Python 3.12..."
    if [[ -n "$WINGET_BIN" ]]; then
        winget_install "Python.Python.3.12" || install_python_directly
    else
        install_python_directly
    fi
    find_python || fail "Python was installed, but python.exe could not be located."
fi
"${PYTHON_CMD[@]}" --version

readonly VENV_DIR="${SCRIPT_DIR}/.venv"
readonly VENV_DIR_WINDOWS="$(to_windows_path "$VENV_DIR")"
readonly REQUIREMENTS_WINDOWS="$(to_windows_path "${SCRIPT_DIR}/requirements.txt")"
readonly VENV_PYTHON="${VENV_DIR}/Scripts/python.exe"

info "Creating or updating the virtual environment..."
"${PYTHON_CMD[@]}" -m venv "$VENV_DIR_WINDOWS"
[[ -x "$VENV_PYTHON" ]] || fail "The virtual environment could not be created at ${VENV_DIR}."

info "Installing dependencies from requirements.txt..."
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install --requirement "$REQUIREMENTS_WINDOWS"
"$VENV_PYTHON" -m pip check

info "Checking for Ollama..."
OLLAMA_BIN=""
if ! find_ollama; then
    info "Ollama was not found; installing it..."
    if [[ -n "$WINGET_BIN" ]]; then
        winget_install "Ollama.Ollama" || install_ollama_directly
    else
        install_ollama_directly
    fi
    find_ollama || fail "Ollama was installed, but ollama.exe could not be located."
fi
"$OLLAMA_BIN" --version

ensure_ollama_server

info "Downloading/verifying ${NORA_MODEL} (approximately 9.3 GB)..."
"$OLLAMA_BIN" pull "$NORA_MODEL"

readonly NORA_SCRIPT="$(to_windows_path "${SCRIPT_DIR}/nora.ps1")"

cleanup_installers
trap - EXIT
info "Installation complete. Starting Nora..."
exec "$POWERSHELL_BIN" -NoProfile -ExecutionPolicy Bypass -File "$NORA_SCRIPT"
