"""
whatsapp.py - send photos over WhatsApp as a *linked device*.

Python equivalent of whatsapp-web.js: `neonize` wraps whatsmeow (Go), which
speaks the same multi-device protocol WhatsApp Web uses. You pair once by
scanning a QR code (WhatsApp -> Linked devices), exactly like wwebjs - but
there is no headless Chromium, which matters a lot on a Pi.

Incoming messages are read for ONE purpose: spotting a photo code (see
sharing.py 'qr' mode). They are filtered to 1:1 text from other people and
handed to `on_text`; nothing here ever replies on its own.

Optional, like cv2/pycups: without neonize installed the service reports
`unavailable` and the kiosk simply never offers WhatsApp.

Threading: neonize's client.connect() blocks for the life of the connection,
so it runs in a daemon thread. Callbacks fire on neonize's threads and only
touch plain attributes. Sends are blocking calls; sharing.py runs them via
asyncio.to_thread and serialises them behind its rate limiter.

The neonize API has moved between releases, so every call into it lives in
this file - version drift is a one-file fix.
"""
from __future__ import annotations

import logging
import random
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import config

log = logging.getLogger("pixel.whatsapp")

try:  # optional native dependency (bundles a Go shared library)
    from neonize.client import NewClient
    from neonize.utils import build_jid

    try:
        from neonize.events import ConnectedEv, LoggedOutEv, MessageEv, PairStatusEv
    except Exception:  # pragma: no cover - older/newer layouts
        ConnectedEv = LoggedOutEv = MessageEv = PairStatusEv = None  # type: ignore
    try:
        from neonize.utils.enum import ChatPresence, ChatPresenceMedia
    except Exception:  # pragma: no cover
        ChatPresence = ChatPresenceMedia = None  # type: ignore
    NEONIZE_AVAILABLE = True
except Exception:  # pragma: no cover - not installed (e.g. 32-bit dev box)
    NEONIZE_AVAILABLE = False

try:  # QR -> SVG for the Admin pairing screen (pure Python, tiny)
    import segno

    _SEGNO = True
except Exception:  # pragma: no cover
    _SEGNO = False

SESSION_PATH = config.WHATSAPP_DIR / "session.sqlite3"


class WhatsAppError(Exception):
    """Guest-safe message describing why a send failed."""


def svg_qr(data: str, scale: int = 6) -> str | None:
    """Any string -> QR as an SVG data URI (None without segno)."""
    if not data or not _SEGNO:
        return None
    try:
        return segno.make(data, error="m").svg_data_uri(scale=scale, border=2, dark="#0b1120")
    except Exception:
        return None


# Only 1:1 chats with a person. Groups, status updates, channels and
# broadcast lists are never answered.
_PERSON_SERVERS = {"s.whatsapp.net", "lid"}


def _message_text(msg: Any) -> str:
    """Plain text of an incoming message, '' for media/stickers/etc."""
    m = getattr(msg, "Message", None)
    if m is None:
        return ""
    text = getattr(m, "conversation", "") or ""
    if not text:
        ext = getattr(m, "extendedTextMessage", None)
        text = getattr(ext, "text", "") or "" if ext is not None else ""
    return text


def normalize_phone(raw: str, default_cc: str = "") -> str:
    """'+20 10-1234 5678' / '0020…' / '010…' (+ default cc '20') -> '201012345678'."""
    digits = re.sub(r"\D", "", raw or "")
    if (raw or "").strip().startswith("00"):
        digits = digits[2:]
    elif not (raw or "").strip().startswith("+") and digits.startswith("0") and default_cc:
        digits = re.sub(r"\D", "", default_cc) + digits[1:]
    if not 8 <= len(digits) <= 15:
        raise WhatsAppError("That doesn't look like a full phone number. "
                            "Include the country code, e.g. +20…")
    return digits


class WhatsAppService:
    def __init__(self) -> None:
        self._client: Any = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.state = "unavailable" if not NEONIZE_AVAILABLE else "stopped"
        self.qr: str | None = None
        self.error: str | None = None
        self.me: str | None = None
        # Set by sharing.bind_loop: (text, chat_jid, sender_key) -> None.
        # The ONLY thing incoming messages are used for is spotting photo codes.
        self.on_text: Any = None

    # ---------------------------------------------------------------- state
    @property
    def available(self) -> bool:
        return NEONIZE_AVAILABLE

    @property
    def connected(self) -> bool:
        if self.state != "connected" or self._client is None:
            return False
        try:
            return bool(self._client.is_connected)
        except Exception:
            return True  # property missing in this version; trust our state

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,           # unavailable|stopped|starting|pairing|connected|error
            "connected": self.connected,
            "me": self.me,
            "error": self.error,
            "qr": self.qr,
            "qr_svg": self._qr_svg(),
            "has_session": SESSION_PATH.exists(),
        }

    def _qr_svg(self) -> str | None:
        return svg_qr(self.qr) if self.qr else None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if not NEONIZE_AVAILABLE:
            self.state = "unavailable"
            return
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self.state, self.error, self.qr = "starting", None, None
            self._thread = threading.Thread(target=self._run, name="whatsapp", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            client = NewClient(str(SESSION_PATH))
            self._client = client

            def on_qr(_client: Any, data: bytes) -> None:
                self.qr = data.decode() if isinstance(data, (bytes, bytearray)) else str(data)
                self.state = "pairing"

            client.qr(on_qr)

            if ConnectedEv is not None:
                @client.event(ConnectedEv)
                def _on_connected(c: Any, _ev: Any) -> None:
                    self.state, self.qr, self.error = "connected", None, None
                    self.me = self._own_number(c)
                    log.info("WhatsApp connected as %s", self.me)

            if PairStatusEv is not None:
                @client.event(PairStatusEv)
                def _on_pair(_c: Any, _ev: Any) -> None:
                    self.qr = None  # scanned; ConnectedEv follows

            if MessageEv is not None:
                @client.event(MessageEv)
                def _on_message(_c: Any, ev: Any) -> None:
                    self._handle_incoming(ev)

            if LoggedOutEv is not None:
                @client.event(LoggedOutEv)
                def _on_logout(_c: Any, _ev: Any) -> None:
                    self.state, self.me, self.qr = "stopped", None, None
                    self.error = "Logged out from the phone. Link the device again."

            client.connect()  # blocks until disconnected
            if self.state not in ("error",):
                self.state = "stopped"
        except Exception as e:  # pragma: no cover - depends on live service
            log.exception("WhatsApp client crashed")
            self.state, self.error = "error", str(e)
        finally:
            self._client = None

    def _handle_incoming(self, ev: Any) -> None:
        """Filter hard, then hand plain text from a person to on_text.

        Never replies here - sharing.py decides, and it only ever answers a
        valid, unexpired photo code with that photo."""
        try:
            src = ev.Info.MessageSource
            if getattr(src, "IsFromMe", False) or getattr(src, "IsGroup", False):
                return
            chat = src.Chat
            if getattr(chat, "Server", "") not in _PERSON_SERVERS:
                return
            text = _message_text(ev)
            if not text or len(text) > 500 or self.on_text is None:
                return
            sender = src.Sender if getattr(src, "Sender", None) is not None else chat
            key = f"{getattr(sender, 'User', '')}@{getattr(sender, 'Server', '')}"
            self.on_text(text, chat, key)
        except Exception:  # never let a weird message kill the client thread
            log.debug("ignored unparseable incoming message", exc_info=True)

    @staticmethod
    def _own_number(client: Any) -> str | None:
        try:
            me = client.get_me()
            jid = getattr(me, "JID", me)
            return str(getattr(jid, "User", "")) or None
        except Exception:
            return None

    def stop(self) -> None:
        client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
        if self.state != "unavailable":
            self.state, self.qr = "stopped", None

    def logout(self) -> None:
        """Unlink this device and wipe the session so a fresh QR can be scanned."""
        client = self._client
        if client is not None:
            try:
                client.logout()
            except Exception as e:
                log.warning("logout failed: %s", e)
        self.stop()
        if self._thread:
            self._thread.join(timeout=5)
        for p in config.WHATSAPP_DIR.glob("session.sqlite3*"):  # incl. -wal/-shm
            try:
                p.unlink()
            except OSError:
                shutil.rmtree(p, ignore_errors=True)
        self.me, self.error = None, None

    # ---------------------------------------------------------------- sends
    def send_image(self, digits: str, image: Path, caption: str, *,
                   verify: bool = True, typing: bool = True) -> None:
        """Blocking. Send to a typed number (already normalized)."""
        client = self._require_client()
        try:
            jid = build_jid(digits)
            if verify:
                found = client.is_on_whatsapp(f"+{digits}")
                hit = found[0] if found else None
                if not hit or not getattr(hit, "IsIn", False):
                    raise WhatsAppError("That number isn't on WhatsApp. Check it and try again.")
                jid = getattr(hit, "JID", None) or jid
        except WhatsAppError:
            raise
        except Exception as e:  # pragma: no cover - depends on live service
            raise WhatsAppError(f"WhatsApp send failed: {e}") from e
        self.reply_image(jid, image, caption, typing=typing)

    def reply_image(self, jid: Any, image: Path, caption: str, *, typing: bool = True) -> None:
        """Blocking. Send to a chat JID - used to answer a guest's photo code."""
        client = self._require_client()
        try:
            if typing and ChatPresence is not None:
                try:
                    client.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_COMPOSING,
                                              ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
                    time.sleep(random.uniform(1.2, 2.8))
                    client.send_chat_presence(jid, ChatPresence.CHAT_PRESENCE_PAUSED,
                                              ChatPresenceMedia.CHAT_PRESENCE_MEDIA_TEXT)
                except Exception:
                    pass  # cosmetic only
            client.send_image(jid, image.read_bytes(), caption=caption)
        except Exception as e:  # pragma: no cover - depends on live service
            raise WhatsAppError(f"WhatsApp send failed: {e}") from e

    def _require_client(self) -> Any:
        client = self._client
        if client is None or not self.connected:
            raise WhatsAppError("WhatsApp is not connected right now.")
        return client


service = WhatsAppService()
