"""Run the official Windows App as a real app window, not a Chrome tab.

Cloud PC connects with window.open() of /webclient/. Chromium only keeps that
inside the Windows App window when the launch uses an installed PWA
(--app-id) and PwaNavigationCapturing. A plain --app=URL window shows a URL
bar on login.microsoftonline.com and can send Cloud PC into a normal tab —
that is the failure users see. Match Windows: app chrome only, no omnibox.
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
# Keep window.open() / Cloud PC / Microsoft login inside the same app container.
PWA_NAV = "PwaNavigationCapturing:aux_context_keep_same_container/true"
BASE_FEATURES = f"{PWA_NAV},PointerLockOptions,KeyboardLock,OverlayScrollbar"


def browser_binary():
    # Prefer Chrome (diverted wrapper injects PWA_NAV on every start). Edge is
    # second — it has no equivalent divert and often falls back to --app=URL.
    prefer = (os.environ.get("DEVOS_WINDOWS_APP_BROWSER") or "chrome").strip().lower()
    chrome_first = (
        ("chrome", shutil.which("google-chrome-stable")),
        ("chrome", shutil.which("google-chrome")),
        ("chrome", "/opt/google/chrome/google-chrome"),
        ("chrome", "/opt/google/chrome/chrome"),
        ("edge", "/opt/microsoft/msedge/msedge"),
        ("edge", shutil.which("microsoft-edge-stable")),
        ("edge", shutil.which("microsoft-edge")),
        ("chromium", shutil.which("chromium")),
    )
    edge_first = (
        ("edge", "/opt/microsoft/msedge/msedge"),
        ("edge", shutil.which("microsoft-edge-stable")),
        ("edge", shutil.which("microsoft-edge")),
        ("chrome", shutil.which("google-chrome-stable")),
        ("chrome", shutil.which("google-chrome")),
        ("chrome", "/opt/google/chrome/google-chrome"),
        ("chrome", "/opt/google/chrome/chrome"),
        ("chromium", shutil.which("chromium")),
    )
    candidates = edge_first if prefer in ("edge", "msedge", "microsoft-edge") else chrome_first
    for family, candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return family, str(candidate)
    raise OSError("Install Google Chrome or Microsoft Edge to open Windows App.")


def profile_dir(family: str) -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    profile = base / "devos/windows-app" / family
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    return profile


def applications_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"


def everyday_browser_profiles() -> list[Path]:
    home = Path.home()
    return [
        home / ".config/google-chrome",
        home / ".config/chromium",
        home / ".config/microsoft-edge",
        home / ".config/microsoft-edge-stable",
    ]


def _app_id_from_desktop(text: str, filename: str = "") -> str | None:
    low = text.lower()
    if "windows.cloud.microsoft" not in low and "windows app" not in low:
        return None
    m = re.search(r"--app-id=([a-z0-9]{32})", text)
    if m:
        return m.group(1)
    # Updates rewrite Exec to devos-windows-app and drop --app-id. The id is
    # still the chrome-<id>-Default.desktop filename Chrome created.
    fm = re.fullmatch(r"chrome-([a-z0-9]{32})(?:-Default|-Profile_\d+)?\.desktop", filename)
    return fm.group(1) if fm else None


def _app_id_from_preferences(profile: Path) -> str | None:
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
        for m in re.finditer(r'"([a-z0-9]{32})"[^}]{0,240}windows\.cloud\.microsoft', blob):
            return m.group(1)
        for m in re.finditer(r'windows\.cloud\.microsoft[^}]{0,240}"([a-z0-9]{32})"', blob):
            return m.group(1)
    return None


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
            found = _app_id_from_desktop(text, entry.name)
            if found:
                return found

    candidates: list[Path] = []
    if profile is not None:
        candidates.append(profile)
    else:
        candidates.extend(everyday_browser_profiles())
        for family in ("chrome", "edge", "chromium"):
            candidates.append(
                Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
                / "devos/windows-app"
                / family
            )

    seen: set[Path] = set()
    for prof in candidates:
        try:
            key = prof.resolve()
        except OSError:
            key = prof
        if key in seen or not prof.is_dir():
            continue
        seen.add(key)
        found = _app_id_from_preferences(prof)
        if found:
            return found
    return None


def _window_ids() -> set[str]:
    if not shutil.which("wmctrl"):
        return set()
    try:
        listing = subprocess.check_output(["wmctrl", "-lx"], text=True, timeout=3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return set()
    ids = set()
    for line in listing.splitlines():
        low = line.lower()
        if WM_CLASS.lower() in low or "windows.cloud.microsoft" in low or "windows app" in low:
            parts = line.split()
            if parts:
                ids.add(parts[0])
    return ids


def _window_appeared(previous: set[str] | None = None, timeout_s: float = 2.0) -> bool:
    """True when a Windows App window is mapped. Unknown when wmctrl is absent."""
    if not shutil.which("wmctrl"):
        return True
    before = previous if previous is not None else set()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        now = _window_ids()
        if now - before:
            return True
        time.sleep(0.25)
    return False


def focus_existing_window() -> bool:
    """Raise a mapped Windows App window.

    A Chrome or installer process that merely mentions the portal is not a
    window. Treating it as one made the next click do nothing.
    """
    if not shutil.which("wmctrl"):
        return False
    try:
        listing = subprocess.check_output(["wmctrl", "-lx"], text=True, timeout=3)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False
    for line in listing.splitlines():
        low = line.lower()
        if WM_CLASS.lower() in low or "windows.cloud.microsoft" in low or "windows app" in low:
            parts = line.split()
            if not parts:
                continue
            subprocess.run(["wmctrl", "-ia", parts[0]], check=False, timeout=3)
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
    _family, binary = browser_binary()
    return [
        binary,
        *_chrome_extra(),
        "--profile-directory=Default",
        f"--class={WM_CLASS}",
        f"--enable-features={BASE_FEATURES}",
        f"--app-id={app_id}",
    ]


def allow_plain_app_url() -> bool:
    return os.environ.get("DEVOS_WINDOWS_APP_ALLOW_PLAIN_APP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def launch_command(app_id: str | None = None, *, isolated: bool = True):
    family, binary = browser_binary()
    profile = profile_dir(family) if isolated else None
    if app_id is None and profile is not None:
        app_id = discover_app_id(profile)
    if app_id is None:
        app_id = discover_app_id(None)

    # Prefer the everyday Chrome/Edge PWA when we have an id and isolation is
    # not forced — that is the only reliable Cloud PC / login window path.
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
    elif allow_plain_app_url() or force_isolated:
        # Setup / forced isolation only. Plain --app= shows a URL bar on
        # login.microsoftonline.com — never use for normal launches.
        cmd.append(f"--app={URL}")
    else:
        # Caller must install the PWA first (open_isolated waits for --app-id).
        cmd.append(f"--app-id=pending")
    return cmd


def _spawn(cmd: list[str]):
    if any(a == "--app-id=pending" for a in cmd):
        raise OSError("Windows App PWA is not installed yet.")
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


def _wait_for_pwa_install(timeout_s: float = 45.0) -> str | None:
    """Chrome force-installs policy PWAs only while a real window is open."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        found = discover_app_id(None)
        if found:
            return found
        time.sleep(0.5)
    return None


def _visible_window_command() -> list[str]:
    """Open the portal in the Chrome that is already running.

    A taskbar pin often hits an existing Chrome. --app-id is easy for that
    Chrome to ignore, so the click looks dead. A new window is visible.
    """
    _family, binary = browser_binary()
    return [
        binary,
        *_chrome_extra(),
        "--profile-directory=Default",
        "--new-window",
        URL,
    ]


def _portal_command() -> list[str]:
    """App window for the portal when a PWA id is not ready yet."""
    family, binary = browser_binary()
    force_isolated = os.environ.get("DEVOS_WINDOWS_APP_ISOLATED", "").strip() in ("1", "true", "yes")
    cmd = [
        binary,
        *_chrome_extra(),
        f"--class={WM_CLASS}",
        f"--enable-features={BASE_FEATURES}",
        f"--app={URL}",
        "--window-size=1280,800",
    ]
    if force_isolated:
        profile = profile_dir(family)
        cmd[1:1] = [f"--user-data-dir={profile}", "--profile-directory=Default"]
    else:
        cmd.insert(1, "--profile-directory=Default")
    return cmd


def open_via_devos_pwa() -> bool:
    """Use the same installer path as other DevOS web apps (Office, Outlook…)."""
    # devos-pwa used to exec this launcher, which started devos-pwa again.
    if os.environ.get("DEVOS_WINDOWS_APP_IN_PWA") == "1":
        return False
    pwa = shutil.which("devos-pwa")
    if not pwa:
        return False
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
    env["DEVOS_WINDOWS_APP_IN_PWA"] = "1"
    env["DEVOS_WINDOWS_APP_PARENT"] = "1"
    subprocess.Popen(
        [pwa, URL, names, desktop],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    return True


def _notify(message: str) -> None:
    if shutil.which("kdialog"):
        subprocess.Popen(
            ["kdialog", "--title", "Windows App", "--sorry", message],
            start_new_session=True,
        )
    elif shutil.which("notify-send"):
        subprocess.Popen(
            ["notify-send", "-a", "DevOS", "Windows App", message],
            start_new_session=True,
        )


def restore_menu_entry() -> None:
    """Remove a user shortcut that marks Windows App deleted.

    ~/.local/share/applications overrides /usr/share. The PWA installer used to
    write Hidden=true there, so the menu still showed a cached icon that would
    not open.
    """
    path = applications_dir() / "devos-web-winapp.desktop"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if "Hidden=true" not in text and "NoDisplay=true" not in text:
        return
    try:
        if "Exec=" not in text:
            path.unlink()
        else:
            kept = [
                line for line in text.splitlines()
                if line.strip() not in {"Hidden=true", "NoDisplay=true", "X-DevOS-Hidden=true"}
            ]
            path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")
    except OSError:
        return
    for cmd in ("kbuildsycoca6", "kbuildsycoca5"):
        if shutil.which(cmd):
            subprocess.Popen(
                [cmd],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            break


def open_isolated():
    restore_menu_entry()
    if focus_existing_window():
        return None

    force_isolated = os.environ.get("DEVOS_WINDOWS_APP_ISOLATED", "").strip() in ("1", "true", "yes")
    app_id = discover_app_id(None)

    # Installed Windows App PWA → real app window (no URL bar on Microsoft login).
    if app_id and not force_isolated:
        proc = _spawn(launch_via_default_pwa(app_id))
        # The running Chrome (the one with your other sites) often accepts the
        # process and then drops --app-id. If no Windows App window is mapped,
        # open a normal window so the click is visible.
        if _window_appeared():
            return proc
        return _spawn(_visible_window_command())

    # No PWA yet. Do not wait. The taskbar click must show a window now.
    if not force_isolated:
        open_via_devos_pwa()
        return _spawn(_visible_window_command())

    # Forced isolation: setup window only long enough to install, then --app-id.
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
    installed = _wait_for_pwa_install(45.0) or discover_app_id(profile)
    if installed:
        try:
            proc.terminate()
        except OSError:
            pass
        if not force_isolated:
            return _spawn(launch_via_default_pwa(installed))
        return _spawn(launch_command(installed, isolated=True))
    return proc


if __name__ == "__main__":
    open_isolated()
