"""User (known faces) management for the Admin dashboard."""
from __future__ import annotations

import json
import math

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import config
import database as db
import vision
from schemas import UserUpdate
from security import require_admin

router = APIRouter(prefix="/api/users", tags=["users"])

# Max Euclidean distance between 128-d descriptors to count as the same person.
# face-api.js uses 0.6 by default; we tighten slightly to reduce false matches.
FACE_MATCH_THRESHOLD = 0.55


@router.get("")
async def get_users(_: bool = Depends(require_admin)):
    return {"users": db.list_users()}


@router.post("")
async def add_user(
    name: str = Form(...),
    bio: str = Form(""),
    language: str = Form("en"),
    is_admin: bool = Form(False),
    face: UploadFile | None = File(None),
    face_descriptor: str | None = Form(None),
    _: bool = Depends(require_admin),
):
    """
    Create a user. Faces are enrolled via a client-side descriptor (face-api.js)
    sent as `face_descriptor` (JSON list of 128 floats). An optional `face`
    image is stored only as a thumbnail. We fall back to server-side dlib
    encoding from the image if no descriptor is provided (Pi only).
    """
    face_image_rel: str | None = None
    encoding: list[float] | None = None

    # Preferred: descriptor computed in the browser.
    if face_descriptor:
        try:
            parsed = json.loads(face_descriptor)
            if isinstance(parsed, list) and len(parsed) >= 64:
                encoding = [float(x) for x in parsed]
        except (ValueError, TypeError):
            encoding = None

    if face is not None:
        data = await face.read()
        safe_name = f"face_{name.replace(' ', '_')}_{face.filename}"
        (config.FACES_DIR / safe_name).write_bytes(data)
        face_image_rel = safe_name
        # Fallback to server-side encoding only if the client didn't send one.
        if encoding is None:
            encoding = vision.compute_encoding_from_image(data)

    if encoding is None:
        db.add_log("system", message=f"No face enrolled for {name}")

    user_id = db.create_user(name=name, bio=bio, language=language,
                             face_image=face_image_rel, face_encoding=encoding,
                             is_admin=is_admin)
    vision.camera.reload_faces()
    return {"ok": True, "user": db.get_user(user_id),
            "face_enrolled": encoding is not None}


@router.post("/enroll")
async def enroll(
    name: str = Form(...),
    descriptor: str = Form(...),
    bio: str = Form(""),
    language: str = Form("en"),
    face: UploadFile | None = File(None),
):
    """
    Public (kiosk) enrolment: the bot collects a name + interests during the
    onboarding chat and registers a brand-new guest with their live face
    descriptor AND a snapshot (for the Admin thumbnail). No admin token (the
    kiosk has none). Never creates an admin user.
    """
    try:
        encoding = [float(x) for x in json.loads(descriptor)]
    except (ValueError, TypeError):
        encoding = []
    if len(encoding) < 64:
        raise HTTPException(status_code=400, detail="Invalid face descriptor.")

    clean_name = name.strip()[:60] or "Friend"
    face_image_rel: str | None = None
    if face is not None:
        data = await face.read()
        safe_name = f"face_{clean_name.replace(' ', '_')}_{face.filename or 'snap.jpg'}"
        (config.FACES_DIR / safe_name).write_bytes(data)
        face_image_rel = safe_name

    user_id = db.create_user(
        name=clean_name, bio=bio.strip()[:500], language=language,
        face_image=face_image_rel, face_encoding=encoding, is_admin=False,
    )
    db.add_log("system", message=f"Kiosk enrolled new guest: {clean_name}", user_id=user_id)
    vision.camera.reload_faces()
    return {"ok": True, "user": db.get_user(user_id)}


class MatchRequest(BaseModel):
    descriptor: list[float]
    peek: bool = False  # dev overlay: match without updating last_seen/visit_count


@router.post("/match")
async def match_face(payload: MatchRequest):
    """
    Public (kiosk) endpoint: given a live 128-d descriptor, return the best
    matching enrolled user, or null. Compares against stored descriptors with
    Euclidean distance. No admin token (the kiosk has none) and it never
    returns the stored biometrics - only the matched name/id.
    """
    probe = payload.descriptor
    best = None
    best_dist = FACE_MATCH_THRESHOLD
    for user_id, name, enc in db.get_known_face_encodings():
        if len(enc) != len(probe):
            continue
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(enc, probe)))
        if dist < best_dist:
            best_dist = dist
            best = (user_id, name)
    if best is None:
        return {"match": None}
    # Capture the PRIOR last_seen before we update it, so the kiosk can phrase
    # the greeting based on how long ago we last saw this person.
    user = db.get_user(best[0])
    prior_last_seen = user.get("last_seen")
    if not payload.peek:
        db.mark_user_seen(best[0])
    return {"match": {
        "id": best[0],
        "name": best[1],
        "language": user.get("language", "en"),
        "bio": user.get("bio", ""),
        "is_admin": bool(user.get("is_admin")),
        "last_seen": prior_last_seen,
        "distance": round(best_dist, 3),
    }}


@router.put("/{user_id}")
async def edit_user(user_id: int, payload: UserUpdate, _: bool = Depends(require_admin)):
    if db.get_user(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    db.update_user(user_id, **payload.model_dump(exclude_unset=True))
    return {"ok": True, "user": db.get_user(user_id)}


@router.delete("/{user_id}")
async def remove_user(user_id: int, _: bool = Depends(require_admin)):
    db.delete_user(user_id)
    vision.camera.reload_faces()
    return {"ok": True}
