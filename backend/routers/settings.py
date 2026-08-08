"""Admin settings + AI provider configuration endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

import ai_brain
import database as db
import image_processor
from schemas import SettingsUpdate
from security import require_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def read_settings(_: bool = Depends(require_admin)):
    """All settings with secrets masked (Admin UI consumes this)."""
    return {
        "settings": db.get_all_settings(reveal_secrets=False),
        "languages": db.SUPPORTED_LANGUAGES,
        "providers": ai_brain.provider_catalog(),
    }


@router.put("")
async def write_settings(payload: SettingsUpdate, _: bool = Depends(require_admin)):
    values = payload.model_dump(exclude_unset=True)
    db.update_settings(values)
    return {"ok": True, "settings": db.get_all_settings(reveal_secrets=False)}


@router.get("/public")
async def public_settings():
    """Behaviour flags the Kiosk is allowed to read (NO secrets)."""
    return {
        "interact_button_visible": db.get_setting("interact_button_visible", True),
        "bot_face_visible": db.get_setting("bot_face_visible", True),
        "auto_interact_mode": db.get_setting("auto_interact_mode", True),
        "face_recognition_enabled": db.get_setting("face_recognition_enabled", True),
        "quiz_enabled": db.get_setting("quiz_enabled", True),
        "active_quiz_id": db.get_setting("active_quiz_id"),
        "kiosk_camera_autostart": db.get_setting("kiosk_camera_autostart", True),
        "camera_idle_off_seconds": db.get_setting("camera_idle_off_seconds", 0),
        "camera_off_after_session": db.get_setting("camera_off_after_session", False),
        "default_language": db.get_setting("default_language", "en"),
        "multilingual_autodetect": db.get_setting("multilingual_autodetect", True),
        "dev_mode": db.get_setting("dev_mode", False),
        "frame_overlay_path": db.get_setting("frame_overlay_path", ""),
        "contact_form_enabled": db.get_setting("contact_form_enabled", True),
        "capture_countdown_seconds": db.get_setting("capture_countdown_seconds", 5),
        "frame_overlay_display": db.get_setting("frame_overlay_display", "both"),
        # Shape of the print, so the Kiosk viewport and the capture match the
        # paper exactly (WYSIWYG - nothing is cropped after the shutter).
        "print_orientation": db.get_setting("print_orientation", "portrait"),
        "capture_aspect": image_processor.print_aspect(),
        # Kiosk background appearance
        "kiosk_bg_mode": db.get_setting("kiosk_bg_mode", "none"),
        "kiosk_bg_color": db.get_setting("kiosk_bg_color", "#070b16"),
        "kiosk_bg_media": db.get_setting("kiosk_bg_media", []),
        "kiosk_bg_slideshow_ms": db.get_setting("kiosk_bg_slideshow_ms", 6000),
        "kiosk_bg_dim": db.get_setting("kiosk_bg_dim", 35),
    }


@router.get("/voices")
async def voices(_: bool = Depends(require_admin)):
    """Voices for the TTS picker, grouped by provider (openai, elevenlabs)."""
    return {"voices": await ai_brain.list_voices()}
