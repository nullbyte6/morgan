#!/usr/bin/env bash
set -euo pipefail

scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "$(uname -s)" == "Linux" ]]; then
    "$scripts/build-linux.sh" "$@"
    xdg-open "$scripts/../build/installer" >/dev/null 2>&1 || true
else
    "$scripts/build-dmg.sh" "$@"
    open "$scripts/../build/installer"
fi
