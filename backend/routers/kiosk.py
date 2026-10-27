"""Closing the kiosk browser from the kiosk itself.

A web page can't close a Chromium started with --kiosk, and this backend runs
as the locked-down `pixel` service user, which can't kill the desktop user's
browser. So POST /exit only *asks*, two ways:

  1. Touches DATA_DIR/kiosk-close. On the Pi, the root-owned systemd path
     unit deploy/pixel-kiosk-close.path watches it and runs
     `pkill -f 'chrom.*--kiosk'` (pixel-kiosk-close.service) - works however
     Chromium was started.
  2. Bumps `requested_at`, which deploy/pixel-kiosk.sh (the desktop launcher)
     polls - covers running from source, where the units aren't installed.

`requested_at` is in-memory on purpose: a backend restart resets it, so it
can never close a freshly started kiosk by mistake.
"""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException, Request

import config

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])
log = logging.getLogger("pixel.kiosk")

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
CLOSE_FLAG = config.DATA_DIR / "kiosk-close"

_exit_requested_at = 0.0


@router.get("/exit")
async def exit_status():
    """Polled by the launcher. `requested_at` is epoch seconds (0 = never)."""
    return {"requested_at": _exit_requested_at}


@router.post("/exit")
async def request_exit(request: Request):
    """Close the kiosk browser. Only the screen on this device may do it -
    nobody else on the network can shut the kiosk."""
    global _exit_requested_at
    host = request.client.host if request.client else ""
    if host not in _LOOPBACK:
        raise HTTPException(status_code=403, detail="Only the kiosk screen on this device can close it.")
    _exit_requested_at = time.time()
    try:
        CLOSE_FLAG.write_text(f"{_exit_requested_at}\n")
    except OSError as e:  # launcher path still works
        log.warning("could not write %s: %s", CLOSE_FLAG, e)
    return {"ok": True}
