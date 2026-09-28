"""Soft save + share (email / WhatsApp) endpoints. Logic lives in sharing.py,
mailer.py and whatsapp.py."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageDraw

import config
import database as db
import mailer
import sharing
from schemas import ShareEmail, ShareSave, ShareWhatsApp, WhatsAppTest
from security import require_admin, require_admin_or_query
from whatsapp import WhatsAppError, normalize_phone, service as wa

router = APIRouter(prefix="/api/share", tags=["share"])


# --------------------------------------------------------------------------
# Kiosk (public)
# --------------------------------------------------------------------------
@router.get("/options")
async def options():
    """What the capture modal may offer right now (live service checks)."""
    return sharing.kiosk_options()


def _guard_enabled() -> None:
    if not db.get_setting("soft_save_enabled", False):
        raise HTTPException(status_code=403, detail="Saving photos is turned off.")


@router.post("/save")
async def save(payload: ShareSave):
    _guard_enabled()
    try:
        return sharing.save_capture(payload.capture_id)
    except sharing.ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/email")
async def email(payload: ShareEmail):
    _guard_enabled()
    try:
        return await sharing.send_email(payload.capture_id, payload.email)
    except sharing.ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/whatsapp")
async def whatsapp(payload: ShareWhatsApp):
    _guard_enabled()
    try:
        return await sharing.send_whatsapp(payload.capture_id, payload.phone)
    except sharing.ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/whatsapp/code")
async def whatsapp_code(payload: ShareSave):
    """'qr' mode: one-time code + wa.me QR. The guest sends the code to the
    booth's WhatsApp and gets the photo back."""
    _guard_enabled()
    try:
        return sharing.create_wa_code(payload.capture_id)
    except sharing.ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/whatsapp/code/{code}")
async def whatsapp_code_status(code: str):
    """Polled by the kiosk: how many phones got the photo, and any failure."""
    return sharing.code_status(code.upper())


@router.post("/whatsapp/code/{code}/retry")
async def whatsapp_code_retry(code: str):
    _guard_enabled()
    try:
        return sharing.retry_code(code.upper())
    except sharing.ShareError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------------------------------------------------------
# Admin: service status (drives the enable/disable state of the checkboxes)
# --------------------------------------------------------------------------
@router.get("/status")
async def status(_: bool = Depends(require_admin)):
    return {
        "email": {"configured": mailer.is_configured(), "verified": mailer.is_ready()},
        "whatsapp": wa.status(),
        "photos_dir": str(config.PHOTOS_DIR),
    }


@router.post("/email/test")
async def email_test(_: bool = Depends(require_admin)):
    """Real SMTP connect + login. Sets smtp_verified on success."""
    try:
        await asyncio.to_thread(mailer.verify)
    except mailer.MailError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "verified": True}


# --------------------------------------------------------------------------
# Admin: WhatsApp linked device
# --------------------------------------------------------------------------
@router.get("/whatsapp/status")
async def wa_status(_: bool = Depends(require_admin)):
    return wa.status()


@router.post("/whatsapp/start")
async def wa_start(_: bool = Depends(require_admin)):
    if not wa.available:
        raise HTTPException(status_code=400,
                            detail="WhatsApp support isn't installed (pip install neonize).")
    db.set_setting("whatsapp_enabled", True)
    wa.start()
    return wa.status()


@router.post("/whatsapp/stop")
async def wa_stop(_: bool = Depends(require_admin)):
    db.set_setting("whatsapp_enabled", False)
    wa.stop()
    return wa.status()


@router.post("/whatsapp/logout")
async def wa_logout(_: bool = Depends(require_admin)):
    db.set_setting("whatsapp_enabled", False)
    await asyncio.to_thread(wa.logout)
    return wa.status()


@router.post("/whatsapp/test")
async def wa_test(payload: WhatsAppTest, _: bool = Depends(require_admin)):
    """Send a small test image - use the operator's own number."""
    try:
        digits = normalize_phone(payload.phone, str(db.get_setting("whatsapp_default_country_code", "") or ""))
        img = Image.new("RGB", (800, 500), (7, 11, 22))
        ImageDraw.Draw(img).text((40, 230), "Pixel WhatsApp test - it works!", fill=(249, 115, 22))
        path = config.CAPTURES_DIR / "whatsapp-test.jpg"
        img.save(path, format="JPEG")
        await asyncio.to_thread(wa.send_image, digits, path, "Pixel test message ✅")
    except WhatsAppError as e:
        raise HTTPException(status_code=400, detail=str(e))
    db.add_log("share", message=f"WhatsApp test sent to {digits}", response="sent",
               meta={"channel": "whatsapp-test", "to": digits, "ok": True})
    return {"ok": True}


# --------------------------------------------------------------------------
# Admin: browse saved photos
# --------------------------------------------------------------------------
@router.get("/photos")
async def photos(day: str | None = None, _: bool = Depends(require_admin)):
    return sharing.list_photos(day)


@router.get("/photos/file/{rel:path}")
async def photo_file(rel: str, _: bool = Depends(require_admin_or_query)):
    try:
        return FileResponse(sharing.resolve_photo(rel))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Photo not found")
