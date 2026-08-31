# Building Pixel for the Raspberry Pi

How to turn the source tree into a **compiled, self-contained binary** you can
ship on a Pi without handing over the source.

Running from source instead? That's [DEPLOYMENT_PI.md](DEPLOYMENT_PI.md) — no
compile step, and a much faster loop while you're still changing things.

---

## What you get

```
backend/build/run.dist/
├── pixel                  # the binary you run
├── libpython3.x.so.1.0    # bundled interpreter
├── *.so                   # compiled backend modules + deps (no .py anywhere)
└── frontend/dist/         # the built Vue app, served by the binary
```

Roughly **80–150 MB**. One process serves the kiosk, the admin dashboard, the
REST API and the WebSockets on port 8000. No nginx, no Node, and no Python
installation needed on the target to *run* it.

Nuitka compiles Python to C and then to real ARM machine code, so there is no
bytecode left to decompile. That's the point — PyInstaller would only bundle
`.pyc` files, which `pyinstxtractor` + a decompiler turn back into readable
source in minutes.

## What is *not* hidden

Be clear-eyed about this:

- **The frontend.** It ships to a browser, so it can only ever be minified.
- **Strings.** API endpoints, prompts and SQL are visible via `strings`.
- **Anyone with root on the device** can read the binary. Compilation raises the
  cost from "five minutes with a decompiler" to "a reverse-engineering project";
  it does not make the code secret. For stronger guarantees you need a read-only
  squashfs, a LUKS-encrypted app partition, and Pi secure boot.

---

## Where the build must run

**On the target architecture: a Pi 4 or Pi 5 running 64-bit Pi OS (Bookworm), or
an `aarch64` container.**

Nuitka compiles through the system C compiler and **cannot cross-compile**. An
x86 machine — including your Windows dev box — cannot produce an ARM binary, no
matter how it's configured. `build_pi.sh` warns if `uname -m` isn't `aarch64`.

The `.so` output is also locked to the exact Python minor version used to build
it, so build and run must use the same Python.

---

## One-shot: build + verify + install

Everything below this point — prerequisites, build, smoke test, install — is
also wired up as a single script, for redeploying after a change without
re-running each step by hand:

```bash
chmod +x deploy/deploy_pi.sh   # once
./deploy/deploy_pi.sh
```

Run it as your normal `pi` user, **not** with `sudo` — it calls `sudo` itself
only for the two steps that need it (apt/pip prerequisites, and the final
install). Already ran the prerequisites once? `./deploy/deploy_pi.sh
--skip-prereqs` skips straight to build → smoke test → install.

It stops at the first failure (e.g. a smoke test failure means it will
**not** install a broken build over your running service), and prints
exactly the same output as running each script manually. The sections below
explain what each step does and how to run it individually — useful when
only one part changed, or when troubleshooting.

## One-time prerequisites

```bash
sudo apt update
sudo apt install -y python3-dev build-essential patchelf ccache nodejs npm

# Nuitka + the app's dependencies must be importable by the SAME interpreter
# that runs the build.
pip3 install --break-system-packages nuitka
pip3 install --break-system-packages -r backend/requirements.txt
```

Using a venv instead? Install into it and point the build at it:

```bash
PYTHON=.venv/bin/python ./build_pi.sh
```

`ccache` is not optional in practice — without it every rebuild recompiles
everything from scratch.

---

## Build

```bash
cd backend
chmod +x build_pi.sh smoke_test.sh
./build_pi.sh
```

The script:

1. Runs `npm ci && npm run build` in `frontend/`, then **fails the build** if
   `index.html` is missing or if source maps leaked into `dist/assets/`.
2. Compiles with `nuitka --standalone`, bundling `frontend/dist` as data.
3. Deletes any residual `.py` / `__pycache__` from the output and strips
   symbols from the shared objects.

**Expect 20–60 minutes on a Pi 4 for the first build.** Later builds are much
faster thanks to `ccache`.

### Why `--standalone` and not `--onefile`

`--onefile` re-extracts the entire payload — interpreter, Pillow, everything —
to tmpfs on *every boot*. On a Pi that's a multi-second startup delay and
pointless SD/RAM churn for an appliance that never moves. `--standalone` boots
instantly, and dropping it into a read-only squashfs makes it just as opaque.

### Why opencv / dlib / pycups are excluded

`build_pi.sh` passes `--nofollow-import-to` for `cv2`, `face_recognition`,
`dlib`, `numpy` and `cups`. Bundling those for ARM is fragile, slow and huge —
and they're public open source, so hiding them buys nothing.

They stay in the Pi's system Python. `config.py` re-adds
`/usr/lib/python3/dist-packages` to `sys.path` when it detects a compiled build
(`PB_EXTRA_SITE_PACKAGES` overrides the path), so the guarded imports in
`vision.py` and `printer.py` still resolve at runtime.

---

## Smoke test — do not skip this

```bash
./smoke_test.sh
```

There is one specific risk with a compiled build: FastAPI introspects your
endpoints at runtime (`inspect.signature`) and resolves the string annotations
that `from __future__ import annotations` produces (`typing.get_type_hints`).
Nuitka's compiled functions implement that protocol, but it's the most likely
thing to break.

The script boots the binary on port 8901 against a throwaway state directory and
checks:

| Check | Proves |
|---|---|
| `GET /api/health` → 200 | the app boots at all |
| DB created outside the bundle | `PB_DATA_DIR` splitting works |
| `PUT /api/settings` → 200 | Pydantic body + `Depends()` survived compilation |
| `POST /api/ai/chat {}` → 422 | validation is real, not silently degraded |
| `PUT /api/settings` no token → 401 | the auth dependency still gates |
| `GET /` contains `id="app"` | the frontend was bundled |
| `GET /admin` → 200 | SPA history fallback works |

It takes 30 seconds and tells you in one shot whether the build is usable. Far
better than discovering a 500 at an event.

---

## Install

```bash
cd ..
chmod +x deploy/install_pi.sh
sudo ./deploy/install_pi.sh backend/build/run.dist
```

This:

- creates a `pixel` system user (no shell, no home) in the `video` and `lp` groups
- apt-installs the optional native libs if missing
- copies the bundle to `/opt/pixel`, **root-owned and read-only**
- creates `/var/lib/pixel` (mode 0700) for the database, captures and uploads
- generates `/etc/pixel/pixel.env` with a random `PB_ADMIN_TOKEN` and
  `PB_SECRET_KEY`, mode 0600 — **it prints the admin token once, save it**
- installs and starts the `pixel` systemd service

Kiosk: `http://<pi-ip>:8000`.

> **Secrets are never baked into the binary or the unit file.** They live only in
> `/etc/pixel/pixel.env`. Keep it that way — a token compiled into the image is a
> token you can't rotate.

---

## Rebuilding after a change

| Changed | Do this |
|---|---|
| Frontend only | `cd frontend && npm run build`, then re-run `build_pi.sh` (the data dir is bundled *into* the binary) |
| Backend only | re-run `build_pi.sh` — `ccache` makes it much quicker |
| Neither, just settings | nothing to rebuild; settings live in SQLite and the Admin edits them live |

There is no way to swap `frontend/dist` on an installed bundle without
recompiling, because it's embedded. If you're iterating on the UI, run from
source ([DEPLOYMENT_PI.md](DEPLOYMENT_PI.md)) until it's settled, then compile.

To deploy a rebuild:

```bash
sudo systemctl stop pixel
sudo ./deploy/install_pi.sh backend/build/run.dist
```

`install_pi.sh` keeps an existing `/etc/pixel/pixel.env` and leaves
`/var/lib/pixel` alone, so your settings, API keys and photos survive.

---

## Troubleshooting

**`No module named nuitka`** — Nuitka isn't installed for the interpreter running
the build. Use `PYTHON=/path/to/python ./build_pi.sh`.

**Build warns "not aarch64"** — you're on the wrong machine. The binary won't run
on the Pi. Build on the Pi.

**Smoke test fails on `PUT /api/settings`** — the introspection problem described
above. Check the server log the script prints; this is the one failure mode worth
reporting in detail.

**App starts but there's no UI** — `frontend/dist` wasn't bundled. Confirm
`frontend/dist/index.html` existed *before* the Nuitka step; `main.py` checks for
the directory at import time.

**`Cannot create state directory ...`** — `PB_DATA_DIR` points somewhere
unwritable. The systemd unit sets `/var/lib/pixel`; if you're running the binary
by hand, set it yourself.

**Camera or printer silently unavailable** — the system-site-packages fallback
didn't resolve. Check:

```bash
/usr/bin/python3 -c "import cv2, cups; print('ok')"
sudo systemctl show pixel -p Environment | tr ' ' '\n' | grep PB_
```

**Everything works but the kiosk camera doesn't** — `getUserMedia` requires a
secure context. `http://<pi-ip>:8000` from another machine blocks the camera; use
the Pi's own Chromium at `http://localhost:8000`.
