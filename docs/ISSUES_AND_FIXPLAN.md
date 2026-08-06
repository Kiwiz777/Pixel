# Issues & Fix Plan — Conversation + Face Recognition

_Logged 2026-06-22. Status: **Phase 1 + Phase 2 IMPLEMENTED & verified.** Phase 3 polish remains._

## ✅ What was implemented (2026-06-22)
- **Conversation loop** (`useBot.js` `converse()`): greet → auto-listen (VAD) → reply →
  repeat, ending on silence / farewell / 8-turn cap. Wired into kiosk auto-greet, the
  `/ws/events` named-greeting path, and the "Talk to Me" button (now toggles "End chat").
- **Client-side face recognition** (`useFaceId.js` + face-api.js, models in
  `frontend/public/models/`): enrol in **Admin → Users** via webcam capture or photo upload
  (descriptor computed in-browser); kiosk computes a live descriptor on presence and calls
  `POST /api/users/match` to greet returning guests by name in their language.
- **Backend**: `POST /api/users` accepts `face_descriptor` (JSON 128 floats); new public
  `POST /api/users/match` returns the best match (Euclidean ≤ 0.55) without exposing biometrics.
- Verified: enrol→match returns the right person (dist 0.11), far descriptor returns null,
  frontend builds, backend boots clean.

Original diagnosis below for reference.

---

## Reported symptoms
1. **User creation "not working"** — adding a person in Admin → Users doesn't result in
   the robot recognising them later.
2. **Bot only greets** — on the kiosk it just says a one-liner ("Hello, say cheese / wave
   to the camera") in various languages and stops.
3. **No conversation after greeting** — it never talks *with* the guest; the greeting is a
   dead end.
4. **Face not recorded** — the person's face isn't stored for later identification.

---

## Root-cause analysis

### A. Face recognition is dead on this machine (covers #1 and #4)
- `face_recognition` (dlib) is **not installed** on the 32-bit Windows dev box — no wheels,
  needs a compiler. So `vision.compute_encoding_from_image()` **returns `None`**.
  Result: a user IS created, but with **no `face_encoding`**, so matching can never happen.
  (User creation likely succeeds at the HTTP level; the *useful* part — the encoding —
  silently no-ops. UI also doesn't make this obvious.)
- Even with the lib, recognition lives in **`vision.py` (server-side OpenCV)**, but we moved
  the camera to the **browser** (getUserMedia). The server now receives **no frames**, so
  `_recognize()` never runs on the laptop regardless. Server-side rec only works on the Pi.
- Net: on the dev laptop there is **zero** enrollment and **zero** recognition.

### B. The greeting is a one-shot, not a conversation (covers #2 and #3)
- Auto-interact flow: presence/`/ws/events` → `bot.ask(greetingPrompt)` → speak once →
  `botState` returns to **idle**. Nothing starts listening afterward.
- So the only way to continue is to manually tap **"Talk to Me."** The robot feels like it
  "only says hello." There is **no conversation loop** (listen → reply → listen …).
- Secondary: the greeting prompt is generic, so replies cluster around "say cheese / wave."

---

## Fix plan

### Phase 1 — Conversation loop (no new deps, high impact) ⟵ do first
Make a greeting flow into a real back-and-forth.
- In `useBot.js`, add a `conversing` flag and a `converse()` cycle:
  `speak → auto-startListening (VAD) → STT → ask → speak → repeat`.
- End the loop when: VAD detects no speech for ~6 s (guest left), the guest says a
  farewell, an explicit "Done" tap, or a turn cap (~6 turns).
- In `KioskView.triggerAutoGreet()` / `onFaceDetected()`: after the greeting audio ends,
  enter `converse()` instead of going idle.
- Keep manual "Talk to Me" working (it just enters the same loop).
- Vary/empower the greeting via the **persona** + recognised name so it's not always
  "say cheese."
- Files: `frontend/src/composables/useBot.js`, `frontend/src/views/KioskView.vue`.

### Phase 2 — Face recognition that works on laptop AND Pi (client-side)
Move face recognition into the browser so it no longer depends on server-side dlib and
works wherever the camera does. Use **face-api.js** (TinyFaceDetector + FaceLandmark68 +
FaceRecognitionNet → 128-d descriptor).
- **Frontend**
  - `npm i face-api.js`; host model weights in `frontend/public/models/`.
  - New `composables/useFaceId.js`: load models once; `describe(videoOrImg) -> Float32Array(128)`.
  - **Enrollment (Admin → Users):** capture from webcam (or uploaded image) → compute
    descriptor in browser → send the **descriptor array** to the backend (not just the image).
  - **Recognition (kiosk):** on presence, compute the live descriptor and match against
    enrolled users — either client-side (fetch descriptors once) or via a backend match
    endpoint. On match, greet by name and start the Phase-1 conversation loop.
- **Backend** (mostly already there — `users.face_encoding` stores a JSON 128-float list)
  - Extend `POST /api/users` and `PUT /api/users/{id}` to accept an optional
    `face_descriptor` (JSON list) and store it via `create_user/update_user`.
  - Add `GET /api/users/descriptors` (returns `[{id,name,language,descriptor}]`) for
    client-side matching, **or** `POST /api/users/match` (body: descriptor) that returns the
    best user using Euclidean distance ≤ ~0.5.
  - Keep the existing OpenCV/dlib path as an optional Pi fallback; gate behind the lib check.
- Files: `frontend/src/composables/useFaceId.js` (new),
  `frontend/src/views/admin/UsersTab.vue`, `frontend/src/views/KioskView.vue`,
  `backend/routers/users.py`, `backend/database.py` (helpers already support it),
  `backend/vision.py` (mark server-side rec as Pi-only fallback).

### Phase 3 — Polish
- Debounce/cooldown so it greets a returning face once per visit.
- Store a face thumbnail at enrollment for the Admin list (already partially done).
- Optional liveness (ignore static photos), multi-face handling.
- Surface enrollment success/failure clearly in Admin → Users (e.g. "Face captured ✓"),
  and confirm the create request errors are shown.

---

## Quick verification checklist (after fixing)
- [ ] Admin → Users: add a person via webcam capture → list shows a "face ✓" badge.
- [ ] `GET /api/users` shows `has_face: true` for that user.
- [ ] Kiosk: stepping into frame greets **by name** (after enrollment) and then **listens**.
- [ ] Speaking a reply continues the conversation without tapping "Talk to Me."
- [ ] Conversation ends gracefully when the guest leaves / is silent.
- [ ] Works on the dev laptop (client-side face-api.js, no dlib).

## Notes / gotchas
- face-api.js model weights (~6 MB) must be bundled in `public/models/` so the kiosk works
  offline on the Pi.
- Browser camera permission + autoplay flags already covered in `docs/DEPLOYMENT_PI.md`.
- TTS is OpenAI by default now; conversation loop should reuse `bot.ask(..., {speak:true})`.
- Keep VAD thresholds (`SILENCE_RMS`, `SILENCE_HOLD_MS` in `useBot.js`) in mind when tuning
  the "guest left" timeout.
