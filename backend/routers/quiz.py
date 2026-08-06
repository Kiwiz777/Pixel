"""
Quiz / MCQ endpoints.

Admin (token-gated) manages multiple quizzes: questions, answers and the
reward config, plus CSV import/export of the question bank and reward-image
upload. Exactly one quiz can be "active" at a time; the kiosk serves that one.

Public (kiosk):
  * GET  /api/quiz/active   -> active quiz with correct-answer flags stripped
  * POST /api/quiz/submit   -> server-side scoring + resolved reward

Scoring and reward resolution (incl. spinning a prize wheel) happen server-side
so correct answers never reach the browser and the wheel can't be gamed.
"""
from __future__ import annotations

import csv
import io
import random
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse

import database as db
from schemas import QuizSubmit, QuizUpsert, VoucherEmail, VoucherPrint
from security import require_admin

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _correct_ids(question: dict[str, Any]) -> set[str]:
    return {
        str(a.get("id"))
        for a in question.get("answers", [])
        if a.get("correct")
    }


def _strip_answers(quiz: dict[str, Any]) -> dict[str, Any]:
    """Return a kiosk-safe copy of a quiz with `correct` flags removed."""
    q = dict(quiz)
    q["questions"] = [
        {
            "id": str(question.get("id")),
            "text": question.get("text", ""),
            "type": "multi" if question.get("type") == "multi" else "single",
            "answers": [
                {"id": str(a.get("id")), "text": a.get("text", "")}
                for a in question.get("answers", [])
            ],
        }
        for question in quiz.get("questions", [])
    ]
    q.pop("reward", None)  # reward is only revealed once (via /submit)
    return q


def _resolve_reward(
    reward: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]] | None, int | None]:
    """Resolve the reward a winner receives.

    For a prize wheel we pick one segment (respecting an optional integer
    `weight`) and also return the full segment list + the winning index so the
    kiosk can animate the wheel landing on the chosen one.
    """
    if reward.get("type") == "wheel":
        segments = [s for s in reward.get("segments", []) if s]
        if not segments:
            return {"type": "none"}, None, None
        weights = [max(1, int(s.get("weight", 1) or 1)) for s in segments]
        index = random.choices(range(len(segments)), weights=weights, k=1)[0]
        return segments[index], segments, index
    return reward, None, None


# --------------------------------------------------------------------------
# Admin: CRUD
# --------------------------------------------------------------------------
@router.get("")
async def list_all(_: bool = Depends(require_admin)):
    return {"quizzes": db.list_quizzes(), "active_quiz_id": db.get_setting("active_quiz_id")}


@router.post("")
async def create(payload: QuizUpsert, _: bool = Depends(require_admin)):
    data = payload.model_dump(exclude_unset=True)
    quiz_id = db.create_quiz(
        title=data.get("title") or "Untitled quiz",
        description=data.get("description", ""),
        pass_score=int(data.get("pass_score", 70)),
        questions=data.get("questions", []),
        reward=data.get("reward", {}),
    )
    if data.get("is_active"):
        db.set_active_quiz(quiz_id)
    return {"ok": True, "quiz": db.get_quiz(quiz_id)}


@router.get("/active")
async def active():
    """Public: the active quiz for the kiosk (no correct-answer flags)."""
    quiz = db.get_active_quiz()
    if not quiz or not quiz.get("questions"):
        return {"quiz": None}
    return {"quiz": _strip_answers(quiz)}


@router.get("/{quiz_id}")
async def get_one(quiz_id: int, _: bool = Depends(require_admin)):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return {"quiz": quiz}


@router.put("/{quiz_id}")
async def update(quiz_id: int, payload: QuizUpsert, _: bool = Depends(require_admin)):
    if not db.get_quiz(quiz_id):
        raise HTTPException(status_code=404, detail="Quiz not found")
    data = payload.model_dump(exclude_unset=True)
    activate = data.pop("is_active", None)
    if data:
        db.update_quiz(quiz_id, **data)
    if activate is True:
        db.set_active_quiz(quiz_id)
    elif activate is False and db.get_setting("active_quiz_id") == quiz_id:
        db.set_active_quiz(None)
    return {"ok": True, "quiz": db.get_quiz(quiz_id)}


@router.delete("/{quiz_id}")
async def remove(quiz_id: int, _: bool = Depends(require_admin)):
    if db.get_setting("active_quiz_id") == quiz_id:
        db.set_active_quiz(None)
    db.delete_quiz(quiz_id)
    return {"ok": True}


@router.post("/{quiz_id}/activate")
async def activate(quiz_id: int, _: bool = Depends(require_admin)):
    if not db.get_quiz(quiz_id):
        raise HTTPException(status_code=404, detail="Quiz not found")
    db.set_active_quiz(quiz_id)
    return {"ok": True, "active_quiz_id": quiz_id}


# --------------------------------------------------------------------------
# Public: take the quiz
# --------------------------------------------------------------------------
@router.post("/submit")
async def submit(payload: QuizSubmit):
    quiz = db.get_quiz(payload.quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    questions = quiz.get("questions", [])
    total = len(questions)
    answers = payload.answers or {}
    correct_count = 0
    for question in questions:
        qid = str(question.get("id"))
        picked = {str(a) for a in (answers.get(qid) or [])}
        if picked and picked == _correct_ids(question):
            correct_count += 1

    score = round((correct_count / total) * 100) if total else 0
    passed = total > 0 and score >= int(quiz.get("pass_score", 70))

    result: dict[str, Any] = {
        "passed": passed,
        "score": score,
        "correct_count": correct_count,
        "total": total,
        "pass_score": int(quiz.get("pass_score", 70)),
        "reward": None,
        "wheel_segments": None,
        "wheel_index": None,
    }
    if passed:
        reward, segments, index = _resolve_reward(quiz.get("reward", {}))
        result["reward"] = reward
        result["wheel_index"] = index
        if segments is not None:
            # Wheel is display-only: never leak voucher codes onto the spinner.
            result["wheel_segments"] = [
                {k: v for k, v in s.items() if k != "code"} for s in segments
            ]

    db.add_log(
        "quiz",
        message=f"Quiz '{quiz.get('title')}' completed: {score}%",
        response="WON" if passed else "no reward",
        meta={"quiz_id": payload.quiz_id, "score": score, "passed": passed},
    )
    return result


# --------------------------------------------------------------------------
# Public: voucher delivery (email / print)
# --------------------------------------------------------------------------
@router.post("/voucher-email")
async def voucher_email(payload: VoucherEmail):
    """Email a won voucher code to the guest.

    Uses the SMTP settings from Admin. Degrades gracefully: with no SMTP
    configured the request is logged and reported as queued so the kiosk flow
    still completes.
    """
    email = (payload.email or "").strip()
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Please enter a valid email address.")

    host = db.get_setting("smtp_host", "")
    sent = False
    error: str | None = None
    if host:
        try:
            _send_voucher_email(email, payload.label, payload.code, host)
            sent = True
        except Exception as e:  # pragma: no cover - depends on live SMTP
            error = str(e)

    db.add_log(
        "quiz",
        message=f"Voucher emailed to {email}",
        response="sent" if sent else "queued (SMTP not configured)" if not host else f"failed: {error}",
        meta={"label": payload.label, "delivery": "email", "sent": sent},
    )
    return {"ok": True, "sent": sent, "configured": bool(host), "error": error}


def _send_voucher_email(to_addr: str, label: str, code: str, host: str) -> None:
    import smtplib
    from email.message import EmailMessage

    port = int(db.get_setting("smtp_port", 587) or 587)
    user = db.get_setting("smtp_user", "")
    password = db.get_setting("smtp_password", "")
    sender = db.get_setting("smtp_from", "") or user
    use_tls = bool(db.get_setting("smtp_tls", True))

    msg = EmailMessage()
    msg["Subject"] = f"Your reward: {label or 'Voucher'}"
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(
        f"Congratulations!\n\nYou won: {label or 'a voucher'}\nYour code: {code}\n\n"
        "Show this code to claim your reward.\n\n— Pixel Photobooth"
    )

    with smtplib.SMTP(host, port, timeout=15) as server:
        if use_tls:
            server.starttls()
        if user:
            server.login(user, password)
        server.send_message(msg)


@router.post("/voucher-print")
async def voucher_print(payload: VoucherPrint):
    """Print a voucher slip (label + code) to the default printer."""
    import config
    import printer as printer_service
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1200, 600), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 1180, 580], outline=(20, 20, 20), width=4)
    d.text((60, 90), "PIXEL PHOTOBOOTH — REWARD VOUCHER", fill=(120, 60, 10))
    d.text((60, 220), (payload.label or "Voucher"), fill=(10, 10, 10))
    d.text((60, 340), f"CODE: {payload.code}", fill=(20, 20, 20))
    d.text((60, 500), "Present this voucher to claim your reward.", fill=(90, 90, 90))

    path = config.CAPTURES_DIR / f"voucher-{uuid.uuid4().hex[:10]}.png"
    img.save(path, format="PNG")
    try:
        res = printer_service.print_file(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Print failed: {e}")
    db.add_log("quiz", message="Voucher printed", response=str(res.get("job_id")),
               meta={"label": payload.label, "delivery": "print"})
    return {"ok": True, "job_id": res.get("job_id"), "printer": res.get("printer")}


# --------------------------------------------------------------------------
# Admin: CSV import / export of the question bank
# --------------------------------------------------------------------------
_CSV_HEADER = ["question", "type", "answer", "correct"]


@router.get("/{quiz_id}/export.csv")
async def export_csv(quiz_id: int, _: bool = Depends(require_admin)):
    quiz = db.get_quiz(quiz_id)
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_CSV_HEADER)
    for question in quiz.get("questions", []):
        qtype = "multi" if question.get("type") == "multi" else "single"
        for a in question.get("answers", []):
            writer.writerow([
                question.get("text", ""),
                qtype,
                a.get("text", ""),
                "true" if a.get("correct") else "false",
            ])
    filename = f"quiz-{quiz_id}-questions.csv"
    return PlainTextResponse(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "correct", "x")


@router.post("/{quiz_id}/import")
async def import_csv(quiz_id: int, file: UploadFile = File(...),
                     _: bool = Depends(require_admin)):
    """Replace a quiz's question bank from a CSV (question,type,answer,correct).

    Consecutive rows sharing a question text are grouped into one question.
    """
    if not db.get_quiz(quiz_id):
        raise HTTPException(status_code=404, detail="Quiz not found")
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "question" not in [f.strip().lower() for f in reader.fieldnames]:
        raise HTTPException(status_code=400, detail="CSV must have a 'question' header column.")

    # Normalise header lookup (case-insensitive).
    def col(row: dict, name: str) -> str:
        for k, v in row.items():
            if k and k.strip().lower() == name:
                return (v or "").strip()
        return ""

    questions: list[dict[str, Any]] = []
    by_text: dict[str, dict[str, Any]] = {}
    for row in reader:
        text = col(row, "question")
        answer = col(row, "answer")
        if not text or not answer:
            continue
        qtype = "multi" if col(row, "type").lower() == "multi" else "single"
        if text not in by_text:
            q = {"id": f"q{uuid.uuid4().hex[:8]}", "text": text, "type": qtype, "answers": []}
            by_text[text] = q
            questions.append(q)
        by_text[text]["answers"].append({
            "id": f"a{uuid.uuid4().hex[:8]}",
            "text": answer,
            "correct": _parse_bool(col(row, "correct")),
        })

    if not questions:
        raise HTTPException(status_code=400, detail="No valid question/answer rows found.")
    db.update_quiz(quiz_id, questions=questions)
    return {"ok": True, "quiz": db.get_quiz(quiz_id), "imported": len(questions)}


# --------------------------------------------------------------------------
# Admin: reward image upload (shown to the winner)
# --------------------------------------------------------------------------
@router.post("/reward-image")
async def upload_reward_image(file: UploadFile = File(...), _: bool = Depends(require_admin)):
    import config
    from PIL import Image

    data = await file.read()
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")
    ext = (file.filename or "reward.png").rsplit(".", 1)[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "webp", "gif"):
        ext = "png"
    name = f"reward-{uuid.uuid4().hex[:10]}.{ext}"
    (config.REWARDS_DIR / name).write_bytes(data)
    return {"ok": True, "image_path": name, "url": f"/media/rewards/{name}"}
