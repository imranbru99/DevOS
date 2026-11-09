"""Run the official Windows App as a real app window, not a Chrome tab.

Cloud PC connects with window.open() of /webclient/. Chromium only keeps that
inside the Windows App window when the launch uses an installed PWA
(--app-id) and PwaNavigationCapturing. A plain --app=URL window sends the
Cloud PC into a normal Chrome tab — that is the failure users see.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

URL = "https://windows.cloud.microsoft/"
WM_CLASS = "chrome-windows.cloud.microsoft__-Default"
# Keep window.open() / Cloud PC inside the same app container (not a browser tab).
PWA_NAV = "PwaNavigationCapturing:aux_context_keep_same_container/true"
BASE_FEATURES = f"{PWA_NAV},PointerLockOptions,KeyboardLock,OverlayScrollbar"


def browser_binary():
    # Prefer Edge, then the diverted google-chrome wrapper (injects PWA_NAV for
    # every Chrome start), and only then the raw chrome binary.
    candidates = (
        ("edge", "/opt/microsoft/msedge/msedge"),
        ("edge", shutil.which("microsoft-edge-stable")),
        ("edge", shutil.which("microsoft-edge")),
        ("chrome", shutil.which("google-chrome-stable")),
        ("chrome", shutil.which("google-chrome")),
        ("chrome", "/opt/google/chrome/google-chrome"),
        ("chrome", "/opt/google/chrome/chrome"),
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


def applications_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"


def _app_id_from_desktop(text: str) -> str | None:
    if "windows.cloud.microsoft" not in text.lower() and "Windows App" not in text:
        return None
    m = re.search(r"--app-id=([a-z0-9]{32})", text)
    return m.group(1) if m else None


def discover_app_id(profile: Path | None = None) -> str | None:
    """Find a Chromium/Edge PWA app id for windows.cloud.microsoft."""
    pinned = os.environ.get("DEVOS_WINDOWS_APP_ID", "").strip()
    if re.fullmatch(r"[a-z0-9]{32}", pinned):
        return pinned

    apps = applications_dir()
    if apps.is_dir():
        for entry in sorted(apps.glob("chrome-*-Default.desktop")) + sorted(apps.glob("chrome-*.desktop")):
            try:
                text = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            found = _app_id_from_desktop(text)
            if found:
                return found

    if profile is None:
        return None

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
    return None


def focus_existing_window() -> bool:
    """Raise an already-open Windows App window if one exists."""
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

    try:
        out = subprocess.check_output(["ps", "-eo", "args"], text=True, timeout=3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    markers = ("--app-id=", f"--app={URL}", "windows.cloud.microsoft", "devos/windows-app/")
    for line in out.splitlines():
        if "windows.cloud.microsoft" in line or "devos/windows-app/" in line:
            if any(m in line for m in markers):
                return True
    return False


def _chrome_extra() -> list[str]:
    extra = ["--no-first-run", "--no-default-browser-check"]
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        extra.append("--disable-features=WaylandFractionalScaleV1")
    flags = os.environ.get("DEVOS_PWA_CHROME_FLAGS", "").strip()
    if flags:
        extra.extend(flags.split())
    return extra


def launch_via_default_pwa(app_id: str) -> list[str]:
    """Installed Windows App in the everyday Chrome profile — Cloud PC stays in-window."""
    family, binary = browser_binary()
    del family  # everyday profile; Edge/Chrome both accept --app-id
    return [
        binary,
        *_chrome_extra(),
        "--profile-directory=Default",
        f"--class={WM_CLASS}",
        f"--enable-features={BASE_FEATURES}",
        f"--app-id={app_id}",
    ]


def launch_command(app_id: str | None = None, *, isolated: bool = True):
    family, binary = browser_binary()
    profile = profile_dir(family) if isolated else None
    if app_id is None and profile is not None:
        app_id = discover_app_id(profile)
    if app_id is None:
        app_id = discover_app_id(None)

    # Prefer the everyday Chrome/Edge PWA when we have an id and isolation is
    # not forced — that is the only reliable Cloud PC window path.
    force_isolated = os.environ.get("DEVOS_WINDOWS_APP_ISOLATED", "").strip() in ("1", "true", "yes")
    if app_id and not force_isolated:
        return launch_via_default_pwa(app_id)

    cmd = [
        binary,
        *_chrome_extra(),
        f"--class={WM_CLASS}",
        f"--enable-features={BASE_FEATURES}",
        "--enable-gpu-rasterization",
        "--enable-zero-copy",
        "--ozone-platform-hint=auto",
    ]
    if profile is not None:
        cmd[1:1] = [
            f"--user-data-dir={profile}",
            "--profile-directory=Default",
        ]
    else:
        cmd.append("--profile-directory=Default")

    if app_id:
        cmd.append(f"--app-id={app_id}")
    else:
        # Last resort: tab risk remains until the PWA is installed.
        cmd.append(f"--app={URL}")
    return cmd


def _spawn(cmd: list[str]):
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
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )


def _wait_for_pwa_install(timeout_s: float = 30.0) -> str | None:
    """Chrome force-installs policy PWAs only while a real window is open."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = discover_app_id(None)
        if found:
            return found
        time.sleep(0.5)
    return None


def open_via_devos_pwa() -> bool:
    """Use the same installer path as other DevOS web apps (Office, Outlook…)."""
    pwa = shutil.which("devos-pwa")
    if not pwa:
        return False
    # Only when Chrome/Edge exists; otherwise fall through.
    try:
        browser_binary()
    except OSError:
        return False
    names = "Windows App|Microsoft Windows App"
    desktop = "devos-web-winapp.desktop"
    env = os.environ.copy()
    env["GTK_MODULES"] = ""
    env["GTK3_MODULES"] = ""
    env.pop("LOADED_GTK_MODULES", None)
    subprocess.Popen(
        [pwa, URL, names, desktop],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    return True


def open_isolated():
    if focus_existing_window():
        return None

    force_isolated = os.environ.get("DEVOS_WINDOWS_APP_ISOLATED", "").strip() in ("1", "true", "yes")
    app_id = discover_app_id(None)

    # Installed Windows App PWA → open as a real app window (Cloud PC stays here).
    if app_id and not force_isolated:
        return _spawn(launch_via_default_pwa(app_id))

    # No PWA yet: use DevOS PWA installer (policy force-list + --app-id).
    # This is what prevents Cloud PC from becoming "1 Chrome tab".
    if not force_isolated and open_via_devos_pwa():
        return None

    # Forced isolation or no devos-pwa: open a setup window, wait for install, relaunch.
    family, binary = browser_binary()
    profile = profile_dir(family)
    setup = [
        binary,
        f"--user-data-dir={profile}",
        "--profile-directory=Default",
        *_chrome_extra(),
        f"--class={WM_CLASS}",
        f"--enable-features={BASE_FEATURES}",
        f"--app={URL}",
        "--window-size=1280,800",
    ]
    proc = _spawn(setup)
    installed = _wait_for_pwa_install(30.0) or discover_app_id(profile)
    if installed:
        # Relaunch as PWA so the next Cloud PC connect stays in-window.
        if not force_isolated:
            _spawn(launch_via_default_pwa(installed))
        else:
            _spawn(launch_command(installed, isolated=True))
    return proc


if __name__ == "__main__":
    open_isolated()
