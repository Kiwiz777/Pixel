"""
Saved ("pre-generated") voice clips for fixed lines - the welcome greetings.

Text-to-speech costs tokens and needs internet + an API key. Welcome lines
don't change, so the Admin synthesises them once (Avatar & Welcome ->
"Generate & save voice") and the kiosk plays the MP3s from local disk:
offline, at zero cost per greeting.

Manifest lives in the `welcome_voice_clips` setting:
    {text: {"file", "provider", "voice", "created_at"}}
Files live in config.VOICE_DIR and are served at /media/voice/<file>.
The file name hashes provider + voice + text, so changing the voice and
regenerating makes fresh clips instead of reusing the old voice.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import ai_brain
import config
import database as db


def current_voice() -> tuple[str, str]:
    provider = db.get_setting("tts_provider", "openai")
    if provider == "elevenlabs":
        return provider, db.get_setting("tts_voice_id", "") or ""
    return provider, db.get_setting("openai_tts_voice", "alloy") or "alloy"


def _file_name(text: str, provider: str, voice: str) -> str:
    digest = hashlib.sha1(f"{provider}|{voice}|{text}".encode("utf-8")).hexdigest()[:16]
    return f"clip-{digest}.mp3"


def manifest() -> dict[str, Any]:
    m = db.get_setting("welcome_voice_clips", {}) or {}
    return m if isinstance(m, dict) else {}


def public_clips() -> dict[str, str]:
    """{line text: url} for clips that exist on disk - what the kiosk plays."""
    out: dict[str, str] = {}
    for text, clip in manifest().items():
        name = clip.get("file", "") if isinstance(clip, dict) else ""
        if name and (config.VOICE_DIR / name).exists():
            out[text] = f"/media/voice/{name}"
    return out


async def generate(texts: list[str]) -> dict[str, Any]:
    """Synthesise every line that isn't saved yet with the current voice.

    Lines containing {name} are skipped - they differ per guest. Clips for
    lines no longer in the list are deleted. A line that fails keeps its
    previous clip (if any) so a flaky connection never loses a working voice.
    """
    provider, voice = current_voice()
    wanted: list[str] = []
    for t in texts:
        t = (t or "").strip()
        if t and "{name}" not in t and t not in wanted:
            wanted.append(t)

    old = manifest()
    new: dict[str, Any] = {}
    errors: dict[str, str] = {}
    created = 0
    for text in wanted:
        name = _file_name(text, provider, voice)
        path = config.VOICE_DIR / name
        prev = old.get(text) if isinstance(old.get(text), dict) else None
        if not path.exists():
            try:
                path.write_bytes(await ai_brain.text_to_speech(text))
                created += 1
            except Exception as e:  # AIError, network down, bad key...
                errors[text] = str(e) or e.__class__.__name__
                if prev:
                    new[text] = prev
                continue
        same = prev and prev.get("file") == name
        new[text] = {
            "file": name, "provider": provider, "voice": voice,
            "created_at": prev["created_at"] if same else datetime.now(timezone.utc).isoformat(),
        }

    db.set_setting("welcome_voice_clips", new)
    keep = {c["file"] for c in new.values()}
    for f in config.VOICE_DIR.glob("clip-*.mp3"):
        if f.name not in keep:
            f.unlink(missing_ok=True)
    db.add_log("system", message=f"Saved voice clips: {len(new)} ready, {created} newly generated",
               meta={"errors": errors, "provider": provider, "voice": voice})
    return {"clips": new, "created": created, "errors": errors, "provider": provider, "voice": voice}
