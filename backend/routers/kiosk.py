"""Closing the kiosk browser from the kiosk itself.

A web page can't close a Chromium started with --kiosk, and this backend runs
as the `pixel` service user, so it can't kill the desktop user's browser
either. Instead deploy/pixel-kiosk.sh (the launcher, running in the desktop
session) polls GET /api/kiosk/exit and closes Chromium when it sees a request
newer than its own start.

State is in-memory on purpose: a backend restart resets it to "no request",
so it can never close a freshly started kiosk by mistake.
"""
from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_LAUNCHER_STALE_S = 10.0  # launcher polls every ~2s

_exit_requested_at = 0.0
_launcher_seen_at = 0.0


def _launcher_running() -> bool:
    return time.time() - _launcher_seen_at < _LAUNCHER_STALE_S


@router.get("/exit")
async def exit_status():
    """Polled by the launcher. `requested_at` is epoch seconds (0 = never)."""
    global _launcher_seen_at
    _launcher_seen_at = time.time()
    return {"requested_at": _exit_requested_at}


@router.post("/exit")
async def request_exit(request: Request):
    """Ask the launcher to close the kiosk browser. Only the screen on this
    device may do it - nobody else on the network can shut the kiosk."""
    global _exit_requested_at
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK:
        raise HTTPException(status_code=403, detail="Only the kiosk screen on this device can close it.")
    if not _launcher_running():
        return {"ok": False, "launcher": False}
    _exit_requested_at = time.time()
    return {"ok": True, "launcher": True}
