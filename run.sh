#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — Launcher
#  Double-click this file in Finder to launch the app
# ─────────────────────────────────────────────

# If double-clicked in Finder, relaunch inside a visible Terminal window
if [ -z "$TERM" ] && [ "$(uname)" = "Darwin" ]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/run.command"
    open -a Terminal "$SCRIPT_PATH"
    exit 0
fi

cd "$(dirname "$0")"

# ── Set library path for WeasyPrint (conda path) ─────────────────
if [ -f ".conda-lib-path" ]; then
    ENV_LIB_PATH="$(cat .conda-lib-path)"
    if [ -n "$ENV_LIB_PATH" ] && [ -d "$ENV_LIB_PATH" ]; then
        export DYLD_LIBRARY_PATH="${ENV_LIB_PATH}:${DYLD_LIBRARY_PATH}"
        export DYLD_FALLBACK_LIBRARY_PATH="${ENV_LIB_PATH}:${DYLD_FALLBACK_LIBRARY_PATH}"
    fi
fi

# ── Find Python ───────────────────────────────────────────────────
METHOD=""; ENV_NAME=""
[ -f ".install-method" ] && METHOD="$(cat .install-method)"
[ -f ".conda-env-name" ] && ENV_NAME="$(cat .conda-env-name)"

PYTHON=""
if [ "$METHOD" = "venv" ] && [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    for CONDA_PATH in \
        "$HOME/miniconda3/bin/conda" \
        "$HOME/miniforge3/bin/conda" \
        "$HOME/opt/miniconda3/bin/conda" \
        "$HOME/opt/miniforge3/bin/conda" \
        "$HOME/mambaforge/bin/conda" \
        "$(command -v conda 2>/dev/null)"
    do
        if [ -f "$CONDA_PATH" ]; then
            export PATH="$(dirname "$CONDA_PATH"):$PATH"
            break
        fi
    done
    PYTHON="$(conda run -n "$ENV_NAME" which python 2>/dev/null)"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
fi

if [ -z "$PYTHON" ] || ! $PYTHON -c "import streamlit" &>/dev/null 2>&1; then
    echo ""
    echo "  ❌  Setup not complete. Please run:"
    echo "      bash setup.sh"
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

# ── Auto-Install Missing Packages ─────────────────────────────────
# This ensures existing users get new packages (like openpyxl) 
# automatically after the GitHub pull, without needing setup.sh
echo ""
echo "  📦  Verifying required packages..."
if [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    conda run -n "$ENV_NAME" pip install -r requirements.txt --quiet
else
    $PYTHON -m pip install -r requirements.txt --quiet
fi

# ── Bypass Streamlit Welcome Prompt ───────────────────────────────
# Prevents Streamlit from hanging/crashing when asking for an email
mkdir -p ~/.streamlit
if [ ! -f ~/.streamlit/credentials.toml ]; then
    echo "[general]" > ~/.streamlit/credentials.toml
    echo 'email = ""' >> ~/.streamlit/credentials.toml
fi

# ── Force light theme always (ignores OS/browser dark mode) ───────
mkdir -p .streamlit
cat > .streamlit/config.toml << 'TOMLEOF'
[theme]
base = "light"
primaryColor = "#1a7f6e"
backgroundColor = "#f5f6fa"
secondaryBackgroundColor = "#ffffff"
textColor = "#1a1d2e"
TOMLEOF

# ── Launch ────────────────────────────────────────────────────────
echo ""
echo "  ✅  Starting Medical Booklet Creator..."
echo "      Opening in your browser now."
echo "      If it doesn't open, go to: http://localhost:8501"
echo ""
echo "      Press Ctrl+C to stop the app."
echo ""

if [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    # Pass library path through to conda run subprocess
    DYLD_LIBRARY_PATH="$DYLD_LIBRARY_PATH" \
    DYLD_FALLBACK_LIBRARY_PATH="$DYLD_FALLBACK_LIBRARY_PATH" \
    conda run -n "$ENV_NAME" \
        env DYLD_LIBRARY_PATH="$DYLD_LIBRARY_PATH" \
            DYLD_FALLBACK_LIBRARY_PATH="$DYLD_FALLBACK_LIBRARY_PATH" \
        python -m streamlit run app.py \
            --server.headless false \
            --browser.gatherUsageStats false
else
    $PYTHON -m streamlit run app.py \
        --server.headless false \
        --browser.gatherUsageStats false
fi