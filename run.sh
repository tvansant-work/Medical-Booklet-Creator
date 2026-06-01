#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — Launcher
# ─────────────────────────────────────────────

# If double-clicked in Finder, relaunch inside a visible Terminal window
if [ -z "$TERM" ] && [ "$(uname)" = "Darwin" ]; then
    SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/Open Medical Booklet.command"
    open -a Terminal "$SCRIPT_PATH"
    exit 0
fi

cd "$(dirname "$0")"

# ── Configuration ─────────────────────────────────────────────────
GITHUB_USER="tvansant-work"
GITHUB_REPO="Medical-Booklet-Creator"
BRANCH="main"

# ── Auto-Update from GitHub ───────────────────────────────────────
echo ""
echo "  🔄  Checking for updates..."

fetch_and_report() {
  local URL="$1"
  local DEST="$2"
  local LABEL="$3"
  local TMP="${DEST}.tmp"

  curl -s -L -H "Cache-Control: no-cache" -H "Pragma: no-cache" -o "$TMP" "$URL"

  if [ ! -s "$TMP" ]; then
    rm -f "$TMP"
    return 1
  fi

  if [ -f "$DEST" ]; then
    OLD_SUM=$(md5 -q "$DEST" 2>/dev/null || md5sum "$DEST" | cut -d' ' -f1)
    NEW_SUM=$(md5 -q "$TMP"  2>/dev/null || md5sum "$TMP"  | cut -d' ' -f1)
    if [ "$OLD_SUM" = "$NEW_SUM" ]; then
      rm -f "$TMP"
      return 1
    else
      mv "$TMP" "$DEST"
      echo "  ✅  Updated: $LABEL"
      return 0
    fi
  else
    mv "$TMP" "$DEST"
    echo "  ✅  New file: $LABEL"
    return 0
  fi
}

# Resolve exact commit SHA to bypass CDN caching
LATEST_SHA=$(curl -s -f \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$GITHUB_USER/$GITHUB_REPO/commits/$BRANCH" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['sha'])" 2>/dev/null)

if [ -n "$LATEST_SHA" ]; then
  RAW_BASE="https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$LATEST_SHA"
else
  RAW_BASE="https://raw.githubusercontent.com/$GITHUB_USER/$GITHUB_REPO/$BRANCH"
fi

# Check run.sh first — if updated, re-exec so new logic runs immediately
fetch_and_report "$RAW_BASE/run.sh" "run.sh" "run.sh"
if [ $? -eq 0 ]; then
  chmod +x run.sh
  echo "  ↩️  Launcher updated — restarting with new version..."
  exec bash run.sh
fi

fetch_and_report "$RAW_BASE/app.py"                        "app.py"                        "app.py"
fetch_and_report "$RAW_BASE/requirements.txt"              "requirements.txt"              "requirements.txt"
fetch_and_report "$RAW_BASE/app_icon.png"                  "app_icon.png"                  "app_icon.png"
fetch_and_report "$RAW_BASE/config.yaml"                   "config.yaml"                   "config.yaml"
fetch_and_report "$RAW_BASE/profiles.html"                 "profiles.html"                 "profiles.html"
fetch_and_report "$RAW_BASE/Open Medical Booklet.command"  "Open Medical Booklet.command"  "Open Medical Booklet.command"

# Ensure launcher is always executable after update
chmod +x "Open Medical Booklet.command" 2>/dev/null

echo "  ✔️  Up to date."

# ── Rewrite old Desktop launcher ──────────────────────────────────
# Old Desktop launchers contain a full ZIP-download block and can't
# self-update. We overwrite them with a simple stub so they stay in
# sync going forward.
DESKTOP_LAUNCHER="$HOME/Desktop/Open Medical Booklet.command"
if [ -f "$DESKTOP_LAUNCHER" ]; then
    if ! grep -qF "stub-v2" "$DESKTOP_LAUNCHER" 2>/dev/null; then
        echo ""
        echo "  🔄  Updating Desktop launcher to current version..."
        cat > "$DESKTOP_LAUNCHER" << 'STUBEOF'
#!/bin/bash
# Medical Booklet Creator — double-click launcher
# stub-v2
cd "$HOME/Documents/medical-booklet"
bash run.sh
STUBEOF
        chmod +x "$DESKTOP_LAUNCHER"
        echo "  ✅  Desktop launcher updated."
    fi
fi

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

# ── Install any new/missing packages ─────────────────────────────
echo ""
echo "  📦  Verifying required packages..."
if [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
    conda run -n "$ENV_NAME" pip install -r requirements.txt --quiet
else
    $PYTHON -m pip install -r requirements.txt --quiet
fi

# ── Bypass Streamlit Welcome Prompt ───────────────────────────────
mkdir -p ~/.streamlit
if [ ! -f ~/.streamlit/credentials.toml ]; then
    echo "[general]" > ~/.streamlit/credentials.toml
    echo 'email = ""' >> ~/.streamlit/credentials.toml
fi

# ── Force light theme always ───────────────────────────────────────
mkdir -p .streamlit
cat > .streamlit/config.toml << 'TOMLEOF'
[theme]
base = "light"
primaryColor = "#1a7f6e"
backgroundColor = "#f5f6fa"
secondaryBackgroundColor = "#ffffff"
textColor = "#1a1d2e"
TOMLEOF

# ── Apply Custom Icon (Cocoa) ─────────────────────────────────────
# Re-applied every launch because:
#   1. The auto-updater (mv) strips com.apple.FinderInfo (the xattr
#      that stores the custom icon) from updated files.
#   2. You may push a new app_icon.png to GitHub at any time —
#      this block ensures all users pick it up automatically on
#      their next launch.
#
# FIX: paths are written into the AppleScript via a temp file
# (set … to POSIX file "…") rather than bare heredoc expansion,
# which broke silently when paths contained spaces.
ICON_PATH="$(pwd)/app_icon.png"

apply_icon() {
    local TARGET="$1"
    echo "  🖼️  Applying icon to: $(basename "$TARGET")"

    if [ ! -f "$ICON_PATH" ]; then
        echo "  ⚠️  Icon PNG not found at: $ICON_PATH"
        return 1
    fi
    if [ ! -f "$TARGET" ]; then
        echo "  ⚠️  Target not found: $TARGET"
        return 1
    fi

    # Write a temp AppleScript file so we can safely embed paths that
    # contain spaces or special characters — heredoc expansion inside
    # osascript source breaks on filenames with spaces (e.g. the
    # "Open Medical Booklet.command" filename itself).
    local TMPSCRIPT
    TMPSCRIPT="$(mktemp /tmp/apply_icon_XXXXXX.applescript)"

    # Use printf so the paths land inside AppleScript string literals
    # exactly, with no shell word-splitting or glob expansion.
    printf 'use framework "AppKit"\n' > "$TMPSCRIPT"
    printf 'use scripting additions\n' >> "$TMPSCRIPT"
    printf 'set iconPath to "%s"\n' "$ICON_PATH" >> "$TMPSCRIPT"
    printf 'set targetPath to "%s"\n' "$TARGET" >> "$TMPSCRIPT"
    printf 'set theImage to current application'\''s NSImage'\''s alloc()'\''s initWithContentsOfFile_(iconPath)\n' >> "$TMPSCRIPT"
    printf 'if theImage is missing value then\n' >> "$TMPSCRIPT"
    printf '    return "error: NSImage could not load icon"\n' >> "$TMPSCRIPT"
    printf 'end if\n' >> "$TMPSCRIPT"
    printf 'set ws to current application'\''s NSWorkspace'\''s sharedWorkspace()\n' >> "$TMPSCRIPT"
    printf 'set ok to ws'\''s setIcon:theImage forFile:targetPath options:0\n' >> "$TMPSCRIPT"
    printf 'if ok then\n' >> "$TMPSCRIPT"
    printf '    return "ok"\n' >> "$TMPSCRIPT"
    printf 'else\n' >> "$TMPSCRIPT"
    printf '    return "error: setIcon returned false"\n' >> "$TMPSCRIPT"
    printf 'end if\n' >> "$TMPSCRIPT"

    local ICON_RESULT
    ICON_RESULT=$(osascript "$TMPSCRIPT" 2>&1)
    rm -f "$TMPSCRIPT"

    if [ "$ICON_RESULT" = "ok" ]; then
        echo "  ✅  Icon set. Refreshing Finder..."
        touch "$TARGET"
        touch "$(dirname "$TARGET")"
        # Refresh Finder — quote the path properly in the inline script
        osascript -e "tell application \"Finder\" to update item (POSIX file \"$TARGET\" as alias)" 2>/dev/null || true
        echo "  ✅  Done."
    else
        echo "  ⚠️  Icon not set: $ICON_RESULT"
    fi
}

echo ""
if [ -f "$ICON_PATH" ]; then
    # Apply to the in-folder launcher
    apply_icon "$(pwd)/Open Medical Booklet.command"
    # Apply to the Desktop shortcut (the one users actually double-click)
    if [ -f "$DESKTOP_LAUNCHER" ]; then
        apply_icon "$DESKTOP_LAUNCHER"
    fi
else
    echo "  ⚠️  app_icon.png not found — skipping icon update."
fi

# ── Launch ────────────────────────────────────────────────────────
echo ""
echo "  ✅  Starting Medical Booklet Creator..."
echo "      Opening in your browser now."
echo "      If it doesn't open, go to: http://localhost:8501"
echo ""
echo "      Press Ctrl+C to stop the app."
echo ""

if [ "$METHOD" = "conda" ] && [ -n "$ENV_NAME" ]; then
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