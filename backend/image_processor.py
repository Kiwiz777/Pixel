"""
image_processor.py - photobooth image pipeline.

Flow
----
1. capture()        -> grab current camera frame, persist as a "raw" capture.
2. enhance()        -> send a capture to the active image provider (ai_brain)
                       using the Admin-defined "AI Enhance" prompt.
3. apply_frame()    -> composite the Admin-uploaded transparent PNG frame on
                       top of a photo with Pillow.
4. prepare_print()  -> produce the final flattened JPEG used for printing.

All photos live under config.CAPTURES_DIR and are referenced by id so the
Kiosk modal can show raw vs enhanced vs framed versions.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

import ai_brain
import config
import database as db
import vision


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _path(capture_id: str, suffix: str) -> Path:
    return config.CAPTURES_DIR / f"{capture_id}_{suffix}.png"


def _public_url(path: Path) -> str:
    """URL the frontend uses to load a capture (served by main.py static mount)."""
    return f"/media/captures/{path.name}"


# --------------------------------------------------------------------------
# 1. Capture
# --------------------------------------------------------------------------
def capture(user_id: int | None = None) -> dict[str, Any]:
    """Grab the current camera frame (server-side OpenCV) and store it."""
    jpeg = vision.camera.capture_photo()
    return _store_raw(jpeg, user_id=user_id, source="server")


def capture_from_bytes(data: bytes, user_id: int | None = None) -> dict[str, Any]:
    """
    Store a frame captured by the *browser* (getUserMedia -> canvas -> blob).

    This is the path used on dev laptops and on the Pi's Chromium kiosk, where
    the camera is reached through the browser rather than server-side OpenCV.
    """
    return _store_raw(data, user_id=user_id, source="client")


def _store_raw(data: bytes, *, user_id: int | None, source: str) -> dict[str, Any]:
    capture_id = _new_id()
    raw_path = _path(capture_id, "raw")
    image = Image.open(io.BytesIO(data)).convert("RGB")
    image.save(raw_path, format="PNG")
    db.add_log("capture", message="Photo captured", user_id=user_id,
               meta={"capture_id": capture_id, "path": str(raw_path), "source": source})
    return {
        "capture_id": capture_id,
        "raw_url": _public_url(raw_path),
        "width": image.width,
        "height": image.height,
    }


# --------------------------------------------------------------------------
# 2. AI Enhance
# --------------------------------------------------------------------------
async def enhance(capture_id: str, prompt: str | None = None,
                  user_id: int | None = None) -> dict[str, Any]:
    raw_path = _path(capture_id, "raw")
    if not raw_path.exists():
        raise FileNotFoundError(f"Capture '{capture_id}' not found.")

    prompt = prompt or db.get_setting(
        "ai_enhance_prompt", "Enhance this portrait."
    )
    src_bytes = raw_path.read_bytes()
    enhanced_bytes = await ai_brain.enhance_image(src_bytes, prompt, mime="image/png")

    enhanced_path = _path(capture_id, "enhanced")
    Image.open(io.BytesIO(enhanced_bytes)).convert("RGB").save(enhanced_path, format="PNG")
    db.add_log("enhance", message=prompt, response="AI enhance complete",
               user_id=user_id,
               meta={"capture_id": capture_id, "provider": db.get_setting("active_image_provider")})
    return {"capture_id": capture_id, "enhanced_url": _public_url(enhanced_path)}


# --------------------------------------------------------------------------
# 3. Frame overlay (Pillow)
# --------------------------------------------------------------------------
def apply_frame(capture_id: str, *, use_enhanced: bool = True) -> dict[str, Any]:
    """
    Composite the configured transparent PNG frame over the photo.

    The frame is scaled to the photo's dimensions and alpha-composited so the
    photo shows through the transparent centre.
    """
    base_path = _path(capture_id, "enhanced" if use_enhanced else "raw")
    if not base_path.exists():
        base_path = _path(capture_id, "raw")
    if not base_path.exists():
        raise FileNotFoundError(f"Capture '{capture_id}' not found.")

    photo = Image.open(base_path).convert("RGBA")
    frame_rel = db.get_setting("frame_overlay_path", "")
    if frame_rel:
        frame_path = config.FRAMES_DIR / Path(frame_rel).name
        if frame_path.exists():
            frame = Image.open(frame_path).convert("RGBA")
            frame = frame.resize(photo.size, Image.LANCZOS)
            photo = Image.alpha_composite(photo, frame)

    framed_path = _path(capture_id, "framed")
    photo.save(framed_path, format="PNG")
    return {"capture_id": capture_id, "framed_url": _public_url(framed_path)}


# --------------------------------------------------------------------------
# 4. Prepare a flattened JPEG for printing
# --------------------------------------------------------------------------
_CM_PER_INCH = 2.54


def print_target_px() -> tuple[int, int]:
    """
    Pixel dimensions the print-ready JPEG must have, from the Admin settings.

    `print_size_cm` is order-insensitive ("10x15" and "15x10" are the same
    sheet); `print_orientation` decides which side ends up long. So 10x15 cm
    portrait at 300 DPI -> 1181x1772 px.
    """
    raw = str(db.get_setting("print_size_cm", "10x15")).lower().replace(",", ".")
    try:
        a, b = (float(part) for part in raw.split("x", 1))
    except ValueError:
        a, b = 10.0, 15.0
    short, long_ = min(a, b), max(a, b)

    try:
        dpi = max(72, int(db.get_setting("print_dpi", 300)))
    except (TypeError, ValueError):
        dpi = 300

    if str(db.get_setting("print_orientation", "portrait")).lower() == "landscape":
        w_cm, h_cm = long_, short
    else:
        w_cm, h_cm = short, long_
    return round(w_cm / _CM_PER_INCH * dpi), round(h_cm / _CM_PER_INCH * dpi)


def print_aspect() -> float:
    """
    Width/height of the print canvas, for the Kiosk viewport.

    The live preview is shaped to this so guests frame themselves inside the
    region that actually gets printed - the crop happens in front of them,
    not silently at print time.
    """
    w, h = print_target_px()
    return round(w / h, 4) if h else 1.5


def fit_to_print(img: Image.Image) -> Image.Image:
    """
    Reshape a photo to the exact print canvas.

    `cover`   - scale to fill, then centre-crop the overflow. No white bars,
                but a 16:9 capture loses most of its width on portrait paper.
    `contain` - scale to fit inside and pad with white. Keeps the whole frame.

    Deliberately never rotates: turning a landscape group shot 90 degrees to
    "fit" portrait paper just prints everyone sideways.
    """
    target_w, target_h = print_target_px()
    src_w, src_h = img.size
    if not src_w or not src_h:
        return img

    contain = str(db.get_setting("print_fit", "cover")).lower() == "contain"
    scale = (min if contain else max)(target_w / src_w, target_h / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    img = img.resize(new_size, Image.LANCZOS)

    if contain:
        canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
        canvas.paste(img, ((target_w - new_size[0]) // 2, (target_h - new_size[1]) // 2))
        return canvas

    left = (new_size[0] - target_w) // 2
    top = (new_size[1] - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def prepare_print(capture_id: str) -> Path:
    """Pick the best available version (framed > enhanced > raw), flatten to
    a white-backed JPEG sized to the configured paper, and return its path."""
    for suffix in ("framed", "enhanced", "raw"):
        p = _path(capture_id, suffix)
        if p.exists():
            img = Image.open(p)
            if img.mode in ("RGBA", "P"):
                bg = Image.new("RGB", img.size, (255, 255, 255))
                img = img.convert("RGBA")
                bg.paste(img, mask=img.split()[-1])
                img = bg
            else:
                img = img.convert("RGB")
            img = fit_to_print(img)
            out = config.CAPTURES_DIR / f"{capture_id}_print.jpg"
            # Embedding DPI matters: without it CUPS guesses 72 and rescales.
            dpi = max(72, int(db.get_setting("print_dpi", 300) or 300))
            img.save(out, format="JPEG", quality=95, dpi=(dpi, dpi))
            return out
    raise FileNotFoundError(f"No printable image for capture '{capture_id}'.")


# --------------------------------------------------------------------------
# Frame upload helper (used by the Photobooth admin tab)
# --------------------------------------------------------------------------
def save_frame_overlay(filename: str, data: bytes) -> str:
    """Persist an uploaded PNG frame and set it as the active overlay."""
    safe = f"frame_{_new_id()}_{Path(filename).name}"
    if not safe.lower().endswith(".png"):
        safe += ".png"
    dest = config.FRAMES_DIR / safe
    # Validate it's an image and has alpha (transparent areas to see through).
    img = Image.open(io.BytesIO(data))
    img.save(dest, format="PNG")
    db.set_setting("frame_overlay_path", safe)
    return f"/media/frames/{safe}"


# --------------------------------------------------------------------------
# Kiosk background media (images / videos for static or slideshow display)
# --------------------------------------------------------------------------
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_VIDEO_EXT = {".mp4", ".webm", ".ogg", ".mov"}


def save_background_media(filename: str, data: bytes) -> dict[str, Any]:
    """Persist an uploaded background image/video and append it to the list."""
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_EXT:
        kind = "image"
    elif ext in _VIDEO_EXT:
        kind = "video"
    else:
        raise ValueError("Unsupported file type. Use an image or video.")
    safe = f"bg_{_new_id()}{ext}"
    (config.BACKGROUNDS_DIR / safe).write_bytes(data)
    media = db.get_setting("kiosk_bg_media", []) or []
    item = {"file": safe, "type": kind, "url": f"/media/backgrounds/{safe}"}
    media.append(item)
    db.set_setting("kiosk_bg_media", media)
    return item


def list_background_media() -> list[dict[str, Any]]:
    media = db.get_setting("kiosk_bg_media", []) or []
    for m in media:
        m.setdefault("url", f"/media/backgrounds/{m['file']}")
    return media


def delete_background_media(file: str) -> None:
    media = db.get_setting("kiosk_bg_media", []) or []
    media = [m for m in media if m.get("file") != file]
    db.set_setting("kiosk_bg_media", media)
    target = config.BACKGROUNDS_DIR / Path(file).name
    if target.exists():
        try:
            target.unlink()
        except OSError:
            pass
