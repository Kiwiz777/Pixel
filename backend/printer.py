"""
printer.py - Linux CUPS printing integration.

On the Raspberry Pi the bot prints through CUPS. We support two backends:

1. pycups (preferred) - native libcups bindings. Install with `pip install
   pycups` (needs `libcups2-dev` on the Pi: `sudo apt install libcups2-dev`).
2. subprocess fallback - the standard `lpstat` / `lpadmin` / `lp` CLI tools
   that ship with CUPS, used if pycups isn't importable.

On a non-Linux dev machine neither is available, so the module runs in a
"simulated" mode: it reports a fake printer and pretends to print, so the
whole API and UI can be exercised without hardware.

CUPS setup reminder (Raspberry Pi OS / Debian)
----------------------------------------------
    sudo apt update
    sudo apt install -y cups cups-client libcups2-dev
    sudo usermod -aG lpadmin $USER          # allow managing printers
    sudo systemctl enable --now cups
    # add a USB printer (example):
    lpadmin -p PhotoBooth -E -v usb://... -m everywhere
    lpoptions -d PhotoBooth                  # set default
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import database as db

# --- Backend detection -----------------------------------------------------
try:
    import cups  # type: ignore

    _PYCUPS = True
except Exception:
    cups = None  # type: ignore
    _PYCUPS = False

_IS_LINUX = platform.system() == "Linux"
_HAS_LP = shutil.which("lp") is not None and shutil.which("lpstat") is not None


def backend_name() -> str:
    if _PYCUPS:
        return "pycups"
    if _HAS_LP:
        return "cli"
    return "simulated"


# --------------------------------------------------------------------------
# Listing printers
# --------------------------------------------------------------------------
def list_printers() -> list[dict[str, Any]]:
    default = get_default_printer()
    if _PYCUPS:
        conn = cups.Connection()
        printers = conn.getPrinters()
        out = []
        for name, info in printers.items():
            out.append({
                "name": name,
                "description": info.get("printer-info", name),
                "location": info.get("printer-location", ""),
                "state": _state_label(info.get("printer-state")),
                "is_default": name == default,
            })
        return out
    if _HAS_LP:
        return _list_printers_cli(default)
    # Simulated (dev / non-Linux).
    return [{
        "name": "PhotoBooth_Simulated",
        "description": "Simulated printer (no CUPS on this host)",
        "location": "dev",
        "state": "idle",
        "is_default": True,
    }]


def _list_printers_cli(default: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        res = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=10)
        for name in filter(None, (l.strip() for l in res.stdout.splitlines())):
            out.append({
                "name": name,
                "description": name,
                "location": "",
                "state": "idle",
                "is_default": name == default,
            })
    except Exception:
        pass
    return out


def _state_label(code: int | None) -> str:
    return {3: "idle", 4: "printing", 5: "stopped"}.get(code or 0, "unknown")


# --------------------------------------------------------------------------
# Default printer
# --------------------------------------------------------------------------
def get_default_printer() -> str:
    """Prefer the Admin-configured default; fall back to the CUPS default."""
    configured = db.get_setting("default_printer", "")
    if configured:
        return configured
    if _PYCUPS:
        try:
            return cups.Connection().getDefault() or ""
        except Exception:
            return ""
    if _HAS_LP:
        try:
            res = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, timeout=10)
            # "system default destination: PhotoBooth"
            if ":" in res.stdout:
                return res.stdout.split(":", 1)[1].strip()
        except Exception:
            return ""
    return ""


def set_default_printer(name: str) -> dict[str, Any]:
    """Persist the chosen default and, on Linux, tell CUPS too."""
    db.set_setting("default_printer", name)
    applied = False
    if _HAS_LP:
        try:
            subprocess.run(["lpoptions", "-d", name], capture_output=True, text=True, timeout=10)
            applied = True
        except Exception:
            applied = False
    return {"default_printer": name, "applied_to_cups": applied, "backend": backend_name()}


# --------------------------------------------------------------------------
# Print configuration
# --------------------------------------------------------------------------
def get_print_config() -> dict[str, Any]:
    return {
        "default_printer": get_default_printer(),
        "copies": db.get_setting("print_copies", 1),
        "media": db.get_setting("print_media", "4x6.Borderless"),
        "color_mode": db.get_setting("print_color_mode", "color"),
        "size_cm": db.get_setting("print_size_cm", "10x15"),
        "orientation": db.get_setting("print_orientation", "portrait"),
        "dpi": db.get_setting("print_dpi", 300),
        "fit": db.get_setting("print_fit", "cover"),
        "backend": backend_name(),
    }


def update_print_config(*, copies: int | None = None, media: str | None = None,
                        color_mode: str | None = None, size_cm: str | None = None,
                        orientation: str | None = None, dpi: int | None = None,
                        fit: str | None = None) -> dict[str, Any]:
    if copies is not None:
        db.set_setting("print_copies", max(1, int(copies)))
    if media is not None:
        db.set_setting("print_media", media)
    if color_mode is not None:
        db.set_setting("print_color_mode", color_mode)
    if size_cm is not None:
        db.set_setting("print_size_cm", size_cm)
    if orientation is not None:
        value = str(orientation).lower()
        db.set_setting("print_orientation",
                       value if value in ("portrait", "landscape", "auto") else "auto")
    if dpi is not None:
        db.set_setting("print_dpi", max(72, min(600, int(dpi))))
    if fit is not None:
        db.set_setting("print_fit", "contain" if str(fit).lower() == "contain" else "cover")
    return get_print_config()


# --------------------------------------------------------------------------
# Media (paper size) discovery
#
# Media names are printer-specific strings - dye-sub photo printers use names
# like "4x6.Borderless" or "om_100x150mm_100x150mm" - so they are queried from
# the printer rather than typed by hand. The Admin dropdown consumes this.
# --------------------------------------------------------------------------
_FALLBACK_MEDIA = (
    "4x6.Borderless",
    "4x6",
    "om_100x150mm_100x150mm",
    "Custom.100x150mm",
    "5x7",
    "A4",
    "Letter",
)


def _media_from_cli(printer: str) -> list[str]:
    """Parse `lpoptions -p NAME -l`, whose PageSize line marks the default with *."""
    try:
        res = subprocess.run(["lpoptions", "-p", printer, "-l"],
                             capture_output=True, text=True, timeout=10)
    except Exception:
        return []
    for line in res.stdout.splitlines():
        key, sep, values = line.partition(":")
        if not sep:
            continue
        # "PageSize/Media Size: 4x6 *4x6.Borderless Letter"
        if key.split("/", 1)[0].strip() not in ("PageSize", "media", "MediaSize"):
            continue
        return [v.lstrip("*") for v in values.split() if v.strip()]
    return []


def list_media(printer: str | None = None) -> dict[str, Any]:
    """Paper sizes the printer reports. `source` tells the UI how much to trust it."""
    printer = printer or get_default_printer()
    options: list[str] = []
    source = "fallback"

    if printer and _PYCUPS:
        try:
            attrs = cups.Connection().getPrinterAttributes(printer)
            options = [str(v) for v in (attrs.get("media-supported") or []) if v]
            if options:
                source = "ipp"
        except Exception:
            options = []

    if not options and printer and _HAS_LP:
        options = _media_from_cli(printer)
        if options:
            source = "lpoptions"

    if not options:
        options = list(_FALLBACK_MEDIA)
        source = "fallback"

    # Keep the configured value selectable even if the printer doesn't list it.
    current = str(db.get_setting("print_media", "4x6.Borderless"))
    if current and current not in options:
        options.append(current)

    seen: set[str] = set()
    unique = [o for o in options if not (o in seen or seen.add(o))]
    return {"printer": printer, "source": source, "media": unique, "current": current}


# --------------------------------------------------------------------------
# Execute a print job
# --------------------------------------------------------------------------
def print_file(file_path: str | Path, *, printer: str | None = None,
               copies: int | None = None) -> dict[str, Any]:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File to print not found: {file_path}")

    printer = printer or get_default_printer()
    copies = copies or int(db.get_setting("print_copies", 1))
    media = db.get_setting("print_media", "4x6.Borderless")
    color_mode = db.get_setting("print_color_mode", "color")

    orientation = str(db.get_setting("print_orientation", "auto")).lower()
    options = {
        "copies": str(copies),
        "media": media,
        "ColorModel": "RGB" if color_mode == "color" else "Gray",
    }

    if orientation != "auto":
        # prepare_print() has already cropped the photo to exactly the paper
        # shape, so CUPS must not "helpfully" rotate it. IPP
        # orientation-requested 3 = portrait / no rotation, 4 = landscape.
        options["orientation-requested"] = "4" if orientation == "landscape" else "3"
        # The image already matches the media aspect; scale it to the sheet
        # rather than letting CUPS letterbox it in the printable area.
        options["fit-to-page"] = "true"
    # In auto mode we send NO layout options at all, which is exactly what a
    # bare `lp file` does: CUPS scales the image to the printable area keeping
    # its aspect ratio, rotating 90 degrees when that fills more paper. That
    # prints the whole photo uncropped and near full-bleed.

    if _PYCUPS and printer:
        conn = cups.Connection()
        job_id = conn.printFile(printer, str(file_path), "PhotoBooth print", options)
        result = {"job_id": job_id, "backend": "pycups"}
    elif _HAS_LP and printer:
        cmd = ["lp", "-d", printer, "-n", str(copies),
               "-o", f"media={media}",
               "-o", f"ColorModel={options['ColorModel']}"]
        if orientation != "auto":
            cmd += ["-o", f"orientation-requested={options['orientation-requested']}",
                    "-o", "fit-to-page"]
        cmd.append(str(file_path))
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode != 0:
            raise RuntimeError(f"lp failed: {res.stderr.strip()}")
        result = {"job_id": res.stdout.strip(), "backend": "cli"}
    else:
        # Simulated print (dev / non-Linux).
        result = {"job_id": "sim-0001", "backend": "simulated"}

    db.add_log("print", message=f"Printed {file_path.name} x{copies}",
               response=str(result.get("job_id")),
               meta={"printer": printer, "options": options, "backend": result["backend"]})
    result.update({"printer": printer, "copies": copies, "file": file_path.name})
    return result


def job_status(job_id: int | str, printer: str | None = None) -> dict[str, Any]:
    if _PYCUPS:
        try:
            jobs = cups.Connection().getJobs()
            return {"job_id": job_id, "active": int(job_id) in jobs}
        except Exception:
            pass
    return {"job_id": job_id, "active": False, "backend": backend_name()}
