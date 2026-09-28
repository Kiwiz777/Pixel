# 🤖 Pixel — Conversational Photobooth Robot

A smart, multilingual photobooth companion. It watches for guests with a webcam,
greets them in their language, takes photos, enhances them with AI, frames them,
and prints them on a CUPS printer. Built to run locally and deploy on a Raspberry Pi.

- **Backend:** Python · FastAPI · SQLite · OpenCV · Pillow · CUPS
- **Frontend:** Vue 3 · Vite · Tailwind (Liquid-Glass UI, Fredoka + Nunito)
- **AI:** OpenAI · Anthropic (Claude) · Google Gemini · DeepSeek · ElevenLabs (TTS) · Whisper (STT)
- **Languages spoken:** Egyptian Arabic, Gulf Arabic, English, Russian, German, French

---

## Features

| Kiosk (`/`) | Admin (`/admin`) |
|---|---|
| Full-screen live camera feed (WebSocket) | **General** — auto-interact, talk button, language, persona |
| Floating animated robot face (states) | **AI Providers** — keys + active chat/image models + voice |
| Capture · AI Enhance · Frame · Print | **Photobooth** — enhance prompt, PNG frame upload, printer |
| Save photo · Email it · WhatsApp it | **Save & Share** — soft/auto save, email service, saved-photo browser |
| "Talk to Me" voice chat (STT→LLM→TTS) | **WhatsApp** — link a number by QR, anti-ban send limits |
| Auto-greet on face detection | **Users** — enrol faces & bios for recognition |
| Quiz + prize wheel · Contact us | **Logs** — conversations, captures, prints, shares, errors |

---

## Quick start (development)

Requires **Python 3.11+** (64-bit recommended) and **Node 18+**.

### 1) Backend
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
# Optional hardware extras (camera, face rec, printer) — best on Linux/Pi:
# pip install -r requirements-pi.txt

cp .env.example .env          # then set PB_ADMIN_TOKEN to something strong
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Backend runs at **http://localhost:8000** (`/api/health`, docs at `/docs`).

> It boots fine **without** a camera/printer/face-lib — you'll get a placeholder
> feed and a simulated printer so you can develop the whole UI on any machine.

### 2) Frontend
```bash
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173** — Kiosk at `/`, Admin at `/admin`.
Vite proxies `/api`, `/media` and `/ws` to the backend on :8000.

### 3) First-time setup
1. Go to `/admin`, unlock with your `PB_ADMIN_TOKEN` (default `change-me-admin-token`).
2. **AI Providers** → paste API keys, pick the active Chat + Image models, load an ElevenLabs voice.
3. **Photobooth** → set the AI-Enhance prompt, upload a transparent PNG frame, pick a printer.
4. **Users** → add faces so Pixel greets returning guests by name.
5. Open the Kiosk and say hi 👋

---

## Production build
```bash
cd frontend && npm run build      # outputs frontend/dist
cd ../backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
When `frontend/dist` exists, the backend serves the SPA at `/` automatically — one origin, no proxy.

---

## Raspberry Pi deployment
See **[docs/DEPLOYMENT_PI.md](docs/DEPLOYMENT_PI.md)** for the full guide (CUPS setup,
systemd services, autostart kiosk in Chromium). CUPS in one paragraph:

```bash
sudo apt update && sudo apt install -y cups cups-client libcups2-dev
sudo usermod -aG lpadmin $USER
sudo systemctl enable --now cups
lpadmin -p PhotoBooth -E -v usb://YOUR/PRINTER -m everywhere   # add printer
lpoptions -d PhotoBooth                                        # set default
```
Then select it under **Admin → Photobooth → Printer**.

---

## Architecture
See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**. TL;DR:

```
Kiosk (Vue) ──ws/stream(JPEG)── FastAPI ── vision.py ── OpenCV camera
     │   └──ws/events(face)──────┘    ├── ai_brain.py ── OpenAI/Claude/Gemini/DeepSeek/ElevenLabs
     │                                ├── image_processor.py ── Pillow framing
     └──REST /api/*──────────────────┤── printer.py ── CUPS
Admin (Vue) ──REST (bearer token)────┴── database.py ── SQLite (settings/users/logs)
```

## Security notes
- API keys are encrypted at rest (Fernet) and never sent back to the browser.
- Admin endpoints require `Authorization: Bearer <PB_ADMIN_TOKEN>`.
- Set `PB_SECRET_KEY` and a strong `PB_ADMIN_TOKEN` in `.env` before any real deployment.
