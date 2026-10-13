#!/usr/bin/env python3
"""Windows installers that have a native DevOS (Linux) version.

Some Windows programs start under the Windows layer but cannot fully work
there: remote-desktop tools (AnyDesk, TeamViewer) need Windows screen-capture
and input drivers, and AnyDesk crashed as soon as a session was used. When a
downloaded installer matches one of these, DevOS offers the native version
from Flathub instead; it installs per user, without a password.
"""

import os
import re
import shutil
import subprocess
from typing import Callable, Dict, List, Optional

FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"

# pattern -> (display name, Flathub id, why the native version is better)
CATALOG: List[Dict[str, str]] = [
    {"pattern": r"anydesk", "name": "AnyDesk", "flatpak": "com.anydesk.Anydesk",
     "why": "Remote control, file transfer and unattended access only work in the DevOS version."},
    {"pattern": r"zoom", "name": "Zoom", "flatpak": "us.zoom.Zoom",
     "why": "Camera, microphone and screen sharing work properly in the DevOS version."},
    {"pattern": r"discord", "name": "Discord", "flatpak": "com.discordapp.Discord",
     "why": "Voice, video and notifications work properly in the DevOS version."},
    {"pattern": r"spotify", "name": "Spotify", "flatpak": "com.spotify.Client",
     "why": "The DevOS version plays smoothly and uses less memory."},
    {"pattern": r"telegram", "name": "Telegram", "flatpak": "org.telegram.desktop",
     "why": "The DevOS version supports calls and notifications."},
    {"pattern": r"whatsapp", "name": "WhatsApp (ZapZap)", "flatpak": "com.rtosta.zapzap",
     "why": "WhatsApp has no Windows-layer support; this DevOS app opens WhatsApp Web with notifications."},
    {"pattern": r"steam", "name": "Steam", "flatpak": "com.valvesoftware.Steam",
     "why": "The DevOS version runs Windows games through Proton automatically."},
    {"pattern": r"obs[-_ ]?studio|^obs", "name": "OBS Studio", "flatpak": "com.obsproject.Studio",
     "why": "Screen and camera capture only work in the DevOS version."},
    {"pattern": r"slack", "name": "Slack", "flatpak": "com.slack.Slack",
     "why": "Calls, screen sharing and notifications work in the DevOS version."},
    {"pattern": r"firefox", "name": "Firefox", "flatpak": "org.mozilla.firefox",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"brave", "name": "Brave", "flatpak": "com.brave.Browser",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"gimp", "name": "GIMP", "flatpak": "org.gimp.GIMP",
     "why": "The DevOS version is faster and supports your graphics tablet."},
    {"pattern": r"blender", "name": "Blender", "flatpak": "org.blender.Blender",
     "why": "The DevOS version uses your graphics card directly."},
    {"pattern": r"audacity", "name": "Audacity", "flatpak": "org.audacityteam.Audacity",
     "why": "Recording works with your microphone in the DevOS version."},
    {"pattern": r"libreoffice", "name": "LibreOffice", "flatpak": "org.libreoffice.LibreOffice",
     "why": "The DevOS version opens Word, Excel and PowerPoint files natively."},
    {"pattern": r"postman", "name": "Postman", "flatpak": "com.getpostman.Postman",
     "why": "The DevOS version is faster and updates itself."},
    {"pattern": r"teamviewer", "name": "Remmina (remote desktop)", "flatpak": "org.remmina.Remmina",
     "why": "TeamViewer's Windows version cannot control this PC; Remmina is the DevOS remote-desktop app."},
]


def match(file_path: str) -> Optional[Dict[str, str]]:
    """Catalog entry for a downloaded installer, by its file name."""
    base = os.path.basename(file_path).lower()
    # Windows installers and Android packages: both have DevOS versions for
    # popular apps, which also saves the one-time Android download.
    if not base.endswith((".exe", ".msi", ".apk", ".xapk")):
        return None
    stem = os.path.splitext(base)[0]
    for entry in CATALOG:
        if re.search(entry["pattern"], stem):
            return entry
    return None


def is_installed(app_id: str) -> bool:
    if not shutil.which("flatpak"):
        return False
    out = subprocess.run(["flatpak", "info", app_id], capture_output=True, text=True)
    return out.returncode == 0


def parse_progress(line: str) -> Optional[int]:
    """Percentage from a flatpak install line ("Installing 2/3… ████  45%  2.1 MB/s")."""
    found = re.findall(r"(\d{1,3})%", line)
    if not found:
        return None
    value = int(found[-1])
    return value if 0 <= value <= 100 else None


def install(app_id: str, progress: Callable[[int, str], None] = None) -> Dict[str, str]:
    """Install for the current user from Flathub (no password needed)."""
    if not shutil.which("flatpak"):
        return {"status": "ERROR", "error": "App installs are not available on this system."}
    subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB_URL],
                   capture_output=True)
    proc = subprocess.Popen(
        ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", app_id],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    tail = []
    line = bytearray()
    while True:
        ch = proc.stdout.read(1)
        if not ch:
            break
        if ch not in (b"\r", b"\n"):
            line += ch
            continue
        text = line.decode("utf-8", "replace").strip()
        line.clear()
        if not text:
            continue
        tail = (tail + [text])[-3:]
        percent = parse_progress(text)
        if progress and percent is not None:
            progress(percent, "Downloading and installing...")
    proc.wait()
    if proc.returncode != 0:
        return {"status": "ERROR", "error": "The download did not finish. Check the internet connection.",
                "details": " | ".join(tail)}
    return {"status": "INSTALLED"}


def launch(app_id: str) -> None:
    subprocess.Popen(["flatpak", "run", app_id], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
