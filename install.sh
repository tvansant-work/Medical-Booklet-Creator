#!/bin/bash
# ─────────────────────────────────────────────
#  Medical Booklet Creator — One-line Installer
#
#  Usage (paste into Terminal):
#    bash <(curl -fsSL https://raw.githubusercontent.com/tvansant-work/Medical-Booklet-Creator/main/install.sh)
# ─────────────────────────────────────────────

set -e

APP_DIR="$HOME/Documents/medical-booklet"

echo ""
echo "══════════════════════════════════════════════"
echo "   Medical Booklet Creator — Installing"
echo "══════════════════════════════════════════════"
echo ""
echo "  📥  Downloading..."

curl -fsSL \
    "https://github.com/tvansant-work/Medical-Booklet-Creator/archive/refs/heads/main.zip" \
    -o /tmp/mb.zip

rm -rf /tmp/Medical-Booklet-Creator-main
unzip -q /tmp/mb.zip -d /tmp/
rm -f /tmp/mb.zip

echo "  📂  Installing to ~/Documents/medical-booklet..."

rm -rf "$APP_DIR"
rm -f "$HOME/Desktop/Open Medical Booklet.command"
mv /tmp/Medical-Booklet-Creator-main "$APP_DIR"

cd "$APP_DIR"
echo ""
bash setup.sh