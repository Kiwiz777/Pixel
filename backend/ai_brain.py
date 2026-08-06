"""
ai_brain.py - the conversational + generative core.

Responsibilities
----------------
1. Dynamic LLM routing: send a chat prompt to whichever provider the Admin
   marked "active" (OpenAI / Anthropic / Google Gemini / DeepSeek).
2. Image-to-image "AI Enhance" routing (OpenAI image edit by default; the
   structure makes it trivial to add Gemini/StabilityAI later).
3. Text-to-Speech via ElevenLabs (multilingual: Egyptian & Gulf Arabic,
   English, Russian, German, French).
4. Speech-to-Text (OpenAI Whisper by default).

Everything is async and uses a single shared httpx client. Providers are
called over their REST APIs so we don't need five heavyweight SDKs - keys
come from the encrypted `settings` table at call time (never hard-coded),
so the Admin can change provider/keys live with no restart.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any

import httpx

import database as db

# Shared async client (connection pooling). Lazily created.
_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    return _client


async def aclose() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


class AIError(RuntimeError):
    """Raised when a provider call fails or no key is configured."""


# --------------------------------------------------------------------------
# Provider registry - default model + endpoint metadata
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProviderInfo:
    key_name: str          # settings key holding the API key
    label: str
    default_model: str
    models: tuple[str, ...]


CHAT_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "api_key_openai", "OpenAI", "gpt-4o",
        ("gpt-4o", "gpt-4o-mini", "gpt-4.1", "o4-mini"),
    ),
    "anthropic": ProviderInfo(
        "api_key_anthropic", "Anthropic (Claude)", "claude-opus-4-8",
        ("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    ),
    "gemini": ProviderInfo(
        "api_key_gemini", "Google Gemini", "gemini-2.0-flash",
        ("gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro"),
    ),
    "deepseek": ProviderInfo(
        "api_key_deepseek", "DeepSeek", "deepseek-chat",
        ("deepseek-chat", "deepseek-reasoner"),
    ),
}

IMAGE_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "api_key_openai", "OpenAI Images", "gpt-image-1",
        ("gpt-image-1", "dall-e-3"),
    ),
    "gemini": ProviderInfo(
        "api_key_gemini", "Gemini Images", "gemini-2.0-flash-exp-image-generation",
        ("gemini-2.0-flash-exp-image-generation",),
    ),
}


def provider_catalog() -> dict[str, Any]:
    """Expose the registry to the Admin UI for building dropdowns."""
    return {
        "chat": {k: {"label": v.label, "models": list(v.models),
                     "default_model": v.default_model, "key_name": v.key_name}
                 for k, v in CHAT_PROVIDERS.items()},
        "image": {k: {"label": v.label, "models": list(v.models),
                      "default_model": v.default_model, "key_name": v.key_name}
                  for k, v in IMAGE_PROVIDERS.items()},
    }


# --------------------------------------------------------------------------
# Language helpers (for the speak/persona layer)
# --------------------------------------------------------------------------
_LANG_NAMES = {
    "ar-EG": "Egyptian Arabic",
    "ar-GULF": "Gulf Arabic",
    "en": "English",
    "ru": "Russian",
    "de": "German",
    "fr": "French",
}


def _language_instruction() -> str:
    autodetect = db.get_setting("multilingual_autodetect", True)
    default_lang = db.get_setting("default_language", "en")
    if autodetect:
        return ("Detect the language the user is speaking and reply in that same "
                "language. You are fluent in Egyptian Arabic, Gulf Arabic, English, "
                "Russian, German and French.")
    name = _LANG_NAMES.get(default_lang, "English")
    return f"Always reply in {name}."


# --------------------------------------------------------------------------
# Chat routing
# --------------------------------------------------------------------------
async def chat(prompt: str, *, history: list[dict[str, str]] | None = None,
               system: str | None = None) -> dict[str, Any]:
    """
    Route a chat prompt to the active provider and return:
        {"text": <reply>, "provider": ..., "model": ...}
    `history` is a list of {"role": "user"|"assistant", "content": str}.
    """
    provider = db.get_setting("active_chat_provider", "anthropic")
    model = db.get_setting("active_chat_model") or CHAT_PROVIDERS[provider].default_model
    info = CHAT_PROVIDERS.get(provider)
    if info is None:
        raise AIError(f"Unknown chat provider '{provider}'.")
    api_key = db.get_setting(info.key_name)
    if not api_key:
        raise AIError(f"No API key configured for {info.label}.")

    persona = system or db.get_setting("system_persona", "You are a friendly robot.")
    system_prompt = f"{persona}\n\n{_language_instruction()}"
    history = history or []

    if provider in ("openai", "deepseek"):
        text = await _chat_openai_compatible(provider, api_key, model, system_prompt, history, prompt)
    elif provider == "anthropic":
        text = await _chat_anthropic(api_key, model, system_prompt, history, prompt)
    elif provider == "gemini":
        text = await _chat_gemini(api_key, model, system_prompt, history, prompt)
    else:  # pragma: no cover
        raise AIError(f"Provider '{provider}' not implemented.")

    return {"text": text, "provider": provider, "model": model}


async def extract(text: str, instruction: str) -> str:
    """
    Persona-free, single-shot extraction (e.g. pull a name from a spoken reply).
    Uses the active chat provider but with a neutral system prompt and NO
    language redirection, so the model returns just the requested value.
    """
    provider = db.get_setting("active_chat_provider", "anthropic")
    model = db.get_setting("active_chat_model") or CHAT_PROVIDERS[provider].default_model
    info = CHAT_PROVIDERS.get(provider)
    if info is None:
        raise AIError(f"Unknown chat provider '{provider}'.")
    api_key = db.get_setting(info.key_name)
    if not api_key:
        raise AIError(f"No API key configured for {info.label}.")
    system = ("You are a precise information-extraction tool. Output ONLY the requested "
              "value with no quotes, punctuation, labels or extra words.")
    prompt = f"{instruction}\n\nInput: {text}"
    if provider in ("openai", "deepseek"):
        return await _chat_openai_compatible(provider, api_key, model, system, [], prompt)
    if provider == "anthropic":
        return await _chat_anthropic(api_key, model, system, [], prompt)
    if provider == "gemini":
        return await _chat_gemini(api_key, model, system, [], prompt)
    raise AIError(f"Provider '{provider}' not implemented.")


def _max_tokens() -> int:
    """Reply-length cap (Admin-tunable). Bounded so a bad value can't stall a turn."""
    try:
        return max(16, min(2048, int(db.get_setting("chat_max_tokens", 120))))
    except (TypeError, ValueError):
        return 120


async def _chat_openai_compatible(provider: str, api_key: str, model: str,
                                  system_prompt: str, history: list[dict[str, str]],
                                  prompt: str) -> str:
    base = "https://api.openai.com/v1" if provider == "openai" else "https://api.deepseek.com"
    messages = [{"role": "system", "content": system_prompt}, *history,
                {"role": "user", "content": prompt}]
    r = await _http().post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": messages, "temperature": 0.7,
              "max_tokens": _max_tokens()},
    )
    _raise_for_status(r, provider)
    data = r.json()
    return data["choices"][0]["message"]["content"].strip()


async def _chat_anthropic(api_key: str, model: str, system_prompt: str,
                          history: list[dict[str, str]], prompt: str) -> str:
    messages = [*history, {"role": "user", "content": prompt}]
    r = await _http().post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        json={"model": model, "system": system_prompt, "max_tokens": _max_tokens(),
              "messages": messages},
    )
    _raise_for_status(r, "anthropic")
    data = r.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


async def _chat_gemini(api_key: str, model: str, system_prompt: str,
                       history: list[dict[str, str]], prompt: str) -> str:
    contents = []
    for m in history:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    r = await _http().post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={"systemInstruction": {"parts": [{"text": system_prompt}]},
              "contents": contents,
              "generationConfig": {"maxOutputTokens": _max_tokens()}},
    )
    _raise_for_status(r, "gemini")
    data = r.json()
    cand = (data.get("candidates") or [{}])[0]
    parts = cand.get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


# --------------------------------------------------------------------------
# Image-to-image "AI Enhance"
# --------------------------------------------------------------------------
async def enhance_image(image_bytes: bytes, prompt: str,
                        *, mime: str = "image/png") -> bytes:
    """
    Send an image + prompt to the active image provider and return the
    edited image bytes. Defaults to OpenAI's image edit endpoint.
    """
    provider = db.get_setting("active_image_provider", "openai")
    model = db.get_setting("active_image_model") or IMAGE_PROVIDERS[provider].default_model
    info = IMAGE_PROVIDERS.get(provider)
    if info is None:
        raise AIError(f"Unknown image provider '{provider}'.")
    api_key = db.get_setting(info.key_name)
    if not api_key:
        raise AIError(f"No API key configured for {info.label}.")

    if provider == "openai":
        return await _enhance_openai(api_key, model, image_bytes, prompt, mime)
    if provider == "gemini":
        return await _enhance_gemini(api_key, model, image_bytes, prompt, mime)
    raise AIError(f"Image provider '{provider}' not implemented.")


async def _enhance_openai(api_key: str, model: str, image_bytes: bytes,
                          prompt: str, mime: str) -> bytes:
    files = {"image": ("photo.png", image_bytes, mime)}
    data = {"model": model, "prompt": prompt, "size": "1024x1024", "n": "1"}
    r = await _http().post(
        "https://api.openai.com/v1/images/edits",
        headers={"Authorization": f"Bearer {api_key}"},
        data=data, files=files,
    )
    _raise_for_status(r, "openai-image")
    payload = r.json()["data"][0]
    if payload.get("b64_json"):
        return base64.b64decode(payload["b64_json"])
    # Some models return a URL instead of base64.
    img = await _http().get(payload["url"])
    img.raise_for_status()
    return img.content


async def _enhance_gemini(api_key: str, model: str, image_bytes: bytes,
                          prompt: str, mime: str) -> bytes:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    r = await _http().post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={"contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]}], "generationConfig": {"responseModalities": ["IMAGE"]}},
    )
    _raise_for_status(r, "gemini-image")
    for part in r.json()["candidates"][0]["content"]["parts"]:
        if "inlineData" in part:
            return base64.b64decode(part["inlineData"]["data"])
    raise AIError("Gemini returned no image data.")


# --------------------------------------------------------------------------
# Text-to-Speech (ElevenLabs)
# --------------------------------------------------------------------------
# Built-in OpenAI TTS voices (no API call needed to list them).
OPENAI_TTS_VOICES = (
    "alloy", "ash", "ballad", "coral", "echo",
    "fable", "onyx", "nova", "sage", "shimmer",
)


async def text_to_speech(text: str, *, voice_id: str | None = None) -> bytes:
    """
    Return MP3 audio bytes for `text`, using the Admin-selected TTS provider.

    Providers:
      * openai     - /v1/audio/speech (multilingual, no extra account needed
                     beyond the OpenAI key already used for chat/STT).
      * elevenlabs - high-quality multilingual voices.
    """
    provider = db.get_setting("tts_provider", "openai")
    if provider == "openai":
        return await _tts_openai(text, voice_id)
    if provider == "elevenlabs":
        return await _tts_elevenlabs(text, voice_id)
    raise AIError(f"Unknown TTS provider '{provider}'.")


async def _tts_openai(text: str, voice_id: str | None) -> bytes:
    api_key = db.get_setting("api_key_openai")
    if not api_key:
        raise AIError("No OpenAI API key configured for text-to-speech.")
    model = db.get_setting("openai_tts_model", "gpt-4o-mini-tts")
    voice = voice_id or db.get_setting("openai_tts_voice", "alloy")
    r = await _http().post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "voice": voice, "input": text, "response_format": "mp3"},
    )
    _raise_for_status(r, "openai-tts")
    return r.content


async def _tts_elevenlabs(text: str, voice_id: str | None,
                          model_id: str = "eleven_multilingual_v2") -> bytes:
    api_key = db.get_setting("api_key_elevenlabs")
    if not api_key:
        raise AIError("No ElevenLabs API key configured.")
    voice = voice_id or db.get_setting("tts_voice_id")
    if not voice:
        raise AIError("No ElevenLabs voice selected (set tts_voice_id).")
    r = await _http().post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
        headers={"xi-api-key": api_key, "accept": "audio/mpeg"},
        json={"text": text, "model_id": model_id,
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
    )
    _raise_for_status(r, "elevenlabs")
    return r.content


async def list_voices() -> dict[str, Any]:
    """
    List voices for the Admin voice picker, grouped by provider. OpenAI voices
    are a fixed set; ElevenLabs voices are fetched if a key is present.
    """
    out: dict[str, Any] = {
        "openai": [{"voice_id": v, "name": v.capitalize()} for v in OPENAI_TTS_VOICES],
        "elevenlabs": [],
    }
    el_key = db.get_setting("api_key_elevenlabs")
    if el_key:
        try:
            r = await _http().get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": el_key},
            )
            if r.is_success:
                out["elevenlabs"] = [
                    {"voice_id": v["voice_id"], "name": v["name"], "labels": v.get("labels", {})}
                    for v in r.json().get("voices", [])
                ]
        except Exception:
            pass
    return out


# --------------------------------------------------------------------------
# Speech-to-Text (OpenAI Whisper by default)
# --------------------------------------------------------------------------
async def speech_to_text(audio_bytes: bytes, *, filename: str = "speech.webm",
                         language: str | None = None) -> str:
    provider = db.get_setting("stt_provider", "openai")
    if provider != "openai":
        raise AIError(f"STT provider '{provider}' not implemented.")
    api_key = db.get_setting("api_key_openai")
    if not api_key:
        raise AIError("No OpenAI API key configured for speech-to-text.")
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data: dict[str, str] = {"model": "whisper-1"}
    # Whisper wants ISO-639-1; strip our region suffix (ar-EG -> ar).
    if language:
        data["language"] = language.split("-")[0]
    r = await _http().post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        data=data, files=files,
    )
    _raise_for_status(r, "whisper")
    return r.json().get("text", "").strip()


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------
def _raise_for_status(r: httpx.Response, provider: str) -> None:
    if r.is_success:
        return
    detail = r.text[:500]
    raise AIError(f"{provider} request failed ({r.status_code}): {detail}")
