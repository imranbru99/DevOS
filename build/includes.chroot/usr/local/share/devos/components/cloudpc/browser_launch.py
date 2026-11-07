"""Run the official Windows App in a persistent, separate browser process.

Prefers a real installed PWA (--app-id) when the profile already has one, focuses
an existing Windows App window when possible, and falls back to --app=URL.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

URL = "https://windows.cloud.microsoft/"
WM_CLASS = "chrome-windows.cloud.microsoft__-Default"


def browser_binary():
    # Prefer a separately installed Edge; never reuse the everyday Chrome profile.
    candidates = (
        ("edge", "/opt/microsoft/msedge/msedge"),
        ("edge", shutil.which("microsoft-edge-stable")),
        ("edge", shutil.which("microsoft-edge")),
        ("chrome", "/opt/google/chrome/chrome"),
        ("chrome", shutil.which("google-chrome-stable")),
        ("chrome", shutil.which("google-chrome")),
        ("chromium", shutil.which("chromium")),
    )
    for family, candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return family, str(candidate)
    raise OSError("Install Microsoft Edge or Google Chrome to open Windows App.")


def profile_dir(family: str) -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    profile = base / "devos/windows-app" / family
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    return profile


def discover_app_id(profile: Path) -> str | None:
    """Find a Chromium/Edge PWA app id for windows.cloud.microsoft in this profile."""
    # Explicit override for admins / first-boot pinning.
    pinned = os.environ.get("DEVOS_WINDOWS_APP_ID", "").strip()
    if re.fullmatch(r"[a-z0-9]{32}", pinned):
        return pinned

    # Web Applications local state (Chromium PWA install records).
    candidates = [
        profile / "Default" / "Web Applications" / "Manifest Resources",
        profile / "Default" / "Extensions",
        profile / "Default",
    ]
    # Prefer desktop files created when the user installs the PWA.
    apps = Path.home() / ".local/share/applications"
    if apps.is_dir():
        for entry in apps.glob("chrome-*.desktop"):
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "windows.cloud.microsoft" not in text.lower() and "Windows App" not in text:
                continue
            m = re.search(r"--app-id=([a-z0-9]{32})", text)
            if m:
                return m.group(1)

    # Preferences / Local State may list installed web apps by URL.
    for name in ("Preferences", "Secure Preferences"):
        pref = profile / "Default" / name
        if not pref.is_file():
            continue
        try:
            data = json.loads(pref.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        blob = json.dumps(data)
        if "windows.cloud.microsoft" not in blob:
            continue
        for m in re.finditer(r'"app_id"\s*:\s*"([a-z0-9]{32})"', blob):
            return m.group(1)
        for m in re.finditer(r'"([a-z0-9]{32})"[^}]{0,200}windows\.cloud\.microsoft', blob):
            return m.group(1)

    # Last resort: scan any chrome-*-Default.desktop that mentions the portal.
    for path in candidates:
        if not path.exists():
            continue
    return None


def focus_existing_window() -> bool:
    """Raise an already-open Windows App window if one exists."""
    # wmctrl (X11 / XWayland)
    if shutil.which("wmctrl"):
        try:
            listing = subprocess.check_output(["wmctrl", "-lx"], text=True, timeout=3)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            listing = ""
        for line in listing.splitlines():
            low = line.lower()
            if WM_CLASS.lower() in low or "windows.cloud.microsoft" in low or "windows app" in low:
                wid = line.split()[0]
                subprocess.run(["wmctrl", "-ia", wid], check=False, timeout=3)
                return True

    # KWin (Wayland-friendly when available)
    for qd in ("qdbus6", "qdbus-qt6", "qdbus"):
        if not shutil.which(qd):
            continue
        try:
            # Best-effort: activate by caption match via kwin scripts is fragile;
            # try xdg-activation via desktop file if the process is already up.
            pass
        except OSError:
            continue

    # If a browser process already holds our isolated profile + app URL, avoid a second window.
    try:
        out = subprocess.check_output(["ps", "-eo", "args"], text=True, timeout=3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    marker = f"devos/windows-app/"
    for line in out.splitlines():
        if marker in line and ("--app-id=" in line or f"--app={URL}" in line or WM_CLASS in line):
            # Process exists; wmctrl may have failed on pure Wayland — still skip duplicate launch.
            return True
    return False


def launch_command(app_id: str | None = None):
    family, binary = browser_binary()
    profile = profile_dir(family)
    if app_id is None:
        app_id = discover_app_id(profile)
    cmd = [
        binary,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        "--no-first-run",
        "--no-default-browser-check",
        f"--class={WM_CLASS}",
        "--enable-features=PointerLockOptions,KeyboardLock,OverlayScrollbar",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ozone-platform-hint=auto",
    ]
    if app_id:
        cmd.append(f"--app-id={app_id}")
    else:
        cmd.append(f"--app={URL}")
    return cmd


def open_isolated():
    if focus_existing_window():
        return None
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "devos"
    state.mkdir(parents=True, exist_ok=True)
    fd = os.open(state / "windows-app-browser.log", os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    env = os.environ.copy()
    # Same Chromium+KDE trap as the main browser: colorreload-gtk-module SIGSEGVs
    # on theme/palette changes. Keep Windows App isolated from those modules.
    env["GTK_MODULES"] = ""
    env["GTK3_MODULES"] = ""
    env.pop("LOADED_GTK_MODULES", None)
    with os.fdopen(fd, "a") as log:
        return subprocess.Popen(
            launch_command(),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )


if __name__ == "__main__":
    open_isolated()
