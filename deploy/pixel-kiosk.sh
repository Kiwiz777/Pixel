#!/usr/bin/env bash
#
# pixel-kiosk.sh - start the Pixel kiosk (Chromium --kiosk) and close it on
# request from the kiosk's hidden staff menu (5 taps, top-left).
#
# Run it AS THE DESKTOP USER (not root, not the `pixel` service user) - it's
# what the "Start Pixel Kiosk" desktop icon and the login autostart call.
# install_kiosk_desktop.sh puts it at ~/.local/bin/pixel-kiosk.
#
# Why a launcher: a web page can't close a --kiosk Chromium, and the backend
# runs as `pixel`, which can't touch the desktop user's processes. So this
# script polls GET /api/kiosk/exit and closes Chromium itself.
#
# Env overrides:
#   PIXEL_URL=http://localhost:8000/    what the kiosk opens (keep it localhost:
#                                       the camera and the close button need it)
#   PIXEL_BROWSER=chromium-browser      browser binary
#
set -uo pipefail

URL="${PIXEL_URL:-http://localhost:8000/}"
BASE="$(printf '%s' "$URL" | sed -E 's#^(https?://[^/]+).*#\1#')"   # scheme://host:port
PROFILE="$HOME/.config/pixel-kiosk"
RUN_DIR="${XDG_RUNTIME_DIR:-/tmp}"

BROWSER="${PIXEL_BROWSER:-}"
if [ -z "$BROWSER" ]; then
  for b in chromium-browser chromium google-chrome; do
    command -v "$b" >/dev/null 2>&1 && { BROWSER="$b"; break; }
  done
fi
[ -n "$BROWSER" ] || { echo "!! Chromium not found (set PIXEL_BROWSER)" >&2; exit 1; }

# One kiosk at a time - a second click on the icon just does nothing.
exec 9>"$RUN_DIR/pixel-kiosk.lock"
if ! flock -n 9; then
  echo "Pixel kiosk is already running."
  exit 0
fi

# The backend may still be booting (desktop autostart races systemd).
echo "==> Waiting for Pixel at $BASE"
for _ in $(seq 1 90); do
  curl -fsS -o /dev/null "$BASE/api/health" && break
  sleep 2
done

# We close Chromium with SIGTERM; tell it the last run ended cleanly so it
# never shows a "Restore pages?" bubble on the kiosk.
PREFS="$PROFILE/Default/Preferences"
if [ -f "$PREFS" ]; then
  sed -i 's/"exited_cleanly":false/"exited_cleanly":true/; s/"exit_type":"[^"]*"/"exit_type":"Normal"/' "$PREFS"
fi

START="$(date +%s)"
# A dedicated profile so the kiosk is its own process (an open normal
# Chromium window would otherwise absorb it and we'd lose track of it).
"$BROWSER" \
  --kiosk \
  --user-data-dir="$PROFILE" \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --no-first-run \
  --check-for-update-interval=31536000 \
  --autoplay-policy=no-user-gesture-required \
  --use-fake-ui-for-media-stream \
  "$URL" >/dev/null 2>&1 &
PID=$!
echo "==> Kiosk started (pid $PID). Close it from the staff menu: 5 taps top-left."

close_browser() {
  kill -TERM "$PID" 2>/dev/null || return
  for _ in $(seq 1 10); do
    kill -0 "$PID" 2>/dev/null || return
    sleep 0.5
  done
  kill -KILL "$PID" 2>/dev/null
}
trap 'close_browser; exit 0' INT TERM

while kill -0 "$PID" 2>/dev/null; do
  sleep 2
  REQ="$(curl -fsS --max-time 2 "$BASE/api/kiosk/exit" 2>/dev/null \
        | sed -n 's/.*"requested_at":[[:space:]]*\([0-9.eE+-]*\).*/\1/p')"
  if [ -n "$REQ" ] && awk -v r="$REQ" -v s="$START" 'BEGIN { exit !(r > s) }'; then
    echo "==> Close requested from the kiosk."
    close_browser
    break
  fi
done
wait "$PID" 2>/dev/null
echo "==> Kiosk closed. Start it again with the \"Start Pixel Kiosk\" icon."
