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
import io
import re
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

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


# Built-in model lists (October 2026). These go stale - the Admin's "Refresh"
# button pulls the live list from each provider (list_models below), and any
# model id can be typed in, so a new release never needs a code change.
CHAT_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "api_key_openai", "OpenAI", "gpt-6.1-terra",
        ("gpt-6.1-terra", "gpt-6-luna", "gpt-6-astra", "gpt-5.5"),
    ),
    "anthropic": ProviderInfo(
        "api_key_anthropic", "Anthropic (Claude)", "claude-opus-5-5",
        ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"),
    ),
    "gemini": ProviderInfo(
        "api_key_gemini", "Google Gemini", "gemini-3.6-flash",
        ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-pro-preview"),
    ),
    "deepseek": ProviderInfo(
        "api_key_deepseek", "DeepSeek", "deepseek-v4-flash",
        ("deepseek-v4-flash", "deepseek-v4-pro"),
    ),
}

IMAGE_PROVIDERS: dict[str, ProviderInfo] = {
    "openai": ProviderInfo(
        "api_key_openai", "OpenAI Images", "gpt-image-2.5-sunburst",
        ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare", "gpt-image-2"),
    ),
    "gemini": ProviderInfo(
        "api_key_gemini", "Gemini Images", "gemini-3.1-flash-image",
        ("gemini-3.1-flash-image", "gemini-3-pro-image"),
    ),
}

# Model ids the providers have shut down. A saved setting naming one of these
# silently uses the provider default instead of failing every request.
RETIRED_MODELS = {
    "gpt-image-1", "dall-e-2", "dall-e-3",                      # OpenAI images (2026)
    "deepseek-chat", "deepseek-reasoner",                        # DeepSeek V3 aliases (Jul 2026)
    "gemini-2.0-flash", "gemini-2.0-pro", "gemini-1.5-pro",
    "gemini-2.0-flash-exp-image-generation",
}

# Extra output room for "thinking" models. Their hidden reasoning counts
# toward the output cap, so the bare reply cap (~120) could leave nothing for
# the answer. Reply length is held by the prompt instead (_length_instruction).
_REASONING_HEADROOM = 1024


def resolve_model(kind: str, provider: str) -> str:
    """The configured model for `kind` ('chat' | 'image'), or the provider
    default when unset or retired."""
    registry = CHAT_PROVIDERS if kind == "chat" else IMAGE_PROVIDERS
    info = registry.get(provider)
    if info is None:
        raise AIError(f"Unknown {kind} provider '{provider}'.")
    model = (db.get_setting(f"active_{kind}_model") or "").strip()
    return info.default_model if not model or model in RETIRED_MODELS else model


def migrate_retired_models() -> None:
    """Startup: clear saved models the provider has shut down, so the Admin
    shows the working default instead of a dead id."""
    for kind in ("chat", "image"):
        if (db.get_setting(f"active_{kind}_model") or "") in RETIRED_MODELS:
            db.set_setting(f"active_{kind}_model", "")


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
    model = resolve_model("chat", provider)
    info = CHAT_PROVIDERS[provider]
    api_key = db.get_setting(info.key_name)
    if not api_key:
        raise AIError(f"No API key configured for {info.label}.")

    persona = system or db.get_setting("system_persona", "You are a friendly robot.")
    system_prompt = f"{persona}\n\n{_language_instruction()} {_length_instruction()}"
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
    model = resolve_model("chat", provider)
    info = CHAT_PROVIDERS[provider]
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


def _length_instruction() -> str:
    # ~0.7 words per token: keeps spoken replies inside the Admin's cap even on
    # models whose token cap had to be raised for their hidden reasoning.
    return f"Keep every reply under about {max(12, int(_max_tokens() * 0.7))} words."


def _max_tokens() -> int:
    """Reply-length cap (Admin-tunable). Bounded so a bad value can't stall a turn."""
    try:
        return max(16, min(2048, int(db.get_setting("chat_max_tokens", 120))))
    except (TypeError, ValueError):
        return 120


def _openai_legacy(model: str) -> bool:
    """Pre-reasoning OpenAI chat models: take temperature + max_tokens."""
    return model.startswith(("gpt-4", "gpt-3.5", "chatgpt-4o"))


async def _chat_openai_compatible(provider: str, api_key: str, model: str,
                                  system_prompt: str, history: list[dict[str, str]],
                                  prompt: str) -> str:
    base = "https://api.openai.com/v1" if provider == "openai" else "https://api.deepseek.com"
    messages = [{"role": "system", "content": system_prompt}, *history,
                {"role": "user", "content": prompt}]
    body: dict[str, Any] = {"model": model, "messages": messages}
    if provider == "openai" and not _openai_legacy(model):
        # GPT-5/6 reasoning models reject temperature and max_tokens; their
        # reasoning shares the completion budget, so give it headroom.
        body["max_completion_tokens"] = _max_tokens() + _REASONING_HEADROOM
        body["reasoning_effort"] = "low"
    else:
        body["temperature"] = 0.7
        body["max_tokens"] = _max_tokens() + (_REASONING_HEADROOM if provider == "deepseek" else 0)
    data = await _post_adaptive(
        provider, f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"}, json=body,
        optional={"reasoning_effort": ("reasoning_effort",), "temperature": ("temperature",)},
    )
    return (data["choices"][0]["message"].get("content") or "").strip()


# Claude models that think by default (thinking can't be switched off on
# several of them) - they need output headroom and run at low effort here.
_CLAUDE_THINKING = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable", "claude-mythos")
# Models that accept the server-side refusal fallback ("default" routing).
_CLAUDE_FALLBACK = ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5")


async def _chat_anthropic(api_key: str, model: str, system_prompt: str,
                          history: list[dict[str, str]], prompt: str) -> str:
    messages = [*history, {"role": "user", "content": prompt}]
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    body: dict[str, Any] = {"model": model, "system": system_prompt,
                            "max_tokens": _max_tokens(), "messages": messages}
    if model.startswith(_CLAUDE_THINKING):
        # Low effort: a photobooth one-liner needs little reasoning, and less
        # thinking is less latency before the guest hears anything.
        body["max_tokens"] = _max_tokens() + _REASONING_HEADROOM
        body["output_config"] = {"effort": "low"}
    if model in _CLAUDE_FALLBACK:
        # If a safety classifier declines, the API retries on a fallback
        # model in the same call instead of leaving the guest with silence.
        headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
        body["fallbacks"] = "default"
    data = await _post_adaptive(
        "anthropic", "https://api.anthropic.com/v1/messages", headers=headers, json=body,
        optional={"output_config": ("output_config", "effort"), "fallbacks": ("fallbacks",)},
    )
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text and data.get("stop_reason") == "refusal":
        raise AIError("The model declined to answer that.")
    return text


async def _chat_gemini(api_key: str, model: str, system_prompt: str,
                       history: list[dict[str, str]], prompt: str) -> str:
    contents = []
    for m in history:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    gen: dict[str, Any] = {"maxOutputTokens": _max_tokens()}
    if not model.startswith(("gemini-1", "gemini-2.0")):
        # 2.5+ think by default and that counts toward maxOutputTokens.
        gen["maxOutputTokens"] = _max_tokens() + _REASONING_HEADROOM
        if not model.startswith("gemini-2"):
            gen["thinkingConfig"] = {"thinkingLevel": "low"}
    data = await _post_adaptive(
        "gemini",
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={"systemInstruction": {"parts": [{"text": system_prompt}]},
              "contents": contents, "generationConfig": gen},
        optional={"generationConfig.thinkingConfig": ("thinkingConfig", "thinkingLevel")},
    )
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
    model = resolve_model("image", provider)
    info = IMAGE_PROVIDERS[provider]
    api_key = db.get_setting(info.key_name)
    if not api_key:
        raise AIError(f"No API key configured for {info.label}.")

    if provider == "openai":
        return await _enhance_openai(api_key, model, image_bytes, prompt, mime)
    if provider == "gemini":
        return await _enhance_gemini(api_key, model, image_bytes, prompt, mime)
    raise AIError(f"Image provider '{provider}' not implemented.")


# Canvases the images/edits endpoint accepts for gpt-image models.
_GPT_IMAGE_SIZES = ((1024, 1024), (1024, 1536), (1536, 1024))


def _openai_image_size(model: str, image_bytes: bytes) -> str:
    """
    Pick the output canvas closest to the photo's own shape.

    Hardcoding 1024x1024 squared every photo, so a portrait or widescreen shot
    came back reshaped and then got cropped again on the way to the printer.
    Older dall-e edit models only accept square sizes, so they keep it.
    """
    if not model.startswith("gpt-image"):
        return "1024x1024"
    try:
        with Image.open(io.BytesIO(image_bytes)) as im:
            source = im.width / im.height
    except Exception:
        return "1024x1024"
    w, h = min(_GPT_IMAGE_SIZES, key=lambda s: abs(s[0] / s[1] - source))
    return f"{w}x{h}"


async def _enhance_openai(api_key: str, model: str, image_bytes: bytes,
                          prompt: str, mime: str) -> bytes:
    files = {"image": ("photo.png", image_bytes, mime)}
    data = {"model": model, "prompt": prompt, "n": "1",
            "size": _openai_image_size(model, image_bytes)}
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
                         language: str | None = None,
                         prompt: str | None = None) -> dict[str, Any]:
    provider = db.get_setting("stt_provider", "openai")
    if provider != "openai":
        raise AIError(f"STT provider '{provider}' not implemented.")
    api_key = db.get_setting("api_key_openai")
    if not api_key:
        raise AIError("No OpenAI API key configured for speech-to-text.")
    model = db.get_setting("stt_model", "gpt-4o-mini-transcribe")
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data: dict[str, str] = {"model": model}

    # The two model families take different parameters, and sending the wrong
    # ones is a 400. whisper-1 is the legacy path: it is the only one that
    # returns verbose_json (duration + detected language, which the kiosk
    # diagnostics show) and the only one that accepts temperature.
    if model == "whisper-1":
        # Greedy decoding. Left at the default, Whisper samples and will invent
        # text to fill near-silence.
        data["temperature"] = "0"
        data["response_format"] = "verbose_json"
        # Whisper wants ISO-639-1; strip our region suffix (ar-EG -> ar).
        if language:
            data["language"] = language.split("-")[0]
    else:
        # gpt-4o-*-transcribe: json only, no temperature.
        data["response_format"] = "json"
        # Auto-detection is good, but an explicit hint beats it - and the kiosk
        # only sends one when the guest (or the Admin) actually chose a
        # language. No hint means we genuinely don't know, so let it detect.
        if language:
            data["language"] = language.split("-")[0]

    # Optional context bias - proper nouns and setting cut misrecognition
    # considerably. Supported on both families. A per-request prompt (e.g. from
    # the contact form) wins over the global Admin one.
    hint = (prompt or str(db.get_setting("stt_prompt", "") or "")).strip()
    if hint:
        data["prompt"] = hint[:800]

    r = await _http().post(
        "https://api.openai.com/v1/audio/transcriptions",
        headers={"Authorization": f"Bearer {api_key}"},
        data=data, files=files,
    )
    _raise_for_status(r, "stt")
    payload = r.json()
    raw = (payload.get("text") or "").strip()
    kept = _drop_hallucination(raw)
    return {
        "text": kept,
        "raw": raw,                                    # what the model said pre-filter
        "filtered": bool(raw) and not kept,            # True = boilerplate was dropped
        "model": model,
        # verbose_json only; absent on the gpt-4o models.
        "language": payload.get("language") or "",
        "duration": round(float(payload.get("duration") or 0), 2),
    }


_DIACRITICS = re.compile(r"[ً-ْٰ]")
_PUNCT = re.compile(r"[^\w\s؀-ۿ♪]", re.UNICODE)


def _normalise(text: str) -> str:
    """Fold Arabic orthography + punctuation so the blocklist matches variants."""
    out = _DIACRITICS.sub("", text.lower().strip())
    for src, dst in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي")):
        out = out.replace(src, dst)
    out = _PUNCT.sub("", out)
    return " ".join(out.split())


# Whisper was trained on a lot of YouTube subtitles, so when it is handed
# silence or noise it emits the most common phrases from that data. These are
# the usual ones. Matching is against the WHOLE normalised transcript, so a
# guest who genuinely says "thanks" is unaffected.
_RAW_HALLUCINATIONS = {
    # Arabic
    "اشتركوا في القناه", "اشتركوا في القناه ولا تنسوا تفعيل الجرس",
    "شكرا على المشاهده", "شكرا لكم على المشاهده", "شكرا للمشاهده",
    "لا تنسى الاشتراك في القناه", "الى اللقاء في الفيديو القادم",
    "اراكم في الفيديو القادم", "ترجمه نانسي قنقر", "المزيد من الفيديوهات",
    "انتهى الفيديو", "ترجمه",
    # English
    "thanks for watching", "thank you for watching", "thanks for watching!",
    "please subscribe", "subscribe to my channel", "like and subscribe",
    "see you in the next video", "you", "bye", "thank you", "thank you.",
    # Non-speech markers
    "[music]", "(music)", "♪", "♪♪", "[silence]", "[applause]",
}

# Normalised at import: the entries must go through the same folding as the
# transcript, or variants like "على" -> "علي" and "[music]" -> "music" never match.
_HALLUCINATIONS = frozenset(_normalise(p) for p in _RAW_HALLUCINATIONS)


def _drop_hallucination(text: str) -> str:
    if not text:
        return text
    if _normalise(text) in _HALLUCINATIONS:
        return ""
    return text


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------
async def _post_adaptive(provider: str, url: str, *, json: dict[str, Any],
                         headers: dict[str, str] | None = None,
                         params: dict[str, str] | None = None,
                         optional: dict[str, tuple[str, ...]] | None = None) -> dict[str, Any]:
    """POST, and if a 400 names one of the `optional` fields, drop that field
    and retry. New models keep rejecting knobs older ones accepted (and vice
    versa); a kiosk should degrade to plain defaults, not go silent.
    `optional` maps a dotted body path to words that identify it in the error."""
    body = dict(json)
    remaining = dict(optional or {})
    while True:
        r = await _http().post(url, headers=headers, params=params, json=body)
        if r.status_code != 400 or not remaining:
            break
        err = r.text
        hit = next((path for path, words in remaining.items()
                    if any(w in err for w in words) and _pop_path(body, path)), None)
        if hit is None:
            break
        remaining.pop(hit)
    _raise_for_status(r, provider)
    return r.json()


def _pop_path(body: dict[str, Any], path: str) -> bool:
    """Remove a dotted path from a (copied) request body; True if it existed."""
    *parents, leaf = path.split(".")
    node = body
    for key in parents:
        if not isinstance(node.get(key), dict):
            return False
        node[key] = dict(node[key])  # don't mutate the caller's nested dicts
        node = node[key]
    return node.pop(leaf, None) is not None


# --------------------------------------------------------------------------
# Live model lists (Admin -> AI Providers -> Refresh)
# --------------------------------------------------------------------------
_NOT_CHAT = ("audio", "realtime", "tts", "transcribe", "whisper", "image", "embedding",
             "search", "moderation", "instruct", "dall-e", "imagen", "veo", "aqa", "live", "codex")


async def list_models(provider: str, kind: str) -> list[str]:
    """Model ids `provider` currently offers this key, filtered to `kind`
    ('chat' | 'image' | 'tts' | 'stt'), newest-looking first."""
    keys = {"openai": "api_key_openai", "anthropic": "api_key_anthropic",
            "gemini": "api_key_gemini", "deepseek": "api_key_deepseek"}
    if provider not in keys:
        raise AIError(f"Unknown provider '{provider}'.")
    api_key = db.get_setting(keys[provider])
    if not api_key:
        raise AIError(f"Add the {provider} API key first, then refresh.")

    if provider == "gemini":
        r = await _http().get("https://generativelanguage.googleapis.com/v1beta/models",
                              params={"key": api_key, "pageSize": "1000"})
        _raise_for_status(r, provider)
        ids = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
               if "generateContent" in m.get("supportedGenerationMethods", [])]
    else:
        url, headers = {
            "openai": ("https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"}),
            "deepseek": ("https://api.deepseek.com/models", {"Authorization": f"Bearer {api_key}"}),
            "anthropic": ("https://api.anthropic.com/v1/models?limit=1000",
                          {"x-api-key": api_key, "anthropic-version": "2023-06-01"}),
        }[provider]
        r = await _http().get(url, headers=headers)
        _raise_for_status(r, provider)
        ids = [m["id"] for m in r.json().get("data", [])]

    def wanted(mid: str) -> bool:
        low = mid.lower()
        if kind == "image":
            return "image" in low and "imagen" not in low
        if kind == "tts":
            return "tts" in low
        if kind == "stt":
            return "transcribe" in low or low == "whisper-1"
        if provider == "openai" and not low.startswith(("gpt-", "o1", "o3", "o4", "o5", "chatgpt")):
            return False
        return not any(word in low for word in _NOT_CHAT)

    return sorted({i for i in ids if wanted(i) and i not in RETIRED_MODELS}, reverse=True)


def _raise_for_status(r: httpx.Response, provider: str) -> None:
    if r.is_success:
        return
    detail = r.text[:500]
    raise AIError(f"{provider} request failed ({r.status_code}): {detail}")
