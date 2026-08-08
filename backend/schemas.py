"""Pydantic request/response models for the API."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# --- Settings --------------------------------------------------------------
class SettingsUpdate(BaseModel):
    """Partial update of any settings keys. Secrets left blank are ignored."""
    model_config = {"extra": "allow"}


# --- Users -----------------------------------------------------------------
class UserCreate(BaseModel):
    name: str
    bio: str = ""
    language: str = "en"


class UserUpdate(BaseModel):
    name: str | None = None
    bio: str | None = None
    language: str | None = None


# --- Chat ------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    prompt: str
    history: list[ChatMessage] = Field(default_factory=list)
    speak: bool = False          # also synthesize audio (ElevenLabs)
    user_id: int | None = None


# --- Photobooth ------------------------------------------------------------
class EnhanceRequest(BaseModel):
    capture_id: str
    prompt: str | None = None
    user_id: int | None = None


class FrameRequest(BaseModel):
    capture_id: str
    use_enhanced: bool = True


class PrintRequest(BaseModel):
    capture_id: str
    printer: str | None = None
    copies: int | None = None


# --- Printer ---------------------------------------------------------------
# --- Contact us ------------------------------------------------------------
class ContactCreate(BaseModel):
    name: str
    phone: str = ""
    note: str = ""
    source: str = "form"        # form|voice


class ContactParse(BaseModel):
    text: str                   # raw transcript to pull name/phone out of


class DefaultPrinterRequest(BaseModel):
    name: str


class PrintConfigUpdate(BaseModel):
    copies: int | None = None
    media: str | None = None
    color_mode: str | None = None
    size_cm: str | None = None          # "10x15" (order-insensitive)
    orientation: str | None = None      # portrait|landscape
    dpi: int | None = None
    fit: str | None = None              # cover|contain


# --- TTS -------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None


# --- Quiz / MCQ ------------------------------------------------------------
class QuizUpsert(BaseModel):
    """Create/update a quiz. All fields optional so PUT can patch partially."""
    title: str | None = None
    description: str | None = None
    pass_score: int | None = None
    is_active: bool | None = None
    questions: list[dict[str, Any]] | None = None
    reward: dict[str, Any] | None = None


class QuizSubmit(BaseModel):
    quiz_id: int
    # map of question id -> list of selected answer ids
    answers: dict[str, list[str]] = Field(default_factory=dict)


class VoucherEmail(BaseModel):
    label: str = ""
    code: str
    email: str


class VoucherPrint(BaseModel):
    label: str = ""
    code: str


class OK(BaseModel):
    ok: bool = True
    detail: str | None = None
    data: dict[str, Any] | None = None
