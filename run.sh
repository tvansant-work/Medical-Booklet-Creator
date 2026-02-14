#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — Launcher
#  Run from Terminal: bash run.sh
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

# ── Read install method recorded during setup ─
METHOD=""
ENV_NAME=""
if [ -f ".install-method" ]; then
    METHOD="$(cat .install-method)"
fi
if [ -f ".conda-env-name" ]; then
    ENV_NAME="$(cat .conda-env-name)"
fi

# ── Find the right Python ─────────────────────
PYTHON=""

if [ "$METHOD" = "venv" ] && [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"

elif [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    # Locate conda
    for CONDA_PATH in \
        "$HOME/miniforge3/bin/conda" \
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

else
    # Fallback: try venv or system python3
    if [ -f ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON="python3"
    fi
fi

# ── Guard: setup not run yet ──────────────────
if [ -z "$PYTHON" ] || [ ! -f "$PYTHON" ] && ! command -v "$PYTHON" &>/dev/null; then
    echo ""
    echo "  ❌  Setup has not been completed."
    echo "      Please run:  bash setup.sh"
    echo ""
    exit 1
fi

if ! $PYTHON -c "import streamlit" &>/dev/null; then
    echo ""
    echo "  ❌  Packages not found. Please run:  bash setup.sh"
    echo ""
    exit 1
fi

# ── Launch ────────────────────────────────────
echo ""
echo "  ✅  Starting Medical Booklet Creator..."
echo "      Your browser will open automatically."
echo "      If it doesn't, go to: http://localhost:8501"
echo ""
echo "      Press Ctrl+C to stop the app."
echo ""

if [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    conda run -n "$ENV_NAME" python -m streamlit run app.py \
        --server.headless false \
        --browser.gatherUsageStats false
else
    $PYTHON -m streamlit run app.py \
        --server.headless false \
        --browser.gatherUsageStats false
fi
