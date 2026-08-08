# CLAUDE.md — Photobooth Robot ("Pixel")

Guidance for working in this repo. Read this first.

## What this is
A smart, conversational **photobooth robot companion**. A FastAPI backend drives a
webcam, AI providers, and a CUPS printer; a Vue 3 kiosk + admin frontend is the face.
Runs locally now, ultimately deploys on a **Raspberry Pi (Linux)**.

Two frontend surfaces:
- `/`        — public **Kiosk** (live feed, animated bot face, capture, voice chat)
- `/admin`   — secure **Admin** dashboard (behaviour, AI keys, printer, users, logs)

## Layout
```
backend/                FastAPI app (run from this dir)
  main.py               app + WebSockets (/ws/stream, /ws/events) + static /media
  config.py             paths, ports, secrets, camera tuning (env-overridable)
  database.py           SQLite: settings (kv), users, logs  + helpers
  security.py           Fernet encryption of API keys + admin bearer auth
  ai_brain.py           LLM router (OpenAI/Anthropic/Gemini/DeepSeek) + ElevenLabs TTS + Whisper STT
  vision.py             OpenCV camera thread, JPEG stream, frame-skipped face recognition, event bus
  image_processor.py    capture -> enhance -> PIL frame overlay -> print-ready JPEG
  printer.py            CUPS via pycups, falls back to lp/lpstat CLI, then simulated
  schemas.py            Pydantic request models
  routers/              settings, users, logs, printer, photobooth, ai
  requirements.txt      core deps (any OS)   |  requirements-pi.txt  hardware extras
frontend/               Vue 3 + Vite + Tailwind
  src/views/            KioskView.vue, AdminView.vue, admin/*Tab.vue
  src/components/        BotFace.vue, CaptureModal.vue, ToggleSwitch.vue
  src/composables/      useBot.js (chat + mic STT + TTS playback + VAD auto-stop),
                        useCamera.js (getUserMedia), usePresence.js (client face/motion
                        auto-interact), useSecretAccess.js (hidden admin gesture)
  src/lib/api.js        fetch wrapper + admin token + wsUrl()
docs/                   ARCHITECTURE.md, DEPLOYMENT_PI.md (run from source),
                        BUILD.md (compile to a shippable ARM binary)
```

## Running (dev)
Two terminals. See README.md for full detail.
```
# backend
cd backend && .venv/Scripts/python -m uvicorn main:app --reload --port 8000
# frontend (proxies /api,/media,/ws to :8000)
cd frontend && npm run dev      # http://localhost:5173
```

## Key design decisions (don't fight these)
- **Graceful degradation is mandatory.** `cv2`, `face_recognition`, `pycups`, and
  `cryptography` are all optional imports. The app MUST boot without them (it does on
  the 32-bit Windows dev box). Guard every hardware/native import in try/except and
  provide a fallback (placeholder frame, simulated printer, plaintext-but-working keys).
- **All runtime config lives in the SQLite `settings` table**, not in code. The Admin
  edits it live; no restart. Add new behaviour flags to `DEFAULT_SETTINGS` in database.py.
- **API keys are secrets.** Stored encrypted (Fernet via security.py), never returned to
  the UI in plaintext — only masked previews + a `<key>__set` boolean. Blank secret on
  PUT = keep existing (so masked previews posted back don't wipe keys).
- **Provider calls go through httpx REST**, not five vendor SDKs — uniform, light, and
  keys are read per-call from settings so switching provider is instant.
- **Frontend talks same-origin** (`/api`, `/ws`, `/media`); Vite proxies in dev, FastAPI
  serves `frontend/dist` in prod.

## Gotchas
- 32-bit Python on the dev box has **no wheels for cryptography/httptools** → we use
  `uvicorn` + `websockets` (not `uvicorn[standard]`) and let cryptography be optional.
- **Camera is browser-side** (`useCamera.js` getUserMedia) so the kiosk works on a laptop
  and on the Pi's Chromium. Capture grabs a `<canvas>` frame → uploads the blob to
  `POST /api/photobooth/capture` (multipart `frame`). Server-side OpenCV (`vision.py`,
  `/ws/stream`) still exists and is the path for **face-recognition auto-interact** on the
  Pi; the kiosk no longer renders the WS stream for the live feed.
- **SPA history fallback** lives in `main.py`: any non-`/api|/ws|/media|/assets` GET returns
  `index.html`. Without it, refreshing/deep-linking `/admin` on the FastAPI-served build
  404s → blank page. (This was the "blank admin after login" bug.)
- **No nav bar on the kiosk.** Admin is reached via a hidden gesture (`useSecretAccess.js`):
  type `admin` or 5-tap the invisible top-right hot-corner, both within 3s → `/admin`.
- Static media: `/media/{captures,frames,faces,backgrounds}`. Kiosk background (color/image/
  video/slideshow) is configured in **Admin → Kiosk** and read from `/api/settings/public`.
- `BotFace.vue` is **EMO-style**: borderless dark screen + glowing cyan eyes, no robot box.
- **TTS is provider-agnostic** (`tts_provider`: `openai` default | `elevenlabs`). OpenAI TTS
  (`/v1/audio/speech`) needs only the OpenAI key, so ElevenLabs is optional. STT = Whisper.
- **Auto-interact** has two paths: client-side presence (`usePresence.js`, browser
  FaceDetector→motion fallback) fires a generic greeting on the laptop; server-side OpenCV
  face rec (`/ws/events`) adds named greetings on the Pi.
- **Voice has VAD**: recording auto-stops after ~1.3s of silence (Web Audio RMS in
  `useBot.js`) — no manual "send". Manual stop still works.
- Admin auth = static bearer token `PB_ADMIN_TOKEN`. Fine for a LAN kiosk; swap for real
  sessions if it ever faces the internet.

## Conventions
- Backend modules keep the exact names from the spec (vision/image_processor/printer/
  ai_brain/database). Routers are thin; logic lives in the service modules.
- Frontend: semantic Tailwind component classes in `style.css` (`.btn-primary`, `.glass`,
  `.field`…). Design system = **Liquid Glass**, fonts **Fredoka** (display) + **Nunito**
  (body), brand orange `#F97316` + electric blue `#2563EB`. Respect `prefers-reduced-motion`.
- An **impeccable** design hook reviews every frontend write. Address real findings;
  document false positives.

## Verify after changes
- Backend: `cd backend && .venv/Scripts/python -m py_compile *.py routers/*.py`
- Frontend: `cd frontend && npm run build`
- Smoke: boot uvicorn, `curl /api/health`, `curl -X POST /api/photobooth/capture`.
