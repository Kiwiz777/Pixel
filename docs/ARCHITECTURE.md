# Architecture

## Overview
Single-process FastAPI backend + Vue SPA. One origin in production; Vite proxy in dev.

```
┌─────────────────────────────────────────────────────────────────────┐
│                            FastAPI (main.py)                          │
│                                                                       │
│  WebSockets                REST routers/            Services           │
│  ───────────               ─────────────            ────────           │
│  /ws/stream  ── JPEG ───►  /api/photobooth ───────► image_processor ──┐│
│  /ws/events  ◄─ events ──  /api/ai ───────────────► ai_brain ─────────┤│
│                            /api/printer ──────────► printer ──────────┤│
│                            /api/users   ──────────► vision (enrol) ───┤│
│                            /api/settings ─────┐                       ││
│                            /api/logs ─────────┤                       ││
│                                               ▼                       ▼│
│                                          database.py (SQLite)  vision.py│
│                                          settings/users/logs   camera   │
│  Static: /media/{captures,frames,faces}                        thread   │
└─────────────────────────────────────────────────────────────────────┘
```

## Modules

### vision.py
- `CameraManager` owns a single `cv2.VideoCapture` in a **background thread** (capture is
  blocking). Async code reads the latest encoded JPEG; it never touches OpenCV directly.
- Face recognition runs only every `FACE_DETECT_EVERY_N_FRAMES` (default 15) on a
  downscaled frame, comparing against encodings cached from the `users` table.
- An `EventBus` fans recognised faces out to subscribers via `call_soon_threadsafe`
  (thread → asyncio). `/ws/events` forwards them to the kiosk for auto-interact.
- **Degrades:** no OpenCV → generated placeholder frame (Pillow); no face lib → no
  recognition, everything else works.

### ai_brain.py
- One async `httpx` client; provider chosen at call time from settings.
- `chat()` routes to OpenAI / DeepSeek (OpenAI-compatible) / Anthropic / Gemini, injecting
  persona + a language instruction (auto-detect or fixed default).
- `enhance_image()` routes image-to-image (OpenAI image edits / Gemini inline image).
- `text_to_speech()` ElevenLabs multilingual; `speech_to_text()` Whisper.
- Raises `AIError` (→ HTTP 400) when a key is missing or a provider errors.

### image_processor.py
Pipeline by `capture_id`: `raw` → `enhanced` (AI) → `framed` (Pillow alpha-composite of
the admin PNG) → `print` (flattened JPEG). Each stage is an addressable PNG under
`data/captures/`, so the kiosk modal can show whichever version exists.

### printer.py
Backend probe order: **pycups** → **lp/lpstat CLI** → **simulated**. `backend_name()`
reports which is active. Admin can list printers, set default (persisted + pushed to CUPS
via `lpoptions`), edit copies/media/colour, and run a generated test print.

### sharing.py / mailer.py / whatsapp.py (soft save + delivery)
- `sharing.save_capture(id)` writes the best version (frame burned in, enhanced if it
  exists) to `PB_PHOTOS_DIR/<YYYY-MM-DD>/<YYYY-MM-DD_HH-MM-SS>[_ai].jpg` in local time.
  Idempotent per capture+version; enhancing afterwards adds an `_ai` file.
- `sharing.kiosk_options()` = admin checkbox **AND** live service state. Served publicly at
  `GET /api/share/options`; the capture modal fetches it on open.
- `mailer` is the single SMTP path (photo emails + quiz vouchers). 465 → SMTP_SSL, else
  STARTTLS if `smtp_tls`. `verify()` sets `smtp_verified`; changing SMTP settings clears it.
- `whatsapp.service` runs a neonize linked-device client in a daemon thread (QR pairing,
  session in `DATA_DIR/whatsapp/`). `sharing.send_whatsapp` serialises sends behind an
  asyncio lock with min-interval + jitter, and enforces hour/day/per-number quotas counted
  from `logs` rows of type `share` (so they survive restarts).
- WhatsApp **QR mode** (default): `create_wa_code` issues a short-lived one-time code and a
  `wa.me` link (shown as a QR). The guest sends the pre-filled message; neonize's
  MessageEv → `whatsapp._handle_incoming` (1:1 text only) → `sharing._on_incoming_text`
  (thread → loop) → photo sent back into that chat. Anything without a live code is
  ignored — the bot never sends anything but that photo. The kiosk polls the code status
  for sent/failed.
- Routes: `routers/share.py` — public `options|save|email|whatsapp`,
  `whatsapp/code` (+ `/{code}` status, `/{code}/retry`), admin `status`,
  `email/test`, `whatsapp/{status,start,stop,logout,test}`, `photos`, `photos/file/...`.

### database.py
- `settings` is a typed key/value store (JSON values, `is_secret` flag). Adding a flag =
  add to `DEFAULT_SETTINGS`; it's seeded on `init_db()`.
- `users` holds a 128-d face encoding (JSON) never exposed to the API (`has_face` boolean
  instead). `logs` is the append-only event trail powering the Logs tab.

### security.py
Fernet key derived from `SECRET_KEY` (SHA-256). `encrypt`/`decrypt` tolerate legacy
plaintext; `mask` builds the `sk-****1234` previews. `require_admin` is the bearer gate.

## Frontend
- `KioskView` owns two WebSockets (stream + events) with auto-reconnect, the BotFace, and
  the capture flow. `useBot` composable encapsulates chat + mic recording + audio playback.
- `AdminView` is a token-gated shell loading settings + provider catalogue once and sharing
  them with the tab components via props/emit (`@save` posts a partial patch). Tabs that
  need live service state (SharingTab, WhatsAppTab) fetch `/api/share/status` themselves.
- Design tokens + component classes live in `src/style.css`; Tailwind config maps the
  brand/electric/ink palettes and the bot animations.

## Data flow: a full visit
1. Guest approaches → `vision` recognises/sees a face → `/ws/events` → kiosk asks
   `ai_brain.chat` for a greeting → ElevenLabs audio plays, BotFace = *speaking*.
2. Guest taps **Capture** → `image_processor.capture` saves `raw` → modal opens.
3. **AI Enhance** → `ai_brain.enhance_image` → `enhanced` PNG shown.
4. **Print** → frame overlay composited → `prepare_print` flattens → `printer.print_file`.
5. **Save / Email it / WhatsApp it** (if enabled in Save & Share) → `sharing.save_capture`
   → optional `mailer.send` / `whatsapp.service.send_image`. Errors → kiosk notice + Retry.
6. Every step writes a row to `logs`, visible in Admin → Logs.
