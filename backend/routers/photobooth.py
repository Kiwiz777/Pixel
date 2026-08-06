"""Kiosk-facing photobooth endpoints: capture, enhance, frame, print, upload frame."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import ai_brain
import database as db
import image_processor
import printer as printer_service
from schemas import EnhanceRequest, FrameRequest, PrintRequest
from security import require_admin

router = APIRouter(prefix="/api/photobooth", tags=["photobooth"])


@router.post("/capture")
async def capture(frame: UploadFile | None = File(None)):
    """
    Triggered by the Kiosk 'Capture Photo' button.

    If the kiosk sends a `frame` (browser getUserMedia -> canvas blob), we store
    that. Otherwise we grab from the server-side camera (OpenCV on the Pi).
    """
    if frame is not None:
        data = await frame.read()
        return image_processor.capture_from_bytes(data)
    return image_processor.capture()


# --------------------------------------------------------------------------
# Kiosk background media (admin upload, kiosk reads via /api/settings/public)
# --------------------------------------------------------------------------
@router.get("/backgrounds")
async def list_backgrounds(_: bool = Depends(require_admin)):
    return {"media": image_processor.list_background_media()}


@router.post("/backgrounds")
async def upload_background(file: UploadFile = File(...), _: bool = Depends(require_admin)):
    data = await file.read()
    try:
        item = image_processor.save_background_media(file.filename or "bg", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "item": item}


@router.delete("/backgrounds/{file}")
async def delete_background(file: str, _: bool = Depends(require_admin)):
    image_processor.delete_background_media(file)
    return {"ok": True, "media": image_processor.list_background_media()}


@router.post("/enhance")
async def enhance(payload: EnhanceRequest):
    try:
        return await image_processor.enhance(
            payload.capture_id, prompt=payload.prompt, user_id=payload.user_id
        )
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/frame")
async def frame(payload: FrameRequest):
    try:
        return image_processor.apply_frame(payload.capture_id, use_enhanced=payload.use_enhanced)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/print")
async def print_capture(payload: PrintRequest):
    try:
        path = image_processor.prepare_print(payload.capture_id)
        return printer_service.print_file(path, printer=payload.printer, copies=payload.copies)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/frame-overlay")
async def upload_frame_overlay(file: UploadFile = File(...), _: bool = Depends(require_admin)):
    """Admin: upload the transparent PNG frame used for compositing."""
    data = await file.read()
    try:
        url = image_processor.save_frame_overlay(file.filename or "frame.png", data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")
    return {"ok": True, "frame_url": url}
