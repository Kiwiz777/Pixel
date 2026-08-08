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
    contact = db.create_contact(name, payload.phone or "", payload.note or "",
                                payload.source or "form")
    db.add_log("contact", message=f"{name} {payload.phone or ''}".strip(),
               meta={"source": payload.source or "form"})
    return {"ok": True, "contact": contact}


# Digits, spaces and the punctuation phone numbers legitimately contain.
_PHONE_CHARS = re.compile(r"[^\d+()\-\s]")


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
        'Extract the person\'s name and phone number from the text. Respond with '
        'ONLY a JSON object, no prose and no code fences, exactly: '
        '{"name": "", "phone": ""}. Write spoken-out digits as digits. Leave a '
        'field as an empty string if it is not present.'
    )
    try:
        raw = await ai_brain.extract(text, instruction)
    except ai_brain.AIError as e:
        raise HTTPException(status_code=400, detail=str(e))

    name, phone = "", ""
    # Models sometimes wrap JSON in prose or fences despite instructions.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            name = str(data.get("name") or "").strip()
            phone = str(data.get("phone") or "").strip()
        except (ValueError, AttributeError):
            pass

    phone = _PHONE_CHARS.sub("", phone).strip()
    return {"name": name, "phone": phone, "transcript": text}


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
