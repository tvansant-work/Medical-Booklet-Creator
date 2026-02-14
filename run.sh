#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — Launcher
#  Double-click this file, or run: bash run.sh
# ─────────────────────────────────────────────

# If double-clicked in Finder, macOS runs this without a visible Terminal.
# Relaunch inside Terminal so staff can see progress and press Ctrl+C to stop.
if [ -z "$TERM" ] && [ "$(uname)" = "Darwin" ]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    open -a Terminal "$SCRIPT_PATH"
    exit 0
fi

cd "$(dirname "$0")"

# ── Auto-update from GitHub ───────────────────
if command -v git &>/dev/null && [ -d ".git" ]; then
    echo ""
    echo "  🔄  Checking for updates..."

    git fetch --quiet origin 2>/dev/null &
    FETCH_PID=$!
    sleep 5
    if kill -0 $FETCH_PID 2>/dev/null; then
        kill $FETCH_PID 2>/dev/null
        echo "  ⚠️   No internet — running current version."
    else
        wait $FETCH_PID
        LOCAL=$(git rev-parse HEAD 2>/dev/null)
        REMOTE=$(git rev-parse origin/main 2>/dev/null || git rev-parse origin/master 2>/dev/null)

        if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
            echo "  📦  Update found — downloading..."
            git pull --quiet --ff-only origin main 2>/dev/null \
                || git pull --quiet --ff-only origin master 2>/dev/null \
                || echo "  ⚠️   Update skipped (local changes detected)."

            # Update packages if requirements changed
            if [ -f ".venv/bin/pip" ]; then
                .venv/bin/pip install -r requirements.txt -q 2>/dev/null
            elif [ -f ".conda-env-name" ] && command -v conda &>/dev/null; then
                conda run -n "$(cat .conda-env-name)" pip install -r requirements.txt -q 2>/dev/null
            fi
            echo "  ✅  Updated."
        else
            echo "  ✅  Already up to date."
        fi
    fi
fi

# ── Find Python ───────────────────────────────
METHOD=""; ENV_NAME=""
[ -f ".install-method" ] && METHOD="$(cat .install-method)"
[ -f ".conda-env-name" ] && ENV_NAME="$(cat .conda-env-name)"

PYTHON=""
if [ "$METHOD" = "venv" ] && [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    for CONDA_PATH in "$HOME/miniforge3/bin/conda" "$HOME/opt/miniforge3/bin/conda" \
                      "$HOME/mambaforge/bin/conda" "$(command -v conda 2>/dev/null)"; do
        [ -f "$CONDA_PATH" ] && { export PATH="$(dirname "$CONDA_PATH"):$PATH"; break; }
    done
    PYTHON="$(conda run -n "$ENV_NAME" which python 2>/dev/null)"
elif [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
fi

if [ -z "$PYTHON" ] || ! $PYTHON -c "import streamlit" &>/dev/null 2>&1; then
    echo ""
    echo "  ❌  Setup not complete. Please run setup first:"
    echo "      bash setup.sh"
    echo ""
    read -p "  Press Enter to close..."
    exit 1
fi

# ── Launch ────────────────────────────────────
echo ""
echo "  ✅  Starting Medical Booklet Creator..."
echo "      Opening in your browser now."
echo "      If it doesn't open, go to: http://localhost:8501"
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
