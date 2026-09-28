#!/usr/bin/env bash
#
# build_pi.sh - compile the Photobooth Robot into a standalone ARM binary.
#
# MUST run on the target architecture: a Raspberry Pi 4/5 running 64-bit
# Pi OS (Bookworm), or an aarch64 container. Nuitka compiles through the
# system C compiler and cannot cross-compile from x86.
#
# Output: build/run.dist/  -> a self-contained directory, entrypoint `pixel`.
#
# Usage:  cd backend && ./build_pi.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
cd "$HERE"

# Nuitka compiles with whichever interpreter can import the app's deps. If you
# installed them into a venv rather than system-wide, point PYTHON at it:
#   PYTHON=.venv/bin/python ./build_pi.sh
PYTHON="${PYTHON:-python3}"

echo "==> Target: $(uname -m) / $("$PYTHON" --version)"
if [ "$(uname -m)" != "aarch64" ]; then
  echo "!!  WARNING: not aarch64. The binary will not run on 64-bit Pi OS." >&2
fi

# ---------------------------------------------------------------------------
# 1. Build the Vue frontend. Source maps stay off so the build ships minified
#    bundles only (Vite's default; asserted here so a stray config can't leak).
# ---------------------------------------------------------------------------
echo "==> Building frontend"
pushd "$ROOT/frontend" >/dev/null
npm ci
npm run build
popd >/dev/null

if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "!!  frontend/dist/index.html missing - frontend build failed" >&2
  exit 1
fi
if compgen -G "$ROOT/frontend/dist/assets/*.map" >/dev/null; then
  echo "!!  source maps found in dist/assets - set build.sourcemap=false" >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# 2. Compile the backend.
#
#    --standalone (not --onefile): onefile re-extracts the whole payload to
#    tmpfs on every boot, which on a Pi is a multi-second startup cost and
#    pointless SD/RAM churn for an appliance that never moves.
#
#    The optional native extras are excluded on purpose. Bundling opencv and
#    dlib for ARM is fragile and buys nothing - they are public open source.
#    They stay in the Pi's system Python; config.py re-adds that directory to
#    sys.path so the guarded imports in vision.py / printer.py still resolve.
# ---------------------------------------------------------------------------
echo "==> Compiling backend with Nuitka (this takes a while on a Pi)"
"$PYTHON" -m nuitka \
  --standalone \
  --output-dir=build \
  --output-filename=pixel \
  --company-name="Photobooth Robot" \
  --product-name="Pixel" \
  --include-data-dir="$ROOT/frontend/dist=frontend/dist" \
  --include-package=routers \
  --include-package=uvicorn \
  --include-package=websockets \
  --include-package=anyio \
  --include-package=h11 \
  --include-package=email.mime \
  --nofollow-import-to=cv2 \
  --nofollow-import-to=face_recognition \
  --nofollow-import-to=dlib \
  --nofollow-import-to=numpy \
  --nofollow-import-to=cups \
  --nofollow-import-to=neonize \
  --nofollow-import-to=tkinter \
  --enable-plugin=anti-bloat \
  --assume-yes-for-downloads \
  run.py

# ---------------------------------------------------------------------------
# 3. Strip anything that could leak source. Nuitka should not emit .py for
#    compiled modules, but bundled dependencies can carry their own.
# ---------------------------------------------------------------------------
DIST="$HERE/build/run.dist"
echo "==> Stripping residual source from $DIST"
find "$DIST" -name '*.py' -delete 2>/dev/null || true
find "$DIST" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
find "$DIST" -name '*.so' -exec strip --strip-unneeded {} + 2>/dev/null || true

echo
echo "==> Done: $DIST"
echo "    entrypoint : $DIST/pixel"
echo "    size       : $(du -sh "$DIST" | cut -f1)"
echo
echo "Next: ./smoke_test.sh   (verify FastAPI/Pydantic survived compilation)"
