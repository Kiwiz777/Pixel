#!/usr/bin/env bash
#
# install_pi.sh - install a compiled build onto a Raspberry Pi.
#
# Run ON THE PI, as root, with a build/run.dist produced by backend/build_pi.sh.
#
#   sudo ./deploy/install_pi.sh backend/build/run.dist
#
set -euo pipefail

DIST="${1:-backend/build/run.dist}"
APP_DIR=/opt/pixel
STATE_DIR=/var/lib/pixel
ENV_FILE=/etc/pixel/pixel.env

[ "$(id -u)" -eq 0 ] || { echo "!! must run as root" >&2; exit 1; }
[ -x "$DIST/pixel" ] || { echo "!! no binary at $DIST/pixel" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Service account. No login shell, no home - it only runs the binary.
# ---------------------------------------------------------------------------
if ! id pixel >/dev/null 2>&1; then
  echo "==> Creating 'pixel' service user"
  useradd --system --no-create-home --shell /usr/sbin/nologin pixel
fi
usermod -aG video,lp pixel

# ---------------------------------------------------------------------------
# 2. Optional native extras, in the SYSTEM python (deliberately not bundled).
#    Skipped if already present - the app degrades gracefully without them.
# ---------------------------------------------------------------------------
echo "==> Ensuring optional hardware libs"
apt-get update -qq
apt-get install -y --no-install-recommends \
  python3-opencv python3-numpy cups cups-client libcups2-dev >/dev/null
python3 -c 'import cups' 2>/dev/null || pip3 install --break-system-packages pycups
# WhatsApp photo delivery (optional - the app just hides the option without it).
python3 -c 'import neonize' 2>/dev/null || pip3 install --break-system-packages neonize \
  || echo "   (neonize install failed - WhatsApp sending will be unavailable)"
# neonize downloads its Go library (neonize-linux-arm64.so) from GitHub into
# its own package folder on FIRST IMPORT. The service can't do that: it runs
# as `pixel` under ProtectSystem=strict, so /usr/local is read-only and the
# import fails. Import it once here, as root, to fetch the library now.
if python3 -c 'import importlib.util,sys; sys.exit(not importlib.util.find_spec("neonize"))' 2>/dev/null; then
  if python3 -c 'import neonize.client' >/dev/null 2>&1; then
    echo "   neonize OK ($(python3 -c 'import neonize; print(neonize.__version__)'))"
  else
    echo "   !! neonize is installed but won't load - WhatsApp will be unavailable:"
    python3 -c 'import neonize.client' 2>&1 | tail -n 3 | sed 's/^/      /'
  fi
fi

# ---------------------------------------------------------------------------
# 3. Application bundle -> read-only, owned by root. The service user can
#    execute it but never modify it.
# ---------------------------------------------------------------------------
echo "==> Installing bundle to $APP_DIR"
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
cp -a "$DIST/." "$APP_DIR/"
chown -R root:root "$APP_DIR"
chmod -R a-w "$APP_DIR"
chmod 0755 "$APP_DIR/pixel"

# ---------------------------------------------------------------------------
# 4. Writable state, owned by the service user.
# ---------------------------------------------------------------------------
mkdir -p "$STATE_DIR"
chown -R pixel:pixel "$STATE_DIR"
chmod 0700 "$STATE_DIR"

# Soft-saved guest photos: a SHARED folder, unlike the private state dir.
# setgid + group-writable so the human login user (added to the `pixel`
# group) can browse, copy and clean it up without sudo.
PHOTOS_DIR=/srv/pixel/photos
mkdir -p "$PHOTOS_DIR"
chown pixel:pixel "$PHOTOS_DIR"
chmod 2775 "$PHOTOS_DIR"
chmod 0755 "$(dirname "$PHOTOS_DIR")"
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
  usermod -aG pixel "$SUDO_USER"
  echo "==> $SUDO_USER added to group 'pixel' (photos: $PHOTOS_DIR; re-login to apply)"
fi

# ---------------------------------------------------------------------------
# 5. Secrets. Generated once, never baked into the image.
# ---------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  echo "==> Generating $ENV_FILE"
  mkdir -p "$(dirname "$ENV_FILE")"
  cat >"$ENV_FILE" <<EOF
PB_ADMIN_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | head -c 40)
PB_SECRET_KEY=$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 64)
PB_CORS_ORIGINS=http://localhost:8000
EOF
  chown root:root "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "    admin token: $(grep PB_ADMIN_TOKEN "$ENV_FILE" | cut -d= -f2)"
  echo "    (save it now - the file is root-only from here on)"
else
  echo "==> Keeping existing $ENV_FILE"
fi

# ---------------------------------------------------------------------------
# 6. Service.
# ---------------------------------------------------------------------------
echo "==> Installing systemd unit"
cp "$(dirname "$0")/pixel.service" /etc/systemd/system/pixel.service
systemctl daemon-reload
systemctl enable --now pixel

sleep 2
systemctl --no-pager --lines=15 status pixel || true
echo
echo "==> Kiosk: http://$(hostname -I | awk '{print $1}'):8000"
