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
# STEP 1: FIND A PACKAGE MANAGER
# ─────────────────────────────────────────────

INSTALL_METHOD=""
CONDA_EXE=""

echo "▶  Detecting package manager..."

# Check for Homebrew first
if command -v brew &>/dev/null; then
    echo "   ✅ Homebrew found."
    INSTALL_METHOD="homebrew"

else
    # Look for conda/mamba in common locations
    for CANDIDATE in \
        "$(command -v conda 2>/dev/null)" \
        "$HOME/miniconda3/bin/conda" \
        "$HOME/miniforge3/bin/conda" \
        "$HOME/opt/miniconda3/bin/conda" \
        "$HOME/opt/miniforge3/bin/conda" \
        "$HOME/mambaforge/bin/conda" \
        "/opt/homebrew/Caskroom/miniconda/base/bin/conda"
    do
        if [ -f "$CANDIDATE" ]; then
            CONDA_EXE="$CANDIDATE"
            export PATH="$(dirname "$CONDA_EXE"):$PATH"
            echo "   ✅ Conda found at: $CONDA_EXE"
            INSTALL_METHOD="conda"
            break
        fi
    done

    # Nothing found — install Miniforge (user-space, no admin needed)
    if [ -z "$INSTALL_METHOD" ]; then
        echo ""
        echo "   No package manager found."
        echo "   Installing Miniforge to ~/miniforge3 (no admin password required)..."
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
        CONDA_EXE="$HOME/miniforge3/bin/conda"
        export PATH="$(dirname "$CONDA_EXE"):$PATH"
        echo "   ✅ Miniforge installed."
        INSTALL_METHOD="conda"
    fi
fi

echo ""

# ─────────────────────────────────────────────
# STEP 2: CREATE PYTHON ENVIRONMENT + INSTALL
# LIBRARIES AND PACKAGES TOGETHER
#
# KEY FIX: For conda, we install pango/cairo INTO
# the app environment (not base), then write an
# activation hook so DYLD_LIBRARY_PATH is set
# automatically — this is what WeasyPrint needs
# to find libgobject at runtime.
# ─────────────────────────────────────────────

if [ "$INSTALL_METHOD" = "conda" ]; then

    echo "▶  Creating Python environment with PDF libraries..."
    echo "   (This installs pango and cairo alongside Python — may take a few minutes)"
    echo ""

    # Remove old environment if it exists, so we start clean
    conda env remove -n medical-booklet -q 2>/dev/null

    # Create environment with pango + cairo installed directly into it
    # This ensures WeasyPrint can find the .dylib files at the right path
    conda create -y -q -n medical-booklet \
        python=3.11 \
        pango \
        cairo \
        glib \
        gobject-introspection \
        -c conda-forge 2>&1 | tail -3

    echo ""
    echo "   ✅ Environment with PDF libraries created."
    echo ""
    echo "▶  Installing Python packages..."

    conda run -n medical-booklet pip install --upgrade pip -q
    conda run -n medical-booklet pip install -r requirements.txt -q

    # ── CRITICAL FIX: Write a conda activation hook ──────────────
    # This sets DYLD_LIBRARY_PATH to the environment's lib/ folder
    # every time the environment is activated (including via conda run).
    # Without this, WeasyPrint cannot find libgobject-2.0-0 at import time.

    # Find where the environment was installed
    ENV_LIB="$(conda run -n medical-booklet python -c "import sys, os; print(os.path.join(os.path.dirname(sys.executable), '..', 'lib'))" 2>/dev/null | xargs realpath 2>/dev/null)"

    if [ -n "$ENV_LIB" ] && [ -d "$ENV_LIB" ]; then
        # Create the activation hooks directory
        ENV_PREFIX="$(conda run -n medical-booklet python -c "import sys; print(sys.prefix)" 2>/dev/null)"
        HOOK_DIR="$ENV_PREFIX/etc/conda/activate.d"
        mkdir -p "$HOOK_DIR"

        cat > "$HOOK_DIR/weasyprint-libs.sh" << HOOKEOF
#!/bin/bash
# Set library path so WeasyPrint can find libgobject and friends
export DYLD_LIBRARY_PATH="${ENV_LIB}:\${DYLD_LIBRARY_PATH}"
export DYLD_FALLBACK_LIBRARY_PATH="${ENV_LIB}:\${DYLD_FALLBACK_LIBRARY_PATH}"
HOOKEOF

        echo "   ✅ Library path hook written to environment."
    else
        echo "   ⚠️  Could not determine env lib path — writing fallback."
    fi

    # Also write the lib path to a local file so run.sh can set it directly
    # (conda run doesn't always execute activation hooks)
    conda run -n medical-booklet python -c \
        "import sys, os; print(os.path.normpath(os.path.join(sys.prefix, 'lib')))" \
        2>/dev/null > .conda-lib-path

    echo "conda" > .install-method
    echo "medical-booklet" > .conda-env-name

else

    # ── Homebrew path ─────────────────────────────
    echo "▶  Installing PDF rendering libraries..."
    brew install pango cairo gobject-introspection 2>&1 | grep -E "(Installing|Pouring|already installed|Error)"
    echo "   ✅ Libraries ready."
    echo ""

    echo "▶  Creating Python environment..."
    if ! command -v python3 &>/dev/null; then
        brew install python
    fi

    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q

    echo "venv" > .install-method
    echo "   ✅ Environment created."

fi

echo ""
echo "▶  Verifying WeasyPrint can load..."
if [ "$INSTALL_METHOD" = "conda" ]; then
    ENV_LIB_PATH="$(cat .conda-lib-path 2>/dev/null)"
    DYLD_LIBRARY_PATH="$ENV_LIB_PATH" DYLD_FALLBACK_LIBRARY_PATH="$ENV_LIB_PATH" \
        conda run -n medical-booklet python -c "from weasyprint import HTML; print('   ✅ WeasyPrint OK.')" 2>&1 \
        || echo "   ⚠️  WeasyPrint check failed — try running bash setup.sh again."
else
    .venv/bin/python -c "from weasyprint import HTML; print('   ✅ WeasyPrint OK.')" 2>&1 \
        || echo "   ⚠️  WeasyPrint check failed — try running bash setup.sh again."
fi

echo ""
echo "══════════════════════════════════════════════"
echo "   ✅  Setup complete!"
echo ""
echo "   To start the app, run:"
echo "       bash run.sh"
echo "══════════════════════════════════════════════"
echo ""
