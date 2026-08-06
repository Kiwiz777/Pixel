# Raspberry Pi Deployment

Target: Raspberry Pi 4/5 (4GB+) running Raspberry Pi OS (64-bit, Bookworm).
64-bit OS matters — it gives prebuilt wheels for `cryptography` and friends.

## 1. System packages
```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev build-essential cmake \
  libcups2-dev cups cups-client \
  libatlas-base-dev libopenjp2-7 \
  chromium-browser

# camera: enable + test
sudo apt install -y v4l-utils
v4l2-ctl --list-devices
```

## 2. CUPS printer
```bash
sudo usermod -aG lpadmin "$USER"
sudo systemctl enable --now cups

# Discover and add a printer (USB example). 'everywhere' = driverless/IPP.
lpinfo -v
sudo lpadmin -p PhotoBooth -E -v "usb://Canon/SELPHY" -m everywhere
lpoptions -d PhotoBooth                       # set system default
lpstat -p -d                                  # verify

# 4x6 photo media is typical for photobooths:
lpoptions -p PhotoBooth -o media=4x6.Borderless
```
Later, confirm/override it in **Admin → Photobooth → Printer**.

## 3. App install
```bash
git clone <your-repo> /home/pi/photobooth && cd /home/pi/photobooth

# backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-pi.txt            # opencv + face-recognition + pycups
cp .env.example .env
#   set PB_SECRET_KEY=$(openssl rand -base64 48)
#   set PB_ADMIN_TOKEN to something strong
#   set PB_DATA_DIR=/home/pi/photobooth/backend/data

# frontend (build once; backend then serves dist/)
cd ../frontend
npm ci
npm run build
```

## 4. systemd service (backend)
`/etc/systemd/system/photobooth.service`:
```ini
[Unit]
Description=Photobooth Robot backend
After=network-online.target cups.service
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/photobooth/backend
EnvironmentFile=/home/pi/photobooth/backend/.env
ExecStart=/home/pi/photobooth/backend/.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now photobooth
journalctl -u photobooth -f
```
The backend serves the built SPA at `http://<pi>:8000/` (kiosk) and `/admin`.

## 5. Kiosk autostart (Chromium full-screen)
`/home/pi/.config/autostart/photobooth-kiosk.desktop`:
```ini
[Desktop Entry]
Type=Application
Name=Photobooth Kiosk
Exec=chromium-browser --kiosk --noerrdialogs --disable-infobars \
  --autoplay-policy=no-user-gesture-required \
  --use-fake-ui-for-media-stream http://localhost:8000/
X-GNOME-Autostart-enabled=true
```
`--autoplay-policy=no-user-gesture-required` lets ElevenLabs TTS play automatically;
`--use-fake-ui-for-media-stream` auto-grants camera/mic so kiosk needs no prompts.

## 6. Tuning (`.env`)
- `PB_STREAM_WIDTH/HEIGHT/FPS` — drop to 960×540 @ 15fps on a Pi 4 if the feed stutters.
- `PB_FACE_DETECT_EVERY_N` — raise (e.g. 25) to cut CPU; lower for snappier greetings.
- `PB_CAMERA_INDEX` — change if `/dev/video0` isn't the webcam.

## Troubleshooting
- **No video:** `v4l2-ctl --list-devices`; check `PB_CAMERA_INDEX`; ensure the user is in
  the `video` group.
- **Print fails:** `lpstat -p`, `lpq`; confirm default with `lpoptions -d`; check the
  backend reports `backend: pycups` or `cli` (not `simulated`) in Admin → Photobooth.
- **dlib/face-recognition build is slow:** expected on first install; increase swap
  (`sudo dphys-swapfile`) if it OOMs on a 2GB Pi.
- **TTS silent:** browser autoplay — confirm the Chromium autoplay flag above.
