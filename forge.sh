#!/usr/bin/env bash
# Launch the Forge TUI on Linux / macOS without installing.
# Prefers a local .venv if present, else the system python3.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$HERE/.venv/bin/python" ]; then
    PY="$HERE/.venv/bin/python"
else
    PY="$(command -v python3 || command -v python)"
fi
exec "$PY" "$HERE/forge_tui.py" "$@"
