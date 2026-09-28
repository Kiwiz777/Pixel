"""
main.py - FastAPI entrypoint for the Photobooth Robot backend.

Wires together:
  * REST routers (settings, users, logs, printer, photobooth, ai)
  * WebSocket /ws/stream  - live MJPEG-over-WS camera feed for the Kiosk
  * WebSocket /ws/events  - face-detected / auto-interact events for the Kiosk
  * Static /media         - captures + frames served to the frontend
  * Lifespan              - init DB, start camera thread, bind event bus loop

Run (dev):   uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import contextlib

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import ai_brain
import config
import database as db
import printer as printer_service
import sharing
import vision
import whatsapp
from routers import ai, contacts, logs, photobooth, printer, quiz, settings, share, users


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    db.init_db()
    vision.bus.bind_loop(asyncio.get_running_loop())
    vision.camera.start()
    sharing.bind_loop(asyncio.get_running_loop())  # WhatsApp photo codes -> replies
    if db.get_setting("whatsapp_enabled", False):
        whatsapp.service.start()  # no-op (state=unavailable) without neonize
    yield
    # --- shutdown ---
    whatsapp.service.stop()
    vision.camera.stop()
    await ai_brain.aclose()


app = FastAPI(title="Photobooth Robot API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST routers
app.include_router(settings.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(printer.router)
app.include_router(photobooth.router)
app.include_router(ai.router)
app.include_router(quiz.router)
app.include_router(contacts.router)
app.include_router(share.router)

# Static media (captures + uploaded frames + face refs)
app.mount("/media/captures", StaticFiles(directory=config.CAPTURES_DIR), name="captures")
app.mount("/media/frames", StaticFiles(directory=config.FRAMES_DIR), name="frames")
app.mount("/media/faces", StaticFiles(directory=config.FACES_DIR), name="faces")
app.mount("/media/backgrounds", StaticFiles(directory=config.BACKGROUNDS_DIR), name="backgrounds")
app.mount("/media/rewards", StaticFiles(directory=config.REWARDS_DIR), name="rewards")
app.mount("/media/wheel", StaticFiles(directory=config.WHEEL_DIR), name="wheel")
app.mount("/media/recordings", StaticFiles(directory=config.RECORDINGS_DIR), name="recordings")


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "camera_available": vision.camera.available,
        "printer_backend": printer_service.backend_name(),
        "whatsapp": whatsapp.service.state,
        "chat_provider": db.get_setting("active_chat_provider"),
    }


# --------------------------------------------------------------------------
# WebSocket: live camera stream (binary JPEG frames)
# --------------------------------------------------------------------------
@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    interval = 1.0 / max(1, config.STREAM_FPS)
    try:
        while True:
            frame = vision.camera.latest_jpeg()
            if frame is not None:
                await ws.send_bytes(frame)
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception:
        with contextlib.suppress(Exception):
            await ws.close()


# --------------------------------------------------------------------------
# WebSocket: bot events (face detected -> auto interact)
# --------------------------------------------------------------------------
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    await ws.accept()
    queue = vision.bus.subscribe()
    try:
        await ws.send_json({"type": "connected"})
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        vision.bus.unsubscribe(queue)


# --------------------------------------------------------------------------
# Optionally serve the built Vue app (production on the Pi).
# In dev, the Vite server handles the frontend instead.
#
# IMPORTANT: this is a single-page app using history-mode routing. A plain
# StaticFiles mount 404s on deep links like /admin (there is no admin.html),
# which shows up as a blank page on refresh. So we serve real files when they
# exist and fall back to index.html for every other (non-API) GET path.
# --------------------------------------------------------------------------
# Resolved in config.py so it works both in dev (sibling frontend/dist) and
# in a compiled build (bundled beside the code).
_DIST = config.DIST_DIR
if _DIST.exists():
    from fastapi.responses import FileResponse

    # Hashed build assets (JS/CSS/img) live under /assets.
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    _INDEX = _DIST / "index.html"
    _RESERVED = ("api/", "ws/", "media/", "assets/")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        # Never swallow API/WebSocket/media routes - let them 404 normally.
        if full_path.startswith(_RESERVED):
            raise HTTPException(status_code=404, detail="Not Found")
        # Serve a real static file if one exists (favicon, robots, etc.)...
        candidate = (_DIST / full_path).resolve()
        if full_path and candidate.is_file() and _DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        # ...otherwise hand back the SPA shell so vue-router can take over.
        return FileResponse(_INDEX)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
