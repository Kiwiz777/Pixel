"""
mailer.py - the one SMTP service (voucher emails + photo delivery).

Settings come from the `settings` table (Admin -> Save & Share -> Email
service), read per call so edits apply without a restart.

"Connected" for email means `smtp_verified`: set by verify() after a real
login succeeds, and cleared by database.update_settings whenever an smtp_*
value changes. The kiosk only offers "Email it" while it is True.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from pathlib import Path

import database as db


class MailError(Exception):
    """SMTP not configured, or the server refused us. Message is guest-safe."""


def is_configured() -> bool:
    return bool(db.get_setting("smtp_host", ""))


def is_ready() -> bool:
    """Configured AND the last connection test passed."""
    return is_configured() and bool(db.get_setting("smtp_verified", False))


def _open() -> smtplib.SMTP:
    host = db.get_setting("smtp_host", "")
    if not host:
        raise MailError("Email service is not configured.")
    port = int(db.get_setting("smtp_port", 587) or 587)
    user = db.get_setting("smtp_user", "")
    password = db.get_setting("smtp_password", "") or ""
    # 465 is implicit TLS (SMTPS); anything else upgrades with STARTTLS.
    if port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
        if bool(db.get_setting("smtp_tls", True)):
            server.starttls()
    if user:
        server.login(user, password)
    return server


def verify() -> None:
    """Connect + log in, then record the result. Raises MailError on failure."""
    try:
        server = _open()
        server.quit()
    except MailError:
        db.set_setting("smtp_verified", False)
        raise
    except (smtplib.SMTPException, OSError) as e:
        db.set_setting("smtp_verified", False)
        raise MailError(f"Could not connect: {e}") from e
    db.set_setting("smtp_verified", True)


def send(to_addr: str, subject: str, body: str,
         attachments: list[Path] | None = None) -> None:
    """Send a plain-text email, optionally with image attachments."""
    user = db.get_setting("smtp_user", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = db.get_setting("smtp_from", "") or user
    msg["To"] = to_addr
    msg.set_content(body)
    for path in attachments or []:
        subtype = "png" if path.suffix.lower() == ".png" else "jpeg"
        msg.add_attachment(path.read_bytes(), maintype="image", subtype=subtype,
                           filename=path.name)
    try:
        with _open() as server:
            server.send_message(msg)
    except MailError:
        raise
    except smtplib.SMTPRecipientsRefused as e:
        raise MailError("That email address was rejected. Check it and try again.") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"Email could not be sent: {e}") from e
