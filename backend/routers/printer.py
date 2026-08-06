"""CUPS printer management endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import printer as printer_service
from schemas import DefaultPrinterRequest, PrintConfigUpdate
from security import require_admin

router = APIRouter(prefix="/api/printer", tags=["printer"])


@router.get("")
async def list_printers(_: bool = Depends(require_admin)):
    return {
        "backend": printer_service.backend_name(),
        "printers": printer_service.list_printers(),
        "config": printer_service.get_print_config(),
    }


@router.post("/default")
async def set_default(payload: DefaultPrinterRequest, _: bool = Depends(require_admin)):
    return printer_service.set_default_printer(payload.name)


@router.get("/media")
async def list_media(printer: str | None = None, _: bool = Depends(require_admin)):
    """Paper sizes the printer reports, for the Admin media dropdown."""
    return printer_service.list_media(printer)


@router.put("/config")
async def update_config(payload: PrintConfigUpdate, _: bool = Depends(require_admin)):
    return printer_service.update_print_config(
        copies=payload.copies, media=payload.media, color_mode=payload.color_mode,
        size_cm=payload.size_cm, orientation=payload.orientation,
        dpi=payload.dpi, fit=payload.fit,
    )


@router.post("/test")
async def test_print(_: bool = Depends(require_admin)):
    """
    Print an alignment target at the exact configured print geometry.

    Generated at the real target size (not a fixed 600x400) so the sheet that
    comes out proves orientation, scaling and margins are all correct: the
    border should sit just inside the paper edge on all four sides.
    """
    from pathlib import Path

    from PIL import Image, ImageDraw

    import config
    import image_processor

    w, h = image_processor.print_target_px()
    cfg = printer_service.get_print_config()

    img = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(img)
    inset = max(4, min(w, h) // 60)
    # Full-bleed border + corner ticks: if any edge is missing, the image is
    # being cropped or scaled by the printer.
    d.rectangle([inset, inset, w - inset - 1, h - inset - 1], outline=(0, 0, 0), width=max(2, inset // 4))
    arm = min(w, h) // 8
    for cx, cy, dx, dy in ((0, 0, 1, 1), (w, 0, -1, 1), (0, h, 1, -1), (w, h, -1, -1)):
        d.line([cx, cy, cx + dx * arm, cy], fill=(220, 40, 40), width=max(2, inset // 3))
        d.line([cx, cy, cx, cy + dy * arm], fill=(220, 40, 40), width=max(2, inset // 3))
    # Centre cross marks true centre - offset here means margins are uneven.
    d.line([w // 2, h // 2 - arm, w // 2, h // 2 + arm], fill=(40, 80, 220), width=max(2, inset // 4))
    d.line([w // 2 - arm, h // 2, w // 2 + arm, h // 2], fill=(40, 80, 220), width=max(2, inset // 4))

    label = (f"PhotoBooth alignment test\n{cfg['size_cm']} cm  {cfg['orientation']}\n"
             f"{w}x{h}px @ {cfg['dpi']} DPI\nmedia: {cfg['media']}")
    d.multiline_text((inset * 3, inset * 3), label, fill=(0, 0, 0), spacing=inset)

    test_path = Path(config.CAPTURES_DIR) / "_cups_test.jpg"
    dpi = max(72, int(cfg["dpi"] or 300))
    img.save(test_path, format="JPEG", quality=95, dpi=(dpi, dpi))
    try:
        return printer_service.print_file(test_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
