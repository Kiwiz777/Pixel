"""Admin settings + AI provider configuration endpoints."""
from __future__ import annotations

import io
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

import ai_brain
import config
import database as db
import image_processor
import voice_clips
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
        # Lets the kiosk pick "Take the Quiz" vs "Get a Reward" for the button
        # without fetching the full quiz first.
        "active_quiz_has_questions": bool((db.get_active_quiz() or {}).get("questions")),
        "kiosk_camera_autostart": db.get_setting("kiosk_camera_autostart", True),
        "camera_idle_off_seconds": db.get_setting("camera_idle_off_seconds", 0),
        "camera_off_after_session": db.get_setting("camera_off_after_session", False),
        "default_language": db.get_setting("default_language", "en"),
        "multilingual_autodetect": db.get_setting("multilingual_autodetect", True),
        "dev_mode": db.get_setting("dev_mode", False),
        "frame_overlay_path": db.get_setting("frame_overlay_path", ""),
        "contact_form_enabled": db.get_setting("contact_form_enabled", True),
        "diag_show_conversation": db.get_setting("diag_show_conversation", False),
        "diag_show_ai_latency": db.get_setting("diag_show_ai_latency", False),
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
        # Attract mode (background only until a face is seen)
        "attract_mode_enabled": db.get_setting("attract_mode_enabled", False),
        "attract_reveal_seconds": db.get_setting("attract_reveal_seconds", 1),
        "attract_idle_seconds": db.get_setting("attract_idle_seconds", 20),
        "attract_return_after_session": db.get_setting("attract_return_after_session", True),
        "attract_rest_seconds": db.get_setting("attract_rest_seconds", 8),
        "attract_review_idle_seconds": db.get_setting("attract_review_idle_seconds", 45),
        "ui_font": db.get_setting("ui_font", "playful"),
        "attract_tap_to_wake": db.get_setting("attract_tap_to_wake", True),
        "attract_hint": db.get_setting("attract_hint", ""),
        # Prize wheel look (global, shared by every quiz)
        "wheel_style": db.get_setting("wheel_style", {}),
        # Avatar + welcome-on-arrival
        "avatar_style": db.get_setting("avatar_style", "robot"),
        "avatar_name": db.get_setting("avatar_name", "Pixel"),
        "video_avatar": {
            state: f"/media/avatar/{name}"
            for state, name in (db.get_setting("video_avatar", {}) or {}).items()
            if name and (config.AVATAR_DIR / name).exists()
        },
        "video_avatar_shape": db.get_setting("video_avatar_shape", "rounded"),
        "video_avatar_scale": db.get_setting("video_avatar_scale", 1.6),
        "auto_interact_style": db.get_setting("auto_interact_style", "welcome"),
        "welcome_messages": db.get_setting("welcome_messages", ""),
        "welcome_back_messages": db.get_setting("welcome_back_messages", ""),
        "welcome_speak": db.get_setting("welcome_speak", True),
        "welcome_voice_mode": db.get_setting("welcome_voice_mode", "live"),
        "welcome_voice_clips": voice_clips.public_clips(),   # {line: url}
        "greet_dwell_seconds": db.get_setting("greet_dwell_seconds", 2),
        "greet_cooldown_seconds": db.get_setting("greet_cooldown_seconds", 20),
        # AI Enhance style cards - prompts stripped; the kiosk sends the index.
        "enhance_mode": db.get_setting("enhance_mode", "prompt"),
        "enhance_cards": public_enhance_cards(),
    }


def public_enhance_cards() -> list[dict]:
    """Usable cards (title + prompt set) without their prompts. `index` is the
    position in the stored list, which is what /photobooth/enhance resolves."""
    cards = db.get_setting("enhance_cards", []) or []
    return [
        {"index": i, **{k: str(c.get(k) or "") for k in ("title", "description", "emoji", "color", "image")}}
        for i, c in enumerate(cards)
        if isinstance(c, dict) and str(c.get("title") or "").strip() and str(c.get("prompt") or "").strip()
    ]


VIDEO_AVATAR_STATES = ("idle", "talking", "listening", "thinking", "wave")
VIDEO_AVATAR_MAX_BYTES = 80 * 1024 * 1024


@router.post("/avatar-video/{state}")
async def upload_avatar_video(state: str, file: UploadFile = File(...), _: bool = Depends(require_admin)):
    """Upload one clip of the real-person video avatar. MP4 (H.264) or WebM;
    a WebM with transparency gives the cut-out look. Replaces that state's
    previous clip."""
    if state not in VIDEO_AVATAR_STATES:
        raise HTTPException(status_code=400, detail=f"state must be one of {', '.join(VIDEO_AVATAR_STATES)}")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ("mp4", "m4v", "webm"):
        raise HTTPException(status_code=400, detail="Use an MP4 (H.264) or WebM video.")
    data = await file.read()
    if len(data) > VIDEO_AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Clip is over 80 MB - trim it or lower the resolution.")
    name = f"{state}-{uuid.uuid4().hex[:10]}.{ext}"
    (config.AVATAR_DIR / name).write_bytes(data)
    return {"ok": True, "video_avatar": _set_avatar_clip(state, name)}


@router.delete("/avatar-video/{state}")
async def delete_avatar_video(state: str, _: bool = Depends(require_admin)):
    if state not in VIDEO_AVATAR_STATES:
        raise HTTPException(status_code=400, detail="Unknown state.")
    return {"ok": True, "video_avatar": _set_avatar_clip(state, "")}


def _set_avatar_clip(state: str, name: str) -> dict:
    clips = dict(db.get_setting("video_avatar", {}) or {})
    old = clips.get(state)
    if old and old != name:
        (config.AVATAR_DIR / old).unlink(missing_ok=True)
    clips[state] = name
    db.set_setting("video_avatar", clips)
    return clips


@router.get("/models/{kind}/{provider}")
async def live_models(kind: str, provider: str, _: bool = Depends(require_admin)):
    """Live model list from the provider (Admin "Refresh"), filtered to
    kind = chat | image | tts | stt."""
    if kind not in ("chat", "image", "tts", "stt"):
        raise HTTPException(status_code=400, detail="kind must be chat, image, tts or stt")
    try:
        return {"models": await ai_brain.list_models(provider, kind)}
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # network down, provider outage
        raise HTTPException(status_code=502, detail=f"Could not reach {provider}: {e}")


@router.get("/voices")
async def voices(_: bool = Depends(require_admin)):
    """Voices for the TTS picker, grouped by provider (openai, elevenlabs)."""
    return {"voices": await ai_brain.list_voices()}


@router.post("/wheel-image/{kind}")
async def upload_wheel_image(kind: str, file: UploadFile = File(...), _: bool = Depends(require_admin)):
    """Upload custom prize-wheel art: a `frame` (bezel drawn over the wheel)
    or `background` (drawn behind it). Caller still has to save the returned
    path into `wheel_style` via PUT /api/settings."""
    if kind not in ("frame", "background"):
        raise HTTPException(status_code=400, detail="kind must be 'frame' or 'background'")
    from PIL import Image

    data = await file.read()
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")
    ext = (file.filename or "wheel.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp"):
        ext = "png"
    name = f"{kind}-{uuid.uuid4().hex[:10]}.{ext}"
    (config.WHEEL_DIR / name).write_bytes(data)
    return {"ok": True, "path": name, "url": f"/media/wheel/{name}"}
