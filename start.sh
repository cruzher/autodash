#!/bin/sh
# Strip CRLF then re-exec with bash
if [ -z "${_REEXEC:-}" ]; then
    sed -i 's/\r//g' "$0" 2>/dev/null || true
    _REEXEC=1 exec bash "$0" "$@"
fi

set -euo pipefail
cd "$(dirname "$(realpath "$0")")"

VENV_DIR=".venv"
REQUIREMENTS="requirements.txt"
HASH_FILE="$VENV_DIR/.requirements-hash"

echo ""
echo "========================================="
echo " autodash"
echo "========================================="
echo ""

# -- xdotool (Linux, window positioning) -----------------------------------
if ! command -v xdotool >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "[..] Installing xdotool ..."
        sudo apt-get install -y xdotool -qq >/dev/null
        echo "[OK] xdotool installed."
    else
        echo "[WARN] xdotool not found — install manually: sudo apt install xdotool"
    fi
fi

# -- Python ----------------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found — install: sudo apt install python3 python3-venv"
    exit 1
fi
if ! python3 -c 'import venv' >/dev/null 2>&1; then
    echo "[ERROR] python3-venv not found — install: sudo apt install python3-venv"
    exit 1
fi
echo "[OK] Python $(python3 --version 2>&1 | cut -d' ' -f2)"

# -- Virtual environment ---------------------------------------------------
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[..] Creating virtual environment ..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created."
fi
. "$VENV_DIR/bin/activate"

# -- Python dependencies (skip when requirements.txt is unchanged) ---------
CURRENT_HASH=$(sha256sum "$REQUIREMENTS" 2>/dev/null | cut -d' ' -f1 || true)
STORED_HASH=$(cat "$HASH_FILE" 2>/dev/null || true)
DEPS_UPDATED=false

if [ "$CURRENT_HASH" != "$STORED_HASH" ]; then
    echo "[..] Installing Python dependencies ..."
    pip install --upgrade pip --quiet
    if [ -f "$REQUIREMENTS" ]; then
        pip install -r "$REQUIREMENTS" --quiet
    else
        pip install playwright --quiet
    fi
    echo "$CURRENT_HASH" > "$HASH_FILE"
    echo "[OK] Dependencies installed."
    DEPS_UPDATED=true
fi

# -- Playwright Chromium (skip when already installed and deps unchanged) --
CHROMIUM_DIR="${HOME}/.cache/ms-playwright"
if [ "$DEPS_UPDATED" = "true" ] || ! ls "$CHROMIUM_DIR"/chromium-* >/dev/null 2>&1; then
    echo "[..] Installing Playwright system dependencies ..."
    if playwright install-deps chromium >/dev/null; then
        echo "[OK] System dependencies installed."
    else
        echo "[WARN] Could not install system deps — run manually:"
        echo "       sudo $VENV_DIR/bin/playwright install-deps chromium"
    fi
    echo "[..] Installing Chromium browser ..."
    playwright install chromium
    echo "[OK] Chromium ready."
fi

# -- Start -----------------------------------------------------------------
echo ""
echo "========================================="
echo " Starting monitor ..."
echo " Press Ctrl+C to stop."
echo "========================================="
echo ""

python monitor.py
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "[ERROR] monitor.py exited with code $EXIT_CODE."
    exit $EXIT_CODE
fi
