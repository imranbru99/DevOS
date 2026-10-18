#!/usr/bin/env python3
"""
DevOS Apps - the "Installed apps" manager.

One window that lists every app the user can launch (Linux apps, Windows
apps and Android apps), with search, sort, a type filter and per-app
actions: Open, Uninstall, Clear cache and Clear data & cookies (reset).

Everything that decides *what* happens (discovery, size computation,
command / deletion plans) lives in plain classes that import without a
display and are covered by tests/unit/test_apps_manager.py. PyQt5 is only
imported inside run_gui().

User-facing text never names the underlying tools; scrub() makes sure of
that for strings that come from command output.

CLI:
  apps_manager.py                         open the window
  apps_manager.py --list                  JSON of discovered apps
  apps_manager.py --dry-run-uninstall ID  JSON plan, nothing is executed
  apps_manager.py --uninstall ID          window focused on ID + confirm
                                          (ID may be a .desktop file path)
"""

import argparse
import glob
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PLATFORM_LINUX = "linux"
PLATFORM_WINDOWS = "windows"
PLATFORM_ANDROID = "android"

TYPE_LABELS = {
    PLATFORM_LINUX: "Linux app",
    PLATFORM_WINDOWS: "Windows app",
    PLATFORM_ANDROID: "Android app",
}
TYPE_SYSTEM = "System app"

SYSTEM_APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications"]

# Desktop ids (file name without .desktop, compared lowercase) that are part
# of DevOS itself or core system tools. They are not listed at all.
PROTECTED_DESKTOP_IDS = {
    "org.kde.dolphin", "org.kde.konsole", "systemsettings",
    "org.kde.systemsettings", "kinfocenter", "org.kde.kinfocenter",
    "org.kde.plasma-systemmonitor", "calamares", "install-debian",
    "org.kde.plasmashell", "org.kde.krunner", "org.kde.kmenuedit",
    "org.kde.khelpcenter", "org.kde.kscreen", "org.kde.polkit-kde-authentication-agent-1",
}
PROTECTED_DESKTOP_PREFIXES = ("devos-",)

# Entries that belong to the compatibility layers / package tooling. Their
# names would leak tool names and removing them breaks other apps.
HIDDEN_DESKTOP_PREFIXES = (
    "wine", "waydroid", "org.kde.discover", "flatpak", "software-properties",
    "apturl", "update-manager", "synaptic", "gdebi", "ubuntu", "debian-",
    "kcm_", "org.kde.kcm",
)

# Packages that are always shown as "System app" and cannot be uninstalled.
PROTECTED_PACKAGES = {
    "plasma-desktop", "plasma-workspace", "plasma-framework", "kwin-x11",
    "kwin-common", "kwin-wayland", "sddm", "systemsettings", "dolphin",
    "konsole", "calamares", "python3", "python3-minimal", "python3-pyqt5",
    "network-manager", "plasma-nm", "pipewire", "pipewire-pulse",
    "wireplumber", "pulseaudio", "plasma-pa", "kinfocenter",
    "plasma-systemmonitor", "kde-cli-tools", "khelpcenter", "kscreen",
    "powerdevil", "bluedevil", "plasma-discover", "kio", "kded5",
    "xdg-desktop-portal-kde", "xorg", "xserver-xorg-core", "policykit-1",
    "polkit-kde-agent-1", "pkexec", "polkitd", "systemd", "sudo", "apt",
    "dpkg", "flatpak", "waydroid", "wine", "wine64", "wine32",
    "kubuntu-desktop", "ubuntu-minimal", "ubuntu-standard", "linux-generic",
    "grub-efi-amd64", "grub-pc", "shim-signed", "snapper", "breeze",
    "plasma-integration", "frameworkintegration", "kmenuedit", "kscreenlocker",
    "kwalletmanager", "kwallet", "libkf5wallet-bin", "ark",
}
PROTECTED_PRIORITIES = {"required", "important"}

# Android packages that ship with the Android image itself.
ANDROID_SYSTEM_PREFIXES = ("com.android.", "android.", "org.lineageos.",
                           "com.google.android.", "org.chromium.webview")

# Words the user must never see in this UI, and what to say instead.
_BANNED = [
    (r"apt-get", "installer"), (r"apt", "installer"), (r"dpkg", "installer"),
    (r"flatpak", "app store"), (r"waydroid", "Android"), (r"wine", "Windows support"),
    (r"ubuntu", "DevOS"), (r"plasma", "desktop"), (r"kde", ""),
]
_BANNED_RE = re.compile(r"\b(" + "|".join(p for p, _ in _BANNED) + r")\b", re.IGNORECASE)
_BANNED_MAP = {p: r for p, r in _BANNED}

# Chromium-style and Gecko browsers. Paths are relative to $HOME.
BROWSERS = {
    "chrome": {
        "ids": {"google-chrome", "google-chrome-stable", "google-chrome-beta", "com.google.chrome"},
        "engine": "chromium", "profiles": [".config/google-chrome"],
        "full": [".config/google-chrome"], "caches": [".cache/google-chrome"],
        "procs": ["chrome"],
    },
    "chromium": {
        "ids": {"chromium", "chromium-browser", "org.chromium.chromium"},
        "engine": "chromium", "profiles": [".config/chromium"],
        "full": [".config/chromium"], "caches": [".cache/chromium"],
        "procs": ["chromium", "chromium-browser"],
    },
    "edge": {
        "ids": {"microsoft-edge", "microsoft-edge-stable", "com.microsoft.edge"},
        "engine": "chromium", "profiles": [".config/microsoft-edge"],
        "full": [".config/microsoft-edge"], "caches": [".cache/microsoft-edge"],
        "procs": ["msedge"],
    },
    "brave": {
        "ids": {"brave-browser", "com.brave.browser"},
        "engine": "chromium", "profiles": [".config/BraveSoftware/Brave-Browser"],
        "full": [".config/BraveSoftware/Brave-Browser"],
        "caches": [".cache/BraveSoftware/Brave-Browser"], "procs": ["brave"],
    },
    "vivaldi": {
        "ids": {"vivaldi-stable", "vivaldi"},
        "engine": "chromium", "profiles": [".config/vivaldi"],
        "full": [".config/vivaldi"], "caches": [".cache/vivaldi"],
        "procs": ["vivaldi-bin"],
    },
    "falkon": {
        "ids": {"org.kde.falkon", "falkon"},
        "engine": "chromium", "profiles": [".config/falkon/profiles"],
        "full": [".config/falkon", ".local/share/falkon"], "caches": [".cache/falkon"],
        "procs": ["falkon"],
    },
    "firefox": {
        "ids": {"firefox", "firefox-esr", "org.mozilla.firefox"},
        "engine": "gecko", "profiles": [".mozilla/firefox"],
        "full": [".mozilla/firefox"], "caches": [".cache/mozilla/firefox"],
        "procs": ["firefox", "firefox-bin", "firefox-esr"],
    },
}
# Inside each profile directory. History, Login Data and Bookmarks are kept.
CHROMIUM_COOKIE_ITEMS = [
    "Cookies", "Cookies-journal", "Network/Cookies", "Network/Cookies-journal",
    "Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage",
    "Service Worker/ScriptCache",
]
CHROMIUM_CACHE_ITEMS = ["Cache", "Code Cache", "GPUCache", "Service Worker/CacheStorage"]
GECKO_COOKIE_ITEMS = ["cookies.sqlite", "cookies.sqlite-wal", "cookies.sqlite-shm",
                      "cache2", "startupCache"]
GECKO_CACHE_ITEMS = ["cache2", "startupCache"]

# Extra config dir names for apps whose folder differs from their id.
CONFIG_ALIASES = {
    "code": ["Code"], "codium": ["VSCodium"], "vscodium": ["VSCodium"],
    "com.visualstudio.code": ["Code"], "com.vscodium.codium": ["VSCodium"],
    "obs-studio": ["obs-studio"], "slack": ["Slack"], "discord": ["discord"],
    "spotify": ["spotify"], "libreoffice": ["libreoffice"],
}
# Cache folders that live under ~/.config (Electron apps).
ELECTRON_CACHE_ITEMS = ["Cache", "CachedData", "Code Cache", "GPUCache",
                        "Service Worker/CacheStorage", "logs"]

# Folder names that must never be deleted as an "app folder".
DENY_VARIANTS = {
    "kde", "plasma", "kdedefaults", "autostart", "systemd", "pulse", "dconf",
    "fontconfig", "menus", "gtk-2.0", "gtk-3.0", "gtk-4.0", "devos",
    "applications", "icons", "fonts", "mime", "environment.d", "xsettingsd",
    "kded5", "kded6", "session", "trash", "keyrings", "kwalletd", "kwallet",
    "baloo", "akonadi", "flatpak", "waydroid", "winlayer", "wine", "mozilla",
    "nvidia", "ibus", "fcitx", "pipewire", "wireplumber", "dbus-1", "ssh",
    "gnupg", "python", "python3", "java", "system", "settings", "app", "apps",
    "files", "terminal", "browser", "editor", "update", "software", "help",
    "media", "x11", "xorg", "desktop", "config", "cache", "share", "local",
    "data", "user", "home", "org", "com", "net", "kio", "kf5", "kf6",
    "evolution", "goa-1.0", "containers", "docker", "git", "npm", "pip",
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def scrub(text: str) -> str:
    """Replace tool names with plain words for anything shown to the user."""
    if not text:
        return text

    def repl(m):
        return _BANNED_MAP.get(m.group(1).lower(), "")

    out = _BANNED_RE.sub(repl, text)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def human_size(n: Optional[int]) -> str:
    if n is None:
        return "—"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}" if n < 100 else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_human_size(text: str) -> Optional[int]:
    """'1.2 GB' / '352,6 MB' / '12 kB' / '900 bytes' -> bytes."""
    if not text:
        return None
    m = re.search(r"([\d.,]+)\s*([kKMGT]?i?B|bytes?)?", text.replace(" ", " "))
    if not m:
        return None
    num = m.group(1).replace(",", ".")
    if num.count(".") > 1:
        num = num.replace(".", "", num.count(".") - 1)
    try:
        val = float(num)
    except ValueError:
        return None
    unit = (m.group(2) or "B").upper()
    mult = {"B": 1, "BYTE": 1, "BYTES": 1, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3,
            "TB": 1000 ** 4, "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3,
            "TIB": 1024 ** 4}.get(unit, 1)
    return int(val * mult)


def dir_size(path: str) -> int:
    """Bytes used under path; never follows symlinks, skips errors."""
    total = 0
    seen = set()
    try:
        st = os.lstat(path)
    except OSError:
        return 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size
    for root, dirs, files in os.walk(path, topdown=True, followlinks=False):
        for name in files + [d for d in dirs if os.path.islink(os.path.join(root, d))]:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += getattr(st, "st_blocks", 0) * 512 or st.st_size
    return total


def strip_arch(pkg: str) -> str:
    return pkg.split(":", 1)[0].strip()


def is_within(path: str, root: str) -> bool:
    """True if path is strictly inside root (both already absolute/real)."""
    path = os.path.normpath(path)
    root = os.path.normpath(root)
    if path == root:
        return False
    return path.startswith(root.rstrip(os.sep) + os.sep)


def resolved_target(path: str) -> str:
    """Real location of `path` itself: parents resolved, the last component
    is NOT followed (deleting a symlink removes the link, not its target)."""
    ap = os.path.abspath(path)
    return os.path.join(os.path.realpath(os.path.dirname(ap)), os.path.basename(ap))


def safe_target(path: str, roots: Iterable[str]) -> bool:
    """A deletion target is allowed only if it really lives inside a root."""
    target = resolved_target(path)
    for root in roots:
        if not root:
            continue
        if is_within(target, os.path.realpath(root)):
            return True
    return False


# ---------------------------------------------------------------------------
# Parsers (pure)
# ---------------------------------------------------------------------------


def parse_desktop_text(text: str) -> Dict[str, str]:
    """Keys of the [Desktop Entry] group (non-localized)."""
    entry: Dict[str, str] = {}
    in_group = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_group = line == "[Desktop Entry]"
            continue
        if not in_group or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if "[" in key:
            continue
        entry.setdefault(key, value.strip())
    return entry


def parse_desktop_file(path: str) -> Dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_desktop_text(f.read())
    except OSError:
        return {}


def _bool(value: Optional[str]) -> bool:
    return (value or "").strip().lower() == "true"


def _list(value: Optional[str]) -> List[str]:
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def desktop_visible(entry: Dict[str, str], which: Callable = shutil.which) -> bool:
    if not entry:
        return False
    if entry.get("Type", "Application") != "Application":
        return False
    if _bool(entry.get("NoDisplay")) or _bool(entry.get("Hidden")):
        return False
    only = _list(entry.get("OnlyShowIn"))
    if only and "KDE" not in only:
        return False
    if "KDE" in _list(entry.get("NotShowIn")):
        return False
    try_exec = entry.get("TryExec")
    if try_exec:
        if os.path.isabs(try_exec):
            if not os.path.exists(try_exec):
                return False
        elif which(try_exec) is None:
            return False
    if not entry.get("Name") or not entry.get("Exec"):
        return False
    return True


def desktop_id_protected(desktop_id: str) -> bool:
    did = desktop_id.lower()
    if did.endswith(".desktop"):
        did = did[:-8]
    return did in PROTECTED_DESKTOP_IDS or did.startswith(PROTECTED_DESKTOP_PREFIXES)


def desktop_id_hidden(desktop_id: str) -> bool:
    did = desktop_id.lower()
    # Secondary Chrome/Chromium profile web app entries (Profile 1, Profile 2...)
    if re.search(r"(?:chrome|chromium)-[a-p0-9]{32}-profile_", did):
        return True
    return did.startswith(HIDDEN_DESKTOP_PREFIXES)


def friendly_pwa_name(name: str) -> str:
    s = name.strip()
    if s.startswith("http://") or s.startswith("https://"):
        low = s.lower()
        if "onedrive" in low:
            return "OneDrive"
        if "weather" in low:
            return "Weather"
        if "bing.com/maps" in low or "maps" in low:
            return "Maps"
        if "windows.cloud" in low:
            return "Windows App"
        clean = re.sub(r"^https?://(www\.)?", "", s).split("/")[0]
        return clean.capitalize() if clean else s
    return s


def unescape_desktop_string(value: str) -> str:
    """Desktop-entry string escapes: \\s \\n \\t \\r \\\\."""
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def exec_to_argv(exec_line: str, name: str = "", icon: str = "", desktop_path: str = "") -> List[str]:
    """Turn a desktop Exec= value into argv (field codes removed)."""
    value = unescape_desktop_string(exec_line or "")
    try:
        parts = shlex.split(value)
    except ValueError:
        parts = value.split()
    argv: List[str] = []
    for p in parts:
        if p in ("%f", "%F", "%u", "%U", "%d", "%D", "%n", "%N", "%v", "%m"):
            continue
        if p == "%i":
            if icon:
                argv += ["--icon", icon]
            continue
        if p == "%k":
            if desktop_path:
                argv.append(desktop_path)
            continue
        p = p.replace("%c", name).replace("%%", "%")
        argv.append(p)
    return argv


_WINEPREFIX_RE = re.compile(r'WINEPREFIX=(?:"((?:[^"\\]|\\.)*)"|\'([^\']*)\'|((?:\\.|\S)+))')


def extract_wineprefix(exec_line: str, home: str) -> Optional[str]:
    """`env WINEPREFIX="/home/u/.wine" wine ...` -> /home/u/.wine"""
    if not exec_line or "WINEPREFIX=" not in exec_line:
        return None
    m = _WINEPREFIX_RE.search(exec_line)
    if not m:
        return None
    if m.group(1) is not None:
        val = re.sub(r"\\(.)", r"\1", unescape_desktop_string(m.group(1)))
    elif m.group(2) is not None:
        val = m.group(2)
    else:
        val = re.sub(r"\\(.)", r"\1", unescape_desktop_string(m.group(3)))
    if not val:
        return None
    val = val.replace("${HOME}", home).replace("$HOME", home)
    if val.startswith("~"):
        val = home + val[1:]
    return os.path.normpath(val)


def parse_dpkg_search(output: str) -> Dict[str, str]:
    """`dpkg-query -S` lines ("pkg[:arch][, pkg2]: /path") -> {path: pkg}."""
    result: Dict[str, str] = {}
    for line in (output or "").splitlines():
        if line.startswith("diversion ") or ": /" not in line:
            continue
        pkgs, _, path = line.partition(": /")
        path = "/" + path.strip()
        first = pkgs.split(",")[0].strip()
        if first:
            result[path] = strip_arch(first)
    return result


def parse_dpkg_info(output: str) -> Dict[str, Dict[str, object]]:
    """`dpkg-query -W -f='${Installed-Size}\\t${Package}\\t${Priority}\\t${Essential}\\t${Version}\\n'`
    -> {pkg: {size_kib, priority, essential, version}}. Extra columns optional."""
    info: Dict[str, Dict[str, object]] = {}
    for line in (output or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 2:
            continue
        size_s, pkg = parts[0].strip(), strip_arch(parts[1])
        if not pkg:
            continue
        info[pkg] = {
            "size_kib": int(size_s) if size_s.isdigit() else None,
            "priority": parts[2].strip().lower() if len(parts) > 2 else "",
            "essential": len(parts) > 3 and parts[3].strip().lower() == "yes",
            "version": parts[4].strip() if len(parts) > 4 else "",
        }
    return info


def parse_flatpak_list(output: str) -> List[Dict[str, str]]:
    """Tab separated: application, name, version, size, installation."""
    apps = []
    for line in (output or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].strip() or parts[0].startswith("Application"):
            continue
        parts += [""] * (5 - len(parts))
        apps.append({
            "appid": parts[0].strip(), "name": parts[1].strip() or parts[0].strip(),
            "version": parts[2].strip(), "size": parts[3].strip(),
            "installation": parts[4].strip().lower(),
        })
    return apps


def parse_waydroid_list(output: str) -> List[Dict[str, str]]:
    apps = []
    cur: Dict[str, str] = {}
    for line in (output or "").splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            if cur.get("package"):
                apps.append(cur)
            cur = {"name": s[5:].strip()}
        elif s.lower().startswith("packagename:"):
            cur["package"] = s.split(":", 1)[1].strip()
    if cur.get("package"):
        apps.append(cur)
    return apps


def waydroid_running(status_output: str) -> bool:
    return bool(re.search(r"Session:\s*RUNNING", status_output or ""))


def parse_apt_simulation(output: str) -> List[str]:
    """`apt-get -s remove X` -> packages that would be removed."""
    pkgs = []
    for line in (output or "").splitlines():
        m = re.match(r"^Remv\s+(\S+)", line)
        if m:
            pkgs.append(strip_arch(m.group(1)))
    return pkgs


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def default_runner(argv: List[str], timeout: int = 120, env: Optional[dict] = None) -> Tuple[int, str]:
    """Run argv, return (returncode, combined output). Missing tool -> 127."""
    run_env = os.environ.copy()
    run_env.setdefault("LC_ALL", "C")
    if env:
        run_env.update(env)
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, timeout=timeout, env=run_env)
        return proc.returncode, proc.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "Timed out."
    except OSError as exc:
        return 126, str(exc)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class App:
    id: str
    name: str
    platform: str                      # linux / windows / android
    kind: str                          # deb / flatpak / desktop / windows / android
    icon: str = ""
    desktop_files: List[str] = field(default_factory=list)
    desktop_ids: List[str] = field(default_factory=list)
    entries: List[str] = field(default_factory=list)   # names of included launchers
    exec: str = ""
    terminal: bool = False
    workdir: str = ""
    package: str = ""
    appid: str = ""
    installation: str = ""
    prefix: str = ""
    android_package: str = ""
    size_bytes: Optional[int] = None
    version: str = ""
    system: bool = False
    uninstallable: bool = True
    lock_reason: str = ""
    location: str = ""

    @property
    def type_label(self) -> str:
        return TYPE_SYSTEM if self.system else TYPE_LABELS.get(self.platform, "App")

    def to_json(self) -> dict:
        d = asdict(self)
        d["type"] = self.type_label
        return d


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class AppDiscovery:
    def __init__(self, home: Optional[str] = None, app_dirs: Optional[List[str]] = None,
                 runner: Callable = default_runner, which: Callable = shutil.which):
        self.home = os.path.abspath(home or os.path.expanduser("~"))
        self.user_app_dir = os.path.join(self.home, ".local/share/applications")
        self.app_dirs = list(app_dirs) if app_dirs is not None else SYSTEM_APP_DIRS + [self.user_app_dir]
        self.prefixes_root = os.path.join(self.home, ".local/share/winlayer/prefixes")
        self.runner = runner
        self.which = which

    # -- desktop files ------------------------------------------------------

    def iter_desktop_files(self) -> List[Tuple[str, str, Dict[str, str]]]:
        """[(desktop_id, path, entry)] with XDG override (user dir wins)."""
        found: Dict[str, Tuple[str, Dict[str, str]]] = {}
        for base in self.app_dirs:
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                for fn in sorted(files):
                    if not fn.endswith(".desktop"):
                        continue
                    path = os.path.join(root, fn)
                    rel = os.path.relpath(path, base)
                    did = rel.replace(os.sep, "-")
                    found[did] = (path, parse_desktop_file(path))
        return [(did, p, e) for did, (p, e) in sorted(found.items())]

    def friendly_location(self, app: App) -> str:
        if app.kind == "deb":
            return "Installed for all users"
        if app.kind == "flatpak":
            return "Installed only for you" if app.installation == "user" else "Installed for all users"
        if app.kind == "windows":
            if app.prefix.startswith(self.prefixes_root + os.sep):
                return "Home › Windows apps › " + os.path.basename(app.prefix)
            if app.prefix.startswith(self.home + os.sep):
                return "Home › hidden Windows apps folder"
            return "Windows apps folder"
        if app.kind == "android":
            return "Android"
        if app.kind == "desktop":
            if app.desktop_files and app.desktop_files[0].startswith(self.home + os.sep):
                return "Installed only for you"
            return "Installed for all users"
        return ""

    # -- Linux --------------------------------------------------------------

    def dpkg_owners(self, paths: List[str]) -> Dict[str, str]:
        if not paths or not self.which("dpkg-query"):
            return {}
        owners: Dict[str, str] = {}
        for i in range(0, len(paths), 200):
            _rc, out = self.runner(["dpkg-query", "-S"] + paths[i:i + 200], timeout=120)
            owners.update(parse_dpkg_search(out))
        return owners

    def dpkg_info(self, pkgs: List[str]) -> Dict[str, Dict[str, object]]:
        if not pkgs or not self.which("dpkg-query"):
            return {}
        fmt = "${Installed-Size}\t${Package}\t${Priority}\t${Essential}\t${Version}\n"
        info: Dict[str, Dict[str, object]] = {}
        pkgs = sorted(set(pkgs))
        for i in range(0, len(pkgs), 200):
            _rc, out = self.runner(["dpkg-query", "-W", "-f=" + fmt] + pkgs[i:i + 200], timeout=120)
            info.update(parse_dpkg_info(out))
        return info

    def is_windows_entry(self, did: str, entry: Dict[str, str]) -> bool:
        return did.lower().startswith("winlayer-") or "WINEPREFIX=" in entry.get("Exec", "")

    def is_android_entry(self, did: str, entry: Dict[str, str]) -> bool:
        return did.startswith("waydroid.") or entry.get("Exec", "").strip().startswith("waydroid app launch")

    def discover_linux(self, desktop_files=None) -> List[App]:
        files = desktop_files if desktop_files is not None else self.iter_desktop_files()
        visible = []
        for did, path, entry in files:
            if self.is_windows_entry(did, entry) or self.is_android_entry(did, entry):
                continue
            if desktop_id_protected(did) or desktop_id_hidden(did):
                continue
            if not desktop_visible(entry, self.which):
                continue
            visible.append((did, path, entry))

        owners = self.dpkg_owners([p for _d, p, _e in visible])
        info = self.dpkg_info(list(set(owners.values())))

        groups: Dict[str, App] = {}
        for did, path, entry in visible:
            pkg = owners.get(path, "")
            if pkg:
                app_id = "deb:" + pkg
                kind = "deb"
            else:
                m_pwa = re.match(r"^(?:chrome|chromium)-([a-p0-9]{32})-(?:Default|Profile_.*)$", did[:-8], re.I)
                pwa_exec = re.search(r"--app-id=([a-p0-9]{32})", entry.get("Exec", ""), re.I)
                wmclass = entry.get("StartupWMClass", "")
                pwa_wm = re.match(r"^crx_([a-p0-9]{32})$", wmclass, re.I)
                pwa_id = (m_pwa.group(1) if m_pwa else (pwa_exec.group(1) if pwa_exec else (pwa_wm.group(1) if pwa_wm else None)))
                if pwa_id:
                    app_id = "pwa:" + pwa_id.lower()
                    kind = "desktop"
                else:
                    app_id = "desktop:" + did[:-8]
                    kind = "desktop"
            raw_name = scrub(entry.get("Name", did)) or did
            name = friendly_pwa_name(raw_name) if app_id.startswith("pwa:") else raw_name
            app = groups.get(app_id)
            if app is None:
                app = App(id=app_id, name=name, platform=PLATFORM_LINUX, kind=kind,
                          icon=entry.get("Icon", ""), exec=entry.get("Exec", ""),
                          terminal=_bool(entry.get("Terminal")), workdir=entry.get("Path", ""),
                          package=pkg)
                groups[app_id] = app
            elif (pkg and did[:-8] == pkg) or (app_id.startswith("pwa:") and ("-Default" in did or "--profile-directory=Default" in entry.get("Exec", ""))):
                # Prefer the launcher named like the package as the main one, or the Default profile for PWAs.
                app.name, app.icon, app.exec = name, entry.get("Icon", app.icon), entry.get("Exec", app.exec)
                app.terminal = _bool(entry.get("Terminal"))
            app.desktop_files.append(path)
            app.desktop_ids.append(did)
            app.entries.append(name)

        # Collect any associated hidden profile desktop files for PWAs so uninstall cleans all
        for app in groups.values():
            if app.id.startswith("pwa:"):
                pwa_hash = app.id[4:]
                for did_all, path_all, _ in files:
                    if pwa_hash in did_all.lower() and path_all not in app.desktop_files:
                        app.desktop_files.append(path_all)
                        app.desktop_ids.append(did_all)

        for app in groups.values():
            if app.kind == "deb":
                pi = info.get(app.package, {})
                kib = pi.get("size_kib")
                app.size_bytes = int(kib) * 1024 if isinstance(kib, int) else None
                app.version = str(pi.get("version") or "")
                if (app.package in PROTECTED_PACKAGES
                        or pi.get("priority") in PROTECTED_PRIORITIES or pi.get("essential")):
                    app.system = True
                    app.uninstallable = False
                    app.lock_reason = "This app is part of DevOS and can't be uninstalled."
            else:
                in_user = all(p.startswith(self.user_app_dir + os.sep) for p in app.desktop_files)
                if not in_user:
                    app.system = True
                    app.uninstallable = False
                    app.lock_reason = "This app came with DevOS and can't be uninstalled."
            app.location = self.friendly_location(app)
        return list(groups.values())

    # -- Flatpak ------------------------------------------------------------

    def discover_flatpak(self) -> List[App]:
        if not self.which("flatpak"):
            return []
        rc, out = self.runner(["flatpak", "list", "--app",
                               "--columns=application,name,version,size,installation"], timeout=60)
        if rc != 0:
            return []
        apps = []
        for fp in parse_flatpak_list(out):
            app = App(id="flatpak:" + fp["appid"], name=scrub(fp["name"]) or fp["appid"],
                      platform=PLATFORM_LINUX, kind="flatpak", icon=fp["appid"],
                      appid=fp["appid"], installation=fp["installation"] or "system",
                      size_bytes=parse_human_size(fp["size"]), version=fp["version"])
            app.location = self.friendly_location(app)
            apps.append(app)
        return apps

    # -- Windows ------------------------------------------------------------

    def allowed_prefix(self, prefix: str) -> bool:
        """Only per-app folders DevOS owns may be removed wholesale."""
        real = os.path.realpath(prefix)
        if is_within(real, os.path.realpath(self.prefixes_root)):
            return True
        home_real = os.path.realpath(self.home)
        return (os.path.dirname(real) == home_real
                and os.path.basename(real).startswith(".wine-"))

    def windows_roots(self) -> List[str]:
        return [self.prefixes_root, self.home]

    def discover_windows(self, desktop_files=None) -> List[App]:
        files = desktop_files if desktop_files is not None else self.iter_desktop_files()
        groups: Dict[str, App] = {}

        def group_for(prefix: str) -> App:
            prefix = os.path.normpath(prefix)
            app = groups.get(prefix)
            if app is None:
                app = App(id="win:" + os.path.basename(prefix).lstrip("."), name="",
                          platform=PLATFORM_WINDOWS, kind="windows", prefix=prefix,
                          icon="application-x-msdownload")
                groups[prefix] = app
            return app

        if os.path.isdir(self.prefixes_root):
            for d in sorted(os.listdir(self.prefixes_root)):
                p = os.path.join(self.prefixes_root, d)
                if os.path.isdir(p):
                    group_for(p)
        try:
            for d in sorted(os.listdir(self.home)):
                p = os.path.join(self.home, d)
                if d.startswith(".wine-") and os.path.isdir(os.path.join(p, "drive_c")):
                    group_for(p)
        except OSError:
            pass

        for did, path, entry in files:
            if not path.startswith(self.home + os.sep):
                continue
            prefix = None
            if did.lower().startswith("winlayer-"):
                prefix = os.path.join(self.prefixes_root, did[len("winlayer-"):-len(".desktop")])
            else:
                prefix = extract_wineprefix(entry.get("Exec", ""), self.home)
            if not prefix:
                continue
            app = group_for(prefix)
            app.desktop_files.append(path)
            app.desktop_ids.append(did)
            if desktop_visible(entry, lambda _x: True):
                nm = scrub(re.sub(r"\s*\(Windows\)\s*$", "", entry.get("Name", "")))
                app.entries.append(nm)
                is_uninst = nm.lower().startswith("uninstall")
                if (not app.name or (app.name.lower().startswith("uninstall") and not is_uninst)
                        or did.lower().startswith("winlayer-")):
                    app.name = nm
                    app.exec = entry.get("Exec", "")
                    app.workdir = entry.get("Path", "")
                    if entry.get("Icon"):
                        app.icon = entry["Icon"]

        apps = []
        for prefix, app in sorted(groups.items()):
            if not app.name:
                base = os.path.basename(prefix).lstrip(".")
                if base.startswith("wine-"):
                    base = base[5:]
                app.name = base.replace("_", " ").replace("-", " ").strip().title() or "Windows app"
            if not self.allowed_prefix(prefix):
                app.uninstallable = False
                app.lock_reason = ("This Windows app shares its folder with other Windows "
                                   "apps, so it can't be removed here.")
            app.location = self.friendly_location(app)
            apps.append(app)
        return apps

    # -- Android ------------------------------------------------------------

    def android_running(self) -> bool:
        if not self.which("waydroid"):
            return False
        _rc, out = self.runner(["waydroid", "status"], timeout=20)
        return waydroid_running(out)

    def discover_android(self, desktop_files=None) -> List[App]:
        files = desktop_files if desktop_files is not None else self.iter_desktop_files()
        apps: Dict[str, App] = {}
        for did, path, entry in files:
            if not did.startswith("waydroid.") or _bool(entry.get("NoDisplay")):
                continue
            pkg = did[len("waydroid."):-len(".desktop")]
            app = App(id="android:" + pkg, name=scrub(entry.get("Name", pkg)) or pkg,
                      platform=PLATFORM_ANDROID, kind="android",
                      icon=entry.get("Icon", "") or "smartphone", android_package=pkg,
                      exec=entry.get("Exec", ""), desktop_files=[path], desktop_ids=[did])
            apps[pkg] = app
        if self.android_running():
            _rc, out = self.runner(["waydroid", "app", "list"], timeout=60)
            for item in parse_waydroid_list(out):
                pkg = item["package"]
                if pkg not in apps:
                    apps[pkg] = App(id="android:" + pkg, name=scrub(item.get("name") or pkg),
                                    platform=PLATFORM_ANDROID, kind="android",
                                    icon="smartphone", android_package=pkg)
        result = []
        for pkg, app in sorted(apps.items()):
            if pkg.startswith(ANDROID_SYSTEM_PREFIXES):
                app.system = True
                app.uninstallable = False
                app.lock_reason = "This app is part of Android and can't be uninstalled."
            app.location = self.friendly_location(app)
            result.append(app)
        return result

    # -- all ----------------------------------------------------------------

    def discover_all(self) -> List[App]:
        files = self.iter_desktop_files()
        apps: List[App] = []
        for fn in (lambda: self.discover_linux(files), self.discover_flatpak,
                   lambda: self.discover_windows(files), lambda: self.discover_android(files)):
            try:
                apps.extend(fn())
            except Exception as exc:  # one broken source must not hide the others
                sys.stderr.write(f"apps: discovery error: {exc}\n")
        apps.sort(key=lambda a: a.name.casefold())
        return apps

    def compute_size(self, app: App) -> Optional[int]:
        """Slow sizes (folders). Fast ones are already filled in."""
        if app.kind == "windows" and app.prefix:
            return dir_size(app.prefix) if os.path.isdir(app.prefix) else 0
        return app.size_bytes


# ---------------------------------------------------------------------------
# Plans (pure) and execution
# ---------------------------------------------------------------------------


def browser_key(app: App) -> Optional[str]:
    keys = {k.lower() for k in [app.package, app.appid] + [d[:-8] for d in app.desktop_ids] if k}
    for name, spec in BROWSERS.items():
        if keys & spec["ids"]:
            return name
    return None


def _flatpak_rel(rel: str) -> str:
    if rel.startswith(".config/"):
        return "config/" + rel[len(".config/"):]
    if rel.startswith(".cache/"):
        return "cache/" + rel[len(".cache/"):]
    if rel.startswith(".local/share/"):
        return "data/" + rel[len(".local/share/"):]
    return rel


def name_variants(app: App) -> List[str]:
    raw = set()
    for k in [app.package, app.appid] + [d[:-8] if d.endswith(".desktop") else d for d in app.desktop_ids]:
        if not k:
            continue
        raw.add(k)
        if k.count(".") >= 2:
            raw.add(k.rsplit(".", 1)[-1])
    if app.name and app.platform == PLATFORM_LINUX:
        low = app.name.lower()
        raw.add(low)
        raw.add(low.replace(" ", "-"))
        raw.add(low.replace(" ", ""))
    out = set()
    for v in raw:
        for c in (v, v.lower()):
            if (re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", c) and len(c) >= 3
                    and c.lower() not in DENY_VARIANTS):
                out.add(c)
        for alias in CONFIG_ALIASES.get(v.lower(), []):
            out.add(alias)
    return sorted(out)


def _profile_dirs(root: str) -> List[str]:
    try:
        return [os.path.join(root, d) for d in sorted(os.listdir(root))
                if os.path.isdir(os.path.join(root, d)) and not os.path.islink(os.path.join(root, d))]
    except OSError:
        return []


class AppActions:
    """Builds plans (what would happen) and executes them."""

    def __init__(self, discovery: AppDiscovery, runner: Callable = None, which: Callable = None):
        self.d = discovery
        self.home = discovery.home
        self.runner = runner or discovery.runner
        self.which = which or discovery.which

    # -- helpers ------------------------------------------------------------

    def _existing(self, rels_or_paths: Iterable[str]) -> List[str]:
        out = []
        for p in rels_or_paths:
            full = p if os.path.isabs(p) else os.path.join(self.home, p)
            if os.path.lexists(full) and full not in out:
                out.append(full)
        return out

    def _browser_base(self, app: App) -> str:
        if app.kind == "flatpak" and app.appid:
            return os.path.join(self.home, ".var/app", app.appid)
        return self.home

    def _browser_paths(self, app: App, key: str, items: List[str], full: bool, cache_only: bool) -> List[str]:
        spec = BROWSERS[key]
        base = self._browser_base(app)
        rel = _flatpak_rel if app.kind == "flatpak" else (lambda r: r)
        paths = [os.path.join(base, rel(c)) for c in spec["caches"]]
        if full and not cache_only:
            paths += [os.path.join(base, rel(f)) for f in spec["full"]]
        else:
            for root in spec["profiles"]:
                root = os.path.join(base, rel(root))
                for prof in _profile_dirs(root):
                    paths += [os.path.join(prof, it) for it in items]
        return self._existing(paths)

    def process_names(self, app: App) -> List[str]:
        key = browser_key(app)
        return list(BROWSERS[key]["procs"]) if key else []

    def running_pids(self, app: App) -> List[int]:
        pids = []
        if not self.which("pgrep"):
            return pids
        for name in self.process_names(app):
            rc, out = self.runner(["pgrep", "-x", name], timeout=10)
            if rc == 0:
                pids += [int(x) for x in out.split() if x.isdigit()]
        return pids

    def close_app(self, app: App) -> int:
        n = 0
        for pid in self.running_pids(app):
            try:
                os.kill(pid, signal.SIGTERM)
                n += 1
            except OSError:
                pass
        return n

    # -- open ---------------------------------------------------------------

    def open_command(self, app: App) -> List[str]:
        if app.kind == "flatpak":
            return ["flatpak", "run", app.appid]
        if app.kind == "android":
            return ["waydroid", "app", "launch", app.android_package]
        argv = exec_to_argv(app.exec, app.name, app.icon,
                            app.desktop_files[0] if app.desktop_files else "")
        if argv and app.terminal:
            argv = ["konsole", "-e"] + argv
        return argv

    def open_app(self, app: App) -> Tuple[bool, str]:
        argv = self.open_command(app)
        if not argv:
            return False, f"{app.name} has no start command."
        cwd = app.workdir if app.workdir and os.path.isdir(app.workdir) else self.home
        try:
            subprocess.Popen(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            return True, f"Opening {app.name}…"
        except OSError:
            return False, f"{app.name} could not be started."

    # -- uninstall ------------------------------------------------------------

    def uninstall_plan(self, app: App) -> dict:
        plan = {"action": "uninstall", "app_id": app.id, "app_name": app.name,
                "kind": "command", "argv": [], "paths": [], "post": [],
                "roots": [], "precheck": None, "requires_android": False, "message": ""}
        if not app.uninstallable:
            plan.update(kind="refuse", message=app.lock_reason or f"{app.name} can't be uninstalled.")
            return plan
        if app.kind == "deb":
            plan["argv"] = ["pkexec", "apt-get", "remove", "-y", app.package]
            plan["precheck"] = ["apt-get", "-s", "remove", app.package]
        elif app.kind == "flatpak":
            argv = ["flatpak", "uninstall", "-y", "--noninteractive"]
            if app.installation == "user":
                argv.append("--user")
            plan["argv"] = argv + [app.appid]
        elif app.kind == "android":
            plan["argv"] = ["waydroid", "app", "remove", app.android_package]
            plan["requires_android"] = True
        elif app.kind == "windows":
            if not self.d.allowed_prefix(app.prefix):
                plan.update(kind="refuse", message=(
                    "This Windows app's folder is outside the Windows apps area, "
                    "so DevOS will not delete it."))
                return plan
            plan["kind"] = "delete"
            plan["roots"] = self.d.windows_roots()
            plan["paths"] = ([app.prefix] if os.path.lexists(app.prefix) else []) + \
                [p for p in app.desktop_files if os.path.lexists(p)]
            if self.which("update-desktop-database"):
                plan["post"] = [["update-desktop-database", self.d.user_app_dir]]
        elif app.kind == "desktop":
            plan["kind"] = "delete"
            plan["roots"] = [self.d.user_app_dir]
            plan["paths"] = [p for p in app.desktop_files if os.path.lexists(p)]
            if self.which("update-desktop-database"):
                plan["post"] = [["update-desktop-database", self.d.user_app_dir]]
        else:
            plan.update(kind="refuse", message=f"{app.name} can't be uninstalled here.")
        return plan

    def prepare_uninstall(self, app: App) -> dict:
        """Plan + dry-run checks that do not need a password."""
        plan = self.uninstall_plan(app)
        plan["also_removes"] = []
        if plan["kind"] == "command" and plan.get("precheck") and self.which("apt-get"):
            _rc, out = self.runner(plan["precheck"], timeout=120)
            removed = [p for p in parse_apt_simulation(out) if p != app.package]
            info = self.d.dpkg_info(removed) if removed else {}
            bad = [p for p in removed if p in PROTECTED_PACKAGES
                   or info.get(p, {}).get("priority") in PROTECTED_PRIORITIES
                   or info.get(p, {}).get("essential")]
            if bad:
                plan.update(kind="refuse", message=(
                    f"Removing {app.name} would also remove {len(bad)} part(s) of DevOS, "
                    "so it was not uninstalled."))
                plan["blocked_by"] = bad
            plan["also_removes"] = removed
        if plan["requires_android"] and not self.d.android_running():
            plan["android_ready"] = False
        return plan

    # -- cache ------------------------------------------------------------------

    def cache_plan(self, app: App) -> dict:
        plan = {"action": "clear_cache", "app_id": app.id, "app_name": app.name,
                "kind": "delete", "paths": [], "roots": [self.home], "argv": [], "post": [],
                "needs_closed": self.process_names(app), "message": ""}
        if app.kind == "android":
            plan.update(kind="refuse", message="Clearing only the cache isn't available for Android apps. Use Clear data.")
            return plan
        if app.kind == "windows":
            pats = [os.path.join(app.prefix, "drive_c/users/*/AppData/Local/Temp"),
                    os.path.join(app.prefix, "drive_c/users/*/Temp"),
                    os.path.join(app.prefix, "drive_c/windows/temp")]
            paths = []
            for pat in pats:
                for p in sorted(glob.glob(pat)):
                    paths += [os.path.join(p, c) for c in sorted(os.listdir(p))] if os.path.isdir(p) else []
            plan["paths"] = paths
            plan["roots"] = self.d.windows_roots()
            return plan
        key = browser_key(app)
        paths: List[str] = []
        if key:
            items = CHROMIUM_CACHE_ITEMS if BROWSERS[key]["engine"] == "chromium" else GECKO_CACHE_ITEMS
            paths += self._browser_paths(app, key, items, full=False, cache_only=True)
        if app.kind == "flatpak" and app.appid:
            paths += self._existing([os.path.join(self.home, ".var/app", app.appid, "cache")])
        for v in name_variants(app):
            paths += self._existing([os.path.join(".cache", v)])
            paths += self._existing([os.path.join(".config", v, it) for it in ELECTRON_CACHE_ITEMS])
        plan["paths"] = list(dict.fromkeys(paths))
        return plan

    # -- data / cookies ---------------------------------------------------------

    def data_label(self, app: App) -> str:
        if app.kind == "windows":
            return "Reset (removes the app's settings)"
        if browser_key(app):
            return "Clear cookies & site data"
        if app.kind == "android":
            return "Clear data"
        return "Reset app data"

    def data_plan(self, app: App, full: bool = False) -> dict:
        plan = {"action": "clear_data", "app_id": app.id, "app_name": app.name,
                "kind": "delete", "paths": [], "roots": [self.home], "argv": [], "post": [],
                "needs_closed": self.process_names(app), "full": full,
                "requires_android": False, "message": "", "is_browser": False}
        if app.system:
            plan.update(kind="refuse", message="DevOS system apps can't be reset here.")
            return plan
        if app.kind == "android":
            plan.update(kind="command", argv=["pkexec", "waydroid", "shell", "pm", "clear",
                                             app.android_package], requires_android=True)
            return plan
        if app.kind == "windows":
            # Settings live in the user profile inside the folder; the
            # installed program (Program Files) stays so the app still opens.
            paths = []
            for pat in ("drive_c/users/*/AppData", "drive_c/users/*/Temp",
                        "drive_c/users/*/Application Data", "drive_c/users/*/Local Settings"):
                paths += sorted(glob.glob(os.path.join(app.prefix, pat)))
            plan["paths"] = [p for p in paths if os.path.lexists(p)]
            plan["roots"] = self.d.windows_roots()
            return plan
        key = browser_key(app)
        if key:
            plan["is_browser"] = True
            items = CHROMIUM_COOKIE_ITEMS if BROWSERS[key]["engine"] == "chromium" else GECKO_COOKIE_ITEMS
            plan["paths"] = self._browser_paths(app, key, items, full=full, cache_only=False)
            return plan
        paths: List[str] = []
        if app.kind == "flatpak" and app.appid:
            paths += self._existing([os.path.join(self.home, ".var/app", app.appid)])
        for v in name_variants(app):
            paths += self._existing([os.path.join(".config", v), os.path.join(".config", v + "rc"),
                                     os.path.join(".local/share", v), os.path.join(".local/state", v),
                                     os.path.join(".cache", v)])
        plan["paths"] = list(dict.fromkeys(paths))
        return plan

    # -- execution ---------------------------------------------------------------

    def delete_paths(self, paths: List[str], roots: List[str]) -> Tuple[int, List[str]]:
        freed = 0
        errors: List[str] = []
        home_real = os.path.realpath(self.home)
        for p in paths:
            if not os.path.lexists(p):
                continue
            if not safe_target(p, roots) or resolved_target(p) == home_real:
                errors.append(f"Skipped {p}: outside the allowed folders.")
                continue
            size = dir_size(p)
            try:
                if os.path.islink(p) or not os.path.isdir(p):
                    os.unlink(p)
                else:
                    shutil.rmtree(p, ignore_errors=True)
                if not os.path.lexists(p):
                    freed += size
                else:
                    errors.append(f"Could not fully remove {p}.")
            except OSError as exc:
                errors.append(f"Could not remove {p}: {exc.strerror or exc}")
        return freed, errors

    def friendly_failure(self, rc: int, output: str) -> str:
        if rc == 127 and output.strip().endswith(": not found"):
            return "A system component needed for this is missing."
        if rc in (126, 127) and ("pkexec" in output or "Not authorized" in output
                                 or "dismissed" in output.lower() or not output.strip()):
            return "The password prompt was cancelled."
        lines = [l for l in output.strip().splitlines() if l.strip()][-3:]
        return scrub("\n".join(lines)) or "Something went wrong."

    def execute(self, plan: dict) -> dict:
        result = {"ok": False, "freed_bytes": 0, "errors": [], "message": ""}
        name = plan.get("app_name", "The app")
        if plan["kind"] == "refuse":
            result["message"] = plan.get("message", "")
            return result
        if plan.get("requires_android") and not self.d.android_running():
            result["message"] = "Open Android first, then try again."
            return result
        if plan["kind"] == "command":
            rc, out = self.runner(plan["argv"], timeout=3600)
            if rc != 0:
                result["message"] = self.friendly_failure(rc, out)
                return result
            result["ok"] = True
        elif plan["kind"] == "delete":
            freed, errors = self.delete_paths(plan["paths"], plan["roots"])
            result.update(ok=not errors or freed > 0, freed_bytes=freed, errors=errors)
        for argv in plan.get("post", []):
            self.runner(argv, timeout=60)
        action = plan.get("action")
        if action == "uninstall":
            result["message"] = f"{name} was uninstalled." if result["ok"] else \
                (result["errors"][0] if result["errors"] else "Uninstall failed.")
        elif action == "clear_cache":
            result["message"] = (f"Freed {human_size(result['freed_bytes'])} from {name}."
                                 if plan["paths"] else f"{name} has no cache to clear.")
        else:
            if plan["kind"] == "command":
                result["message"] = f"{name}'s data was cleared."
            elif plan["paths"]:
                result["message"] = f"{name} was reset. Freed {human_size(result['freed_bytes'])}."
            else:
                result["message"] = f"{name} has no saved data to clear."
        return result


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def find_app(apps: List[App], key: str) -> Optional[App]:
    if not key:
        return None
    if key.endswith(".desktop") or os.path.sep in key:
        real = os.path.realpath(key)
        for a in apps:
            if any(os.path.realpath(p) == real for p in a.desktop_files):
                return a
        base = os.path.basename(key)
        for a in apps:
            if base in a.desktop_ids or any(os.path.basename(p) == base for p in a.desktop_files):
                return a
        entry = parse_desktop_file(key) if os.path.isfile(key) else {}
        argv = exec_to_argv(entry.get("Exec", ""))
        if argv:
            first = os.path.basename(argv[0])
            for a in apps:
                aa = exec_to_argv(a.exec)
                if aa and os.path.basename(aa[0]) == first and first not in ("env", "python3", "sh", "bash"):
                    return a
        key = base[:-8] if base.endswith(".desktop") else base
    for a in apps:
        if key in (a.id, a.package, a.appid, a.android_package) or key + ".desktop" in a.desktop_ids:
            return a
    low = key.casefold()
    for a in apps:
        if a.name.casefold() == low:
            return a
    return None


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QWidget#root, QDialog { background: #0b0f19; }
QWidget { color: #e5e7eb; font-family: "Inter", "Noto Sans", sans-serif; font-size: 14px; }
QLabel { background: transparent; }
QLabel#title { font-size: 26px; font-weight: 600; color: #f9fafb; }
QLabel#subtitle, QLabel#muted { color: #9ca3af; font-size: 13px; }
QLabel#appname { font-size: 15px; font-weight: 600; color: #f3f4f6; }
QLabel#size { color: #cbd5e1; font-size: 13px; }
QLabel#badge { color: #38bdf8; background: rgba(56,189,248,0.12); border-radius: 8px;
  padding: 2px 8px; font-size: 12px; }
QLabel#badgeSystem { color: #a78bfa; background: rgba(167,139,250,0.12); border-radius: 8px;
  padding: 2px 8px; font-size: 12px; }
QLabel#key { color: #9ca3af; font-size: 13px; }
QLabel#val { color: #e5e7eb; font-size: 13px; }
QLabel#status { color: #9ca3af; font-size: 13px; }
QFrame#row { background: #111827; border-radius: 12px; border: 1px solid #1f2937; }
QFrame#row:hover { background: #1a2335; }
QFrame#details { background: #0f1626; border-radius: 10px; border: none; }
QLineEdit { background: #111827; border: 1px solid #1f2937; border-radius: 10px;
  padding: 9px 12px; color: #f3f4f6; selection-background-color: #38bdf8; }
QLineEdit:focus { border-color: #38bdf8; }
QComboBox { background: #111827; border: 1px solid #1f2937; border-radius: 10px;
  padding: 8px 12px; min-width: 150px; }
QComboBox:hover { background: #1a2335; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView { background: #111827; border: 1px solid #1f2937;
  selection-background-color: #1a2335; color: #e5e7eb; outline: none; }
QPushButton { background: #1f2937; color: #e5e7eb; border: none; border-radius: 10px;
  padding: 8px 16px; }
QPushButton:hover { background: #273449; }
QPushButton:disabled { color: #6b7280; background: #161e2e; }
QPushButton#primary { background: #38bdf8; color: #0b0f19; font-weight: 600; }
QPushButton#primary:hover { background: #7dd3fc; }
QPushButton#danger { background: rgba(239,68,68,0.14); color: #fca5a5; }
QPushButton#danger:hover { background: #ef4444; color: #fff; }
QPushButton#dangerSolid { background: #ef4444; color: #fff; font-weight: 600; }
QPushButton#dangerSolid:hover { background: #f87171; }
QPushButton:disabled#danger { color: #6b7280; background: #161e2e; }
QToolButton { background: transparent; border: none; border-radius: 8px; padding: 6px;
  color: #cbd5e1; font-size: 18px; }
QToolButton:hover { background: #273449; }
QToolButton::menu-indicator { image: none; }
QMenu { background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 8px 22px; border-radius: 6px; color: #e5e7eb; }
QMenu::item:selected { background: #1a2335; }
QMenu::item:disabled { color: #6b7280; }
QMenu::separator { height: 1px; background: #1f2937; margin: 4px 8px; }
QCheckBox { color: #e5e7eb; spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
  border: 1px solid #374151; background: #0b0f19; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QProgressBar { background: transparent; border: none; max-height: 3px; }
QProgressBar::chunk { background: #38bdf8; }
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #273449; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
"""

SORTS = [("Name (A to Z)", "name", False), ("Name (Z to A)", "name", True),
         ("Size (large to small)", "size", True), ("Size (small to large)", "size", False)]
FILTERS = [("All apps", None), ("Linux apps", PLATFORM_LINUX),
           ("Windows apps", PLATFORM_WINDOWS), ("Android apps", PLATFORM_ANDROID)]


def run_gui(focus: Optional[str] = None, discovery: Optional[AppDiscovery] = None) -> int:
    from PyQt5 import QtCore, QtGui, QtWidgets

    disc = discovery or AppDiscovery()
    actions = AppActions(disc)

    class Task(QtCore.QThread):
        done = QtCore.pyqtSignal(object)
        progress = QtCore.pyqtSignal(object)

        def __init__(self, fn, parent=None):
            super().__init__(parent)
            self.fn = fn

        def run(self):
            try:
                res = self.fn(self.progress.emit)
            except Exception as exc:  # report, never crash the window
                res = {"ok": False, "message": scrub(f"Something went wrong: {exc}"), "error": True}
            self.done.emit(res)

    def icon_for(app: App) -> "QtGui.QIcon":
        fallback = {"windows": "application-x-ms-dos-executable",
                    "android": "smartphone"}.get(app.kind, "application-x-executable")
        name = app.icon or ""
        if name and os.path.isabs(name) and os.path.exists(name):
            return QtGui.QIcon(name)
        ic = QtGui.QIcon.fromTheme(name) if name else QtGui.QIcon()
        if ic.isNull():
            ic = QtGui.QIcon.fromTheme(fallback, QtGui.QIcon.fromTheme("application-x-executable"))
        if ic.isNull():
            ic = QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_DesktopIcon)
        return ic

    class ConfirmDialog(QtWidgets.QDialog):
        def __init__(self, parent, title, text, ok_text, danger=True, checkbox=None, extra=None):
            super().__init__(parent)
            self.setWindowTitle(title)
            self.setModal(True)
            self.setMinimumWidth(440)
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(24, 22, 24, 20)
            lay.setSpacing(12)
            t = QtWidgets.QLabel(title)
            t.setObjectName("appname")
            t.setStyleSheet("font-size: 18px;")
            lay.addWidget(t)
            body = QtWidgets.QLabel(text)
            body.setWordWrap(True)
            body.setObjectName("muted")
            body.setStyleSheet("font-size: 14px; color: #cbd5e1;")
            lay.addWidget(body)
            if extra:
                ex = QtWidgets.QLabel(extra)
                ex.setWordWrap(True)
                ex.setObjectName("muted")
                lay.addWidget(ex)
            self.check = None
            if checkbox:
                self.check = QtWidgets.QCheckBox(checkbox)
                lay.addWidget(self.check)
            lay.addSpacing(6)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            cancel = QtWidgets.QPushButton("Cancel")
            cancel.clicked.connect(self.reject)
            ok = QtWidgets.QPushButton(ok_text)
            ok.setObjectName("dangerSolid" if danger else "primary")
            ok.clicked.connect(self.accept)
            row.addWidget(cancel)
            row.addWidget(ok)
            lay.addLayout(row)
            cancel.setFocus()

        def checked(self):
            return bool(self.check and self.check.isChecked())

    class AppRow(QtWidgets.QFrame):
        def __init__(self, app: App, win):
            super().__init__()
            self.app = app
            self.win = win
            self.setObjectName("row")
            self.setCursor(QtCore.Qt.PointingHandCursor)
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(14, 0, 10, 0)
            outer.setSpacing(0)

            head = QtWidgets.QWidget()
            head.setFixedHeight(64)
            h = QtWidgets.QHBoxLayout(head)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(14)
            self.icon = QtWidgets.QLabel()
            self.icon.setFixedSize(36, 36)
            self.icon.setPixmap(icon_for(app).pixmap(36, 36))
            h.addWidget(self.icon)
            col = QtWidgets.QVBoxLayout()
            col.setSpacing(3)
            col.addStretch(1)
            nm = QtWidgets.QLabel(app.name)
            nm.setObjectName("appname")
            col.addWidget(nm)
            brow = QtWidgets.QHBoxLayout()
            brow.setSpacing(8)
            badge = QtWidgets.QLabel(app.type_label)
            badge.setObjectName("badgeSystem" if app.system else "badge")
            brow.addWidget(badge)
            if app.version:
                v = QtWidgets.QLabel(scrub(app.version)[:32])
                v.setObjectName("muted")
                brow.addWidget(v)
            brow.addStretch(1)
            col.addLayout(brow)
            col.addStretch(1)
            h.addLayout(col, 1)
            self.size_lbl = QtWidgets.QLabel()
            self.size_lbl.setObjectName("size")
            self.size_lbl.setMinimumWidth(80)
            self.size_lbl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            h.addWidget(self.size_lbl)
            more = QtWidgets.QToolButton()
            more.setText("⋯")
            more.setToolTip("More options")
            more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            more.setMenu(self.build_menu())
            h.addWidget(more)
            outer.addWidget(head)

            self.details = QtWidgets.QFrame()
            self.details.setObjectName("details")
            self.details.setVisible(False)
            outer.addWidget(self.details)
            self.build_details()
            self.refresh_size()

        def build_menu(self):
            m = QtWidgets.QMenu(self)
            a = self.app
            m.addAction("Open", lambda: self.win.do_open(a)).setEnabled(bool(actions.open_command(a)))
            m.addAction("Details", self.toggle)
            m.addSeparator()
            c = m.addAction("Clear cache", lambda: self.win.do_cache(a))
            c.setEnabled(a.kind != "android")
            d = m.addAction(actions.data_label(a) + "…", lambda: self.win.do_data(a))
            d.setEnabled(not a.system)
            m.addSeparator()
            u = m.addAction("Uninstall…", lambda: self.win.do_uninstall(a))
            u.setEnabled(a.uninstallable)
            return m

        def build_details(self):
            a = self.app
            lay = QtWidgets.QVBoxLayout(self.details)
            lay.setContentsMargins(16, 14, 16, 14)
            lay.setSpacing(10)
            grid = QtWidgets.QGridLayout()
            grid.setHorizontalSpacing(24)
            grid.setVerticalSpacing(6)
            self.detail_size = QtWidgets.QLabel()
            self.detail_size.setObjectName("val")
            rows = [("Size", self.detail_size), ("Type", a.type_label),
                    ("Location", a.location or "—")]
            if a.version:
                rows.append(("Version", scrub(a.version)))
            others = [e for e in dict.fromkeys(a.entries) if e and e != a.name]
            if others:
                rows.append(("Also includes", ", ".join(others[:6])))
            if a.lock_reason:
                rows.append(("Note", a.lock_reason))
            for i, (k, v) in enumerate(rows):
                kl = QtWidgets.QLabel(k)
                kl.setObjectName("key")
                vl = v if isinstance(v, QtWidgets.QLabel) else QtWidgets.QLabel(v)
                vl.setObjectName("val")
                vl.setWordWrap(True)
                vl.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                grid.addWidget(kl, i, 0, QtCore.Qt.AlignTop)
                grid.addWidget(vl, i, 1)
            grid.setColumnStretch(1, 1)
            lay.addLayout(grid)
            btns = QtWidgets.QHBoxLayout()
            btns.setSpacing(8)
            b = QtWidgets.QPushButton("Open")
            b.setObjectName("primary")
            b.setEnabled(bool(actions.open_command(a)))
            b.clicked.connect(lambda: self.win.do_open(a))
            btns.addWidget(b)
            b = QtWidgets.QPushButton("Clear cache")
            b.setEnabled(a.kind != "android")
            b.clicked.connect(lambda: self.win.do_cache(a))
            btns.addWidget(b)
            b = QtWidgets.QPushButton(actions.data_label(a))
            b.setEnabled(not a.system)
            b.clicked.connect(lambda: self.win.do_data(a))
            btns.addWidget(b)
            btns.addStretch(1)
            b = QtWidgets.QPushButton("Uninstall")
            b.setObjectName("danger")
            b.setEnabled(a.uninstallable)
            if not a.uninstallable:
                b.setToolTip(a.lock_reason)
            b.clicked.connect(lambda: self.win.do_uninstall(a))
            btns.addWidget(b)
            lay.addLayout(btns)
            lay.addSpacing(4)

        def refresh_size(self):
            text = human_size(self.app.size_bytes) if self.app.size_bytes is not None else (
                "…" if self.app.kind == "windows" else "")
            self.size_lbl.setText(text)
            self.detail_size.setText(human_size(self.app.size_bytes) if self.app.size_bytes is not None
                                     else ("Calculating…" if self.app.kind == "windows" else "Unknown"))

        def toggle(self):
            self.details.setVisible(not self.details.isVisible())
            if self.details.isVisible():
                self.win.ensure_visible(self)

        def mouseReleaseEvent(self, ev):
            if ev.button() == QtCore.Qt.LeftButton and ev.pos().y() <= 64:
                self.toggle()
            super().mouseReleaseEvent(ev)

        def mouseDoubleClickEvent(self, ev):
            if ev.pos().y() <= 64:
                self.win.do_open(self.app)

    class Window(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("root")
            self.setWindowTitle("Apps")
            self.setWindowIcon(QtGui.QIcon.fromTheme("preferences-desktop-apps",
                                                     QtGui.QIcon.fromTheme("applications-all")))
            self.resize(940, 760)
            self.apps: List[App] = []
            self.rows: Dict[str, AppRow] = {}
            self.tasks = set()
            self.focus = focus

            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(28, 24, 28, 12)
            lay.setSpacing(14)
            t = QtWidgets.QLabel("Apps")
            t.setObjectName("title")
            lay.addWidget(t)
            st = QtWidgets.QLabel("Installed apps")
            st.setObjectName("subtitle")
            lay.addWidget(st)

            bar = QtWidgets.QHBoxLayout()
            bar.setSpacing(10)
            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Search apps")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self.apply_view)
            bar.addWidget(self.search, 1)
            self.sort = QtWidgets.QComboBox()
            for label, _k, _r in SORTS:
                self.sort.addItem("Sort by: " + label)
            self.sort.currentIndexChanged.connect(self.apply_view)
            bar.addWidget(self.sort)
            self.filter = QtWidgets.QComboBox()
            for label, _p in FILTERS:
                self.filter.addItem("Show: " + label)
            self.filter.currentIndexChanged.connect(self.apply_view)
            bar.addWidget(self.filter)
            lay.addLayout(bar)

            info = QtWidgets.QHBoxLayout()
            self.count = QtWidgets.QLabel("Finding apps…")
            self.count.setObjectName("muted")
            info.addWidget(self.count)
            info.addStretch(1)
            refresh = QtWidgets.QPushButton("Refresh")
            refresh.clicked.connect(self.reload)
            info.addWidget(refresh)
            lay.addLayout(info)

            self.busy = QtWidgets.QProgressBar()
            self.busy.setRange(0, 0)
            self.busy.setTextVisible(False)
            self.busy.setFixedHeight(3)
            self.busy.setVisible(False)
            lay.addWidget(self.busy)

            self.scroll = QtWidgets.QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            holder = QtWidgets.QWidget()
            holder.setObjectName("root")
            self.list = QtWidgets.QVBoxLayout(holder)
            self.list.setContentsMargins(0, 0, 6, 0)
            self.list.setSpacing(8)
            self.list.addStretch(1)
            self.scroll.setWidget(holder)
            lay.addWidget(self.scroll, 1)

            self.empty = QtWidgets.QLabel("No apps match your search.")
            self.empty.setObjectName("muted")
            self.empty.setAlignment(QtCore.Qt.AlignCenter)
            self.empty.setVisible(False)
            lay.addWidget(self.empty)

            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("status")
            lay.addWidget(self.status)
            self.reload()

        # -- tasks --
        def start(self, fn, on_done, on_progress=None, status=None):
            task = Task(fn, self)
            self.tasks.add(task)
            task.done.connect(on_done)
            if on_progress:
                task.progress.connect(on_progress)
            task.finished.connect(lambda: self._finished(task))
            if status:
                self.status.setText(status)
            self.busy.setVisible(True)
            task.start()

        def _finished(self, task):
            self.tasks.discard(task)
            self.busy.setVisible(bool(self.tasks))
            task.deleteLater()

        def notify(self, msg, error=False):
            self.status.setStyleSheet("color: #fca5a5;" if error else "")
            self.status.setText(msg)

        def error_box(self, title, msg):
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle(title)
            box.setIcon(QtWidgets.QMessageBox.Warning)
            box.setText(msg)
            box.exec_()

        # -- loading --
        def reload(self):
            self.count.setText("Finding apps…")
            self.start(lambda _p: disc.discover_all(), self.loaded, status="Finding apps…")

        def loaded(self, apps):
            if isinstance(apps, dict):
                self.notify(apps.get("message", "Could not list apps."), True)
                apps = []
            for row in self.rows.values():
                row.setParent(None)
                row.deleteLater()
            self.rows = {}
            self.apps = apps
            for a in apps:
                self.rows[a.id] = AppRow(a, self)
            self.apply_view()
            self.notify("")
            pending = [a for a in apps if a.kind == "windows"]
            if pending:
                def sizes(progress):
                    for a in pending:
                        progress((a.id, disc.compute_size(a)))
                    return None
                self.start(sizes, lambda _r: self.apply_view() if self.sort.currentIndex() >= 2 else None,
                           self.size_ready)
            if self.focus:
                key, self.focus = self.focus, None
                QtCore.QTimer.singleShot(0, lambda: self.focus_uninstall(key))

        def size_ready(self, item):
            app_id, size = item
            row = self.rows.get(app_id)
            if row:
                row.app.size_bytes = size
                row.refresh_size()

        def apply_view(self):
            text = self.search.text().strip().casefold()
            _l, key, rev = SORTS[max(0, self.sort.currentIndex())]
            plat = FILTERS[max(0, self.filter.currentIndex())][1]
            if key == "name":
                ordered = sorted(self.apps, key=lambda a: a.name.casefold(), reverse=rev)
            else:
                ordered = sorted(self.apps, key=lambda a: (a.size_bytes if a.size_bytes is not None else -1),
                                 reverse=rev)
            while self.list.count():
                self.list.takeAt(0)
            shown = 0
            for a in ordered:
                row = self.rows.get(a.id)
                if row is None:
                    continue
                ok = (plat is None or a.platform == plat) and (
                    not text or text in a.name.casefold()
                    or any(text in e.casefold() for e in a.entries)
                    or text in a.type_label.casefold())
                self.list.addWidget(row)
                row.setVisible(ok)
                shown += ok
            self.list.addStretch(1)
            self.count.setText(f"{shown} app{'s' if shown != 1 else ''} found")
            self.empty.setVisible(shown == 0 and bool(self.apps or text))

        def ensure_visible(self, row):
            QtCore.QTimer.singleShot(30, lambda: self.scroll.ensureWidgetVisible(row, 0, 40))

        # -- actions --
        def do_open(self, app):
            ok, msg = actions.open_app(app)
            self.notify(msg, not ok)

        def ensure_closed(self, app) -> bool:
            if not actions.process_names(app) or not actions.running_pids(app):
                return True
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle(f"Close {app.name}")
            box.setIcon(QtWidgets.QMessageBox.Information)
            box.setText(f"{app.name} is open. Close it first, then try again.")
            close_btn = box.addButton("Close it for me", QtWidgets.QMessageBox.AcceptRole)
            box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
            box.exec_()
            if box.clickedButton() is not close_btn:
                return False
            actions.close_app(app)
            for _ in range(20):
                QtCore.QThread.msleep(250)
                QtWidgets.QApplication.processEvents()
                if not actions.running_pids(app):
                    return True
            self.error_box(app.name, f"{app.name} is still open. Close it and try again.")
            return False

        def finish(self, res, refresh=False):
            if not isinstance(res, dict):
                return
            msg = res.get("message", "")
            if res.get("ok"):
                self.notify(msg)
            else:
                self.notify(msg.splitlines()[0] if msg else "Failed.", True)
                if msg:
                    self.error_box("Apps", msg)
            if refresh and res.get("ok"):
                self.reload()

        def do_cache(self, app):
            if not self.ensure_closed(app):
                return
            plan = actions.cache_plan(app)
            self.start(lambda _p: actions.execute(plan), self.finish,
                       status=f"Clearing cache of {app.name}…")

        def do_data(self, app):
            if app.system:
                return
            label = actions.data_label(app)
            is_browser = browser_key(app) is not None
            if app.kind == "windows":
                text = (f"This removes {app.name}'s settings, saved files in its AppData folder and "
                        "temporary files. The app itself stays installed.")
            elif is_browser:
                text = (f"This signs you out of websites and removes cookies and cached files from "
                        f"{app.name}. Your history, saved passwords and bookmarks are kept.")
            elif app.kind == "android":
                text = f"This erases everything {app.name} has stored, including sign-ins and settings."
            else:
                text = f"This removes {app.name}'s settings, sign-ins and cached files. It will start fresh."
            dlg = ConfirmDialog(self, label.replace("…", ""), text, "Clear" if is_browser else "Reset",
                                checkbox=("Also remove history, saved passwords and bookmarks"
                                          if is_browser else None))
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            if not self.ensure_closed(app):
                return
            plan = actions.data_plan(app, full=dlg.checked())
            self.start(lambda _p: actions.execute(plan), self.finish,
                       status=f"Clearing data of {app.name}…")

        def do_uninstall(self, app):
            if not app.uninstallable:
                self.error_box("Uninstall", app.lock_reason or f"{app.name} can't be uninstalled.")
                return
            self.start(lambda _p: actions.prepare_uninstall(app),
                       lambda plan: self.confirm_uninstall(app, plan),
                       status=f"Checking {app.name}…")

        def confirm_uninstall(self, app, plan):
            self.notify("")
            if plan.get("error"):
                self.finish(plan)
                return
            if plan["kind"] == "refuse":
                self.error_box("Uninstall", plan.get("message", ""))
                return
            if plan.get("android_ready") is False:
                self.error_box("Uninstall", "Open Android first, then try again.")
                return
            extra = None
            others = [p for p in plan.get("also_removes", [])]
            if others:
                extra = ("These parts will be removed too: " + ", ".join(others[:8])
                         + (" and more." if len(others) > 8 else "."))
            text = f"{app.name} and its files will be removed from this computer."
            if app.kind == "windows":
                text = f"{app.name}, its Windows folder and its menu entries will be removed."
            dlg = ConfirmDialog(self, f"Uninstall {app.name}?", text, "Uninstall", extra=extra)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            self.start(lambda _p: actions.execute(plan), lambda r: self.finish(r, refresh=True),
                       status=f"Uninstalling {app.name}…")

        def focus_uninstall(self, key):
            app = find_app(self.apps, key)
            if app is None:
                self.error_box("Uninstall", "This app is part of DevOS or can't be uninstalled here.")
                return
            self.filter.setCurrentIndex(0)
            self.search.clear()
            row = self.rows.get(app.id)
            if row:
                row.details.setVisible(True)
                self.ensure_visible(row)
            self.do_uninstall(app)

    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    qapp.setApplicationName("Apps")
    qapp.setDesktopFileName("devos-apps")
    if QtGui.QIcon.themeName() in ("", "hicolor"):
        QtGui.QIcon.setThemeName("breeze-dark")
    font = QtGui.QFont("Inter")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Noto Sans")
    font.setPixelSize(14)
    qapp.setFont(font)
    qapp.setStyleSheet(STYLE)
    win = Window()
    win.show()
    if os.environ.get("DEVOS_APPS_SMOKE"):
        QtCore.QTimer.singleShot(int(os.environ.get("DEVOS_APPS_SMOKE")), qapp.quit)
    return qapp.exec_()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DevOS Apps - installed apps manager")
    p.add_argument("--list", action="store_true", help="print discovered apps as JSON")
    p.add_argument("--no-sizes", action="store_true", help="with --list: skip folder sizes")
    p.add_argument("--dry-run-uninstall", metavar="ID", help="print the uninstall plan as JSON")
    p.add_argument("--uninstall", metavar="ID", help="open the window and ask to uninstall ID")
    args = p.parse_args(argv)

    if args.list or args.dry_run_uninstall:
        disc = AppDiscovery()
        apps = disc.discover_all()
        if args.list:
            if not args.no_sizes:
                for a in apps:
                    a.size_bytes = disc.compute_size(a)
            print(json.dumps([a.to_json() for a in apps], indent=2))
            return 0
        app = find_app(apps, args.dry_run_uninstall)
        if app is None:
            print(json.dumps({"error": "not found", "id": args.dry_run_uninstall}, indent=2))
            return 1
        print(json.dumps(AppActions(disc).prepare_uninstall(app), indent=2))
        return 0
    return run_gui(focus=args.uninstall)


if __name__ == "__main__":
    sys.exit(main())
