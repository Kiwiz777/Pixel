"""
SQLite persistence layer for the Photobooth Robot.

Tables
------
- settings   : key/value store for ALL runtime config (API keys [encrypted],
               active providers, bot behaviour flags, printer + frame config).
- users      : people the bot can recognise (face encoding + bio).
- logs       : audit/event trail (conversations, captures, prints, errors).

Design notes
------------
* We use a tiny key/value `settings` table rather than a wide column table so
  the Admin can add behaviour flags without migrations.
* API keys are encrypted at rest via security.encrypt/decrypt and are *never*
  returned in plaintext to the UI (the API returns masked previews instead).
* Connections use WAL + row factory; helpers below open short-lived
  connections which is plenty for a single-kiosk workload.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

import config
import security

# Keys whose values must be encrypted at rest.
SECRET_KEYS = {
    "api_key_openai",
    "api_key_anthropic",
    "api_key_gemini",
    "api_key_deepseek",
    "api_key_elevenlabs",
    "smtp_password",
}

# Default settings seeded on first run. These mirror the Admin UI controls.
DEFAULT_SETTINGS: dict[str, Any] = {
    # --- API keys (encrypted on write) ---
    "api_key_openai": "",
    "api_key_anthropic": "",
    "api_key_gemini": "",
    "api_key_deepseek": "",
    "api_key_elevenlabs": "",
    # --- Active providers / models ---
    "active_chat_provider": "anthropic",          # openai|anthropic|gemini|deepseek
    "active_chat_model": "claude-opus-4-8",
    "active_image_provider": "openai",            # provider used for AI Enhance
    "active_image_model": "gpt-image-1",
    # Text-to-speech: provider-agnostic so ElevenLabs is optional.
    "tts_provider": "openai",                     # openai | elevenlabs
    "tts_voice_id": "",                           # ElevenLabs voice id
    "openai_tts_model": "gpt-4o-mini-tts",        # gpt-4o-mini-tts | tts-1 | tts-1-hd
    "openai_tts_voice": "alloy",                  # alloy|echo|fable|onyx|nova|shimmer|...
    "stt_provider": "openai",                     # whisper via openai by default
    # --- Bot behaviour ---
    "auto_interact_mode": True,                   # greet faces automatically
    "interact_button_visible": True,              # show "Talk to Me" button
    "bot_face_visible": True,                     # show the floating EMO robot face on the kiosk
    "ai_enhance_prompt": "Enhance this portrait: studio lighting, vibrant, "
                          "clean background, keep the person's identity intact.",
    "default_language": "en",                     # en|ar-EG|ar-GULF|ru|de|fr
    "multilingual_autodetect": True,
    "system_persona": "You are Pixel, a cheerful multilingual photobooth robot. "
                      "Keep replies short, warm and fun.",
    "dev_mode": False,                            # show recognition overlay on the kiosk
    # Master switch for ALL face detection/recognition (client dwell-watch +
    # server-side OpenCV). Auto-Interact greeting behaviour layers on top of this.
    "face_recognition_enabled": True,
    # --- Quiz / MCQ game ---
    "quiz_enabled": True,                         # show the "Take the Quiz" button on the kiosk
    "active_quiz_id": None,                        # which quiz the kiosk serves (nullable)
    # When False, the kiosk main screen does NOT auto-start the webcam; it leads
    # with the buttons (e.g. "Take the Quiz") and starts the camera on demand.
    "kiosk_camera_autostart": True,
    # Turn the camera off after this many seconds of no interaction (0 = never).
    "camera_idle_off_seconds": 0,
    # Turn the camera off again once a photo session finishes (on-demand camera).
    "camera_off_after_session": False,
    # --- Email (SMTP) for voucher delivery (optional; graceful if unset) ---
    "smtp_host": "",
    "smtp_port": 587,
    "smtp_user": "",
    "smtp_password": "",
    "smtp_from": "",
    "smtp_tls": True,
    # --- Kiosk appearance / background ---
    # mode: "none" | "color" | "image" | "video" | "slideshow"
    "kiosk_bg_mode": "none",
    "kiosk_bg_color": "#070b16",
    "kiosk_bg_media": [],                         # list of {file, type} under data/backgrounds
    "kiosk_bg_slideshow_ms": 6000,                # per-slide duration for slideshow
    "kiosk_bg_dim": 35,                           # darken overlay 0-100 for legibility
    # Cap on reply length. Short replies are faster twice over: less time
    # generating, and TTS cost scales with character count. ~120 tokens is
    # 2-3 spoken sentences, which is all a photobooth greeting needs.
    "chat_max_tokens": 120,
    # --- Photobooth / printer ---
    "frame_overlay_path": "",                     # relative path under data/frames
    "default_printer": "",                        # CUPS printer name
    "print_copies": 1,
    "print_media": "4x6.Borderless",              # CUPS PageSize name (see /api/printer/media)
    "print_color_mode": "color",                  # color|monochrome
    # Print geometry. The photo is cropped/scaled to exactly this shape before
    # it reaches CUPS - otherwise CUPS auto-rotates a landscape photo onto
    # portrait paper to maximise coverage, which is why prints came out sideways.
    "print_size_cm": "10x15",                     # paper size in cm, order-insensitive
    # portrait|landscape crop the photo to the paper shape before printing.
    # "auto" sends the photo untouched and lets CUPS fit + rotate it, which is
    # what a bare `lp file` does: no crop at all, photo laid whichever way
    # fills more paper.
    "print_orientation": "auto",
    "print_dpi": 300,                             # 300 = photo quality
    "print_fit": "cover",                         # cover (crop to fill) | contain (white bars)
}

# Languages the bot speaks (used by the Admin language dropdown).
SUPPORTED_LANGUAGES = [
    {"code": "ar-EG", "label": "Egyptian Arabic", "native": "مصرى"},
    {"code": "ar-GULF", "label": "Gulf Arabic", "native": "خليجي"},
    {"code": "en", "label": "English", "native": "English"},
    {"code": "ru", "label": "Russian", "native": "Русский"},
    {"code": "de", "label": "German", "native": "Deutsch"},
    {"code": "fr", "label": "French", "native": "Français"},
]


# --------------------------------------------------------------------------
# Connection handling
# --------------------------------------------------------------------------
@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,                 -- JSON-encoded scalar
    is_secret   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    bio           TEXT DEFAULT '',
    language      TEXT DEFAULT 'en',  -- preferred greeting language
    face_image    TEXT,               -- relative path under data/faces
    face_encoding TEXT,               -- JSON list[float] (128-d), nullable
    last_seen     TEXT,
    visit_count   INTEGER NOT NULL DEFAULT 0,
    is_admin      INTEGER NOT NULL DEFAULT 0,  -- operators the bot should NOT chat up
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,        -- conversation|capture|print|enhance|face|error|system
    user_id     INTEGER,             -- nullable FK -> users.id
    message     TEXT,                 -- human-readable summary / prompt
    response    TEXT,                 -- bot reply / result
    meta        TEXT,                 -- JSON blob (provider, language, paths, etc.)
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_logs_type ON logs(type);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);

CREATE TABLE IF NOT EXISTS quizzes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT DEFAULT '',
    pass_score  INTEGER NOT NULL DEFAULT 70,  -- percent (0-100) needed to win
    is_active   INTEGER NOT NULL DEFAULT 0,    -- exactly one active at a time
    questions   TEXT NOT NULL DEFAULT '[]',    -- JSON list[question]
    reward      TEXT NOT NULL DEFAULT '{}',    -- JSON reward config
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def init_db() -> None:
    """Create tables (idempotent) and seed default settings."""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # Lightweight migration: add columns introduced after first release.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "is_admin" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")
        # Seed any missing default settings.
        existing = {row["key"] for row in conn.execute("SELECT key FROM settings")}
        now = _utcnow()
        for key, default in DEFAULT_SETTINGS.items():
            if key in existing:
                continue
            is_secret = 1 if key in SECRET_KEYS else 0
            stored = default
            if is_secret and default:
                stored = security.encrypt(default)
            conn.execute(
                "INSERT INTO settings(key, value, is_secret, updated_at) VALUES (?,?,?,?)",
                (key, json.dumps(stored), is_secret, now),
            )


# --------------------------------------------------------------------------
# Settings helpers
# --------------------------------------------------------------------------
def get_setting(key: str, default: Any = None, *, decrypt_secret: bool = True) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value, is_secret FROM settings WHERE key=?", (key,)).fetchone()
    if row is None:
        return default
    value = json.loads(row["value"]) if row["value"] is not None else None
    if row["is_secret"] and decrypt_secret:
        value = security.decrypt(value)
    return value


def set_setting(key: str, value: Any) -> None:
    is_secret = 1 if key in SECRET_KEYS else 0
    stored = security.encrypt(value) if (is_secret and value) else value
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value, is_secret, updated_at)
            VALUES (?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                           is_secret=excluded.is_secret,
                                           updated_at=excluded.updated_at
            """,
            (key, json.dumps(stored), is_secret, _utcnow()),
        )


def get_all_settings(*, reveal_secrets: bool = False) -> dict[str, Any]:
    """
    Return every setting. Secret values are masked unless reveal_secrets=True.
    The masked form is what the Admin UI consumes so keys never hit the wire.
    """
    out: dict[str, Any] = {}
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value, is_secret FROM settings").fetchall()
    for row in rows:
        raw = json.loads(row["value"]) if row["value"] is not None else None
        if row["is_secret"]:
            plain = security.decrypt(raw)
            if reveal_secrets:
                out[row["key"]] = plain
            else:
                out[row["key"]] = security.mask(plain)
                out[f"{row['key']}__set"] = bool(plain)
        else:
            out[row["key"]] = raw
    return out


def update_settings(values: dict[str, Any]) -> None:
    """Bulk update. Empty-string secrets are ignored so masked previews
    posted back from the UI don't wipe stored keys."""
    for key, value in values.items():
        if key in SECRET_KEYS and (value is None or value == ""):
            continue  # don't overwrite an existing secret with a blank
        set_setting(key, value)


# --------------------------------------------------------------------------
# Users helpers
# --------------------------------------------------------------------------
def list_users() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()
    return [_user_public(dict(r)) for r in rows]


def get_user(user_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return _user_public(dict(row)) if row else None


def create_user(name: str, bio: str = "", language: str = "en",
                face_image: str | None = None,
                face_encoding: Iterable[float] | None = None,
                is_admin: bool = False) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users(name, bio, language, face_image, face_encoding, is_admin, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (name, bio, language, face_image,
             json.dumps(list(face_encoding)) if face_encoding is not None else None,
             1 if is_admin else 0, _utcnow()),
        )
        return int(cur.lastrowid)


def update_user(user_id: int, **fields: Any) -> None:
    if not fields:
        return
    if "face_encoding" in fields and fields["face_encoding"] is not None:
        fields["face_encoding"] = json.dumps(list(fields["face_encoding"]))
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id=?", (*fields.values(), user_id))


def delete_user(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))


def mark_user_seen(user_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_seen=?, visit_count=visit_count+1 WHERE id=?",
            (_utcnow(), user_id),
        )


def get_known_face_encodings() -> list[tuple[int, str, list[float]]]:
    """Return (user_id, name, encoding) for users that have a face encoding."""
    out: list[tuple[int, str, list[float]]] = []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, face_encoding FROM users WHERE face_encoding IS NOT NULL"
        ).fetchall()
    for r in rows:
        try:
            out.append((r["id"], r["name"], json.loads(r["face_encoding"])))
        except Exception:
            continue
    return out


def _user_public(row: dict[str, Any]) -> dict[str, Any]:
    """Hide the raw 128-d encoding from API responses; expose a boolean."""
    row = dict(row)
    row["has_face"] = row.get("face_encoding") is not None
    row["is_admin"] = bool(row.get("is_admin"))
    row.pop("face_encoding", None)
    return row


# --------------------------------------------------------------------------
# Logs helpers
# --------------------------------------------------------------------------
def add_log(log_type: str, *, message: str | None = None, response: str | None = None,
            user_id: int | None = None, meta: dict[str, Any] | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO logs(type, user_id, message, response, meta, created_at)
               VALUES (?,?,?,?,?,?)""",
            (log_type, user_id, message, response,
             json.dumps(meta) if meta else None, _utcnow()),
        )
        return int(cur.lastrowid)


def list_logs(log_type: str | None = None, limit: int = 100,
              offset: int = 0) -> list[dict[str, Any]]:
    query = "SELECT * FROM logs"
    params: list[Any] = []
    if log_type:
        query += " WHERE type=?"
        params.append(log_type)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with get_conn() as conn:
        rows = conn.execute(query, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("meta"):
            try:
                d["meta"] = json.loads(d["meta"])
            except Exception:
                pass
        out.append(d)
    return out


def clear_logs(log_type: str | None = None) -> int:
    with get_conn() as conn:
        if log_type:
            cur = conn.execute("DELETE FROM logs WHERE type=?", (log_type,))
        else:
            cur = conn.execute("DELETE FROM logs")
        return cur.rowcount


# --------------------------------------------------------------------------
# Quiz helpers
# --------------------------------------------------------------------------
# A quiz row stores its questions + reward as JSON so the Admin can edit the
# whole structure freely (and CSV import/export the question bank) with no
# migrations. Shape:
#   questions = [
#     {"id": "q1", "text": "...", "type": "single"|"multi",
#      "answers": [{"id":"a1","text":"...","correct":true}, ...]}
#   ]
#   reward = {"type": "prints"|"ai_enhance"|"image"|"voucher"|"wheel", ...}
def _quiz_row(row: dict[str, Any]) -> dict[str, Any]:
    d = dict(row)
    for k in ("questions", "reward"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else ([] if k == "questions" else {})
        except Exception:
            d[k] = [] if k == "questions" else {}
    d["is_active"] = bool(d.get("is_active"))
    return d


def list_quizzes() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM quizzes ORDER BY created_at DESC").fetchall()
    return [_quiz_row(dict(r)) for r in rows]


def get_quiz(quiz_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    return _quiz_row(dict(row)) if row else None


def get_active_quiz() -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM quizzes WHERE is_active=1 ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return _quiz_row(dict(row)) if row else None


def create_quiz(title: str, description: str = "", pass_score: int = 70,
                questions: list | None = None, reward: dict | None = None) -> int:
    now = _utcnow()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO quizzes(title, description, pass_score, is_active,
                                   questions, reward, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (title, description, int(pass_score), 0,
             json.dumps(questions or []), json.dumps(reward or {}), now, now),
        )
        return int(cur.lastrowid)


def update_quiz(quiz_id: int, **fields: Any) -> None:
    if not fields:
        return
    for k in ("questions", "reward"):
        if k in fields and not isinstance(fields[k], str):
            fields[k] = json.dumps(fields[k])
    fields["updated_at"] = _utcnow()
    cols = ", ".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(f"UPDATE quizzes SET {cols} WHERE id=?", (*fields.values(), quiz_id))


def delete_quiz(quiz_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM quizzes WHERE id=?", (quiz_id,))


def set_active_quiz(quiz_id: int | None) -> None:
    """Mark a single quiz active (or clear all when None)."""
    now = _utcnow()
    with get_conn() as conn:
        conn.execute("UPDATE quizzes SET is_active=0, updated_at=? WHERE is_active=1", (now,))
        if quiz_id is not None:
            conn.execute("UPDATE quizzes SET is_active=1, updated_at=? WHERE id=?", (now, quiz_id))
    set_setting("active_quiz_id", quiz_id)
