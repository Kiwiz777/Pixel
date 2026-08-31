#!/usr/bin/env bash
#
# deploy_pi.sh - one-shot build, verify and install on the Raspberry Pi.
#
# Chains the steps documented in docs/BUILD.md so a fresh (or updated) Pi
# goes from source tree to a running `pixel` systemd service with one
# command, instead of running each step by hand every time:
#
#   0. one-time build prerequisites (apt + pip)   [skip with --skip-prereqs]
#   1. backend/build_pi.sh    - compile the frontend + backend (Nuitka)
#   2. backend/smoke_test.sh  - boot the binary and check it actually works
#   3. deploy/install_pi.sh   - install/replace the `pixel` systemd service
#
# Each step is a real, independently-runnable script (see docs/BUILD.md for
# what they do and why) - this is just the glue so you don't have to.
#
# Run ON THE PI (aarch64, 64-bit Pi OS) as your normal user, NOT root/sudo -
# it calls sudo itself for the two steps that actually need it (prereqs,
# install), so the build itself doesn't run as root.
#
# Usage:
#   ./deploy/deploy_pi.sh                 # prereqs + build + smoke test + install
#   ./deploy/deploy_pi.sh --skip-prereqs   # already ran this once - skip apt/pip setup
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

SKIP_PREREQS=0
for arg in "$@"; do
  case "$arg" in
    --skip-prereqs) SKIP_PREREQS=1 ;;
    -h|--help)
      sed -n '2,22p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) echo "!! unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then
  echo "!! run this as your normal pi user, not root - it calls sudo itself where needed" >&2
  exit 1
fi

PYTHON="${PYTHON:-python3}"

if [ "$SKIP_PREREQS" -eq 0 ]; then
  echo "==> Step 0/3: one-time build prerequisites"
  sudo apt update
  sudo apt install -y python3-dev build-essential patchelf ccache nodejs npm
  "$PYTHON" -m pip install --break-system-packages --upgrade nuitka
  "$PYTHON" -m pip install --break-system-packages -r "$ROOT/backend/requirements.txt"
else
  echo "==> Step 0/3: skipped (--skip-prereqs)"
fi

echo "==> Step 1/3: build (backend/build_pi.sh)"
PYTHON="$PYTHON" bash "$ROOT/backend/build_pi.sh"

echo "==> Step 2/3: smoke test (backend/smoke_test.sh)"
bash "$ROOT/backend/smoke_test.sh"

echo "==> Step 3/3: install as the 'pixel' systemd service (deploy/install_pi.sh)"
sudo bash "$HERE/install_pi.sh" "$ROOT/backend/build/run.dist"

echo
echo "==> Deployed. Kiosk: http://$(hostname -I | awk '{print $1}'):8000"
