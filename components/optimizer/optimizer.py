#!/usr/bin/env python3
"""
DevOS Optimizer - keeps the desktop fast with friendly, low-noise suggestions.

Runs per user session as a KDE system-tray app:
  * Idle app suggestions: GUI apps that have been unfocused and idle for a
    while and hold a lot of memory get one polite "close it?" suggestion.
  * Clean up: a dialog that sizes and removes user-owned temp files, caches,
    the recycle bin, Windows-app temp folders, old downloads and old logs.
  * Low-disk warnings and an optional tip from the local DevOS AI.

CLI:
  optimizer.py --tray         start the tray app (default)
  optimizer.py --cleanup      open the Clean up dialog (single-instance aware)
  optimizer.py --scan         print reclaimable sizes as JSON (deletes nothing)
  optimizer.py --idle-report  print tracked GUI apps as JSON after one sample

Everything above the "GUI" section is plain stdlib and importable without a
display so it can be unit-tested. PyQt5 is imported lazily in the GUI path.
"""

import argparse
import configparser
import functools
import shlex
import glob
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_NAME = "DevOS Optimizer"
MB = 1024 * 1024
GB = 1024 * MB
DAY = 86400

DEFAULT_IDLE_MINUTES = 15
MIN_IDLE_MINUTES = 10
IDLE_CHOICES = (10, 15, 20, 30)
MIN_RSS_BYTES = 150 * MB
CPU_ACTIVE_PCT = 2.0
SUGGESTION_INTERVAL_S = 10 * 60
SAMPLE_INTERVAL_S = 60
LOW_DISK_FRACTION = 0.10
LOW_DISK_BYTES = 5 * GB

AI_URL = "http://127.0.0.1:11434/v1/chat/completions"
AI_TIMEOUT_S = 20
AI_UNAVAILABLE_MSG = "The local AI is starting — try again in a minute."

# Session/system processes that must never be suggested or signalled.
PROTECTED_NAMES = {
    "plasmashell", "kwin", "kwin_x11", "kwin_wayland", "xorg", "x", "xwayland",
    "sddm", "sddm-helper", "sddm-greeter", "ksmserver", "kded5", "kded6",
    "kdeinit5", "klauncher", "startplasma-x11", "startplasma-wayland",
    "plasma_session", "systemd", "dbus-daemon", "dbus-broker", "pulseaudio",
    "pipewire", "pipewire-pulse", "wireplumber", "krunner", "kaccess",
    "kglobalaccel5", "kactivitymanagerd", "kscreen_backend_launcher",
    "polkit-kde-authentication-agent-1", "xembedsniproxy",
    "gmenudbusmenuproxy", "org_kde_powerdevil", "baloo_file",
    "xdg-desktop-portal", "xdg-desktop-portal-kde", "kwalletd5", "kwalletd6",
    "ibus-daemon", "fcitx5", "at-spi-bus-launcher", "at-spi2-registryd",
    "gpg-agent", "ssh-agent", "calamares", "devos-optimizer",
    # DevOS AI & Core Services (never suggest closing or kill)
    "devos-ai", "devos-ai-core", "devos-ai-code-agent", "devos-code-agent",
    "devos-chat", "devos-ai-models", "devos-ai-api", "devos-dashboard",
    "devos-security", "devos-vault", "devos-session", "devos-taskman",
    "llama-server", "ollama",
}

# Parents under which a DISPLAY-bearing process counts as a separate app
# (used only by the /proc fallback when wmctrl is unavailable).
SESSION_PARENTS = {
    "plasmashell", "krunner", "kwin_x11", "ksmserver", "kdeinit5", "klauncher",
    "startplasma-x11", "plasma_session", "systemd", "dolphin", "kded5",
}

# Background helpers that carry DISPLAY but are not "apps" for the user.
NON_APP_NAMES = {
    "bash", "sh", "zsh", "fish", "dash", "sleep", "xdg-dbus-proxy",
    "kioslave5", "kiod5", "kio_http_cache_cleaner", "kdeconnectd",
    "dconf-service", "gvfsd", "obexd", "xsettingsd", "ksystemstats",
    "drkonqi", "kioworker", "file.so", "kuiserver5",
}

PRETTY_NAMES = {
    "chrome": "Chrome", "google-chrome": "Chrome", "chromium": "Chromium",
    "chromium-browse": "Chromium", "firefox": "Firefox", "firefox-bin": "Firefox",
    "codium": "VSCodium", "code": "VS Code", "thunderbird": "Thunderbird",
    "libreoffice": "LibreOffice", "soffice.bin": "LibreOffice",
    "gimp": "GIMP", "gimp-2.10": "GIMP", "inkscape": "Inkscape",
    "vlc": "VLC", "telegram-desktop": "Telegram", "slack": "Slack",
    "discord": "Discord", "spotify": "Spotify", "okular": "Okular",
    "dolphin": "Dolphin", "konsole": "Konsole", "kate": "Kate",
    "obs": "OBS Studio", "steam": "Steam", "zoom": "Zoom",
}


def human_size(num):
    num = float(max(0, num))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return "%d %s" % (int(num), unit)
            return "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f TB" % num


def home_dir():
    return os.path.expanduser("~")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def config_path(home=None):
    base = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    if not base:
        base = os.path.join(home or home_dir(), ".config")
    return os.path.join(base, "devos", "optimizer.json")


def clamp_idle_minutes(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_IDLE_MINUTES
    return max(MIN_IDLE_MINUTES, min(value, 24 * 60))


def load_config(path=None):
    path = path or config_path()
    cfg = {"idle_minutes": DEFAULT_IDLE_MINUTES, "never_ask": [], "paused_until": 0}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            cfg.update({k: data[k] for k in cfg if k in data})
    except (OSError, ValueError):
        pass
    cfg["idle_minutes"] = clamp_idle_minutes(cfg["idle_minutes"])
    if not isinstance(cfg["never_ask"], list):
        cfg["never_ask"] = []
    cfg["never_ask"] = sorted({str(x).lower() for x in cfg["never_ask"]})
    try:
        cfg["paused_until"] = float(cfg["paused_until"])
    except (TypeError, ValueError):
        cfg["paused_until"] = 0
    return cfg


def save_config(cfg, path=None):
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def is_live_session(cmdline_path="/proc/cmdline"):
    try:
        with open(cmdline_path, "r", encoding="utf-8", errors="replace") as fh:
            return "boot=casper" in fh.read().split()
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Path safety + size scanning
# ---------------------------------------------------------------------------

def is_within(path, root):
    """True if the fully resolved `path` stays inside the resolved `root`."""
    real_root = os.path.realpath(root)
    real_path = os.path.realpath(path)
    if real_path == real_root:
        return True
    return real_path.startswith(real_root.rstrip(os.sep) + os.sep)


def is_safe_entry(path, root, uid=None):
    """A file is safe to count/delete if it lives inside root without any
    symlink escaping it, is not a symlink pointing outside root, and (when
    uid is given) is owned by that uid."""
    try:
        st = os.lstat(path)
    except OSError:
        return False
    if os.path.abspath(path) == os.path.abspath(root):
        # single-file target (e.g. ~/.xsession-errors.old): must be a real file
        return stat.S_ISREG(st.st_mode) and (uid is None or st.st_uid == uid)
    if not is_within(os.path.dirname(path), root):
        return False
    if stat.S_ISLNK(st.st_mode) and not is_within(path, root):
        return False
    if uid is not None and st.st_uid != uid:
        return False
    return stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)


class Target(object):
    """One root directory (or single file) belonging to a cleanup category."""

    def __init__(self, root, min_age_s=0, uid=None, exclude=(), max_depth=None):
        self.root = root
        self.min_age_s = min_age_s
        self.uid = uid
        self.exclude = [os.path.realpath(p) for p in exclude]
        self.max_depth = max_depth

    def _excluded(self, path):
        real = os.path.realpath(path)
        for ex in self.exclude:
            if real == ex or real.startswith(ex.rstrip(os.sep) + os.sep):
                return True
        return False

    def iter_files(self, now=None):
        """Yield (path, size) for deletable files. Never follows symlinks."""
        now = time.time() if now is None else now
        root = self.root
        try:
            root_st = os.lstat(root)
        except OSError:
            return
        if stat.S_ISLNK(root_st.st_mode):
            return  # never treat a symlinked root as a target
        if stat.S_ISREG(root_st.st_mode):
            if self._accept(root, root_st, now):
                yield root, root_st.st_size
            return
        if not stat.S_ISDIR(root_st.st_mode):
            return
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, filenames in os.walk(root, topdown=True,
                                                    onerror=lambda e: None,
                                                    followlinks=False):
            if not is_within(dirpath, root) or self._excluded(dirpath):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if not self._excluded(os.path.join(dirpath, d))]
            if self.max_depth is not None and \
                    dirpath.rstrip(os.sep).count(os.sep) - base_depth >= self.max_depth:
                dirnames[:] = []
            # os.walk lists symlinks-to-directories in dirnames (never followed);
            # treat the link itself as an entry, subject to the same checks.
            linked_dirs = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
            for name in filenames + linked_dirs:
                path = os.path.join(dirpath, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if self._accept(path, st, now):
                    yield path, st.st_size

    def _accept(self, path, st, now):
        if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
            return False
        if self.uid is not None and st.st_uid != self.uid:
            return False
        if self.min_age_s and (now - st.st_mtime) < self.min_age_s:
            return False
        if self._excluded(path):
            return False
        return is_safe_entry(path, self.root, self.uid)


def _listdir_safe(path):
    try:
        return os.listdir(path)
    except OSError:
        return []


class Category(object):
    def __init__(self, cid, label, description, targets, default_checked=True,
                 list_files=False):
        self.id = cid
        self.label = label
        self.description = description
        self.targets = targets
        self.default_checked = default_checked
        self.list_files = list_files


TMPISH_DIR_NAMES = ("tmp", "temp", "Temp", ".tmp", "TEMP")


def _cache_tmpish_dirs(cache_root):
    found = []
    for entry in _listdir_safe(cache_root):
        app_dir = os.path.join(cache_root, entry)
        if os.path.islink(app_dir) or not os.path.isdir(app_dir):
            continue
        for name in TMPISH_DIR_NAMES:
            cand = os.path.join(app_dir, name)
            if os.path.isdir(cand) and not os.path.islink(cand):
                found.append(cand)
    return sorted(set(found))


def build_categories(home=None, uid=None, tmp_roots=("/tmp", "/var/tmp")):
    """Return the cleanup categories. Only user-owned paths are targeted."""
    home = home or home_dir()
    uid = os.getuid() if uid is None and hasattr(os, "getuid") else uid
    cache = os.path.join(home, ".cache")
    local_share = os.path.join(home, ".local", "share")
    tmpish = _cache_tmpish_dirs(cache)

    temp_targets = [Target(r, min_age_s=DAY, uid=uid) for r in tmp_roots]
    temp_targets += [Target(d, min_age_s=DAY, uid=uid) for d in tmpish]

    trash_targets = [Target(os.path.join(local_share, "Trash"), uid=uid)]

    # Graphics and compiled shader caches
    shader_roots = [
        os.path.join(cache, "mesa_shader_cache"),
        os.path.join(home, ".nv", "GLCache"),
        os.path.join(cache, "vulkan"),
    ]
    for p in sorted(glob.glob(os.path.join(cache, "qtshadercache*"))):
        shader_roots.append(p)
    shader_targets = [Target(r, uid=uid) for r in shader_roots if not os.path.islink(r)]

    # Developer package & language build caches
    dev_roots = [
        os.path.join(cache, "pip"),
        os.path.join(home, ".npm", "_cacache"),
        os.path.join(cache, "yarn"),
        os.path.join(home, ".cargo", "registry", "cache"),
        os.path.join(cache, "go-build"),
    ]
    dev_targets = [Target(r, uid=uid) for r in dev_roots if not os.path.islink(r)]

    # Clipboard history (DevOS Clipboard JSON + KDE Klipper history files)
    clip_files = [
        os.path.join(local_share, "DevOS", "clipboard-history.json"),
        os.path.join(local_share, "klipper", "history.lst"),
        os.path.join(local_share, "klipper", "history2.lst"),
        os.path.join(local_share, "klipper", "data"),
    ]
    clip_targets = [Target(f, uid=uid) for f in clip_files if not os.path.islink(f)]

    # Recent files and documents history
    recent_files = [
        os.path.join(local_share, "recently-used.xbel"),
        os.path.join(local_share, "RecentlyUsed.xbel"),
        os.path.join(local_share, "recent-documents"),
    ]
    recent_targets = [Target(f, uid=uid) for f in recent_files if not os.path.islink(f)]

    # Notifications history & related web/app caches
    notif_patterns = [
        os.path.join(local_share, "DevOS", "webapps", "*", "storage", "Platform Notifications"),
        os.path.join(home, ".config", "*", "Platform Notifications"),
        os.path.join(home, ".config", "*", "*", "Platform Notifications"),
        os.path.join(local_share, "plasma_notifications"),
        os.path.join(local_share, "notifications"),
        os.path.join(local_share, "knotifications5"),
        os.path.join(local_share, "knotifications6"),
        os.path.join(cache, "knotifications5"),
        os.path.join(cache, "knotifications6"),
        os.path.join(cache, "notify-osd"),
        os.path.join(local_share, "notify-osd"),
        os.path.join(local_share, "xfce4", "notifyd"),
        os.path.join(cache, "xfce4", "notifyd"),
        os.path.join(local_share, "dunst"),
        os.path.join(cache, "dunst"),
    ]
    notif_roots = []
    for pattern in notif_patterns:
        for match in sorted(glob.glob(pattern)):
            if (os.path.isdir(match) or os.path.isfile(match)) and not os.path.islink(match) and is_within(match, home):
                notif_roots.append(match)
    for notif_cache in sorted(glob.glob(os.path.join(cache, "*notif*"))):
        if not os.path.islink(notif_cache) and is_within(notif_cache, home):
            notif_roots.append(notif_cache)
    for notif_local in sorted(glob.glob(os.path.join(local_share, "*notif*"))):
        if not os.path.islink(notif_local) and is_within(notif_local, home):
            notif_roots.append(notif_local)
    for nfile in [os.path.join(home, ".config", "plasmanotifyrc")]:
        if os.path.isfile(nfile) and not os.path.islink(nfile):
            notif_roots.append(nfile)
    notif_targets = [Target(r, uid=uid) for r in sorted(set(notif_roots))]

    # Application Web, GPU, and bytecode caches in ~/.config and WebApps
    app_cache_patterns = [
        os.path.join(home, ".config", "*", "GPUCache"),
        os.path.join(home, ".config", "*", "*", "GPUCache"),
        os.path.join(home, ".config", "*", "Code Cache"),
        os.path.join(home, ".config", "*", "*", "Code Cache"),
        os.path.join(home, ".config", "*", "DawnCache"),
        os.path.join(home, ".config", "*", "*", "DawnCache"),
        os.path.join(local_share, "DevOS", "webapps", "*", "storage", "GPUCache"),
        os.path.join(local_share, "DevOS", "webapps", "*", "storage", "Code Cache"),
    ]
    app_cache_roots = []
    for pattern in app_cache_patterns:
        for match in sorted(glob.glob(pattern)):
            if os.path.isdir(match) and not os.path.islink(match) and is_within(match, home):
                app_cache_roots.append(match)

    # Exclusions for generic ~/.cache target so items are not counted twice
    cache_exclude = [os.path.join(cache, "devos")] + tmpish + [t.root for t in shader_targets + dev_targets + notif_targets]
    cache_targets = [Target(cache, min_age_s=3600, uid=uid, exclude=cache_exclude)]
    cache_targets += [Target(r, min_age_s=3600, uid=uid) for r in sorted(set(app_cache_roots))]

    win_patterns = [
        os.path.join(local_share, "winlayer", "prefixes", "*", "drive_c", "users",
                     "*", "AppData", "Local", "Temp"),
        os.path.join(local_share, "winlayer", "prefixes", "*", "drive_c", "windows", "temp"),
        os.path.join(home, ".wine", "drive_c", "users", "*", "AppData", "Local", "Temp"),
    ]
    win_roots = []
    for pattern in win_patterns:
        for match in sorted(glob.glob(pattern)):
            if os.path.isdir(match) and not os.path.islink(match) and is_within(match, home):
                win_roots.append(match)
    win_targets = [Target(r, uid=uid) for r in win_roots]

    downloads_targets = [Target(os.path.join(home, "Downloads"), min_age_s=30 * DAY, uid=uid)]

    log_targets = []
    for logs in sorted(glob.glob(os.path.join(local_share, "*", "logs"))):
        if os.path.isdir(logs) and not os.path.islink(logs):
            log_targets.append(Target(logs, min_age_s=7 * DAY, uid=uid))
    log_targets.append(Target(os.path.join(home, ".xsession-errors.old"), uid=uid))
    for crash in sorted(glob.glob(os.path.join(cache, "crash*"))):
        if not os.path.islink(crash):
            log_targets.append(Target(crash, uid=uid))
    for xerr in sorted(glob.glob(os.path.join(home, ".xsession-errors*"))):
        if os.path.isfile(xerr) and not os.path.islink(xerr) and xerr != os.path.join(home, ".xsession-errors"):
            log_targets.append(Target(xerr, uid=uid))

    return [
        Category("temp", "Temporary files",
                 "Your files in /tmp and /var/tmp older than a day, plus app temp folders.",
                 temp_targets),
        Category("cache", "App caches",
                 "Browser caches, thumbnails, GPU/code cache and app data. Apps rebuild them as needed.",
                 cache_targets),
        Category("shaders", "Graphics & shader caches",
                 "Mesa, Vulkan, and OpenGL compiled shader caches. Rebuilt on demand.",
                 shader_targets),
        Category("devcache", "Package & dev caches",
                 "Python pip wheels, NPM, and language build package caches.",
                 dev_targets),
        Category("notifications", "Notifications & cache",
                 "Desktop notification history, active popups, and app/browser notification caches.",
                 notif_targets, default_checked=True),
        Category("clipboard", "Clipboard history",
                 "Saved clipboard clips and copy history in DevOS Clipboard and Klipper.",
                 clip_targets, default_checked=False),
        Category("trash", "Recycle Bin", "Everything currently in the Trash.", trash_targets),
        Category("wintemp", "Windows app temp",
                 "Temp folders inside your Windows app prefixes (like %TEMP% on Windows).",
                 win_targets),
        Category("recent", "Recent files history",
                 "Recently opened document history in file picker and desktop menus.",
                 recent_targets, default_checked=False),
        Category("downloads", "Old downloads",
                 "Files in Downloads older than 30 days. Review before selecting.",
                 downloads_targets, default_checked=False, list_files=True),
        Category("logs", "Crash reports & logs",
                 "App logs older than 7 days, crash dumps, and old session error logs.", log_targets),
    ]


def scan_category(category, now=None):
    """Size a category. Returns a dict; '_entries' holds (path, root) pairs."""
    entries = []
    seen = set()
    total = 0
    for target in category.targets:
        for path, size in target.iter_files(now=now):
            if path in seen:
                continue
            seen.add(path)
            entries.append((path, target.root, target.uid))
            total += size
    result = {
        "id": category.id,
        "label": category.label,
        "description": category.description,
        "default_checked": category.default_checked,
        "size": total,
        "count": len(entries),
        "_entries": entries,
    }
    if category.list_files:
        listed = []
        for path, _root, _uid in entries:
            try:
                listed.append((path, os.lstat(path).st_size))
            except OSError:
                pass
        listed.sort(key=lambda x: -x[1])
        result["_files"] = listed
    return result


def scan_all(categories=None, now=None):
    categories = categories if categories is not None else build_categories()
    return [scan_category(c, now=now) for c in categories]


def clear_live_clipboard():
    """Clear clipboard contents and history in Klipper, X11, and Wayland."""
    for exe in ("qdbus6", "qdbus", "qdbus-qt6", "qdbus-qt5"):
        try:
            subprocess.run([exe, "org.kde.klipper", "/klipper", "clearClipboardHistory"],
                           capture_output=True, timeout=1)
            subprocess.run([exe, "org.kde.klipper", "/klipper", "clearClipboardContents"],
                           capture_output=True, timeout=1)
        except (OSError, subprocess.SubprocessError):
            continue
    try:
        subprocess.run(["xclip", "-selection", "clipboard", "/dev/null"],
                       capture_output=True, timeout=1)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        subprocess.run(["wl-copy", "--clear"], capture_output=True, timeout=1)
    except (OSError, subprocess.SubprocessError):
        pass


def clear_live_notifications():
    """Dismiss active notification popups and clear live desktop notifications."""
    for exe in ("qdbus6", "qdbus", "qdbus-qt6", "qdbus-qt5"):
        try:
            for notif_id in range(1, 200):
                subprocess.run([exe, "org.freedesktop.Notifications",
                                "/org/freedesktop/Notifications",
                                "org.freedesktop.Notifications.CloseNotification",
                                str(notif_id)], capture_output=True, timeout=0.03)
            break
        except (OSError, subprocess.SubprocessError):
            continue


def clean_entries(entries):
    """Delete scanned entries after re-checking safety. Returns (freed, errors)."""
    freed = 0
    errors = 0
    parents = {}
    had_clipboard = False
    had_notifications = False
    for path, root, uid in entries:
        if not is_safe_entry(path, root, uid):
            errors += 1
            continue
        p_lower = path.lower()
        if "clipboard" in p_lower or "klipper" in p_lower:
            had_clipboard = True
        if "notif" in p_lower or "platform notifications" in p_lower:
            had_notifications = True
        try:
            size = os.lstat(path).st_size
            os.remove(path)
            freed += size
            parents[os.path.dirname(path)] = root
        except OSError:
            errors += 1
    # Remove directories emptied by our deletions, never the root itself.
    for directory in sorted(parents, key=lambda p: -p.count(os.sep)):
        root = parents[directory]
        real_root = os.path.realpath(root)
        cur = directory
        while is_within(cur, root) and os.path.realpath(cur) != real_root:
            if os.path.islink(cur):
                break
            try:
                os.rmdir(cur)  # only succeeds when empty
            except OSError:
                break
            cur = os.path.dirname(cur)
    if had_clipboard:
        clear_live_clipboard()
    if had_notifications:
        clear_live_notifications()
    return freed, errors


def public_scan(results):
    """Scan results without private fields or file names (for JSON/AI)."""
    out = []
    for r in results:
        out.append({k: v for k, v in r.items() if not k.startswith("_")})
    return out


# ---------------------------------------------------------------------------
# Memory / disk
# ---------------------------------------------------------------------------

def read_meminfo(path="/proc/meminfo"):
    info = {}
    try:
        with open(path, "r") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1]) * 1024
    except (OSError, ValueError):
        return {"total": 0, "available": 0, "used": 0}
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    return {"total": total, "available": avail, "used": max(0, total - avail)}


def disk_status(paths=None):
    paths = paths or ["/", home_dir()]
    out = []
    seen = set()
    for p in paths:
        try:
            dev = os.stat(p).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            du = shutil.disk_usage(p)
        except OSError:
            continue
        out.append({"path": p, "total": du.total, "free": du.free})
    return out


def low_disk(statuses, fraction=LOW_DISK_FRACTION, min_bytes=LOW_DISK_BYTES):
    return [s for s in statuses
            if s["total"] and (s["free"] < s["total"] * fraction or s["free"] < min_bytes)]


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

try:
    CLK_TCK = os.sysconf("SC_CLK_TCK")
    PAGE_SIZE = os.sysconf("SC_PAGE_SIZE")
except (AttributeError, ValueError, OSError):
    CLK_TCK, PAGE_SIZE = 100, 4096


def parse_proc_stat(text):
    """Parse /proc/<pid>/stat -> (comm, ppid, cpu_seconds)."""
    lpar = text.index("(")
    rpar = text.rindex(")")
    comm = text[lpar + 1:rpar]
    fields = text[rpar + 2:].split()
    ppid = int(fields[1])
    utime, stime = int(fields[11]), int(fields[12])
    return comm, ppid, (utime + stime) / float(CLK_TCK)


def read_process_table(proc_root="/proc"):
    """Return {pid: {comm, ppid, uid, rss, cpu}} for all readable processes."""
    table = {}
    for name in _listdir_safe(proc_root):
        if not name.isdigit():
            continue
        pid = int(name)
        base = os.path.join(proc_root, name)
        try:
            with open(os.path.join(base, "stat"), "r") as fh:
                comm, ppid, cpu = parse_proc_stat(fh.read())
            with open(os.path.join(base, "statm"), "r") as fh:
                rss = int(fh.read().split()[1]) * PAGE_SIZE
            uid = os.stat(base).st_uid
        except (OSError, ValueError, IndexError):
            continue
        table[pid] = {"comm": comm, "ppid": ppid, "uid": uid, "rss": rss, "cpu": cpu}
    return table


def children_map(table):
    kids = {}
    for pid, info in table.items():
        kids.setdefault(info["ppid"], []).append(pid)
    return kids


def process_tree(pid, table, kids=None):
    kids = kids if kids is not None else children_map(table)
    out, stack, seen = [], [pid], set()
    while stack:
        p = stack.pop()
        if p in seen or p not in table:
            continue
        seen.add(p)
        out.append(p)
        stack.extend(kids.get(p, []))
    return out


def tree_rss(pid, table, kids=None):
    return sum(table[p]["rss"] for p in process_tree(pid, table, kids))


def tree_cpu(pid, table, kids=None):
    return sum(table[p]["cpu"] for p in process_tree(pid, table, kids))


def is_runtime(comm):
    return bool(re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|node(?:js)?|java|ruby|perl|bash|sh", comm.lower()))


def app_root(pid, table):
    """Climb parents while they are the same program (e.g. Chrome helpers)."""
    cur = pid
    if is_runtime(table.get(pid, {}).get("comm", "")):
        return pid  # Two Python processes can belong to different applications.
    for _ in range(64):
        info = table.get(cur)
        parent = table.get(info["ppid"]) if info else None
        if not parent or parent["comm"] != info["comm"] or parent["uid"] != info["uid"]:
            return cur
        cur = info["ppid"]
    return cur


DEVOS_CMD_IDENTITIES = (
    ("agent_gui.py", "DevOS AI Code Agent", True),
    ("code_agent.py", "DevOS AI Code Agent", True),
    ("devos-ai-code-agent", "DevOS AI Code Agent", True),
    ("assistant.py", "DevOS AI Chat", True),
    ("devos-chat", "DevOS AI Chat", True),
    ("chat_gui.py", "DevOS AI Chat", True),
    ("ai-core/server.py", "DevOS AI Core (Local Neural Engine & API)", True),
    ("devos-ai-core", "DevOS AI Core (Local Neural Engine & API)", True),
    ("models_gui.py", "DevOS AI Models", True),
    ("models_cli.py", "DevOS AI Models", True),
    ("dashboard_server.py", "DevOS Dashboard", True),
    ("optimizer.py", "DevOS Optimizer", True),
    ("security_gui.py", "DevOS Security", True),
    ("security_center.py", "DevOS Security", True),
    ("notepad.py", "DevOS Notepad", False),
    ("notes.py", "DevOS Notes", False),
    ("phonelink.py", "DevOS Phone Link", False),
    ("islamic", "DevOS Islamic", False),
    ("winlayer", "DevOS WinLayer", True),
    ("vault.py", "DevOS Vault", True),
    ("devos-files", "This PC", False),
    ("devos-thispc", "This PC", False),
    ("cloud_backup.py", "DevOS Cloud Backup", True),
    ("kids_mode.py", "Kids Mode", True),
    ("power_settings.py", "Power Settings", True),
    ("taskman.py", "Task Manager", True),
    ("app_manager.py", "Apps", False),
    ("apps_manager.py", "Apps", False),
    ("explorer.py", "Files", False),
    ("clipboard.py", "Clipboard", True),
    ("first_boot.py", "DevOS Setup", True),
)


def resolve_proc_cmdline(pid, proc_root="/proc"):
    try:
        with open(os.path.join(proc_root, str(pid), "cmdline"), "rb") as fh:
            return fh.read().decode("utf-8", "replace").replace("\x00", " ")
    except OSError:
        return ""


def is_ai_service_active(pid, proc_root="/proc"):
    """Check if process or its command line represents an active DevOS AI daemon."""
    cmd = resolve_proc_cmdline(pid, proc_root)
    if "/ai-core/" in cmd or any(os.path.basename(token) in ("devos-ai", "devos-ai-core", "llama-server", "ollama")
                                       for token in cmd.split()):
        return True
    return False


@functools.lru_cache(maxsize=8)
def desktop_identities(directories):
    """Read app launcher names; never execute launcher contents."""
    found = []
    for directory in directories:
        for path in sorted(glob.glob(os.path.join(directory, "*.desktop"))):
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                parser.read(path, encoding="utf-8")
                entry = parser["Desktop Entry"]
                name = entry.get("Name", "").strip()
                argv = shlex.split(entry.get("Exec", ""))
                if not name or not argv or entry.get("Hidden", "false").lower() == "true":
                    continue
                scripts = [token for token in argv[1:] if token.endswith((".py", ".js", ".jar"))]
                key = scripts[0] if scripts else argv[0]
                if not is_runtime(os.path.basename(key)) and os.path.basename(key) != "env":
                    found.append((os.path.basename(key), name[:100]))
            except (OSError, ValueError, KeyError, configparser.Error):
                continue
    return tuple(found)


def resolve_app_identity(comm, pid=None, proc_root="/proc", desktop_dirs=None):
    """Identify real app name and whether it is a protected system/AI service."""
    comm_lower = comm.lower()
    if pid is not None:
        cmd = resolve_proc_cmdline(pid, proc_root)
        if cmd:
            tokens = cmd.split()
            for pattern, name, is_prot in DEVOS_CMD_IDENTITIES:
                if any(token == pattern or token.endswith("/" + pattern) or
                       (pattern in ("islamic", "winlayer") and "/" + pattern + "/" in token) for token in tokens):
                    return name, is_prot
            if is_ai_service_active(pid, proc_root):
                return "DevOS AI Core (Local Neural Engine & API)", True
            directories = tuple(desktop_dirs) if desktop_dirs is not None else (
                os.path.expanduser("~/.local/share/applications"), "/usr/local/share/applications", "/usr/share/applications")
            basenames = {os.path.basename(token) for token in tokens}
            for executable, name in desktop_identities(directories):
                if executable in basenames:
                    return name, False

    if is_runtime(comm_lower):
        # An unnamed interpreter may be running a download, build, or service.
        # It is not an identifiable idle application that we should offer to close.
        return "Background app", True
    if comm_lower in PRETTY_NAMES:
        return PRETTY_NAMES[comm_lower], comm_lower in PROTECTED_NAMES
    name = comm[:1].upper() + comm[1:]
    return name, comm_lower in PROTECTED_NAMES


def pretty_name(comm, pid=None):
    name, _ = resolve_app_identity(comm, pid)
    return name


def is_protected(comm, pid=None, uid=None, my_uid=None, my_pid=None, proc_root="/proc"):
    if comm.lower() in PROTECTED_NAMES:
        return True
    if pid is not None and pid <= 1:
        return True
    if my_pid is not None and pid == my_pid:
        return True
    if my_uid is not None and uid != my_uid:
        return True
    if pid is not None:
        _, prot = resolve_app_identity(comm, pid, proc_root=proc_root)
        if prot:
            return True
        if is_ai_service_active(pid, proc_root=proc_root):
            return True
    return False


def _run(cmd, timeout=3):
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=timeout, check=False)
        return res.stdout.decode("utf-8", "replace") if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def have_wmctrl():
    return shutil.which("wmctrl") is not None


def wmctrl_windows():
    """Return {pid: [window ids]} for top-level windows, or None if unavailable."""
    if not have_wmctrl() or not os.environ.get("DISPLAY"):
        return None
    out = _run(["wmctrl", "-lp"])
    if out is None:
        return None
    return parse_wmctrl(out)


def parse_wmctrl(text):
    windows = {}
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 3:
            continue
        winid, desktop, pid = parts[0], parts[1], parts[2]
        if desktop == "-1":  # sticky panels/docks
            continue
        try:
            pid = int(pid)
        except ValueError:
            continue
        if pid > 0:
            windows.setdefault(pid, []).append(winid)
    return windows


def active_window_pid():
    if not os.environ.get("DISPLAY"):
        return None
    out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    m = re.search(r"window id # (0x[0-9a-fA-F]+)", out or "")
    if not m or int(m.group(1), 16) == 0:
        return None
    out = _run(["xprop", "-id", m.group(1), "_NET_WM_PID"])
    m = re.search(r"=\s*(\d+)", out or "")
    return int(m.group(1)) if m else None


def _has_display(pid, proc_root="/proc"):
    try:
        with open(os.path.join(proc_root, str(pid), "environ"), "rb") as fh:
            env = fh.read()
    except OSError:
        return False
    return b"\0DISPLAY=" in b"\0" + env


def fallback_gui_pids(table, my_uid, proc_root="/proc"):
    """/proc fallback: user processes with DISPLAY whose parent is a session
    process (or lacks DISPLAY), i.e. probable app roots."""
    pids = []
    for pid, info in table.items():
        if info["uid"] != my_uid:
            continue
        comm = info["comm"].lower()
        if comm in PROTECTED_NAMES or comm in NON_APP_NAMES:
            continue
        if not _has_display(pid, proc_root):
            continue
        parent = table.get(info["ppid"])
        if parent is None or parent["comm"].lower() in SESSION_PARENTS \
                or not _has_display(info["ppid"], proc_root):
            pids.append(pid)
    return pids


def _is_self(pid):
    if pid == os.getpid():
        return True
    try:
        with open("/proc/%d/cmdline" % pid, "rb") as fh:
            return b"optimizer.py" in fh.read()
    except OSError:
        return False


def collect_apps(table=None, windows=None, my_uid=None, my_pid=None):
    """Group GUI processes into apps.
    Returns {key: {key, name, comm, pid, rss, cpu, uid, windows, protected}}."""
    table = table if table is not None else read_process_table()
    my_uid = os.getuid() if my_uid is None else my_uid
    my_pid = os.getpid() if my_pid is None else my_pid
    if windows is None:
        windows = wmctrl_windows()
    if windows is None:
        windows = {pid: [] for pid in fallback_gui_pids(table, my_uid)}
    kids = children_map(table)
    apps = {}
    for pid, wins in windows.items():
        if pid not in table:
            continue
        root = app_root(pid, table)
        info = table[root]
        key = "%s:%d" % (info["comm"].lower(), root)
        app = apps.get(key)
        if app is None:
            name, is_prot = resolve_app_identity(info["comm"], root)
            protected = is_prot or is_protected(info["comm"], root, info["uid"], my_uid, my_pid) or _is_self(root)
            app = apps[key] = {
                "key": key, "name": name,
                "comm": info["comm"].lower(), "pid": root, "uid": info["uid"],
                "rss": tree_rss(root, table, kids), "cpu": tree_cpu(root, table, kids),
                "windows": [],
                "protected": protected,
            }
        app["windows"].extend(wins)
    return apps


# ---------------------------------------------------------------------------
# Idle decision logic (pure)
# ---------------------------------------------------------------------------

class IdleTracker(object):
    """Tracks when each app was last active (focused or using CPU)."""

    def __init__(self, idle_minutes=DEFAULT_IDLE_MINUTES, min_rss=MIN_RSS_BYTES,
                 cpu_active_pct=CPU_ACTIVE_PCT, never_ask=()):
        self.idle_minutes = clamp_idle_minutes(idle_minutes)
        self.min_rss = min_rss
        self.cpu_active_pct = cpu_active_pct
        self.never_ask = {n.lower() for n in never_ask}
        self.state = {}  # key -> {last_active, last_cpu, last_time, app}

    def update(self, now, apps, focused_key=None):
        for key in list(self.state):
            if key not in apps:
                del self.state[key]
        for key, app in apps.items():
            st = self.state.get(key)
            if st is None:
                self.state[key] = {"last_active": now, "last_cpu": app["cpu"],
                                   "last_time": now, "cpu_pct": 0.0, "app": app}
                continue
            dt = now - st["last_time"]
            pct = (app["cpu"] - st["last_cpu"]) / dt * 100.0 if dt > 0 else 0.0
            st["cpu_pct"] = max(0.0, pct)
            if pct > self.cpu_active_pct:
                st["last_active"] = now
            st.update(last_cpu=app["cpu"], last_time=now, app=app)
        if focused_key and focused_key in self.state:
            self.state[focused_key]["last_active"] = now

    def mark_active(self, key, now):
        if key in self.state:
            self.state[key]["last_active"] = now

    def idle_minutes_of(self, key, now):
        st = self.state.get(key)
        return (now - st["last_active"]) / 60.0 if st else 0.0

    def candidates(self, now):
        out = []
        for key, st in self.state.items():
            app = st["app"]
            if app.get("protected") or app["comm"] in PROTECTED_NAMES:
                continue
            if app["comm"] in self.never_ask:
                continue
            if app["rss"] < self.min_rss:
                continue
            if self.idle_minutes_of(key, now) < self.idle_minutes:
                continue
            out.append(app)
        out.sort(key=lambda a: -a["rss"])
        return out


class SuggestionLimiter(object):
    """At most one suggestion per interval, plus an optional pause."""

    def __init__(self, interval_s=SUGGESTION_INTERVAL_S, paused_until=0):
        self.interval_s = interval_s
        self.paused_until = paused_until
        self.last = None

    def can_suggest(self, now):
        if now < self.paused_until:
            return False
        return self.last is None or now - self.last >= self.interval_s

    def record(self, now):
        self.last = now

    def pause(self, now, seconds):
        self.paused_until = now + seconds


def suggestion_text(app, idle_min):
    return "%s has been quiet in the background for %d min and is using %s of memory. Finished with it? You can close it or keep it running." % (
        app["name"], int(idle_min), human_size(app["rss"]))


def focused_app_key(apps, focused_pid, table):
    if not focused_pid or focused_pid not in table:
        return None
    root = app_root(focused_pid, table)
    for key, app in apps.items():
        if app["pid"] == root:
            return key
    return None


def close_app(app, my_uid=None):
    """Politely close an app: wmctrl -ic each window, else SIGTERM. Never SIGKILL."""
    my_uid = os.getuid() if my_uid is None else my_uid
    pid = app["pid"]
    table = read_process_table()
    info = table.get(pid)
    if not info or info["comm"].lower() != app["comm"]:
        return False  # pid gone or reused
    if is_protected(info["comm"], pid, info["uid"], my_uid, os.getpid()) or _is_self(pid):
        return False
    if app.get("windows") and have_wmctrl():
        ok = True
        for win in app["windows"]:
            ok = _run(["wmctrl", "-ic", win]) is not None and ok
        if ok:
            return True
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Local AI
# ---------------------------------------------------------------------------

def build_ai_summary(apps, disks, scan):
    """Short, anonymous summary: app names + MB, disk free, category sizes."""
    top = sorted(apps.values(), key=lambda a: -a["rss"])[:5]
    lines = ["Top memory apps: " + (", ".join(
        "%s %d MB" % (a["name"], a["rss"] // MB) for a in top) or "none")]
    mem = read_meminfo()
    if mem["total"]:
        lines.append("RAM used %d of %d MB." % (mem["used"] // MB, mem["total"] // MB))
    for d in disks:
        lines.append("Disk %s: %.1f GB free of %.1f GB." % (
            "home" if d["path"] != "/" else "system", d["free"] / GB, d["total"] / GB))
    if scan:
        lines.append("Reclaimable: " + ", ".join(
            "%s %s" % (c["label"], human_size(c["size"])) for c in scan))
    return "\n".join(lines)


def ask_ai(summary, url=AI_URL, timeout=AI_TIMEOUT_S):
    payload = {
        "model": "devos",
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": "You are the DevOS assistant. Give one short, "
             "friendly, practical tip (max 2 sentences) to keep this PC fast."},
            {"role": "user", "content": summary},
        ],
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text or AI_UNAVAILABLE_MSG
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return AI_UNAVAILABLE_MSG


# ---------------------------------------------------------------------------
# Single instance
# ---------------------------------------------------------------------------

def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or "/tmp"


def lock_path():
    return os.path.join(runtime_dir(), "devos-optimizer.lock")


def socket_path():
    return os.path.join(runtime_dir(), "devos-optimizer.sock")


def acquire_lock(path=None):
    """Return an open, flock'ed file object, or None if another instance holds it."""
    import fcntl
    fh = open(path or lock_path(), "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def send_to_running(command, path=None):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(path or socket_path())
        s.sendall(command.encode("ascii") + b"\n")
        s.close()
        return True
    except (OSError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# CLI modes
# ---------------------------------------------------------------------------

def cmd_scan():
    results = scan_all()
    mem = read_meminfo()
    print(json.dumps({
        "categories": public_scan(results),
        "total_reclaimable": sum(r["size"] for r in results),
        "default_reclaimable": sum(r["size"] for r in results if r["default_checked"]),
        "memory": mem,
        "disks": disk_status(),
    }, indent=2))
    return 0


def cmd_idle_report(interval=2.0):
    cfg = load_config()
    tracker = IdleTracker(cfg["idle_minutes"], never_ask=cfg["never_ask"])
    t0 = time.time()
    tracker.update(t0, collect_apps())
    time.sleep(interval)
    table = read_process_table()
    apps = collect_apps(table=table)
    now = time.time()
    focused = focused_app_key(apps, active_window_pid(), table)
    tracker.update(now, apps, focused)
    report = []
    for key, st in sorted(tracker.state.items(), key=lambda kv: -kv[1]["app"]["rss"]):
        app = st["app"]
        report.append({
            "name": app["name"], "comm": app["comm"], "pid": app["pid"],
            "rss_mb": round(app["rss"] / MB, 1), "cpu_pct": round(st["cpu_pct"], 1),
            "focused": key == focused, "idle_minutes": round(tracker.idle_minutes_of(key, now), 1),
            "protected": bool(app["protected"]), "never_ask": app["comm"] in tracker.never_ask,
            "windows": len(app["windows"]),
        })
    print(json.dumps({"source": "wmctrl" if wmctrl_windows() is not None else "proc",
                      "idle_threshold_minutes": tracker.idle_minutes,
                      "apps": report}, indent=2))
    return 0


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QDialog, QWidget#toast { background: #0b0f19; color: #e5e7eb;
  font-family: "Inter", "Noto Sans", sans-serif; font-size: 10.5pt; }
QFrame.card, QFrame#card { background: #111827; border-radius: 12px;
  border: 1px solid #1f2937; }
QLabel { color: #e5e7eb; background: transparent; }
QLabel#title { font-size: 18pt; font-weight: 600; color: #f9fafb; }
QLabel#muted { color: #9ca3af; font-size: 9.5pt; }
QLabel#size { color: #38bdf8; font-weight: 600; }
QLabel#total { color: #38bdf8; font-size: 11.5pt; font-weight: 600; }
QLabel#ai { color: #cbd5e1; background: #0f172a; border-radius: 10px; padding: 10px; }
QCheckBox { color: #f3f4f6; font-weight: 600; spacing: 10px; background: transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 5px;
  border: 1px solid #374151; background: #0b0f19; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QPushButton { background: #1f2937; color: #e5e7eb; border: none; border-radius: 8px;
  padding: 7px 14px; font-weight: 500; font-size: 10pt; }
QPushButton:hover { background: #273449; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #38bdf8; color: #0b0f19; font-weight: 600; font-size: 10.5pt; }
QPushButton#primary:hover { background: #7dd3fc; }
QProgressBar { background: #1f2937; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #38bdf8; border-radius: 4px; }
QListWidget { background: #0b0f19; color: #cbd5e1; border: 1px solid #1f2937;
  border-radius: 8px; font-size: 9pt; }
QScrollArea { background: transparent; border: none; }
"""


SECURITY_CLI = "/usr/local/bin/devos-security"


def open_security():
    """The DevOS Security window (components/security)."""
    cmd = [SECURITY_CLI, "gui"] if os.path.exists(SECURITY_CLI) else [
        sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "security", "security_center.py"), "gui"]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        pass


def run_gui(open_cleanup=False):
    from PyQt5 import QtCore, QtGui, QtWidgets

    class ScanThread(QtCore.QThread):
        done = QtCore.pyqtSignal(object)

        def run(self):
            try:
                self.done.emit(scan_all())
            except Exception:  # never crash the tray on a scan problem
                self.done.emit([])

    class CleanThread(QtCore.QThread):
        done = QtCore.pyqtSignal(object, object)

        def __init__(self, entries, parent=None):
            super().__init__(parent)
            self.entries = entries

        def run(self):
            freed, errors = clean_entries(self.entries)
            self.done.emit(freed, errors)

    class AiThread(QtCore.QThread):
        done = QtCore.pyqtSignal(str)

        def __init__(self, summary, parent=None):
            super().__init__(parent)
            self.summary = summary

        def run(self):
            self.done.emit(ask_ai(self.summary))

    def card():
        frame = QtWidgets.QFrame()
        frame.setObjectName("card")
        frame.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        return frame

    class CleanupDialog(QtWidgets.QDialog):
        def __init__(self, tray=None):
            super().__init__()
            self.tray = tray
            self.results = []
            self.rows = {}
            self.threads = []
            self.freed_msg = ""
            self.setWindowTitle("DevOS Optimizer — Clean up")
            self.setWindowIcon(app_icon())
            self.setMinimumSize(640, 700)
            self.resize(660, 720)
            self.setStyleSheet(STYLE)
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(24, 22, 24, 22)
            outer.setSpacing(14)

            title = QtWidgets.QLabel("Clean up")
            title.setObjectName("title")
            sub = QtWidgets.QLabel("Free space safely. Only your own files are touched.")
            sub.setObjectName("muted")
            outer.addWidget(title)
            outer.addWidget(sub)

            # Memory + disk card
            sys_card = card()
            grid = QtWidgets.QGridLayout(sys_card)
            grid.setContentsMargins(16, 14, 16, 14)
            self.mem_label = QtWidgets.QLabel()
            self.mem_bar = QtWidgets.QProgressBar()
            self.mem_bar.setTextVisible(False)
            self.disk_label = QtWidgets.QLabel()
            self.disk_bar = QtWidgets.QProgressBar()
            self.disk_bar.setTextVisible(False)
            grid.addWidget(QtWidgets.QLabel("Memory"), 0, 0)
            grid.addWidget(self.mem_label, 0, 1, QtCore.Qt.AlignRight)
            grid.addWidget(self.mem_bar, 1, 0, 1, 2)
            grid.addWidget(QtWidgets.QLabel("Disk"), 2, 0)
            grid.addWidget(self.disk_label, 2, 1, QtCore.Qt.AlignRight)
            grid.addWidget(self.disk_bar, 3, 0, 1, 2)
            outer.addWidget(sys_card)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            holder = QtWidgets.QWidget()
            holder.setStyleSheet("background: transparent;")
            self.list_layout = QtWidgets.QVBoxLayout(holder)
            self.list_layout.setContentsMargins(0, 0, 0, 0)
            self.list_layout.setSpacing(10)
            self.status = QtWidgets.QLabel("Measuring…")
            self.status.setObjectName("muted")
            self.list_layout.addWidget(self.status)
            self.list_layout.addStretch(1)
            scroll.setWidget(holder)
            outer.addWidget(scroll, 1)

            self.ai_label = QtWidgets.QLabel("")
            self.ai_label.setObjectName("ai")
            self.ai_label.setWordWrap(True)
            self.ai_label.hide()
            outer.addWidget(self.ai_label)

            footer = QtWidgets.QVBoxLayout()
            footer.setSpacing(10)

            top_row = QtWidgets.QHBoxLayout()
            self.total_label = QtWidgets.QLabel("")
            self.total_label.setObjectName("total")
            top_row.addWidget(self.total_label, 1)

            self.security_btn = QtWidgets.QPushButton("Security")
            self.security_btn.setToolTip("Open DevOS Security (virus, web and disk protection)")
            self.security_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.security_btn.clicked.connect(open_security)
            top_row.addWidget(self.security_btn)

            self.rescan_btn = QtWidgets.QPushButton("Rescan")
            self.rescan_btn.setCursor(QtCore.Qt.PointingHandCursor)
            top_row.addWidget(self.rescan_btn)
            footer.addLayout(top_row)

            btn_row = QtWidgets.QHBoxLayout()
            self.ai_btn = QtWidgets.QPushButton("Ask DevOS AI")
            self.ai_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.clean_btn = QtWidgets.QPushButton("Clean selected")
            self.clean_btn.setObjectName("primary")
            self.clean_btn.setCursor(QtCore.Qt.PointingHandCursor)
            self.clean_btn.setMinimumHeight(38)
            btn_row.addWidget(self.ai_btn)
            btn_row.addWidget(self.clean_btn, 1)
            footer.addLayout(btn_row)

            outer.addLayout(footer)

            self.rescan_btn.clicked.connect(self.rescan)
            self.ai_btn.clicked.connect(self.ask_ai)
            self.clean_btn.clicked.connect(self.clean)
            self.refresh_system()
            self.rescan()

        def _start(self, thread):
            self.threads.append(thread)
            thread.finished.connect(lambda t=thread: self.threads.remove(t)
                                    if t in self.threads else None)
            thread.start()

        def refresh_system(self):
            mem = read_meminfo()
            if mem["total"]:
                self.mem_label.setText("%s of %s used" % (human_size(mem["used"]),
                                                          human_size(mem["total"])))
                self.mem_bar.setValue(int(mem["used"] * 100 / mem["total"]))
            disks = disk_status()
            if disks:
                d = min(disks, key=lambda x: x["free"])
                self.disk_label.setText("%s free of %s" % (human_size(d["free"]),
                                                           human_size(d["total"])))
                self.disk_bar.setValue(int((d["total"] - d["free"]) * 100 / max(1, d["total"])))

        def rescan(self):
            self.clean_btn.setEnabled(False)
            self.rescan_btn.setEnabled(False)
            self.status.setText("Measuring…")
            self.status.show()
            self.total_label.setText("")
            t = ScanThread(self)
            t.done.connect(self.on_scanned)
            self._start(t)

        def on_scanned(self, results):
            self.results = results
            for row in self.rows.values():
                row["frame"].deleteLater()
            self.rows = {}
            self.status.hide()
            for i, r in enumerate(results):
                frame = card()
                lay = QtWidgets.QVBoxLayout(frame)
                lay.setContentsMargins(16, 12, 16, 12)
                top = QtWidgets.QHBoxLayout()
                cb = QtWidgets.QCheckBox(r["label"])
                cb.setChecked(r["default_checked"] and r["size"] > 0)
                cb.setEnabled(r["count"] > 0)
                cb.toggled.connect(self.update_total)
                size = QtWidgets.QLabel(human_size(r["size"]))
                size.setObjectName("size")
                top.addWidget(cb, 1)
                top.addWidget(size)
                lay.addLayout(top)
                desc = QtWidgets.QLabel("%s  ·  %d items" % (r["description"], r["count"]))
                desc.setObjectName("muted")
                desc.setWordWrap(True)
                lay.addWidget(desc)
                if r.get("_files"):
                    lw = QtWidgets.QListWidget()
                    lw.setMaximumHeight(110)
                    for path, sz in r["_files"][:200]:
                        lw.addItem("%s  —  %s" % (os.path.basename(path), human_size(sz)))
                    lay.addWidget(lw)
                self.list_layout.insertWidget(i + 1, frame)
                self.rows[r["id"]] = {"frame": frame, "check": cb, "result": r}
            self.rescan_btn.setEnabled(True)
            self.update_total()

        def selected(self):
            return [row["result"] for row in self.rows.values() if row["check"].isChecked()]

        def update_total(self):
            total = sum(r["size"] for r in self.results)
            sel = sum(r["size"] for r in self.selected())
            text = "%s selected  ·  %s reclaimable" % (human_size(sel), human_size(total))
            if self.freed_msg:
                text = self.freed_msg + "  ·  " + text
            self.total_label.setText(text)
            self.clean_btn.setEnabled(sel > 0)

        def clean(self):
            chosen = self.selected()
            if not chosen:
                return
            size = sum(r["size"] for r in chosen)
            names = ", ".join(r["label"] for r in chosen)
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Clean selected")
            box.setText("Permanently remove %s from: %s?" % (human_size(size), names))
            box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel)
            box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
            if box.exec_() != QtWidgets.QMessageBox.Yes:
                return
            entries = [e for r in chosen for e in r["_entries"]]
            self.clean_btn.setEnabled(False)
            self.rescan_btn.setEnabled(False)
            self.total_label.setText("Cleaning…")
            t = CleanThread(entries, self)
            t.done.connect(self.on_cleaned)
            self._start(t)

        def on_cleaned(self, freed, errors):
            msg = "Freed %s" % human_size(freed)
            if errors:
                msg += " (%d items skipped)" % errors
            self.freed_msg = msg
            self.refresh_system()
            self.rescan()
            if self.tray:
                self.tray.notify_plain(msg + ".")

        def ask_ai(self):
            self.ai_btn.setEnabled(False)
            self.ai_label.setText("Asking DevOS AI…")
            self.ai_label.show()
            apps = self.tray.last_apps if self.tray else {}
            if not apps:
                try:
                    apps = collect_apps()
                except Exception:
                    apps = {}
            summary = build_ai_summary(apps, disk_status(), public_scan(self.results))
            t = AiThread(summary, self)
            t.done.connect(self.on_ai)
            self._start(t)

        def on_ai(self, text):
            self.ai_label.setText(text)
            self.ai_btn.setEnabled(True)

    class Toast(QtWidgets.QWidget):
        """Premium-styled notification with action buttons, bottom-right."""

        def __init__(self, title, text, actions, timeout_ms=60000):
            super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                             | QtCore.Qt.WindowStaysOnTopHint)
            self.setObjectName("toast")
            self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setStyleSheet(STYLE + "QWidget#toast { border: 1px solid #1f2937;"
                               " border-radius: 12px; }")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(18, 14, 18, 14)
            head = QtWidgets.QLabel(title)
            head.setStyleSheet("color:#38bdf8; font-weight:600;")
            body = QtWidgets.QLabel(text)
            body.setWordWrap(True)
            lay.addWidget(head)
            lay.addWidget(body)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            for i, (label, callback) in enumerate(actions):
                b = QtWidgets.QPushButton(label)
                if i == 0:
                    b.setObjectName("primary")
                b.setCursor(QtCore.Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, cb=callback: (cb(), self.close()))
                row.addWidget(b)
            lay.addLayout(row)
            self.setFixedWidth(400)
            self.adjustSize()
            geo = QtWidgets.QApplication.desktop().availableGeometry()
            self.move(geo.right() - self.width() - 16, geo.bottom() - self.height() - 16)
            QtCore.QTimer.singleShot(timeout_ms, self.close)

    def app_icon():
        icon = QtGui.QIcon.fromTheme("speedometer")
        if icon.isNull():
            icon = QtGui.QIcon.fromTheme("preferences-system-performance")
        return icon

    class TrayApp(QtCore.QObject):
        def __init__(self, qapp):
            super().__init__()
            self.qapp = qapp
            self.cfg = load_config()
            self.tracker = IdleTracker(self.cfg["idle_minutes"], never_ask=self.cfg["never_ask"])
            self.limiter = SuggestionLimiter(paused_until=self.cfg["paused_until"])
            self.last_apps = {}
            self.last_disk_warn = 0
            self.dialog = None
            self.toast = None

            self.tray = QtWidgets.QSystemTrayIcon(app_icon(), self)
            self.tray.setToolTip(APP_NAME)
            menu = QtWidgets.QMenu()
            menu.addAction("Clean up…", self.open_cleanup)
            menu.addAction("DevOS Security…", open_security)
            menu.addAction("Pause suggestions for 1 hour", self.pause_hour)
            sub = menu.addMenu("Settings: idle minutes")
            group = QtWidgets.QActionGroup(sub)
            for m in IDLE_CHOICES:
                act = sub.addAction("%d minutes" % m)
                act.setCheckable(True)
                act.setChecked(m == self.cfg["idle_minutes"])
                act.triggered.connect(lambda _=False, v=m: self.set_idle(v))
                group.addAction(act)
            menu.addSeparator()
            menu.addAction("Quit", qapp.quit)
            self.menu = menu
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(self.on_activated)
            self.tray.show()

            self.sample_timer = QtCore.QTimer(self)
            self.sample_timer.timeout.connect(self.sample)
            self.sample_timer.start(SAMPLE_INTERVAL_S * 1000)
            QtCore.QTimer.singleShot(5000, self.sample)
            self.disk_timer = QtCore.QTimer(self)
            self.disk_timer.timeout.connect(self.check_disk)
            self.disk_timer.start(30 * 60 * 1000)
            QtCore.QTimer.singleShot(120 * 1000, self.check_disk)
            self.start_server()

        # --- IPC for --cleanup from a second process
        def start_server(self):
            path = socket_path()
            try:
                if os.path.exists(path):
                    os.unlink(path)
                self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.server.bind(path)
                os.chmod(path, 0o600)
                self.server.listen(4)
                self.server.setblocking(False)
            except OSError:
                self.server = None
                return
            self.notifier = QtCore.QSocketNotifier(self.server.fileno(),
                                                   QtCore.QSocketNotifier.Read, self)
            self.notifier.activated.connect(self.on_ipc)

        def on_ipc(self, *_):
            try:
                conn, _addr = self.server.accept()
                conn.settimeout(1)
                data = conn.recv(64)
                conn.close()
            except OSError:
                return
            if data.strip() == b"cleanup":
                self.open_cleanup()

        def on_activated(self, reason):
            if reason == QtWidgets.QSystemTrayIcon.Trigger:
                self.open_cleanup()

        def save(self):
            self.cfg["never_ask"] = sorted(self.tracker.never_ask)
            self.cfg["idle_minutes"] = self.tracker.idle_minutes
            self.cfg["paused_until"] = self.limiter.paused_until
            try:
                save_config(self.cfg)
            except OSError:
                pass

        def set_idle(self, minutes):
            self.tracker.idle_minutes = clamp_idle_minutes(minutes)
            self.save()

        def pause_hour(self):
            self.limiter.pause(time.time(), 3600)
            self.save()
            self.notify_plain("Suggestions paused for 1 hour.")

        def open_cleanup(self):
            if self.dialog is None:
                self.dialog = CleanupDialog(self)
                self.dialog.finished.connect(self._dialog_closed)
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()

        def _dialog_closed(self, *_):
            self.dialog.deleteLater()
            self.dialog = None

        def notify_plain(self, text):
            self.tray.showMessage(APP_NAME, text, app_icon(), 5000)

        def show_toast(self, title, text, actions):
            if self.toast is not None:
                try:
                    self.toast.close()
                except RuntimeError:
                    pass
            self.toast = Toast(title, text, actions)
            self.toast.show()

        def sample(self):
            try:
                table = read_process_table()
                apps = collect_apps(table=table)
                focused = focused_app_key(apps, active_window_pid(), table)
            except Exception:
                return
            now = time.time()
            self.last_apps = apps
            self.tracker.update(now, apps, focused)
            if not self.limiter.can_suggest(now):
                return
            cands = self.tracker.candidates(now)
            if not cands:
                return
            app = cands[0]
            self.limiter.record(now)
            text = suggestion_text(app, self.tracker.idle_minutes_of(app["key"], now))
            self.show_toast("Free up memory", text, [
                ("Close", lambda a=app: self.do_close(a)),
                ("Keep", lambda a=app: self.tracker.mark_active(a["key"], time.time())),
                ("Don't ask for this app", lambda a=app: self.never_ask(a)),
            ])

        def do_close(self, app):
            if close_app(app):
                self.notify_plain("Asked %s to close." % app["name"])

        def never_ask(self, app):
            self.tracker.never_ask.add(app["comm"])
            self.save()

        def check_disk(self):
            low = low_disk(disk_status())
            now = time.time()
            if not low or now - self.last_disk_warn < 6 * 3600:
                return
            self.last_disk_warn = now
            d = min(low, key=lambda x: x["free"])
            self.show_toast("Running low on space",
                            "Only %s free on %s. Clean up temporary files and caches?" % (
                                human_size(d["free"]),
                                "your home folder" if d["path"] != "/" else "the system disk"),
                            [("Clean up", self.open_cleanup), ("Later", lambda: None)])

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setApplicationName("devos-optimizer")
    qapp.setApplicationDisplayName("DevOS Optimizer")
    if hasattr(qapp, "setDesktopFileName"):
        qapp.setDesktopFileName("devos-optimizer")
    qapp.setQuitOnLastWindowClosed(False)
    font = QtGui.QFont("Inter")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Noto Sans")
    qapp.setFont(font)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        # No tray (unusual session): still allow the dialog on demand.
        if open_cleanup:
            dlg = CleanupDialog(None)
            dlg.show()
            qapp.setQuitOnLastWindowClosed(True)
            return qapp.exec_()
        return 0
    tray = TrayApp(qapp)
    if open_cleanup:
        tray.open_cleanup()
    signal.signal(signal.SIGTERM, lambda *_: qapp.quit())
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    return qapp.exec_()


def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tray", action="store_true", help="start the tray app (default)")
    mode.add_argument("--cleanup", action="store_true", help="open the Clean up dialog")
    mode.add_argument("--scan", action="store_true", help="print reclaimable sizes as JSON")
    mode.add_argument("--idle-report", action="store_true",
                      help="print tracked GUI apps as JSON after one sample")
    args = parser.parse_args(argv)

    if args.scan:
        return cmd_scan()
    if args.idle_report:
        return cmd_idle_report()

    # GUI modes never run in the live/installer session.
    if is_live_session():
        return 0
    lock = acquire_lock()
    if lock is None:
        if args.cleanup:
            send_to_running("cleanup")
        return 0
    try:
        return run_gui(open_cleanup=args.cleanup)
    finally:
        try:
            os.unlink(socket_path())
        except OSError:
            pass
        lock.close()


if __name__ == "__main__":
    sys.exit(main())
