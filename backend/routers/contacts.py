"""Kiosk "Contact us" endpoints: submit details, and parse spoken details with AI."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException

import ai_brain
import database as db
from schemas import ContactCreate, ContactParse
from security import require_admin

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


# --------------------------------------------------------------------------
# Public (kiosk)
# --------------------------------------------------------------------------
@router.post("")
async def submit(payload: ContactCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="A name is required.")
    contact = db.create_contact(
        name, payload.phone or "", payload.note or "", payload.source or "form",
        email=_clean_email(payload.email or ""),
        job_title=payload.job_title or "",
        company=payload.company or "",
    )
    db.add_log("contact", message=f"{name} {payload.phone or ''}".strip(),
               meta={"source": payload.source or "form",
                     "company": payload.company or ""})
    return {"ok": True, "contact": contact}


# Digits, spaces and the punctuation phone numbers legitimately contain.
_PHONE_CHARS = re.compile(r"[^\d+()\-\s]")

# Spoken email: "sara at gmail dot com" -> "sara@gmail.com". Whisper transcribes
# dictated addresses in words, and no amount of prompting makes that reliable.
_SPOKEN_AT = re.compile(r"\s*(?:@|\bat\b|\bآت\b|\bأت\b)\s*", re.IGNORECASE)
_SPOKEN_DOT = re.compile(r"\s*(?:\.|\bdot\b|\bpoint\b|\bنقطه\b|\bنقطة\b)\s*", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")


def _clean_email(value: str) -> str:
    """Normalise a dictated or typed address; return '' if it isn't one."""
    if not value:
        return ""
    text = value.strip().lower()
    if "@" not in text:
        text = _SPOKEN_AT.sub("@", text, count=1)
    text = _SPOKEN_DOT.sub(".", text)
    text = re.sub(r"\s+", "", text)
    match = _EMAIL_RE.search(text)
    return match.group(0) if match else ""


@router.post("/parse")
async def parse(payload: ContactParse):
    """
    Pull a name and phone number out of free speech.

    The kiosk records a guest saying something like "hi I'm Sara, my number is
    oh five five one two three...", transcribes it with Whisper, and sends the
    text here. Returning fields (rather than filling them straight in) lets the
    guest check and correct before submitting.
    """
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Nothing to parse.")

    instruction = (
        "Extract contact details from the text. Respond with ONLY a JSON object, "
        "no prose and no code fences, exactly: "
        '{"name": "", "phone": "", "email": "", "job_title": "", "company": ""}. '
        "Rules: write spoken-out digits as digits (e.g. 'oh five five' -> '055'); "
        "for the email, convert spoken 'at' to @ and 'dot' to . and remove all "
        "spaces; job_title is their role (e.g. Marketing Manager); company is the "
        "organisation they work for. Leave a field as an empty string if it is "
        "not mentioned. Do not invent values."
    )
    try:
        raw = await ai_brain.extract(text, instruction)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))

    fields = {"name": "", "phone": "", "email": "", "job_title": "", "company": ""}
    # Models sometimes wrap JSON in prose or fences despite instructions.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            for key in fields:
                fields[key] = str(data.get(key) or "").strip()
        except (ValueError, AttributeError):
            pass

    fields["phone"] = _PHONE_CHARS.sub("", fields["phone"]).strip()
    # Prefer the model's email, but fall back to scanning the raw transcript -
    # it often survives there when the model drops it.
    fields["email"] = _clean_email(fields["email"]) or _clean_email(text)
    return {**fields, "transcript": text}


# --------------------------------------------------------------------------
# Admin
# --------------------------------------------------------------------------
@router.get("")
async def list_all(limit: int = 500, _: bool = Depends(require_admin)):
    return {"contacts": db.list_contacts(limit)}


@router.delete("/{contact_id}")
async def remove(contact_id: int, _: bool = Depends(require_admin)):
    db.delete_contact(contact_id)
    return {"ok": True}


@router.delete("")
async def clear(_: bool = Depends(require_admin)):
    db.clear_contacts()
    return {"ok": True}
