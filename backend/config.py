"""
Central configuration for the Photobooth Robot backend.

Values here are *infrastructure* level (paths, ports, secrets used to
encrypt the DB-stored API keys). Anything the Admin can change at runtime
(API keys, active providers, bot behaviour) lives in the SQLite `settings`
table instead — see database.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # python-dotenv is optional in production
    pass

# True when running from a Nuitka build (see build_pi.sh). Nuitka injects
# `__compiled__` into every module it compiles.
IS_COMPILED = "__compiled__" in globals()

# --------------------------------------------------------------------------
# Paths
#
# Two roots, and they must stay separate once compiled:
#   BASE_DIR / DIST_DIR - read-only bundle. Code + the built Vue app.
#   DATA_DIR            - writable state. DB, captures, uploads, .secret.
#
# Deriving DATA_DIR from __file__ is fine in dev but wrong in a compiled
# build: the bundle lives on a read-only filesystem, so every write fails.
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent


def _find_dist() -> Path:
    """Built Vue app: bundled beside the code when compiled, sibling in dev."""
    for candidate in (BASE_DIR / "frontend" / "dist", BASE_DIR.parent / "frontend" / "dist"):
        if candidate.is_dir():
            return candidate
    # Missing is not fatal - main.py just skips the SPA mount (dev uses Vite).
    return BASE_DIR / "frontend" / "dist"


DIST_DIR = Path(os.getenv("PB_DIST_DIR") or _find_dist())

_DEFAULT_DATA_DIR = Path("/var/lib/pixel") if IS_COMPILED else BASE_DIR / "data"
DATA_DIR = Path(os.getenv("PB_DATA_DIR", _DEFAULT_DATA_DIR))
CAPTURES_DIR = DATA_DIR / "captures"          # raw + enhanced photos
FRAMES_DIR = DATA_DIR / "frames"              # uploaded PNG overlays
FACES_DIR = DATA_DIR / "faces"                # known-face reference images
BACKGROUNDS_DIR = DATA_DIR / "backgrounds"    # kiosk background images/videos
REWARDS_DIR = DATA_DIR / "rewards"            # quiz reward images shown to winners
WHEEL_DIR = DATA_DIR / "wheel"                # prize-wheel custom frame/background art
STYLES_DIR = DATA_DIR / "styles"              # AI Enhance style-card artwork
VOICE_DIR = DATA_DIR / "voice"                # saved (pre-generated) TTS clips
AVATAR_DIR = DATA_DIR / "avatar"              # real-person video avatar clips
RECORDINGS_DIR = DATA_DIR / "recordings"      # kept STT audio, for playback/debugging
WHATSAPP_DIR = DATA_DIR / "whatsapp"          # linked-device session (keep private)
DB_PATH = Path(os.getenv("PB_DB_PATH", DATA_DIR / "photobooth.db"))

# Soft-saved guest photos, as <date>/<datetime>.jpg. Deliberately its own env
# var: DATA_DIR is private (0700 on the Pi), while this folder is meant to be
# browsed/copied/shared by the operator (see docs/DEPLOYMENT_PI.md).
PHOTOS_DIR = Path(os.getenv("PB_PHOTOS_DIR", DATA_DIR / "photos"))

try:
    for _d in (DATA_DIR, CAPTURES_DIR, FRAMES_DIR, FACES_DIR, BACKGROUNDS_DIR,
               REWARDS_DIR, WHEEL_DIR, STYLES_DIR, VOICE_DIR, AVATAR_DIR, RECORDINGS_DIR, WHATSAPP_DIR, PHOTOS_DIR):
        _d.mkdir(parents=True, exist_ok=True)
except OSError as _exc:  # read-only or unwritable state dir - fail loudly, not weirdly
    raise RuntimeError(
        f"Cannot create state directory {DATA_DIR}: {_exc}. "
        "Point PB_DATA_DIR at a writable path (the systemd unit uses /var/lib/pixel)."
    ) from _exc

# A Nuitka standalone build has its own isolated sys.path. The heavy native
# extras (cv2, face_recognition, pycups) are deliberately NOT bundled - they
# stay in the Pi's system Python - so re-add that directory here, before any
# other backend module runs its guarded import of them.
if IS_COMPILED:
    # apt installs land in /usr/lib/python3/dist-packages, but
    # `pip install --break-system-packages` (pycups, neonize) lands in
    # /usr/local/lib/python3.X/dist-packages - both must be searchable.
    _default_extra = os.pathsep.join((
        "/usr/lib/python3/dist-packages",
        f"/usr/local/lib/python{sys.version_info.major}.{sys.version_info.minor}/dist-packages",
    ))
    for _p in os.getenv("PB_EXTRA_SITE_PACKAGES", _default_extra).split(os.pathsep):
        if _p and os.path.isdir(_p) and _p not in sys.path:
            sys.path.append(_p)

# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------
HOST = os.getenv("PB_HOST", "0.0.0.0")
PORT = int(os.getenv("PB_PORT", "8000"))

# CORS origins for the Vite dev server / kiosk. "*" in dev, lock down on Pi.
CORS_ORIGINS = os.getenv(
    "PB_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
).split(",")

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------
# Used to derive a Fernet key that encrypts API keys at rest in SQLite.
# CHANGE THIS in production (.env -> PB_SECRET_KEY). If unset, a per-install
# key is generated and persisted to data/.secret so encryption is stable.
def _load_or_create_secret() -> str:
    env = os.getenv("PB_SECRET_KEY")
    if env:
        return env
    secret_file = DATA_DIR / ".secret"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()
    import secrets

    value = secrets.token_urlsafe(48)
    secret_file.write_text(value, encoding="utf-8")
    try:  # tighten perms on POSIX (no-op on Windows)
        os.chmod(secret_file, 0o600)
    except Exception:
        pass
    return value


SECRET_KEY = _load_or_create_secret()

# Admin auth (simple bearer token gate for the dashboard API).
# Set a strong value in .env for the Pi deployment.
ADMIN_TOKEN = os.getenv("PB_ADMIN_TOKEN", "change-me-admin-token")

# --------------------------------------------------------------------------
# Vision / camera
# --------------------------------------------------------------------------
CAMERA_INDEX = int(os.getenv("PB_CAMERA_INDEX", "0"))
STREAM_WIDTH = int(os.getenv("PB_STREAM_WIDTH", "1280"))
STREAM_HEIGHT = int(os.getenv("PB_STREAM_HEIGHT", "720"))
STREAM_FPS = int(os.getenv("PB_STREAM_FPS", "20"))
STREAM_JPEG_QUALITY = int(os.getenv("PB_STREAM_JPEG_QUALITY", "70"))
# Run face recognition only every Nth frame to keep the Pi responsive.
FACE_DETECT_EVERY_N_FRAMES = int(os.getenv("PB_FACE_DETECT_EVERY_N", "15"))
FACE_MATCH_TOLERANCE = float(os.getenv("PB_FACE_TOLERANCE", "0.55"))
