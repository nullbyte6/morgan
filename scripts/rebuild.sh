#!/usr/bin/env bash
set -euo pipefail

scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
"$scripts/build-dmg.sh" "$@"
open "$scripts/../build/installer"
