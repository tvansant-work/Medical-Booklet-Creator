#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — First-time Setup
#  Run once from Terminal: bash setup.sh
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

echo ""
echo "══════════════════════════════════════════════"
echo "   Medical Booklet Creator — Setup"
echo "══════════════════════════════════════════════"
echo ""

# ─────────────────────────────────────────────
# STEP 1: FIND A PACKAGE MANAGER FOR SYSTEM LIBS
#
# WeasyPrint needs pango + cairo (system libraries).
# We try three paths, no admin password required:
#
#   A) Homebrew already installed  → use it
#   B) Conda/Miniforge installed   → use it
#   C) Neither found               → install Miniforge
#      (installs to ~/miniforge3, user-space only)
# ─────────────────────────────────────────────

INSTALL_METHOD=""

echo "▶  Detecting package manager..."

if command -v brew &>/dev/null; then
    echo "   ✅ Homebrew found."
    INSTALL_METHOD="homebrew"

elif command -v conda &>/dev/null; then
    echo "   ✅ Conda found."
    INSTALL_METHOD="conda"

elif [ -f "$HOME/miniforge3/bin/conda" ]; then
    export PATH="$HOME/miniforge3/bin:$PATH"
    echo "   ✅ Miniforge found."
    INSTALL_METHOD="conda"

elif [ -f "$HOME/opt/miniforge3/bin/conda" ]; then
    export PATH="$HOME/opt/miniforge3/bin:$PATH"
    echo "   ✅ Miniforge found."
    INSTALL_METHOD="conda"

elif [ -f "$HOME/mambaforge/bin/conda" ]; then
    export PATH="$HOME/mambaforge/bin:$PATH"
    echo "   ✅ Mambaforge found."
    INSTALL_METHOD="conda"

else
    echo ""
    echo "   No package manager found."
    echo "   Installing Miniforge to your home folder (~~/miniforge3)."
    echo "   This does not require an admin password."
    echo ""

    ARCH="$(uname -m)"
    if [ "$ARCH" = "arm64" ]; then
        MINI_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh"
    else
        MINI_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-x86_64.sh"
    fi

    curl -fsSL "$MINI_URL" -o /tmp/miniforge.sh
    bash /tmp/miniforge.sh -b -p "$HOME/miniforge3"
    rm /tmp/miniforge.sh
    export PATH="$HOME/miniforge3/bin:$PATH"

    echo "   ✅ Miniforge installed."
    INSTALL_METHOD="conda"
fi

echo ""

# ─────────────────────────────────────────────
# STEP 2: INSTALL PDF RENDERING LIBRARIES
# pango and cairo are required by WeasyPrint
# ─────────────────────────────────────────────

echo "▶  Installing PDF rendering libraries..."

if [ "$INSTALL_METHOD" = "homebrew" ]; then
    brew install pango cairo gobject-introspection 2>&1 | grep -E "(Installing|Pouring|Error|already)"
elif [ "$INSTALL_METHOD" = "conda" ]; then
    conda install -y -q -c conda-forge pango cairo glib 2>&1 | grep -E "(Collecting|installed|error)" | head -10
fi

echo "   ✅ Libraries ready."
echo ""

# ─────────────────────────────────────────────
# STEP 3: SET UP PYTHON ENVIRONMENT
# ─────────────────────────────────────────────

echo "▶  Setting up Python environment..."

if [ "$INSTALL_METHOD" = "conda" ]; then

    # Create a named conda environment so pango/cairo stay on the path
    conda create -y -q -n medical-booklet python=3.11 2>&1 | tail -2

    echo "   ✅ Environment created."
    echo ""
    echo "▶  Installing Python packages (this may take a minute)..."

    conda run -n medical-booklet pip install --upgrade pip -q
    conda run -n medical-booklet pip install -r requirements.txt -q

    # Record method for run.sh
    echo "conda" > .install-method
    echo "medical-booklet" > .conda-env-name

else

    # Homebrew path — standard venv is fine
    if ! command -v python3 &>/dev/null; then
        brew install python
    fi

    python3 -m venv .venv

    echo "   ✅ Environment created."
    echo ""
    echo "▶  Installing Python packages (this may take a minute)..."

    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo "venv" > .install-method

fi

echo "   ✅ Packages installed."
echo ""
echo "══════════════════════════════════════════════"
echo "   ✅  Setup complete!"
echo ""
echo "   To start the app, run:"
echo "       bash run.sh"
echo "══════════════════════════════════════════════"
echo ""
