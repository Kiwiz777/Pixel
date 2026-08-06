"""Conversational AI endpoints: chat, TTS, STT."""
from __future__ import annotations

import base64

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

import ai_brain
import database as db
from schemas import ChatRequest, TTSRequest

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


@router.post("/stt")
async def stt(file: UploadFile = File(...), language: str | None = Form(None)):
    """Transcribe microphone audio captured by the Kiosk."""
    data = await file.read()
    try:
        text = await ai_brain.speech_to_text(
            data, filename=file.filename or "speech.webm", language=language
        )
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"text": text}
