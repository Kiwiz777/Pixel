"""Conversational AI endpoints: chat, TTS, STT."""
from __future__ import annotations

import base64
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import ai_brain
import database as db
import voice_clips
from schemas import ChatRequest, TTSRequest, VoiceClipsRequest
from security import require_admin

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/chat")
async def chat(payload: ChatRequest):
    """Route a prompt to the active LLM provider. Optionally returns TTS audio."""
    try:
        history = [m.model_dump() for m in payload.history]
        result = await ai_brain.chat(payload.prompt, history=history)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.add_log("conversation", message=payload.prompt, response=result["text"],
               user_id=payload.user_id,
               meta={"provider": result["provider"], "model": result["model"]})

    audio_b64 = None
    if payload.speak:
        try:
            audio = await ai_brain.text_to_speech(result["text"])
            audio_b64 = base64.b64encode(audio).decode("ascii")
        except ai_brain.AIError:
            audio_b64 = None  # TTS optional; don't fail the chat

    return {**result, "audio_b64": audio_b64}


class ExtractRequest(BaseModel):
    text: str
    instruction: str


@router.post("/extract")
async def extract(payload: ExtractRequest):
    """Public: persona-free extraction (kiosk uses it to pull a guest's name)."""
    try:
        result = await ai_brain.extract(payload.text, payload.instruction)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"result": result.strip()}


@router.post("/tts")
async def tts(payload: TTSRequest):
    """Synthesize speech and return raw MP3 bytes."""
    try:
        audio = await ai_brain.text_to_speech(payload.text, voice_id=payload.voice_id)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/voice-clips")
async def save_voice_clips(payload: VoiceClipsRequest, _: bool = Depends(require_admin)):
    """Admin: synthesise the welcome lines once and keep the MP3s, so the
    kiosk can greet offline without spending tokens (see voice_clips.py)."""
    return await voice_clips.generate(payload.texts)


@router.post("/stt")
async def stt(file: UploadFile = File(...), language: str | None = Form(None),
              prompt: str | None = Form(None)):
    """
    Transcribe microphone audio captured by the Kiosk.

    `prompt` biases recognition for a specific screen - the contact form sends
    one describing names, job titles and email addresses, which is what makes
    dictated proper nouns land.
    """
    data = await file.read()
    filename = file.filename or "speech.webm"
    # Saved before transcription, so a recording exists even when STT errors -
    # that is exactly the case you want to listen back to.
    audio_url = _keep_recording(data, filename)
    try:
        result = await ai_brain.speech_to_text(data, filename=filename,
                                               language=language, prompt=prompt)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # `raw`/`filtered`/`language`/`duration`/`audio_url` feed the diagnostics panel.
    result["audio_url"] = audio_url
    return result


def _keep_recording(data: bytes, filename: str) -> str:
    """
    Save the clip under data/recordings and prune to the retention limit.

    Best-effort: a full or read-only disk must never break transcription, so
    every failure here is swallowed and simply yields no playback URL.
    """
    if not db.get_setting("stt_keep_recordings", True):
        return ""
    try:
        import config

        ext = Path(filename).suffix.lower() or ".webm"
        if ext not in (".webm", ".ogg", ".wav", ".mp3", ".m4a"):
            ext = ".webm"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        dest = Path(config.RECORDINGS_DIR) / f"stt-{stamp}{ext}"
        dest.write_bytes(data)

        try:
            keep = max(1, min(500, int(db.get_setting("stt_recordings_keep", 60))))
        except (TypeError, ValueError):
            keep = 60
        clips = sorted(Path(config.RECORDINGS_DIR).glob("stt-*"), key=lambda p: p.name)
        for old in clips[:-keep]:
            old.unlink(missing_ok=True)

        return f"/media/recordings/{dest.name}"
    except Exception:
        return ""
