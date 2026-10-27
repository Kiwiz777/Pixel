#!/usr/bin/env bash
#
# install_kiosk_desktop.sh - set up the kiosk launcher for the desktop user.
#
# Run ON THE PI as the desktop (login) user - NOT sudo:
#   ./deploy/install_kiosk_desktop.sh                 # icon + menu entry + autostart at login
#   ./deploy/install_kiosk_desktop.sh --no-autostart  # icon + menu entry only
#
# Installs:
#   ~/.local/bin/pixel-kiosk                       the launcher (pixel-kiosk.sh)
#   ~/Desktop/pixel-kiosk.desktop                  "Start Pixel Kiosk" icon
#   ~/.local/share/applications/pixel-kiosk.desktop  same, in the app menu
#   ~/.config/autostart/pixel-kiosk.desktop        kiosk opens at login
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART=1
for arg in "$@"; do
  case "$arg" in
    --no-autostart) AUTOSTART=0 ;;
    -h|--help) sed -n '2,15p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "!! unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then
  echo "!! run this as the desktop user, not root - the kiosk runs in their session" >&2
  exit 1
fi

BIN="$HOME/.local/bin/pixel-kiosk"
mkdir -p "$(dirname "$BIN")"
install -m 0755 "$HERE/pixel-kiosk.sh" "$BIN"
echo "==> Launcher: $BIN"

entry() { # entry <path>
  mkdir -p "$(dirname "$1")"
  cat >"$1" <<EOF
[Desktop Entry]
Type=Application
Name=Start Pixel Kiosk
Comment=Open the Pixel photobooth full-screen (close it from the staff menu: 5 taps top-left)
Exec=$BIN
Icon=camera-photo
Terminal=false
Categories=Utility;
X-GNOME-Autostart-enabled=true
EOF
  chmod +x "$1"
}

DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
entry "$DESKTOP_DIR/pixel-kiosk.desktop"
# Pi OS's file manager asks before running desktop files unless trusted.
gio set "$DESKTOP_DIR/pixel-kiosk.desktop" metadata::trusted true 2>/dev/null || true
entry "$HOME/.local/share/applications/pixel-kiosk.desktop"
echo "==> Icon: $DESKTOP_DIR/pixel-kiosk.desktop (+ app menu)"

# The old hand-made autostart from docs/DEPLOYMENT_PI.md launched Chromium
# directly; keeping it would open a second, un-closable kiosk.
OLD="$HOME/.config/autostart/photobooth-kiosk.desktop"
if [ -f "$OLD" ]; then
  mv "$OLD" "$OLD.bak"
  echo "==> Disabled old autostart (saved as $OLD.bak)"
fi

if [ "$AUTOSTART" -eq 1 ]; then
  entry "$HOME/.config/autostart/pixel-kiosk.desktop"
  echo "==> Autostart at login: on"
else
  rm -f "$HOME/.config/autostart/pixel-kiosk.desktop"
  echo "==> Autostart at login: off"
fi
