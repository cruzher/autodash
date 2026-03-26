#!/bin/sh
# Strip any CRLF endings then re-exec with bash
if [ -z "${_REEXEC:-}" ]; then
    sed -i 's/\r//g' "$0" 2>/dev/null || true
    _REEXEC=1 exec bash "$0" "$@"
fi

# From here on we are running under bash
set -euo pipefail

cd "$(dirname "$(realpath "$0")")"

VENV_DIR=".venv"
REQUIREMENTS="requirements.txt"

echo ""
echo "========================================="
echo " HybridProtect Monitor - Bootstrap"
echo "========================================="
echo ""

# -- Install xdotool for window positioning on Linux ----------------------
if ! command -v xdotool >/dev/null 2>&1; then
    echo "[..] Installing xdotool for window positioning ..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y xdotool
        echo "[OK] xdotool installed."
    else
        echo "[WARN] apt-get not found - install xdotool manually:"
        echo "       sudo apt install xdotool"
    fi
else
    echo "[OK] xdotool already installed."
fi

# -- Check Python ----------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] python3 not found."
    echo "        Install: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi
PY_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2)
echo "[OK] Found Python $PY_VERSION"

# -- Check venv module -----------------------------------------------------
if ! python3 -c 'import venv' >/dev/null 2>&1; then
    echo "[ERROR] python3-venv not found."
    echo "        Install: sudo apt install python3-venv"
    exit 1
fi

# -- Create venv if needed -------------------------------------------------
if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "[..] Creating virtual environment in $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    echo "[OK] Virtual environment created."
else
    echo "[OK] Virtual environment already exists."
fi

# -- Activate venv ---------------------------------------------------------
. "$VENV_DIR/bin/activate"
echo "[OK] Virtual environment activated."

# -- Upgrade pip -----------------------------------------------------------
echo "[..] Upgrading pip ..."
pip install --upgrade pip --quiet
echo "[OK] pip up to date."

# -- Install dependencies --------------------------------------------------
if [ -f "$REQUIREMENTS" ]; then
    echo "[..] Installing dependencies from $REQUIREMENTS ..."
    pip install -r "$REQUIREMENTS" --quiet
else
    echo "[..] No requirements.txt found - installing playwright directly ..."
    pip install playwright --quiet
fi
echo "[OK] Dependencies installed."

# -- Playwright system deps ------------------------------------------------
echo "[..] Installing Playwright system dependencies ..."
if playwright install-deps chromium 2>/dev/null; then
    echo "[OK] System dependencies installed."
else
    echo "[WARN] Could not install system deps automatically."
    echo "       Run manually if needed:"
    echo "         sudo $VENV_DIR/bin/playwright install-deps chromium"
fi

# -- Install Chromium binary -----------------------------------------------
echo "[..] Installing Playwright Chromium browser ..."
playwright install chromium
echo "[OK] Chromium installed."

# -- Run the monitor -------------------------------------------------------
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
