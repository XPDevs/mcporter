#!/usr/bin/env bash
#
# mcporter launcher (Linux / macOS)
#
#   ./run.sh <mod.jar | mod_dir | folder-of-mods> [options...]
#
# With no arguments it runs interactively and asks for the mod path and the
# target Luanti game.  All extra arguments are passed straight to port.py:
#
#   ./run.sh ~/Downloads/MyMod.jar
#   ./run.sh ~/Downloads/MyMod.jar --install
#   ./run.sh ~/.minecraft/mods --game voxelibre
#
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer an explicit interpreter, then python3, then python.
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
elif command -v python >/dev/null 2>&1; then
    PY="python"
else
    echo "mcporter: Python 3.10+ is required but was not found on your PATH." >&2
    echo "Install it from https://www.python.org/downloads/ and try again." >&2
    exit 1
fi

exec "$PY" "$DIR/port.py" "$@"
