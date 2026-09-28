"""
At-rest encryption for sensitive settings (API keys) and a lightweight
admin-auth dependency for FastAPI.

API keys are encrypted with Fernet (symmetric) using a key derived from
config.SECRET_KEY, so the SQLite file never stores plaintext keys.
"""
from __future__ import annotations

import base64
import hashlib

from fastapi import Header, HTTPException, Query, status

import config

try:
    from cryptography.fernet import Fernet, InvalidToken

    _CRYPTO_AVAILABLE = True
except Exception:  # pragma: no cover - cryptography should normally be present
    _CRYPTO_AVAILABLE = False
    InvalidToken = Exception  # type: ignore


def _fernet() -> "Fernet":
    # Derive a stable 32-byte urlsafe-base64 key from the secret.
    digest = hashlib.sha256(config.SECRET_KEY.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


# A short marker so we can tell encrypted blobs apart from legacy plaintext.
_ENC_PREFIX = "enc::"


def encrypt(value: str | None) -> str | None:
    """Encrypt a plaintext secret for storage. Returns None for falsy input."""
    if not value:
        return value
    if not _CRYPTO_AVAILABLE:
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return _ENC_PREFIX + token


def decrypt(value: str | None) -> str | None:
    """Decrypt a stored secret. Tolerates legacy/plaintext values."""
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        return value  # legacy plaintext, return as-is
    if not _CRYPTO_AVAILABLE:
        return None
    try:
        return _fernet().decrypt(value[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def mask(value: str | None) -> str:
    """Mask a secret for display in the Admin UI, e.g. 'sk-...â€¢â€¢â€¢â€¢f9a2'."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}****{value[-4:]}"


async def require_admin(authorization: str | None = Header(default=None)) -> bool:
    """
    FastAPI dependency that gates Admin endpoints behind a bearer token.

    Send `Authorization: Bearer <PB_ADMIN_TOKEN>`. Kept intentionally simple;
    swap for real sessions/JWT if this ever leaves the local network.
    """
    expected = f"Bearer {config.ADMIN_TOKEN}"
    if not authorization or authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return True


async def require_admin_or_query(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> bool:
    """Like require_admin, but also accepts `?token=` - for admin-only files
    loaded by <img>/<a download>, which can't send an Authorization header."""
    if token is not None and token == config.ADMIN_TOKEN:
        return True
    return await require_admin(authorization)
