"""
sharing.py - "soft save" a capture to disk and deliver it by email/WhatsApp.

Saved photos go to config.PHOTOS_DIR as

    <PB_PHOTOS_DIR>/2026-09-28/2026-09-28_14-03-22.jpg
    <PB_PHOTOS_DIR>/2026-09-28/2026-09-28_14-03-22_ai.jpg   (AI-enhanced version)

local time, flattened JPEG with the frame overlay burned in (same look as the
print). A capture is saved once per version: saving again returns the same
file, while enhancing afterwards produces a new "_ai" file.

Every delivery attempt is logged as type "share" - the WhatsApp quotas are
counted from those rows, so they survive a restart.
"""
from __future__ import annotations

import asyncio
import random
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from PIL import Image

import config
import database as db
import image_processor
import mailer
from whatsapp import WhatsAppError, normalize_phone, service as wa, svg_qr

# (capture_id, variant) -> saved path. In-memory: a capture only lives for
# one kiosk session, and after a restart a re-save just writes a new file.
_saved: dict[tuple[str, str], Path] = {}


class ShareError(Exception):
    """Guest-safe failure message (kiosk shows it with a Retry button)."""


# --------------------------------------------------------------------------
# Status (what the kiosk may offer right now)
# --------------------------------------------------------------------------
def kiosk_options() -> dict[str, Any]:
    enabled = bool(db.get_setting("soft_save_enabled", False))
    return {
        "soft_save": enabled,
        "auto_save": enabled and bool(db.get_setting("soft_save_auto", False)),
        # Checkbox AND a live, verified service - never offer a dead option.
        "email": enabled and bool(db.get_setting("soft_save_email", False)) and mailer.is_ready(),
        "whatsapp": enabled and bool(db.get_setting("soft_save_whatsapp", False)) and wa.connected,
        "whatsapp_mode": _wa_mode(),
    }


def _wa_mode() -> str:
    mode = str(db.get_setting("whatsapp_share_mode", "qr") or "qr")
    return mode if mode in ("qr", "number", "both") else "qr"


# --------------------------------------------------------------------------
# Save
# --------------------------------------------------------------------------
def save_capture(capture_id: str) -> dict[str, Any]:
    """Write the best version of a capture to the photos folder (idempotent)."""
    if not (config.CAPTURES_DIR / f"{capture_id}_raw.png").exists():
        raise ShareError("That photo is no longer available. Please take it again.")
    enhanced = (config.CAPTURES_DIR / f"{capture_id}_enhanced.png").exists()
    variant = "enhanced" if enhanced else "raw"

    cached = _saved.get((capture_id, variant))
    if cached and cached.exists():
        return _describe(cached)

    # apply_frame composites the admin frame (if any) over enhanced-or-raw.
    image_processor.apply_frame(capture_id, use_enhanced=enhanced)
    src = config.CAPTURES_DIR / f"{capture_id}_framed.png"
    img = Image.open(src)
    if img.mode in ("RGBA", "P"):
        rgba = img.convert("RGBA")
        img = Image.new("RGB", rgba.size, (255, 255, 255))
        img.paste(rgba, mask=rgba.split()[-1])
    else:
        img = img.convert("RGB")

    now = datetime.now()  # local time: the operator browses by their own clock
    folder = config.PHOTOS_DIR / now.strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    stem = now.strftime("%Y-%m-%d_%H-%M-%S") + ("_ai" if enhanced else "")
    dest, n = folder / f"{stem}.jpg", 2
    while dest.exists():
        dest, n = folder / f"{stem}_{n}.jpg", n + 1
    img.save(dest, format="JPEG", quality=92)

    _saved[(capture_id, variant)] = dest
    db.add_log("share", message="Photo saved", response=str(dest.relative_to(config.PHOTOS_DIR)),
               meta={"channel": "save", "capture_id": capture_id, "ok": True})
    return _describe(dest)


def _describe(path: Path) -> dict[str, Any]:
    rel = path.relative_to(config.PHOTOS_DIR).as_posix()
    return {"ok": True, "file": rel, "name": path.name}


# --------------------------------------------------------------------------
# Email
# --------------------------------------------------------------------------
async def send_email(capture_id: str, email: str) -> dict[str, Any]:
    email = (email or "").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ShareError("Please enter a valid email address.")
    if not kiosk_options()["email"]:
        raise ShareError("Email sending is not available right now.")
    saved = save_capture(capture_id)
    path = config.PHOTOS_DIR / saved["file"]
    subject = db.get_setting("share_email_subject", "") or "Your photo"
    body = db.get_setting("share_email_body", "") or "Here's your photo!"
    try:
        await asyncio.to_thread(mailer.send, email, subject, body, [path])
    except mailer.MailError as e:
        _log_send("email", email, capture_id, False, str(e))
        raise ShareError(str(e)) from e
    _log_send("email", email, capture_id, True)
    return {"ok": True, "channel": "email", **saved}


# --------------------------------------------------------------------------
# WhatsApp (rate-limited so the number doesn't get flagged)
# --------------------------------------------------------------------------
_wa_lock = asyncio.Lock()
_wa_last_sent = 0.0


def _int(key: str, default: int) -> int:
    try:
        return max(0, int(db.get_setting(key, default)))
    except (TypeError, ValueError):
        return default


def _check_quotas(digits: str) -> None:
    now = datetime.now(timezone.utc)
    ok = ['"channel": "whatsapp"', '"ok": true']
    per_hour = _int("whatsapp_max_per_hour", 40)
    per_day = _int("whatsapp_max_per_day", 200)
    per_rcpt = _int("whatsapp_max_per_recipient_day", 3)
    if per_hour and db.count_logs("share", now - timedelta(hours=1), ok) >= per_hour:
        raise ShareError("WhatsApp is busy right now. Please try again in a few minutes, "
                         "or use email.")
    if per_day and db.count_logs("share", now - timedelta(days=1), ok) >= per_day:
        raise ShareError("WhatsApp sending has reached today's limit. Please use email.")
    if per_rcpt and db.count_logs("share", now - timedelta(days=1),
                                  ok + [f'"to": "{digits}"']) >= per_rcpt:
        raise ShareError("We've already sent a few photos to this number today.")


def _caption() -> str:
    captions = [c.strip() for c in str(db.get_setting("whatsapp_captions", "") or "").splitlines()
                if c.strip()]
    return random.choice(captions) if captions else ""


async def _rate_limited(fn: Any, *args: Any, **kwargs: Any) -> None:
    """Run a blocking WhatsApp send: one at a time, spaced out with jitter."""
    global _wa_last_sent
    async with _wa_lock:
        gap = _int("whatsapp_min_interval_s", 8) + random.uniform(0, 4)
        wait = _wa_last_sent + gap - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            await asyncio.to_thread(fn, *args, **kwargs)
        finally:
            _wa_last_sent = time.monotonic()


async def send_whatsapp(capture_id: str, phone: str) -> dict[str, Any]:
    """'number' mode: the guest typed their number on the kiosk."""
    if not kiosk_options()["whatsapp"] or _wa_mode() == "qr":
        raise ShareError("WhatsApp sending is not available right now.")
    try:
        digits = normalize_phone(phone, str(db.get_setting("whatsapp_default_country_code", "") or ""))
    except WhatsAppError as e:
        raise ShareError(str(e)) from e
    _check_quotas(digits)
    saved = save_capture(capture_id)
    path = config.PHOTOS_DIR / saved["file"]
    try:
        await _rate_limited(
            wa.send_image, digits, path, _caption(),
            verify=bool(db.get_setting("whatsapp_verify_number", True)),
            typing=bool(db.get_setting("whatsapp_typing_indicator", True)),
        )
    except WhatsAppError as e:
        _log_send("whatsapp", digits, capture_id, False, str(e))
        raise ShareError(str(e)) from e
    _log_send("whatsapp", digits, capture_id, True)
    return {"ok": True, "channel": "whatsapp", **saved}


# --------------------------------------------------------------------------
# WhatsApp 'qr' mode: the guest messages US a one-time code, we reply with
# the photo. The bot NEVER sends anything else: no greeting, no "expired",
# no "unknown code" - a message without a live code gets total silence, so
# there is nothing to abuse or probe.
#
# All state lives on the event loop thread: incoming messages arrive on
# neonize's thread and are handed over with run_coroutine_threadsafe.
# --------------------------------------------------------------------------
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I look-alikes
_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{5})(?![A-Z0-9])")


@dataclass
class _PhotoCode:
    capture_id: str
    expires: float                                          # time.monotonic()
    served: set[str] = field(default_factory=set)           # sender keys sent to
    inflight: set[str] = field(default_factory=set)
    failed: dict[str, Any] = field(default_factory=dict)    # sender key -> chat JID
    last_error: str | None = None


_codes: dict[str, _PhotoCode] = {}
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called at startup: route incoming WhatsApp text into the code matcher."""
    global _loop
    _loop = loop
    wa.on_text = _on_incoming_text


def _prune() -> None:
    now = time.monotonic()
    for code in [c for c, e in _codes.items() if e.expires <= now and not e.inflight]:
        del _codes[code]


def _booth_number() -> str:
    override = "".join(ch for ch in str(db.get_setting("whatsapp_booth_number", "") or "") if ch.isdigit())
    return override or (wa.me or "")


def create_wa_code(capture_id: str) -> dict[str, Any]:
    """Issue (or reuse) the code + wa.me QR for a capture. Timer starts now."""
    if not kiosk_options()["whatsapp"] or _wa_mode() == "number":
        raise ShareError("WhatsApp sending is not available right now.")
    if not (config.CAPTURES_DIR / f"{capture_id}_raw.png").exists():
        raise ShareError("That photo is no longer available. Please take it again.")
    booth = _booth_number()
    if not booth:
        raise ShareError("WhatsApp is not ready yet. Please try again in a moment.")
    _prune()

    now = time.monotonic()
    ttl = max(60, _int("whatsapp_code_ttl_s", 300))
    # Reopening the panel keeps the same code (a friend may already have
    # scanned it) unless it's about to run out.
    code = next((c for c, e in _codes.items()
                 if e.capture_id == capture_id and e.expires - now > 60), None)
    if code is None:
        while True:
            code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(5))
            if code not in _codes:
                break
        _codes[code] = _PhotoCode(capture_id=capture_id, expires=now + ttl)

    template = str(db.get_setting("whatsapp_prefill_text", "") or "My photo code: {code}")
    text = template.replace("{code}", code) if "{code}" in template else f"{template} {code}"
    link = f"https://wa.me/{booth}?text={quote(text)}"
    return {"code": code, "link": link, "qr_svg": svg_qr(link, scale=8), **code_status(code)}


def code_status(code: str) -> dict[str, Any]:
    entry = _codes.get(code)
    if entry is None:
        return {"valid": False, "expires_in": 0, "sent": 0, "sending": 0, "failed": 0, "error": None}
    left = max(0, round(entry.expires - time.monotonic()))
    return {
        "valid": left > 0,
        "expires_in": left,
        "sent": len(entry.served),
        "sending": len(entry.inflight),
        "failed": len(entry.failed),
        "error": entry.last_error if entry.failed else None,
    }


def _on_incoming_text(text: str, chat: Any, sender_key: str) -> None:
    """neonize thread -> event loop. Cheap pre-filter so random chatter never
    even schedules work."""
    if _loop is None or not _CODE_RE.search(text.upper()):
        return
    asyncio.run_coroutine_threadsafe(_handle_code_message(text, chat, sender_key), _loop)


async def _handle_code_message(text: str, chat: Any, sender_key: str) -> None:
    now = time.monotonic()
    for code in _CODE_RE.findall(text.upper()):
        entry = _codes.get(code)
        if entry and entry.expires > now:
            break
    else:
        return  # no live code: stay silent
    if sender_key in entry.served or sender_key in entry.inflight:
        return  # already got it / on its way - don't double-send
    if len(entry.served) + len(entry.inflight) >= max(1, _int("whatsapp_code_max_senders", 10)):
        return
    if not kiosk_options()["whatsapp"]:
        return  # admin switched WhatsApp off since the QR was shown
    await _deliver_code(code, entry, chat, sender_key)


async def _deliver_code(code: str, entry: _PhotoCode, chat: Any, sender_key: str) -> None:
    recipient = sender_key.split("@")[0]
    entry.inflight.add(sender_key)
    try:
        _check_quotas(recipient)
        saved = save_capture(entry.capture_id)  # current version, incl. AI enhance
        await _rate_limited(wa.reply_image, chat, config.PHOTOS_DIR / saved["file"], _caption(),
                            typing=bool(db.get_setting("whatsapp_typing_indicator", True)))
    except (ShareError, WhatsAppError) as e:
        entry.failed[sender_key] = chat
        entry.last_error = str(e)
        _log_send("whatsapp", recipient, entry.capture_id, False, f"{e} (code {code})")
    else:
        entry.served.add(sender_key)
        entry.failed.pop(sender_key, None)
        _log_send("whatsapp", recipient, entry.capture_id, True)
    finally:
        entry.inflight.discard(sender_key)


def retry_code(code: str) -> dict[str, Any]:
    """Kiosk Retry: resend to every phone whose delivery failed for this code."""
    entry = _codes.get(code)
    if entry is None or entry.expires <= time.monotonic():
        raise ShareError("This code has expired. Tap WhatsApp it again for a new one.")
    for key, chat in list(entry.failed.items()):
        if key not in entry.inflight:
            entry.failed.pop(key, None)
            entry.inflight.add(key)  # show "sending" immediately, before the task runs
            task = asyncio.get_running_loop().create_task(_redeliver(code, entry, chat, key))
            _tasks.add(task)
            task.add_done_callback(_tasks.discard)
    return code_status(code)


_tasks: set[asyncio.Task] = set()


async def _redeliver(code: str, entry: _PhotoCode, chat: Any, key: str) -> None:
    entry.inflight.discard(key)
    await _deliver_code(code, entry, chat, key)


def _log_send(channel: str, to: str, capture_id: str, ok: bool, error: str | None = None) -> None:
    db.add_log("share", message=f"Photo sent by {channel} to {to}" if ok
               else f"{channel} send to {to} failed",
               response="sent" if ok else error,
               meta={"channel": channel, "to": to, "capture_id": capture_id, "ok": ok})


# --------------------------------------------------------------------------
# Admin: browse the photos folder
# --------------------------------------------------------------------------
def list_photos(day: str | None = None) -> dict[str, Any]:
    days = sorted((p.name for p in config.PHOTOS_DIR.iterdir() if p.is_dir()), reverse=True)
    day = day if day in days else (days[0] if days else None)
    files: list[dict[str, Any]] = []
    if day:
        for p in sorted((config.PHOTOS_DIR / day).glob("*.jpg"), reverse=True):
            files.append({"file": f"{day}/{p.name}", "name": p.name, "size": p.stat().st_size})
    return {"folder": str(config.PHOTOS_DIR), "days": days, "day": day, "photos": files}


def resolve_photo(rel: str) -> Path:
    """Map a 'date/name.jpg' path to disk, refusing anything outside the folder."""
    root = config.PHOTOS_DIR.resolve()
    target = (root / rel).resolve()
    if root not in target.parents or not target.is_file():
        raise FileNotFoundError(rel)
    return target
