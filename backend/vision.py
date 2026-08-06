"""
vision.py - webcam capture, live streaming and face recognition.

Architecture
------------
* A single CameraManager owns the OpenCV VideoCapture. Grabbing frames is
  blocking, so it runs in a background *thread*; async code just reads the
  latest encoded JPEG.
* Face recognition is expensive, so we only run it every N frames
  (config.FACE_DETECT_EVERY_N_FRAMES) and inside the thread, comparing
  against encodings loaded from the SQLite `users` table.
* When a known/unknown face appears, we publish an event onto an asyncio
  event bus. main.py forwards those to the Kiosk over WebSocket so the
  frontend can trigger "auto-interact".

Graceful degradation
---------------------
If OpenCV or face_recognition aren't installed (e.g. plain Windows dev box),
the manager falls back to a generated placeholder frame so the Kiosk still
renders and the rest of the app keeps working.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import config
import database as db

# --- Optional heavy deps: degrade gracefully -------------------------------
try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    _CV2 = True
except Exception:
    cv2 = None  # type: ignore
    np = None  # type: ignore
    _CV2 = False

try:
    import face_recognition  # type: ignore

    _FACE = True
except Exception:
    face_recognition = None  # type: ignore
    _FACE = False


# --------------------------------------------------------------------------
# Event bus (publish/subscribe across asyncio tasks)
# --------------------------------------------------------------------------
class EventBus:
    """Fan-out async event bus. Each subscriber gets its own queue."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish_threadsafe(self, event: dict[str, Any]) -> None:
        """Publish from the camera thread into the asyncio loop."""
        if self._loop is None:
            return
        for q in list(self._subscribers):
            self._loop.call_soon_threadsafe(self._safe_put, q, event)

    @staticmethod
    def _safe_put(q: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


bus = EventBus()


# --------------------------------------------------------------------------
# Camera manager
# --------------------------------------------------------------------------
@dataclass
class _RecognitionState:
    known_encodings: list[Any] = field(default_factory=list)
    known_meta: list[tuple[int, str]] = field(default_factory=list)  # (user_id, name)
    last_announced: dict[str, float] = field(default_factory=dict)   # debounce per identity
    loaded: bool = False


class CameraManager:
    def __init__(self) -> None:
        self._cap = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._latest_frame = None            # raw BGR ndarray (for capture)
        self._frame_count = 0
        self._rec = _RecognitionState()
        self.available = _CV2

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="camera", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap is not None and _CV2:
            self._cap.release()
            self._cap = None

    def reload_faces(self) -> None:
        """Re-read known face encodings from the DB (call after Users change)."""
        self._rec.loaded = False

    # -- frame access ------------------------------------------------------
    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def capture_photo(self) -> bytes:
        """Return a high-quality JPEG of the current frame (for the photobooth)."""
        with self._lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
        if frame is None or not _CV2:
            return self._placeholder_jpeg(capture=True)
        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return buf.tobytes() if ok else self._placeholder_jpeg(capture=True)

    # -- background loop ---------------------------------------------------
    def _loop(self) -> None:
        if _CV2:
            self._open_camera()
        frame_interval = 1.0 / max(1, config.STREAM_FPS)
        while self._running:
            start = time.time()
            frame = self._grab_frame()
            if frame is not None:
                self._frame_count += 1
                with self._lock:
                    self._latest_frame = frame
                    self._latest_jpeg = self._encode_jpeg(frame)
                if (_FACE and self._frame_count % config.FACE_DETECT_EVERY_N_FRAMES == 0
                        and db.get_setting("face_recognition_enabled", True)):
                    self._recognize(frame)
            elapsed = time.time() - start
            time.sleep(max(0.0, frame_interval - elapsed))

    def _open_camera(self) -> None:
        self._cap = cv2.VideoCapture(config.CAMERA_INDEX)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.STREAM_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.STREAM_HEIGHT)
        if not self._cap.isOpened():
            self.available = False

    def _grab_frame(self):
        if not _CV2 or self._cap is None or not self._cap.isOpened():
            return self._placeholder_frame()
        ok, frame = self._cap.read()
        return frame if ok else None

    def _encode_jpeg(self, frame) -> bytes | None:
        ok, buf = cv2.imencode(
            ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), config.STREAM_JPEG_QUALITY]
        )
        return buf.tobytes() if ok else None

    # -- face recognition --------------------------------------------------
    def _ensure_faces_loaded(self) -> None:
        if self._rec.loaded:
            return
        self._rec.known_encodings = []
        self._rec.known_meta = []
        for user_id, name, enc in db.get_known_face_encodings():
            try:
                self._rec.known_encodings.append(np.array(enc))
                self._rec.known_meta.append((user_id, name))
            except Exception:
                continue
        self._rec.loaded = True

    def _recognize(self, frame) -> None:
        self._ensure_faces_loaded()
        try:
            small = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            locations = face_recognition.face_locations(rgb)
            if not locations:
                return
            encodings = face_recognition.face_encodings(rgb, locations)
        except Exception:
            return

        for enc in encodings:
            identity = "unknown"
            user_id = None
            if self._rec.known_encodings:
                distances = face_recognition.face_distance(self._rec.known_encodings, enc)
                best = int(np.argmin(distances))
                if distances[best] <= config.FACE_MATCH_TOLERANCE:
                    user_id, identity = self._rec.known_meta[best]
            self._announce(identity, user_id)

    def _announce(self, identity: str, user_id: int | None) -> None:
        """Debounce + publish a 'face_detected' event for auto-interact."""
        now = time.time()
        key = identity if identity != "unknown" else "unknown"
        last = self._rec.last_announced.get(key, 0)
        if now - last < 8.0:  # don't spam greetings
            return
        self._rec.last_announced[key] = now
        if user_id is not None:
            try:
                db.mark_user_seen(user_id)
                db.add_log("face", message=f"Recognised {identity}", user_id=user_id)
            except Exception:
                pass
        auto = bool(db.get_setting("auto_interact_mode", True))
        bus.publish_threadsafe({
            "type": "face_detected",
            "identity": identity,
            "user_id": user_id,
            "auto_interact": auto,
            "ts": now,
        })

    # -- placeholders (no camera / no cv2) ---------------------------------
    def _placeholder_frame(self):
        if not _CV2:
            return None
        img = np.zeros((config.STREAM_HEIGHT, config.STREAM_WIDTH, 3), dtype=np.uint8)
        img[:] = (32, 28, 40)
        cv2.putText(img, "No camera detected", (60, config.STREAM_HEIGHT // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.4, (180, 160, 220), 3, cv2.LINE_AA)
        return img

    _ph_cache: bytes | None = None

    def _placeholder_jpeg(self, capture: bool = False) -> bytes:
        if _CV2:
            frame = self._placeholder_frame()
            ok, buf = cv2.imencode(".jpg", frame)
            if ok:
                return buf.tobytes()
        # Pure-Python fallback via Pillow (works with zero OpenCV).
        from PIL import Image, ImageDraw
        import io

        im = Image.new("RGB", (config.STREAM_WIDTH, config.STREAM_HEIGHT), (32, 28, 40))
        d = ImageDraw.Draw(im)
        d.text((60, config.STREAM_HEIGHT // 2), "No camera detected", fill=(200, 180, 235))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=80)
        return out.getvalue()


# Module-level singleton used by main.py
camera = CameraManager()


# --------------------------------------------------------------------------
# Face enrolment helper (used by the Users admin endpoint)
# --------------------------------------------------------------------------
def compute_encoding_from_image(image_bytes: bytes) -> list[float] | None:
    """Compute a 128-d face encoding from an uploaded reference photo.
    Returns None if no face is found or face_recognition is unavailable."""
    if not _FACE:
        return None
    import io
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    arr = np.array(image)
    locations = face_recognition.face_locations(arr)
    if not locations:
        return None
    encodings = face_recognition.face_encodings(arr, locations)
    return encodings[0].tolist() if encodings else None
