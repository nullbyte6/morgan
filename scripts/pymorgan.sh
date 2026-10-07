#!/usr/bin/env bash
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

setsid nohup "$root/.venv/bin/python" "$root/entry/desktop.py" >/dev/null 2>&1 < /dev/null &
disown
exit 0
