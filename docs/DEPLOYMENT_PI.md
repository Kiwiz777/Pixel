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
pip install -r requirements-pi.txt            # opencv + face-recognition + pycups + neonize
cp .env.example .env
#   set PB_SECRET_KEY=$(openssl rand -base64 48)
#   set PB_ADMIN_TOKEN to something strong
#   set PB_DATA_DIR=/home/pi/photobooth/backend/data
#   set PB_PHOTOS_DIR=/home/pi/Pictures/pixel      # saved guest photos (see §7)

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
Run as the desktop user (not sudo; `deploy_pi.sh` does this for compiled builds):
```bash
bash deploy/install_kiosk_desktop.sh            # add --no-autostart to skip starting at login
```
This installs `~/.local/bin/pixel-kiosk` (from `deploy/pixel-kiosk.sh`), a **Start Pixel Kiosk**
desktop icon + app-menu entry, and login autostart. To leave the kiosk, tap the top-left corner
5 times within 3s → **Staff menu → Close kiosk**. The launcher polls `/api/kiosk/exit` and closes
Chromium (a page can't close a `--kiosk` browser, and the backend's `pixel` user can't kill it).
Only a request from the Pi itself is accepted. Double-click the icon to start it again.

The old hand-made autostart below is what the launcher replaces - the installer renames it to
`.bak` so you don't get two kiosks. `/home/pi/.config/autostart/photobooth-kiosk.desktop`:
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

## 7. Saved photos, email & WhatsApp
Configure in **Admin → Save & Share** and **Admin → WhatsApp**.

**Photos folder.** Soft-saved photos land in `PB_PHOTOS_DIR` as
`2026-09-28/2026-09-28_14-03-22.jpg` (local time; `_ai` suffix for enhanced versions).
Defaults: `backend/data/photos` from source, `/srv/pixel/photos` for the compiled install
(group `pixel`, so the login user can manage it — `install_pi.sh` adds you to the group).
Browse them in Admin → Save & Share → Saved photos, or share the folder on the LAN:
```bash
sudo apt install -y samba
sudo tee -a /etc/samba/smb.conf >/dev/null <<'EOF'
[pixel-photos]
   path = /srv/pixel/photos
   read only = yes
   guest ok = no
   valid users = @pixel
EOF
sudo smbpasswd -a "$USER" && sudo systemctl restart smbd
# Windows: \\<pi-ip>\pixel-photos   macOS: smb://<pi-ip>/pixel-photos
```

**Email.** Fill in SMTP (Gmail/Outlook need an *app password*), Save, then **Test
connection**. The kiosk only offers "Email it" after a test login succeeds, and any SMTP
edit requires a new test.

**WhatsApp.** Needs `neonize` (64-bit OS only; `install_pi.sh` installs it). Admin →
WhatsApp → **Connect**, then on the booth phone: Settings → Linked devices → scan the QR.
The session survives restarts. Use a dedicated number and keep the default send limits on
a new number — this is the linked-device protocol (like WhatsApp Web), so it's low-risk,
not ban-proof.

By default guests don't type a number: the kiosk shows a QR code that opens WhatsApp with
a message containing a one-time code (valid 5 minutes). When they send it, the booth
replies with their photo. The booth replies to nothing else, not even expired codes, so
don't expect "chatbot" answers when testing. Send the exact pre-filled message.

## Troubleshooting
- **No video:** `v4l2-ctl --list-devices`; check `PB_CAMERA_INDEX`; ensure the user is in
  the `video` group.
- **Print fails:** `lpstat -p`, `lpq`; confirm default with `lpoptions -d`; check the
  backend reports `backend: pycups` or `cli` (not `simulated`) in Admin → Photobooth.
- **dlib/face-recognition build is slow:** expected on first install; increase swap
  (`sudo dphys-swapfile`) if it OOMs on a 2GB Pi.
- **TTS silent:** browser autoplay — confirm the Chromium autoplay flag above.
- **WhatsApp tab says "Not installed":** `python3 -c 'import neonize'` in the Python that
  runs Pixel. Compiled build: pip puts it in `/usr/local/lib/python3.X/dist-packages`,
  which config.py searches automatically.
- **Email/WhatsApp checkbox greyed out:** the service isn't connected — run Test
  connection (email) or link the device (WhatsApp). Checked options for a disconnected
  service are simply hidden on the kiosk.
