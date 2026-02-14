#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — Full Wipe
#  Removes everything installed for this app,
#  including Python/conda if installed by setup.
#
#  Run from Terminal:
#      bash ~/Documents/medical-booklet/wipe.sh
# ─────────────────────────────────────────────

cd "$(dirname "$0")"

echo ""
echo "══════════════════════════════════════════════"
echo "   Medical Booklet Creator — Full Wipe"
echo "══════════════════════════════════════════════"
echo ""

# ── Detect what's present ─────────────────────

# Find conda
CONDA_EXE=""
CONDA_BASE=""
for CANDIDATE in \
    "$(command -v conda 2>/dev/null)" \
    "$HOME/miniconda3/bin/conda" \
    "$HOME/miniforge3/bin/conda" \
    "$HOME/opt/miniconda3/bin/conda" \
    "$HOME/opt/miniforge3/bin/conda" \
    "$HOME/mambaforge/bin/conda"
do
    if [ -f "$CANDIDATE" ]; then
        CONDA_EXE="$CANDIDATE"
        CONDA_BASE="$(dirname "$(dirname "$CANDIDATE")")"
        break
    fi
done

# Check if conda was installed by this app's setup
# (setup installs to ~/miniforge3; miniconda3 may have been pre-existing)
CONDA_INSTALLED_BY_SETUP=false
if [ -f "$HOME/miniforge3/bin/conda" ]; then
    CONDA_INSTALLED_BY_SETUP=true
fi

echo "  This will remove:"
if [ -n "$CONDA_EXE" ]; then
    echo "    • The 'medical-booklet' conda environment"
fi
if [ "$CONDA_INSTALLED_BY_SETUP" = true ]; then
    echo "    • Miniforge (Python) installed by setup  →  $HOME/miniforge3"
fi
if [ -d ".venv" ]; then
    echo "    • Local .venv folder"
fi
echo "    • Setup tracking files"
echo "    • _temp folder"
echo ""

if [ -n "$CONDA_EXE" ] && [ "$CONDA_INSTALLED_BY_SETUP" = false ]; then
    echo "  ℹ️  NOTE: Your existing conda/miniconda at"
    echo "     $CONDA_BASE"
    echo "     was NOT installed by this app's setup."
    echo "     Only the 'medical-booklet' environment inside it will be removed."
    echo "     Your other environments and conda itself will be left alone."
    echo ""
fi

read -p "  Are you sure? Type YES to continue: " CONFIRM
echo ""

if [ "$CONFIRM" != "YES" ]; then
    echo "  Cancelled."
    echo ""
    exit 0
fi

# ── 1. Remove the conda environment ──────────
if [ -n "$CONDA_EXE" ]; then
    echo "▶  Removing conda environment 'medical-booklet'..."
    "$CONDA_EXE" env remove -n medical-booklet -y 2>/dev/null \
        && echo "   ✅ Environment removed." \
        || echo "   ℹ️  No environment found (already clean)."
    echo ""
fi

# ── 2. Remove Miniforge if setup installed it ─
if [ "$CONDA_INSTALLED_BY_SETUP" = true ]; then
    echo "▶  Removing Miniforge (Python) from ~/miniforge3..."
    rm -rf "$HOME/miniforge3"
    echo "   ✅ Miniforge removed."

    # Clean up any shell init lines that setup may have added
    for RC_FILE in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bashrc"; do
        if [ -f "$RC_FILE" ] && grep -q "miniforge3" "$RC_FILE"; then
            # Remove the conda init block
            sed -i.bak '/# >>> conda initialize >>>/,/# <<< conda initialize <<</d' "$RC_FILE"
            sed -i.bak '/miniforge3/d' "$RC_FILE"
            rm -f "${RC_FILE}.bak"
            echo "   ✅ Cleaned conda init from $RC_FILE"
        fi
    done
    echo ""
fi

# ── 3. Remove local .venv ─────────────────────
if [ -d ".venv" ]; then
    echo "▶  Removing local .venv..."
    rm -rf .venv
    echo "   ✅ .venv removed."
    echo ""
fi

# ── 4. Remove setup tracking files ───────────
echo "▶  Removing setup tracking files..."
REMOVED=0
for FILE in .install-method .conda-env-name .conda-lib-path; do
    if [ -f "$FILE" ]; then
        rm "$FILE"
        echo "   ✅ Removed $FILE"
        REMOVED=1
    fi
done
[ $REMOVED -eq 0 ] && echo "   ℹ️  No tracking files found (already clean)."
echo ""

# ── 5. Remove _temp folder ───────────────────
if [ -d "_temp" ]; then
    echo "▶  Removing _temp folder..."
    rm -rf _temp
    echo "   ✅ _temp removed."
    echo ""
fi

echo "══════════════════════════════════════════════"
echo "   ✅  Done. Your computer is back to"
echo "   the state it was in before setup ran."
echo ""
echo "   To do a fresh install, run:"
echo "       bash setup.sh"
echo "══════════════════════════════════════════════"
echo ""
