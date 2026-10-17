#!/usr/bin/env python3
"""
DevOS Phone Link - use your phone's web browser as a remote for this PC.

Nothing has to be installed on the phone. The PC runs a small web server on
the local network; the phone scans a QR code shown in the "Phone Link" window,
pairs once, and then gets a remote with:
  * live stats (CPU, memory, disk, battery, uptime)
  * lock screen, volume and media keys, sleep / shut down (with a confirm step)
  * open DevOS apps, send text to the PC clipboard, show a message on the PC
  * send files to ~/Downloads/Phone, browse and download Documents, Desktop,
    Pictures and Downloads, view a fresh screenshot
  * ask DevOS AI

The phone can never run arbitrary commands: every action is a fixed entry in
a whitelist below, and every file path is resolved and checked against the
allowed folders.

CLI:
  phonelink.py gui         open the Phone Link window (default)
  phonelink.py serve       run the web server (what the user service runs)
  phonelink.py enable      turn Phone Link on (starts at login)
  phonelink.py disable     turn Phone Link off
  phonelink.py pair-code   print a fresh one-time pairing code and URL
  phonelink.py status      print the current state as JSON

Everything above the "GUI" section is plain stdlib and importable without a
display (or on Windows) so it can be unit-tested. PyQt5 and qrcode are
imported lazily in the GUI path.
"""

import argparse
import collections
import configparser
import glob
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

APP_NAME = "Phone Link"
PORT = 8765
MB = 1024 * 1024
GB = 1024 * MB

CODE_TTL_S = 5 * 60
CODE_DIGITS = 6
PAIR_FAILS_PER_IP = 5          # failed pairing attempts per IP per window
PAIR_FAILS_GLOBAL = 30         # across all IPs, so many fake IPs do not help
PAIR_FAIL_WINDOW_S = 60
TOKEN_COOKIE = "devos_phonelink"
COOKIE_MAX_AGE = 365 * 86400
LAST_SEEN_SAVE_S = 300         # do not rewrite the config file on every request

MAX_JSON_BODY = 64 * 1024
MAX_UPLOAD = 2 * GB
MAX_TEXT = 100 * 1024          # clipboard text
MAX_NOTIFY = 500
MAX_QUESTION = 4000
MAX_LIST = 2000

# Folders the phone may browse. Only these, only inside the user's home.
ALLOWED_ROOTS = ("Desktop", "Documents", "Downloads", "Pictures")
UPLOAD_SUBDIR = os.path.join("Downloads", "Phone")

AI_URL = "http://127.0.0.1:11434/v1/chat/completions"
AI_TIMEOUT_S = 120
AI_UNAVAILABLE_MSG = "DevOS AI is starting or not installed. Try again in a minute."

APP_DIR = "/usr/share/applications"
# DevOS launchers that make no sense to start from a phone.
HIDDEN_APPS = {"devos-install", "devos-phonelink", "devos-apphub", "devos-winlayer"}
APP_ID_RE = re.compile(r"^devos-[a-z0-9][a-z0-9-]{0,60}$")

SERVICE_NAME = "devos-phonelink.service"
SYSTEM_UNIT = "/usr/lib/systemd/user/" + SERVICE_NAME
SCRIPT_PATH = os.path.abspath(__file__)


def home_dir():
    return os.path.expanduser("~")


def config_dir(home=None):
    base = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    if not base:
        base = os.path.join(home or home_dir(), ".config")
    return os.path.join(base, "devos")


def devices_path(home=None):
    return os.path.join(config_dir(home), "phonelink.json")


def code_path(home=None):
    # The pairing code lives in its own file so the window (or `pair-code`)
    # and the background server, which are different processes, share it.
    return os.path.join(config_dir(home), "phonelink-code.json")


def sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    """Atomic, owner-only write: tokens and codes must not be world-readable."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp-%d-%d" % (path, os.getpid(), threading.get_ident())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Paired devices
# ---------------------------------------------------------------------------

class TokenStore(object):
    """Paired phones. Only sha256(token) is stored; the phone keeps the token
    in an HttpOnly cookie. The file is re-read when it changes so that a phone
    removed in the window is locked out of the running server at once."""

    def __init__(self, path=None):
        self.path = path or devices_path()
        self.lock = threading.Lock()
        self._data = None
        self._mtime = None

    def _load(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            mtime = None
        if self._data is None or mtime != self._mtime:
            data = _read_json(self.path, {})
            devices = data.get("devices")
            data["devices"] = [d for d in devices if isinstance(d, dict)] if isinstance(devices, list) else []
            self._data, self._mtime = data, mtime
        return self._data

    def _save(self):
        _write_json(self.path, self._data)
        try:
            self._mtime = os.path.getmtime(self.path)
        except OSError:
            self._mtime = None

    def add_device(self, name, now=None):
        """Returns (token, public device dict). The token is shown only once."""
        now = time.time() if now is None else now
        token = secrets.token_urlsafe(32)
        device = {"id": secrets.token_hex(4), "name": clean_text(name, 60) or "Phone",
                  "token_sha256": sha256_hex(token), "paired_at": now, "last_seen": now}
        with self.lock:
            self._load()["devices"].append(device)
            self._save()
        return token, public_device(device)

    def verify(self, token, now=None):
        """Device dict for a valid token, else None."""
        if not token or not isinstance(token, str) or len(token) > 200:
            return None
        digest = sha256_hex(token)
        now = time.time() if now is None else now
        with self.lock:
            for device in self._load()["devices"]:
                if hmac.compare_digest(str(device.get("token_sha256", "")), digest):
                    if now - float(device.get("last_seen", 0) or 0) > LAST_SEEN_SAVE_S:
                        device["last_seen"] = now
                        try:
                            self._save()
                        except OSError:
                            pass
                    return public_device(device)
        return None

    def remove(self, device_id):
        with self.lock:
            data = self._load()
            before = len(data["devices"])
            data["devices"] = [d for d in data["devices"] if d.get("id") != device_id]
            if len(data["devices"]) == before:
                return False
            self._save()
            return True

    def devices(self):
        with self.lock:
            return [public_device(d) for d in self._load()["devices"]]


def public_device(device):
    return {"id": device.get("id", ""), "name": device.get("name", "Phone"),
            "paired_at": device.get("paired_at", 0), "last_seen": device.get("last_seen", 0)}


def clean_text(text, limit):
    """Single line, no control characters, at most `limit` characters."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text or "")).strip()
    return text[:limit]


def summarize_user_agent(ua):
    """'Mozilla/5.0 (Linux; Android 14; Pixel 7) ... Chrome/...' -> 'Pixel 7 (Chrome)'."""
    ua = str(ua or "")
    device = "Phone"
    if "iPhone" in ua:
        device = "iPhone"
    elif "iPad" in ua:
        device = "iPad"
    elif "Android" in ua:
        device = "Android phone"
        m = re.search(r"Android [\d.]+; ([^;)]+)\)", ua)
        # Chrome now reports the model as just "K"; that is not worth showing.
        if m and len(m.group(1).strip()) > 1:
            device = m.group(1).strip()
    elif "Windows" in ua:
        device = "Windows PC"
    elif "Macintosh" in ua:
        device = "Mac"
    elif "Linux" in ua:
        device = "Linux device"
    browser = ""
    for token, label in (("SamsungBrowser", "Samsung Internet"), ("EdgA", "Edge"), ("Edg/", "Edge"),
                         ("Firefox", "Firefox"), ("FxiOS", "Firefox"), ("CriOS", "Chrome"),
                         ("Chrome", "Chrome"), ("Safari", "Safari")):
        if token in ua:
            browser = label
            break
    name = "%s (%s)" % (device, browser) if browser else device
    return clean_text(name, 60)


# ---------------------------------------------------------------------------
# One-time pairing codes
# ---------------------------------------------------------------------------

class PairingCodes(object):
    """One active 6-digit code at a time, valid for 5 minutes, usable once."""

    def __init__(self, path=None, ttl=CODE_TTL_S):
        self.path = path or code_path()
        self.ttl = ttl
        self.lock = threading.Lock()

    def issue(self, now=None):
        now = time.time() if now is None else now
        code = "%0*d" % (CODE_DIGITS, secrets.randbelow(10 ** CODE_DIGITS))
        with self.lock:
            _write_json(self.path, {"sha256": sha256_hex(code), "issued": now,
                                    "expires": now + self.ttl})
        return code, now + self.ttl

    def current(self):
        """Raw record (hash + expiry) or None. Used by the window to notice use."""
        data = _read_json(self.path, {})
        return data if data.get("sha256") else None

    def is_current(self, code):
        data = self.current()
        return bool(data and code and hmac.compare_digest(data["sha256"], sha256_hex(code)))

    def clear(self):
        with self.lock:
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def consume(self, code, now=None):
        """True once for the right, unexpired code; the code is gone afterwards."""
        now = time.time() if now is None else now
        code = str(code or "").strip()
        if not re.match(r"^\d{%d}$" % CODE_DIGITS, code):
            return False
        with self.lock:
            data = _read_json(self.path, {})
            if not data.get("sha256"):
                return False
            if now >= float(data.get("expires", 0) or 0):
                try:
                    os.unlink(self.path)
                except OSError:
                    pass
                return False
            if not hmac.compare_digest(str(data["sha256"]), sha256_hex(code)):
                return False
            try:
                os.unlink(self.path)
            except OSError:
                # Could not delete it, so it would stay reusable: refuse.
                return False
            return True


class RateLimiter(object):
    """Counts failures per key in a sliding window."""

    def __init__(self, limit=PAIR_FAILS_PER_IP, window=PAIR_FAIL_WINDOW_S, global_limit=PAIR_FAILS_GLOBAL):
        self.limit = limit
        self.window = window
        self.global_limit = global_limit
        self.fails = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def _trim(self, key, now):
        q = self.fails[key]
        while q and now - q[0] >= self.window:
            q.popleft()
        return q

    def blocked(self, key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            return (len(self._trim(key, now)) >= self.limit
                    or len(self._trim("*", now)) >= self.global_limit)

    def fail(self, key, now=None):
        now = time.time() if now is None else now
        with self.lock:
            self._trim(key, now).append(now)
            self._trim("*", now).append(now)


# ---------------------------------------------------------------------------
# File safety
# ---------------------------------------------------------------------------

class PathError(ValueError):
    pass


def is_within(path, base):
    base = base.rstrip("/\\") or base
    return path == base or path.startswith(base + os.sep)


def resolve_user_path(home, root, rel=""):
    """Real path of `rel` inside ~/<root>, or PathError.

    Hidden names and ".." are refused outright, and the resolved real path
    (after following symlinks) must still be inside the chosen folder.
    """
    if root not in ALLOWED_ROOTS:
        raise PathError("That folder is not shared with the phone.")
    rel = str(rel or "")
    if "\x00" in rel:
        raise PathError("Bad file name.")
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    if any(p.startswith(".") or ":" in p for p in parts):
        raise PathError("That file is not shared with the phone.")
    base = os.path.realpath(os.path.join(home, root))
    target = os.path.realpath(os.path.join(base, *parts)) if parts else base
    if not is_within(target, base):
        raise PathError("That file is not shared with the phone.")
    return target


def safe_filename(name):
    """A plain file name for something the phone sends: no folders, no hidden
    files, no control characters, not too long."""
    name = str(name or "").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]+", "_", name).strip().lstrip(".").strip()
    if not name:
        name = "file"
    if len(name) > 150:
        stem, ext = os.path.splitext(name)
        name = stem[:150 - len(ext[:20])] + ext[:20]
    return name


def unique_path(directory, name):
    stem, ext = os.path.splitext(name)
    candidate = os.path.join(directory, name)
    n = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, "%s (%d)%s" % (stem, n, ext))
        n += 1
    return candidate


def list_folder(home, root, rel=""):
    path = resolve_user_path(home, root, rel)
    if not os.path.isdir(path):
        raise PathError("That folder does not exist.")
    entries = []
    with os.scandir(path) as it:
        for entry in it:
            if entry.name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir()
                st = entry.stat()
            except OSError:
                continue
            entries.append({"name": entry.name, "dir": is_dir,
                            "size": 0 if is_dir else st.st_size, "mtime": int(st.st_mtime)})
            if len(entries) >= MAX_LIST:
                break
    entries.sort(key=lambda e: (not e["dir"], e["name"].casefold()))
    return entries


# ---------------------------------------------------------------------------
# Whitelisted actions
# ---------------------------------------------------------------------------

class ActionError(ValueError):
    pass


# Each action is a list of commands; the first one that exists and succeeds
# wins. KDE's D-Bus calls come first because the user service is not inside a
# login session, so plain loginctl/systemctl would ask for a password.
ACTIONS = {
    "lock": [["qdbus", "org.freedesktop.ScreenSaver", "/ScreenSaver", "Lock"],
             ["loginctl", "lock-session"], ["xdg-screensaver", "lock"]],
    "volume_up": [["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"]],
    "volume_down": [["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"]],
    "mute": [["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"]],
    "play_pause": [["playerctl", "play-pause"]],
    "next": [["playerctl", "next"]],
    "previous": [["playerctl", "previous"]],
    "sleep": [["qdbus", "org.kde.Solid.PowerManagement",
               "/org/kde/Solid/PowerManagement/Actions/SuspendSession", "suspendToRam"],
              ["systemctl", "suspend"]],
    "shutdown": [["qdbus", "org.kde.ksmserver", "/KSMServer", "logout", "0", "2", "2"],
                 ["systemctl", "poweroff"]],
}
CONFIRM_ACTIONS = {"sleep", "shutdown"}


def validate_action(name, confirm=False):
    if not isinstance(name, str) or name not in ACTIONS:
        raise ActionError("Unknown action.")
    if name in CONFIRM_ACTIONS and confirm is not True:
        raise ActionError("Please confirm on the phone first.")
    return ACTIONS[name]


_env_cache = {"time": 0.0, "env": None}


def session_env():
    """Environment for desktop commands. A systemd user service may start
    before Plasma exports DISPLAY, so ask systemd for the current values."""
    now = time.time()
    if _env_cache["env"] is not None and now - _env_cache["time"] < 30:
        return dict(_env_cache["env"])
    env = dict(os.environ)
    try:
        out = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS",
                           "XDG_RUNTIME_DIR", "XDG_CURRENT_DESKTOP") and not value.startswith("$'"):
            env.setdefault(key, value)
    env.setdefault("DISPLAY", ":0")
    xauth = os.path.join(home_dir(), ".Xauthority")
    if "XAUTHORITY" not in env and os.path.exists(xauth):
        env["XAUTHORITY"] = xauth
    _env_cache.update(time=now, env=env)
    return dict(env)


def run_first(commands, input_text=None, timeout=10):
    """Run the first available command of a fixed list (no shell, ever)."""
    env = session_env()
    for cmd in commands:
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(cmd, input=input_text, text=True, env=env, timeout=timeout,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return True
    return False


def run_action(name, confirm=False, runner=run_first):
    commands = validate_action(name, confirm)
    return bool(runner(commands))


def set_clipboard(text, runner=run_first):
    text = str(text or "")
    if not text or len(text) > MAX_TEXT:
        raise ActionError("Send between 1 and %d characters." % MAX_TEXT)
    # Klipper keeps the text after we exit; xclip forks a helper that does too.
    return bool(runner([["qdbus", "org.kde.klipper", "/klipper", "setClipboardContents", text]])
                or runner([["xclip", "-selection", "clipboard"]], input_text=text))


def notify_pc(text, title="Phone Link", runner=run_first):
    text = clean_text(text, MAX_NOTIFY)
    if not text:
        raise ActionError("Type a message first.")
    return bool(runner([["notify-send", "-a", "Phone Link", "-i", "smartphone", title, text]]))


def list_apps(app_dir=APP_DIR):
    """DevOS apps the phone may open: /usr/share/applications/devos-*.desktop."""
    apps = []
    for path in sorted(glob.glob(os.path.join(app_dir, "devos-*.desktop"))):
        app_id = os.path.basename(path)[:-len(".desktop")]
        if app_id in HIDDEN_APPS or not APP_ID_RE.match(app_id):
            continue
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
            entry = parser["Desktop Entry"]
        except (configparser.Error, KeyError, OSError, UnicodeDecodeError):
            continue
        if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
            continue
        apps.append({"id": app_id, "name": clean_text(entry.get("Name", app_id), 40),
                     "icon": clean_text(entry.get("Icon", ""), 80), "path": path})
    return apps


def open_app(app_id, app_dir=APP_DIR):
    apps = {a["id"]: a for a in list_apps(app_dir)}
    if app_id not in apps:
        raise ActionError("That app cannot be opened from the phone.")
    path = apps[app_id]["path"]
    for cmd in (["kioclient5", "exec", path], ["gtk-launch", app_id]):
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd, env=session_env(), stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
                return True
            except OSError:
                continue
    return False


def screenshot_path():
    base = os.environ.get("XDG_RUNTIME_DIR") or os.path.join(home_dir(), ".cache", "devos")
    return os.path.join(base, "devos-phonelink", "screenshot.png")


def take_screenshot(path=None):
    path = path or screenshot_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        os.unlink(path)
    except OSError:
        pass
    if not shutil.which("spectacle"):
        return None
    try:
        subprocess.run(["spectacle", "-b", "-n", "-f", "-o", path], env=session_env(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    # Spectacle can return a moment before the file is fully written.
    deadline = time.time() + 8
    last = -1
    while time.time() < deadline:
        size = os.path.getsize(path) if os.path.exists(path) else -1
        if size > 0 and size == last:
            return path
        last = size
        time.sleep(0.3)
    return path if os.path.exists(path) and os.path.getsize(path) > 0 else None


def ask_ai(question, url=AI_URL, timeout=AI_TIMEOUT_S):
    question = str(question or "").strip()[:MAX_QUESTION]
    if not question:
        raise ActionError("Type a question first.")
    payload = {
        "model": "devos",
        "max_tokens": 400,
        "stream": False,
        "messages": [
            {"role": "system", "content": "You are DevOS AI. The user is asking from their phone, "
             "so keep answers short and clear."},
            {"role": "user", "content": question},
        ],
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip() or AI_UNAVAILABLE_MSG
    except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError):
        return AI_UNAVAILABLE_MSG


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

_cpu_last = {"sample": None}


def _cpu_sample():
    try:
        with open("/proc/stat", "r") as fh:
            fields = [int(x) for x in fh.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
    return sum(fields), idle


def cpu_percent():
    prev = _cpu_last["sample"]
    if prev is None:
        prev = _cpu_sample()
        time.sleep(0.2)
    cur = _cpu_sample()
    _cpu_last["sample"] = cur
    if not prev or not cur or cur[0] <= prev[0]:
        return None
    total, idle = cur[0] - prev[0], cur[1] - prev[1]
    return round(100.0 * (total - idle) / total, 1)


def read_meminfo(path="/proc/meminfo"):
    info = {}
    try:
        with open(path, "r") as fh:
            for line in fh:
                key, _, rest = line.partition(":")
                parts = rest.split()
                if parts and parts[0].isdigit():
                    info[key] = int(parts[0]) * 1024
    except OSError:
        return None
    total = info.get("MemTotal", 0)
    if not total:
        return None
    used = total - info.get("MemAvailable", info.get("MemFree", 0))
    return {"total": total, "used": used, "percent": round(100.0 * used / total, 1)}


def battery():
    for base in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(os.path.join(base, "capacity")) as fh:
                capacity = int(fh.read().strip())
            with open(os.path.join(base, "status")) as fh:
                status = fh.read().strip()
            return {"percent": capacity, "status": status}
        except (OSError, ValueError):
            continue
    return None


def uptime_seconds():
    try:
        with open("/proc/uptime") as fh:
            return int(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return None


def system_stats(home=None):
    try:
        du = shutil.disk_usage(home or home_dir())
        disk = {"total": du.total, "used": du.used, "free": du.free,
                "percent": round(100.0 * du.used / du.total, 1) if du.total else 0}
    except OSError:
        disk = None
    return {"hostname": socket.gethostname(), "cpu": cpu_percent(), "memory": read_meminfo(),
            "disk": disk, "battery": battery(), "uptime": uptime_seconds()}


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def lan_ip():
    """The address the phone should use, or None when the PC is not on a network.
    A UDP connect sends nothing; it only asks the kernel which route it would use."""
    for probe in ("192.168.0.1", "10.0.0.1", "8.8.8.8"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                ip = s.getsockname()[0]
        except OSError:
            continue
        addr = ipaddress.ip_address(ip)
        if not addr.is_loopback and not addr.is_unspecified and not addr.is_link_local:
            return ip
    return None


def pair_url(ip, code, port=PORT):
    return "http://%s:%d/pair?code=%s" % (ip, port, code)


def server_running(port=PORT, timeout=0.4):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def host_allowed(host_header):
    """Only answer to an IP address or this PC's own name. This stops a web
    page on another site from reaching us through DNS rebinding."""
    host = str(host_header or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else ""
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    name = socket.gethostname().lower()
    return host in ("localhost", name, name + ".local", name + ".lan")


def csrf_ok(headers):
    """POSTs need our custom header (a cross-site page cannot add it without a
    CORS preflight we never approve) and, when sent, a same-site Origin."""
    if headers.get("X-DevOS") != "1":
        return False
    origin = headers.get("Origin")
    if origin is None:
        return True
    return urlsplit(origin).netloc.lower() == str(headers.get("Host", "")).lower()


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------

class ClientError(Exception):
    def __init__(self, status, message):
        Exception.__init__(self, message)
        self.status = status


class PhoneLinkApp(object):
    """Everything the request handler needs; tests build one with temp paths."""

    def __init__(self, home=None, store=None, codes=None, limiter=None, app_dir=APP_DIR):
        self.home = home or home_dir()
        self.store = store or TokenStore()
        self.codes = codes or PairingCodes()
        self.limiter = limiter or RateLimiter()
        self.app_dir = app_dir


# (method, path) -> (handler name, needs a paired phone)
ROUTES = {
    ("GET", "/"): ("page", False),
    ("GET", "/pair"): ("page", False),
    ("GET", "/api/me"): ("me", False),
    ("POST", "/api/pair"): ("pair", False),
    ("POST", "/api/unpair"): ("unpair", True),
    ("GET", "/api/stats"): ("stats", True),
    ("GET", "/api/apps"): ("apps", True),
    ("POST", "/api/open-app"): ("open_app", True),
    ("POST", "/api/action"): ("action", True),
    ("POST", "/api/clipboard"): ("clipboard", True),
    ("POST", "/api/notify"): ("notify", True),
    ("POST", "/api/upload"): ("upload", True),
    ("GET", "/api/files"): ("files", True),
    ("GET", "/api/download"): ("download", True),
    ("POST", "/api/screenshot"): ("screenshot", True),
    ("GET", "/api/screenshot.png"): ("screenshot_png", True),
    ("POST", "/api/ai"): ("ai", True),
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'unsafe-inline'; "
                               "style-src 'unsafe-inline'; img-src 'self' blob: data:; "
                               "frame-ancestors 'none'",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "DevOSPhoneLink/1.0"
    sys_version = ""

    @property
    def app(self):
        return self.server.app

    def log_message(self, fmt, *args):
        # Never log query strings: the pairing link carries the code.
        sys.stderr.write("phonelink: %s %s %s\n" % (self.client_address[0], self.command,
                                                   urlsplit(self.path).path))

    def log_request(self, code="-", size="-"):
        if isinstance(code, int) and code >= 400:
            self.log_message("%s", code)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_OPTIONS(self):
        # Never approve CORS preflights.
        self._json(405, {"error": "Not allowed."})

    # -- plumbing ----------------------------------------------------------
    def _send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, data, extra=None):
        self._send(status, json.dumps(data).encode("utf-8"), "application/json; charset=utf-8", extra)

    def _body_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ClientError(400, "Bad request.")
        if length > MAX_JSON_BODY:
            raise ClientError(413, "That is too much text.")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ClientError(400, "Bad request.")
        if not isinstance(data, dict):
            raise ClientError(400, "Bad request.")
        return data

    def _token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(TOKEN_COOKIE)
        return morsel.value if morsel else None

    def _dispatch(self, method):
        parts = urlsplit(self.path)
        query = parse_qs(parts.query)
        try:
            if not host_allowed(self.headers.get("Host")):
                raise ClientError(400, "Open Phone Link using the address shown on the PC.")
            if method == "POST" and not csrf_ok(self.headers):
                raise ClientError(403, "Request blocked.")
            route = ROUTES.get((method, parts.path))
            if not route:
                raise ClientError(404, "Not found.")
            name, needs_auth = route
            device = None
            if needs_auth:
                device = self.app.store.verify(self._token())
                if not device:
                    raise ClientError(401, "This phone is not paired. Scan the QR code on the PC.")
            getattr(self, "h_" + name)(query, device)
        except ClientError as exc:
            self._safe_json(exc.status, {"error": str(exc)})
        except (ActionError, PathError) as exc:
            self._safe_json(400, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # keep the server alive whatever happens
            sys.stderr.write("phonelink: error: %r\n" % (exc,))
            self._safe_json(500, {"error": "Something went wrong on the PC."})

    def _safe_json(self, status, data):
        try:
            self._json(status, data)
        except OSError:
            pass

    # -- pages -------------------------------------------------------------
    def h_page(self, query, device):
        self._send(200, PAGE_HTML.encode("utf-8"), "text/html; charset=utf-8")

    def h_me(self, query, device):
        device = self.app.store.verify(self._token())
        self._json(200, {"paired": bool(device), "device": device, "pc": socket.gethostname()})

    def h_pair(self, query, device):
        ip = self.client_address[0]
        if self.app.limiter.blocked(ip):
            raise ClientError(429, "Too many wrong codes. Wait a minute and try again.")
        data = self._body_json()
        if not self.app.codes.consume(data.get("code")):
            self.app.limiter.fail(ip)
            raise ClientError(403, "That code is wrong or has expired. Check the code on the PC.")
        token, device = self.app.store.add_device(summarize_user_agent(self.headers.get("User-Agent")))
        notify_quietly("%s is now paired with this PC." % device["name"])
        cookie = "%s=%s; Path=/; Max-Age=%d; HttpOnly; SameSite=Strict" % (
            TOKEN_COOKIE, token, COOKIE_MAX_AGE)
        self._json(200, {"paired": True, "device": device, "pc": socket.gethostname()},
                   {"Set-Cookie": cookie})

    def h_unpair(self, query, device):
        self.app.store.remove(device["id"])
        self._json(200, {"ok": True},
                   {"Set-Cookie": "%s=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict" % TOKEN_COOKIE})

    # -- controls ----------------------------------------------------------
    def h_stats(self, query, device):
        self._json(200, system_stats(self.app.home))

    def h_apps(self, query, device):
        apps = [{"id": a["id"], "name": a["name"]} for a in list_apps(self.app.app_dir)]
        self._json(200, {"apps": apps})

    def h_open_app(self, query, device):
        ok = open_app(str(self._body_json().get("id", "")), self.app.app_dir)
        self._json(200 if ok else 503, {"ok": ok, "error": None if ok else "Could not open the app."})

    def h_action(self, query, device):
        data = self._body_json()
        ok = run_action(data.get("action"), data.get("confirm") is True)
        self._json(200 if ok else 503, {"ok": ok, "error": None if ok else "The PC could not do that."})

    def h_clipboard(self, query, device):
        ok = set_clipboard(self._body_json().get("text"))
        self._json(200 if ok else 503, {"ok": ok, "error": None if ok else "Clipboard is not available."})

    def h_notify(self, query, device):
        ok = notify_pc(self._body_json().get("text"), "From %s" % device["name"])
        self._json(200 if ok else 503, {"ok": ok, "error": None if ok else "Could not show the message."})

    def h_ai(self, query, device):
        self._json(200, {"answer": ask_ai(self._body_json().get("question"))})

    def h_screenshot(self, query, device):
        path = take_screenshot()
        if not path:
            raise ClientError(503, "Could not take a screenshot. Is someone signed in on the PC?")
        self._json(200, {"ok": True, "url": "/api/screenshot.png?t=%d" % int(time.time())})

    def h_screenshot_png(self, query, device):
        path = screenshot_path()
        if not os.path.isfile(path):
            raise ClientError(404, "No screenshot yet.")
        self._stream_file(path, "image/png", "DevOS-screenshot.png", inline=True)

    # -- files -------------------------------------------------------------
    def h_files(self, query, device):
        root = (query.get("root") or [""])[0]
        rel = (query.get("path") or [""])[0]
        if not root:
            roots = [r for r in ALLOWED_ROOTS if os.path.isdir(os.path.join(self.app.home, r))]
            self._json(200, {"roots": roots})
            return
        self._json(200, {"root": root, "path": rel, "entries": list_folder(self.app.home, root, rel)})

    def h_download(self, query, device):
        path = resolve_user_path(self.app.home, (query.get("root") or [""])[0],
                                 (query.get("path") or [""])[0])
        if not os.path.isfile(path):
            raise ClientError(404, "That file does not exist.")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        inline = (query.get("inline") or [""])[0] == "1" and ctype.startswith("image/")
        self._stream_file(path, ctype, os.path.basename(path), inline)

    def _stream_file(self, path, ctype, name, inline=False):
        size = os.path.getsize(path)
        disposition = "%s; filename*=UTF-8''%s" % ("inline" if inline else "attachment", quote(name))
        with open(path, "rb") as fh:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", disposition)
            self.send_header("Cache-Control", "no-store")
            for key, value in SECURITY_HEADERS.items():
                self.send_header(key, value)
            self.end_headers()
            shutil.copyfileobj(fh, self.wfile, MB)

    def h_upload(self, query, device):
        try:
            length = int(self.headers.get("Content-Length") or -1)
        except ValueError:
            length = -1
        if length < 0:
            raise ClientError(411, "Bad request.")
        if length > MAX_UPLOAD:
            self.close_connection = True
            raise ClientError(413, "Files up to 2 GB can be sent.")
        name = safe_filename(unquote(self.headers.get("X-Filename", "")))
        dest_dir = os.path.join(self.app.home, UPLOAD_SUBDIR)
        os.makedirs(dest_dir, exist_ok=True)
        if shutil.disk_usage(dest_dir).free < length + 200 * MB:
            self.close_connection = True
            raise ClientError(507, "The PC does not have enough free space for this file.")
        # Reserve the final name first so two uploads never pick the same one.
        while True:
            final = unique_path(dest_dir, name)
            try:
                os.close(os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
                break
            except FileExistsError:
                continue
        part = os.path.join(dest_dir, ".%s.part" % os.path.basename(final))
        remaining = length
        try:
            with open(part, "wb") as out:
                while remaining > 0:
                    chunk = self.rfile.read(min(MB, remaining))
                    if not chunk:
                        break
                    out.write(chunk)
                    remaining -= len(chunk)
            if remaining:
                raise ClientError(400, "The upload was interrupted.")
            os.replace(part, final)
        except BaseException:
            for leftover in (part, final):
                try:
                    os.unlink(leftover)
                except OSError:
                    pass
            raise
        saved = os.path.basename(final)
        notify_quietly("Received %s from %s (in Downloads/Phone)." % (saved, device["name"]))
        self._json(200, {"ok": True, "name": saved, "size": length})


def notify_quietly(text):
    try:
        notify_pc(text)
    except Exception:
        pass


def make_server(app=None, host="0.0.0.0", port=PORT):
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.app = app or PhoneLinkApp()
    return server


# ---------------------------------------------------------------------------
# Service management (opt-in: off until the user turns it on)
# ---------------------------------------------------------------------------

def user_unit_path():
    return os.path.join(os.path.dirname(config_dir()), "systemd", "user", SERVICE_NAME)


UNIT_TEXT = """[Unit]
Description=DevOS Phone Link (control this PC from your phone's browser)
After=graphical-session.target network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 %s serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def _systemctl(*args):
    try:
        proc = subprocess.run(["systemctl", "--user"] + list(args), capture_output=True,
                              text=True, timeout=20)
        return proc.returncode == 0, (proc.stderr or proc.stdout).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def service_enabled():
    ok, _ = _systemctl("is-enabled", "--quiet", SERVICE_NAME)
    return ok


def enable_service():
    if not os.path.exists(SYSTEM_UNIT) and not os.path.exists(user_unit_path()):
        # Running from a checkout: write a unit pointing at this file.
        os.makedirs(os.path.dirname(user_unit_path()), exist_ok=True)
        with open(user_unit_path(), "w", encoding="utf-8") as fh:
            fh.write(UNIT_TEXT % SCRIPT_PATH)
        _systemctl("daemon-reload")
    ok, err = _systemctl("enable", "--now", SERVICE_NAME)
    return {"ok": ok, "error": None if ok else (err or "Could not turn Phone Link on.")}


def disable_service():
    ok, err = _systemctl("disable", "--now", SERVICE_NAME)
    PairingCodes().clear()
    return {"ok": ok, "error": None if ok else (err or "Could not turn Phone Link off.")}


def status_dict():
    ip = lan_ip()
    return {"running": server_running(), "enabled": service_enabled(), "port": PORT,
            "lan_ip": ip, "url": "http://%s:%d/" % (ip, PORT) if ip else None,
            "paired_devices": TokenStore().devices(),
            "kdeconnect_installed": bool(shutil.which("kdeconnect-app"))}


def cmd_serve(port=PORT):
    try:
        server = make_server(port=port)
    except OSError as exc:
        print("Phone Link could not start on port %d: %s" % (port, exc), file=sys.stderr)
        return 1
    ip = lan_ip()
    print("Phone Link is listening on http://%s:%d/" % (ip or "0.0.0.0", port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_pair_code():
    code, expires = PairingCodes().issue()
    ip = lan_ip()
    print(json.dumps({"code": code, "expires": int(expires),
                      "url": pair_url(ip, code) if ip else None,
                      "running": server_running(),
                      "note": None if ip else "This PC is not on a network. Join Wi-Fi first."},
                     indent=2))
    return 0


# ---------------------------------------------------------------------------
# Phone page (single file, no external resources)
# ---------------------------------------------------------------------------

PAGE_HTML = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0f1a">
<title>DevOS Phone Link</title>
<style>
:root{--bg:#0b0f1a;--card:#121829;--line:#1f2a40;--text:#e5e7eb;--muted:#94a3b8;--accent:#38bdf8;--danger:#f87171}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
header{position:sticky;top:0;z-index:2;background:rgba(11,15,26,.92);backdrop-filter:blur(8px);padding:14px 16px 0;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:19px;font-weight:650}h1 span{color:var(--accent)}
#pc{color:var(--muted);font-size:13px;margin-bottom:10px}
nav{display:flex;gap:4px}nav button{flex:1;background:none;border:0;color:var(--muted);padding:10px 4px;font:inherit;font-weight:600;border-bottom:2px solid transparent}
nav button.on{color:var(--accent);border-color:var(--accent)}
main{padding:14px 16px 40px;max-width:640px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px;margin-bottom:14px}
.card h2{margin:0 0 10px;font-size:14px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
button.b{background:#1b2338;color:var(--text);border:1px solid var(--line);border-radius:12px;padding:14px 6px;font:inherit;font-weight:600;min-height:52px}
button.b:active{background:#24304d}button.p{background:var(--accent);color:#0b0f1a;border-color:var(--accent)}
button.d{color:var(--danger)}
.stat{display:flex;justify-content:space-between;font-size:14px;margin:6px 0 4px}.stat b{color:var(--accent)}
.bar{height:6px;background:#1b2338;border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent);width:0}
textarea,input[type=text],input[type=tel]{width:100%;background:#0b0f1a;color:var(--text);border:1px solid var(--line);border-radius:12px;padding:12px;font:inherit}
textarea{min-height:80px;resize:vertical}
.row{display:flex;gap:8px;margin-top:8px}.row>*{flex:1}
.muted{color:var(--muted);font-size:13px}
.list a,.list div.it{display:flex;justify-content:space-between;gap:10px;padding:12px 4px;border-bottom:1px solid var(--line);color:var(--text);text-decoration:none}
.list .sz{color:var(--muted);font-size:13px;white-space:nowrap}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px}.chips button{background:#1b2338;color:var(--text);border:1px solid var(--line);border-radius:20px;padding:8px 12px;font:inherit}
.chips button.on{border-color:var(--accent);color:var(--accent)}
img.shot{width:100%;border-radius:10px;margin-top:10px;display:block}
.msg{padding:10px 12px;border-radius:12px;margin:8px 0;white-space:pre-wrap}.me{background:#1b2338;margin-left:30px}.ai{background:#0f2a3a;margin-right:30px}
#toast{position:fixed;left:16px;right:16px;bottom:20px;background:#1e293b;border:1px solid var(--line);padding:12px 14px;border-radius:12px;display:none;z-index:5}
.code{font-size:34px;letter-spacing:.3em;text-align:center}
.hide{display:none}
</style></head><body>
<header><h1><span>DevOS</span> Phone Link</h1><div id="pc">Connecting...</div>
<nav id="tabs" class="hide"><button data-t="control" class="on">Control</button><button data-t="files">Files</button><button data-t="ai">Ask AI</button></nav></header>
<main>
<section id="pairing" class="hide">
 <div class="card"><h2>Pair this phone</h2>
 <p>Open <b>Phone Link</b> on your PC (app menu) and turn it on. Then scan the QR code, or type the 6-digit code shown there.</p>
 <input id="code" type="tel" inputmode="numeric" maxlength="6" class="code" placeholder="000000" autocomplete="one-time-code">
 <div class="row"><button class="b p" id="pairBtn">Pair</button></div>
 <p class="muted">Your phone and the PC must be on the same Wi-Fi. Nothing is installed on your phone.</p></div>
</section>
<section id="control" class="hide">
 <div class="card"><h2>This PC</h2><div id="stats" class="muted">Loading...</div></div>
 <div class="card"><h2>Quick controls</h2>
  <div class="grid"><button class="b" data-a="volume_down">Vol -</button><button class="b" data-a="mute">Mute</button><button class="b" data-a="volume_up">Vol +</button>
  <button class="b" data-a="previous">Prev</button><button class="b p" data-a="play_pause">Play/Pause</button><button class="b" data-a="next">Next</button></div>
  <div class="row"><button class="b" data-a="lock">Lock screen</button><button class="b" id="shotBtn">Screenshot</button></div>
  <img id="shot" class="shot hide" alt="Screenshot of the PC"><a id="shotDl" class="muted hide" download="DevOS-screenshot.png">Save screenshot</a></div>
 <div class="card"><h2>Send text to the PC</h2><textarea id="txt" placeholder="Type or paste here"></textarea>
  <div class="row"><button class="b" id="clipBtn">Copy to PC clipboard</button><button class="b" id="noteBtn">Show on PC screen</button></div></div>
 <div class="card"><h2>Open an app</h2><div id="apps" class="grid2"></div></div>
 <div class="card"><h2>Power</h2><div class="grid2"><button class="b" data-a="sleep" data-c="Put the PC to sleep?">Sleep</button><button class="b d" data-a="shutdown" data-c="Shut down the PC now? Unsaved work may be lost.">Shut down</button></div>
  <div class="row"><button class="b" id="unpairBtn">Forget this phone</button></div></div>
</section>
<section id="files" class="hide">
 <div class="card"><h2>Send a file to the PC</h2><input id="up" type="file" multiple>
  <div class="bar" style="margin-top:10px"><i id="upBar"></i></div><div id="upMsg" class="muted" style="margin-top:6px">Files go to Downloads/Phone on the PC (up to 2 GB each).</div></div>
 <div class="card"><h2>Files on the PC</h2><div id="roots" class="chips"></div><div id="crumb" class="muted"></div><div id="list" class="list"></div></div>
</section>
<section id="ai" class="hide">
 <div class="card"><h2>Ask DevOS AI</h2><div id="chat"></div><textarea id="q" placeholder="Ask anything"></textarea>
 <div class="row"><button class="b p" id="askBtn">Ask</button></div><p class="muted">Answered by the AI running on your PC. Nothing leaves your network.</p></div>
</section>
</main><div id="toast"></div>
<script>
"use strict";
const $=s=>document.querySelector(s);
function el(t,a,...kids){const e=document.createElement(t);for(const k in a||{}){if(k==="on")for(const ev in a.on)e.addEventListener(ev,a.on[ev]);else e.setAttribute(k,a[k]);}for(const c of kids)e.append(c);return e;}
let tt;function toast(m){const t=$("#toast");t.textContent=m;t.style.display="block";clearTimeout(tt);tt=setTimeout(()=>t.style.display="none",3200);}
async function api(path,body){
  const o={credentials:"same-origin",headers:{"X-DevOS":"1"}};
  if(body!==undefined){o.method="POST";o.headers["Content-Type"]="application/json";o.body=JSON.stringify(body);}
  const r=await fetch(path,o);let d={};try{d=await r.json();}catch(e){}
  if(r.status===401&&path!=="/api/pair"){showPairing();throw new Error(d.error||"Not paired");}
  if(!r.ok)throw new Error(d.error||("Error "+r.status));return d;}
function size(n){if(n==null)return "";const u=["B","KB","MB","GB","TB"];let i=0;while(n>=1024&&i<4){n/=1024;i++;}return (i?n.toFixed(1):n)+" "+u[i];}
function dur(s){if(s==null)return "-";const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return (d?d+"d ":"")+h+"h "+m+"m";}
let tab="control",timer=null;
function show(t){tab=t;for(const s of ["pairing","control","files","ai"])$("#"+s).classList.toggle("hide",s!==t);
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("on",b.dataset.t===t));
  if(t==="files"&&!$("#roots").childElementCount)loadRoots();}
function showPairing(){$("#tabs").classList.add("hide");show("pairing");clearInterval(timer);}
async function start(){
  const qs=new URLSearchParams(location.search),code=qs.get("code");
  if(code){$("#code").value=code.replace(/\D/g,"").slice(0,6);history.replaceState(null,"","/");}
  let me;try{me=await (await fetch("/api/me",{credentials:"same-origin"})).json();}catch(e){$("#pc").textContent="Cannot reach the PC.";return;}
  $("#pc").textContent=me.paired?("Connected to "+me.pc):("PC: "+me.pc);
  if(!me.paired){showPairing();if(code)$("#pairBtn").focus();return;}
  $("#tabs").classList.remove("hide");show("control");loadStats();loadApps();timer=setInterval(()=>{if(tab==="control"&&!document.hidden)loadStats();},3000);}
$("#pairBtn").onclick=async()=>{try{await api("/api/pair",{code:$("#code").value.trim()});toast("Paired!");start();}catch(e){toast(e.message);}};
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>show(b.dataset.t));
function statRow(label,val,pct){const r=el("div",{},el("div",{class:"stat"},el("span",{},label),el("b",{},val)));
  if(pct!=null){const i=el("i");i.style.width=Math.min(100,pct)+"%";r.append(el("div",{class:"bar"},i));}return r;}
async function loadStats(){try{const s=await api("/api/stats"),box=$("#stats");box.className="";box.replaceChildren();
  box.append(statRow("CPU",s.cpu==null?"-":s.cpu+"%",s.cpu));
  if(s.memory)box.append(statRow("Memory",size(s.memory.used)+" of "+size(s.memory.total),s.memory.percent));
  if(s.disk)box.append(statRow("Disk",size(s.disk.free)+" free",s.disk.percent));
  if(s.battery)box.append(statRow("Battery",s.battery.percent+"% "+s.battery.status,s.battery.percent));
  box.append(statRow("Up for",dur(s.uptime)));}catch(e){}}
async function loadApps(){try{const d=await api("/api/apps"),box=$("#apps");box.replaceChildren();
  for(const a of d.apps)box.append(el("button",{class:"b",on:{click:async()=>{try{await api("/api/open-app",{id:a.id});toast("Opening "+a.name);}catch(e){toast(e.message);}}}},a.name));
  if(!d.apps.length)box.append(el("div",{class:"muted"},"No apps found."));}catch(e){}}
document.querySelectorAll("[data-a]").forEach(b=>b.onclick=async()=>{
  const c=b.dataset.c;if(c&&!confirm(c))return;
  try{await api("/api/action",{action:b.dataset.a,confirm:!!c});toast("Done");}catch(e){toast(e.message);}});
$("#clipBtn").onclick=async()=>{try{await api("/api/clipboard",{text:$("#txt").value});toast("Copied to the PC clipboard");}catch(e){toast(e.message);}};
$("#noteBtn").onclick=async()=>{try{await api("/api/notify",{text:$("#txt").value});toast("Shown on the PC");}catch(e){toast(e.message);}};
$("#shotBtn").onclick=async()=>{toast("Taking screenshot...");try{const d=await api("/api/screenshot",{});$("#shot").src=d.url;$("#shotDl").href=d.url;$("#shot").classList.remove("hide");$("#shotDl").classList.remove("hide");}catch(e){toast(e.message);}};
$("#unpairBtn").onclick=async()=>{if(!confirm("Forget this phone? You will need a new code to pair again."))return;try{await api("/api/unpair",{});}catch(e){}showPairing();};
// Upload: raw body (no multipart) so the PC can stream 2 GB files to disk.
$("#up").onchange=async e=>{const files=[...e.target.files];for(const f of files){await new Promise(res=>{
  const x=new XMLHttpRequest();x.open("POST","/api/upload");x.setRequestHeader("X-DevOS","1");x.setRequestHeader("X-Filename",encodeURIComponent(f.name));
  x.upload.onprogress=p=>{if(p.lengthComputable){$("#upBar").style.width=(100*p.loaded/p.total)+"%";$("#upMsg").textContent="Sending "+f.name+" ("+Math.round(100*p.loaded/p.total)+"%)";}};
  x.onload=()=>{let d={};try{d=JSON.parse(x.responseText);}catch(_){}$("#upMsg").textContent=x.status===200?("Sent "+d.name+" to Downloads/Phone"):(d.error||"Upload failed");res();};
  x.onerror=()=>{$("#upMsg").textContent="Upload failed. Is the PC still on?";res();};x.send(f);});}e.target.value="";};
let cur={root:"",path:""};
async function loadRoots(){try{const d=await api("/api/files"),box=$("#roots");box.replaceChildren();
  for(const r of d.roots)box.append(el("button",{"data-r":r,on:{click:()=>browse(r,"")}},r));if(d.roots.length)browse(d.roots[0],"");}catch(e){toast(e.message);}}
async function browse(root,path){try{const d=await api("/api/files?root="+encodeURIComponent(root)+"&path="+encodeURIComponent(path));cur={root,path};
  document.querySelectorAll("#roots button").forEach(b=>b.classList.toggle("on",b.dataset.r===root));
  $("#crumb").textContent=root+(path?" / "+path.split("/").join(" / "):"");const box=$("#list");box.replaceChildren();
  if(path){const up=path.split("/").slice(0,-1).join("/");box.append(el("a",{href:"#",on:{click:ev=>{ev.preventDefault();browse(root,up);}}},el("span",{},"← Back"),el("span")));}
  for(const f of d.entries){const p=path?path+"/"+f.name:f.name;
    if(f.dir)box.append(el("a",{href:"#",on:{click:ev=>{ev.preventDefault();browse(root,p);}}},el("span",{},"📁 "+f.name),el("span",{class:"sz"},"")));
    else box.append(el("a",{href:"/api/download?root="+encodeURIComponent(root)+"&path="+encodeURIComponent(p),download:f.name},el("span",{},f.name),el("span",{class:"sz"},size(f.size))));}
  if(!d.entries.length)box.append(el("div",{class:"it muted"},"This folder is empty."));}catch(e){toast(e.message);}}
$("#askBtn").onclick=async()=>{const q=$("#q").value.trim();if(!q)return;const chat=$("#chat");chat.append(el("div",{class:"msg me"},q));$("#q").value="";
  const a=el("div",{class:"msg ai"},"Thinking...");chat.append(a);$("#askBtn").disabled=true;
  try{a.textContent=(await api("/api/ai",{question:q})).answer;}catch(e){a.textContent=e.message;}$("#askBtn").disabled=false;};
start();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# GUI (PyQt5 + python3-qrcode, imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QWidget#root { background: #0b0f1a; color: #e5e7eb;
  font-family: "Inter", "Noto Sans", sans-serif; font-size: 10.5pt; }
QFrame#card { background: #111827; border-radius: 12px; border: 1px solid #1f2937; }
QLabel { color: #e5e7eb; background: transparent; }
QLabel#title { font-size: 18pt; font-weight: 600; color: #f9fafb; }
QLabel#muted { color: #9ca3af; font-size: 9.5pt; }
QLabel#code { color: #38bdf8; font-size: 26pt; font-weight: 700; letter-spacing: 4px; }
QLabel#url { color: #cbd5e1; font-size: 10pt; }
QLabel#ok { color: #4ade80; font-weight: 600; }
QLabel#warn { color: #fbbf24; }
QCheckBox { color: #f3f4f6; font-weight: 600; spacing: 12px; background: transparent; }
QCheckBox::indicator { width: 40px; height: 22px; border-radius: 11px;
  border: 1px solid #374151; background: #1f2937; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QPushButton { background: #1f2937; color: #e5e7eb; border: none; border-radius: 10px;
  padding: 8px 16px; }
QPushButton:hover { background: #273449; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #38bdf8; color: #0b0f19; font-weight: 600; }
QPushButton#primary:hover { background: #7dd3fc; }
QListWidget { background: #0b0f19; color: #cbd5e1; border: 1px solid #1f2937;
  border-radius: 8px; }
"""

KDE_CONNECT_HELP = ("Want notifications, clipboard sync and file sharing from a native app? "
                    "Install Phone Connect from your phone's app store "
                    "— DevOS includes the matching app.")


def qr_matrix(text):
    """List of rows of booleans, or None when python3-qrcode is missing."""
    try:
        import qrcode
        from qrcode.constants import ERROR_CORRECT_M
    except ImportError:
        return None
    qr = qrcode.QRCode(border=0, error_correction=ERROR_CORRECT_M)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


def run_gui():
    from PyQt5 import QtCore, QtGui, QtWidgets

    class QrWidget(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.matrix = None
            self.setFixedSize(232, 232)

        def set_text(self, text):
            self.matrix = qr_matrix(text) if text else None
            self.update()

        def paintEvent(self, event):
            painter = QtGui.QPainter(self)
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#ffffff"))
            painter.drawRoundedRect(self.rect(), 14, 14)
            if not self.matrix:
                painter.setPen(QtGui.QColor("#475569"))
                painter.drawText(self.rect().adjusted(16, 16, -16, -16),
                                 QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                                 "QR code needs the python3-qrcode package.\nType the code on "
                                 "your phone instead.")
                return
            n = len(self.matrix)
            quiet = 14  # white margin so phone cameras find the code
            cell = (self.width() - 2 * quiet) / float(n)
            painter.setBrush(QtGui.QColor("#0b0f1a"))
            for y, row in enumerate(self.matrix):
                for x, dark in enumerate(row):
                    if dark:
                        painter.drawRect(QtCore.QRectF(quiet + x * cell, quiet + y * cell,
                                                       cell + 0.6, cell + 0.6))

    def card():
        frame = QtWidgets.QFrame()
        frame.setObjectName("card")
        frame.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        return frame

    def muted(text=""):
        label = QtWidgets.QLabel(text)
        label.setObjectName("muted")
        label.setWordWrap(True)
        return label

    class Window(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("root")
            self.setAttribute(QtCore.Qt.WA_StyledBackground, True)
            self.setWindowTitle("Phone Link")
            self.setWindowIcon(QtGui.QIcon.fromTheme("smartphone", QtGui.QIcon.fromTheme("phone")))
            self.setMinimumSize(560, 760)
            self.setStyleSheet(STYLE)
            self.store = TokenStore()
            self.codes = PairingCodes()
            self.code = None
            self.expires = 0
            self.known_ids = {d["id"] for d in self.store.devices()}
            self.running = False

            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(24, 22, 24, 22)
            outer.setSpacing(14)
            title = QtWidgets.QLabel("Phone Link")
            title.setObjectName("title")
            outer.addWidget(title)
            outer.addWidget(muted("Control this PC from your phone's web browser. "
                                  "Nothing to install on the phone."))

            self.switch = QtWidgets.QCheckBox("Phone Link is off")
            self.switch.toggled.connect(self.on_toggle)
            outer.addWidget(self.switch)

            # Pairing card
            pair = card()
            pl = QtWidgets.QHBoxLayout(pair)
            pl.setContentsMargins(16, 16, 16, 16)
            pl.setSpacing(18)
            self.qr = QrWidget()
            pl.addWidget(self.qr, 0, QtCore.Qt.AlignTop)
            side = QtWidgets.QVBoxLayout()
            side.setSpacing(8)
            self.pair_head = QtWidgets.QLabel("Scan with your phone's camera")
            self.pair_head.setWordWrap(True)
            self.code_label = QtWidgets.QLabel("------")
            self.code_label.setObjectName("code")
            self.code_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.url_label = QtWidgets.QLabel("")
            self.url_label.setObjectName("url")
            self.url_label.setWordWrap(True)
            self.url_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            self.expiry_label = muted()
            self.result_label = QtWidgets.QLabel("")
            self.result_label.setWordWrap(True)
            self.new_code_btn = QtWidgets.QPushButton("New code")
            self.new_code_btn.setObjectName("primary")
            self.new_code_btn.clicked.connect(self.new_code)
            for w in (self.pair_head, self.code_label, self.url_label, self.expiry_label,
                      self.result_label):
                side.addWidget(w)
            side.addStretch(1)
            side.addWidget(self.new_code_btn, 0, QtCore.Qt.AlignLeft)
            pl.addLayout(side, 1)
            outer.addWidget(pair)

            # Paired phones
            dev = card()
            dl = QtWidgets.QVBoxLayout(dev)
            dl.setContentsMargins(16, 14, 16, 14)
            dl.addWidget(QtWidgets.QLabel("Paired phones"))
            self.dev_list = QtWidgets.QListWidget()
            self.dev_list.setMinimumHeight(90)
            dl.addWidget(self.dev_list)
            row = QtWidgets.QHBoxLayout()
            row.addWidget(muted("A removed phone has to scan a new code to connect again."), 1)
            self.remove_btn = QtWidgets.QPushButton("Remove")
            self.remove_btn.clicked.connect(self.remove_device)
            row.addWidget(self.remove_btn)
            dl.addLayout(row)
            outer.addWidget(dev)

            # Help + KDE Connect
            helpc = card()
            hl = QtWidgets.QVBoxLayout(helpc)
            hl.setContentsMargins(16, 14, 16, 14)
            hl.addWidget(muted("1. Turn Phone Link on.  2. Connect your phone to the same Wi-Fi "
                               "as this PC.  3. Scan the QR code with the phone camera and tap "
                               "Pair. Codes work once and expire after 5 minutes."))
            hl.addWidget(muted(KDE_CONNECT_HELP))
            self.kde_btn = QtWidgets.QPushButton("Open Phone Connect")
            have_kde = bool(shutil.which("kdeconnect-app"))
            self.kde_btn.setEnabled(have_kde)
            if not have_kde:
                self.kde_btn.setToolTip("Phone Connect is not installed on this PC.")
            self.kde_btn.clicked.connect(lambda: QtCore.QProcess.startDetached("kdeconnect-app", []))
            hl.addWidget(self.kde_btn, 0, QtCore.Qt.AlignLeft)
            outer.addWidget(helpc)
            outer.addStretch(1)

            self.error_label = QtWidgets.QLabel("")
            self.error_label.setObjectName("warn")
            self.error_label.setWordWrap(True)
            outer.addWidget(self.error_label)

            self.tick_timer = QtCore.QTimer(self)
            self.tick_timer.timeout.connect(self.tick)
            self.tick_timer.start(1000)
            self.ticks = 0
            self.refresh(force=True)

        # -- state -----------------------------------------------------------
        def refresh(self, force=False):
            self.running = server_running()
            enabled = service_enabled()
            self.switch.blockSignals(True)
            self.switch.setChecked(self.running or enabled)
            self.switch.blockSignals(False)
            self.switch.setText("Phone Link is on" if self.running else
                                ("Phone Link is starting..." if enabled else "Phone Link is off"))
            self.refresh_devices()
            self.update_pairing(force)

        def update_pairing(self, force=False):
            ip = lan_ip()
            if not self.running:
                self.show_message("Turn Phone Link on to connect a phone.")
                return
            if not ip:
                self.show_message("This PC is not connected to a network. Join the same Wi-Fi "
                                  "as your phone (network icon in the taskbar), then press "
                                  "New code.")
                return
            if force or not self.code or time.time() >= self.expires:
                self.code, self.expires = self.codes.issue()
            url = pair_url(ip, self.code)
            self.qr.set_text(url)
            self.qr.setVisible(True)
            self.pair_head.setText("Scan with your phone's camera, or open the address below "
                                   "and type the code")
            self.code_label.setText(self.code)
            self.code_label.setVisible(True)
            self.url_label.setText("http://%s:%d" % (ip, PORT))
            self.new_code_btn.setEnabled(True)
            self.update_expiry()

        def show_message(self, text):
            self.code = None
            self.qr.setVisible(False)
            self.code_label.setVisible(False)
            self.pair_head.setText(text)
            self.url_label.setText("")
            self.expiry_label.setText("")
            self.new_code_btn.setEnabled(self.running)

        def update_expiry(self):
            left = int(self.expires - time.time())
            if self.code and left > 0:
                self.expiry_label.setText("Code expires in %d:%02d" % (left // 60, left % 60))

        def refresh_devices(self):
            devices = self.store.devices()
            selected = self.dev_list.currentItem().data(QtCore.Qt.UserRole) \
                if self.dev_list.currentItem() else None
            self.dev_list.clear()
            for d in devices:
                when = time.strftime("%d %b %Y", time.localtime(d["paired_at"] or 0))
                seen = time.strftime("%d %b %H:%M", time.localtime(d["last_seen"] or 0))
                item = QtWidgets.QListWidgetItem("%s  —  paired %s, last used %s" % (d["name"], when, seen))
                item.setData(QtCore.Qt.UserRole, d["id"])
                self.dev_list.addItem(item)
                if d["id"] == selected:
                    self.dev_list.setCurrentItem(item)
            if not devices:
                item = QtWidgets.QListWidgetItem("No phones paired yet.")
                item.setFlags(QtCore.Qt.NoItemFlags)
                self.dev_list.addItem(item)
            new = [d for d in devices if d["id"] not in self.known_ids]
            self.known_ids = {d["id"] for d in devices}
            return new

        def tick(self):
            self.ticks += 1
            self.update_expiry()
            # The server deletes the code file when a phone pairs with it.
            if self.code and self.running and not self.codes.is_current(self.code):
                new = self.refresh_devices()
                if new:
                    self.result_label.setStyleSheet("color: #4ade80; font-weight: 600;")
                    self.result_label.setText("Paired with %s." % new[-1]["name"])
                self.code = None
            if self.code and time.time() >= self.expires:
                self.code = None
            if self.ticks % 3 == 0 or (self.running and not self.code):
                was = self.running
                self.running = server_running()
                if was != self.running:
                    self.refresh()
                else:
                    self.refresh_devices()
                    if self.running and not self.code:
                        self.update_pairing()

        # -- actions ---------------------------------------------------------
        def on_toggle(self, checked):
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            try:
                result = enable_service() if checked else disable_service()
            finally:
                QtWidgets.QApplication.restoreOverrideCursor()
            self.error_label.setText("" if result["ok"] else result["error"])
            if checked and result["ok"]:
                # Give the server a moment to open its port.
                for _ in range(20):
                    if server_running():
                        break
                    QtWidgets.QApplication.processEvents()
                    time.sleep(0.1)
            self.code = None
            self.result_label.setText("")
            self.refresh(force=checked)

        def new_code(self):
            self.result_label.setText("")
            self.code = None
            self.refresh(force=True)

        def remove_device(self):
            item = self.dev_list.currentItem()
            device_id = item.data(QtCore.Qt.UserRole) if item else None
            if not device_id:
                return
            answer = QtWidgets.QMessageBox.question(
                self, "Remove phone", "Remove %s? It will no longer be able to control this PC."
                % item.text().split("  —  ")[0])
            if answer == QtWidgets.QMessageBox.Yes:
                self.store.remove(device_id)
                self.refresh_devices()

        def closeEvent(self, event):
            # Do not leave a valid code behind when nobody is looking at it.
            if self.code and self.codes.is_current(self.code):
                self.codes.clear()
            super().closeEvent(event)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Phone Link")
    app.setDesktopFileName("devos-phonelink")
    win = Window()
    win.show()
    return app.exec_()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="DevOS Phone Link")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the Phone Link window (default)")
    serve = sub.add_parser("serve", help="run the web server for phones")
    serve.add_argument("--port", type=int, default=PORT)
    sub.add_parser("enable", help="turn Phone Link on (also at every login)")
    sub.add_parser("disable", help="turn Phone Link off")
    sub.add_parser("pair-code", help="print a fresh one-time pairing code and URL")
    sub.add_parser("status", help="print the current state as JSON")
    args = parser.parse_args(argv)

    if args.cmd == "serve":
        return cmd_serve(args.port)
    if args.cmd == "enable":
        result = enable_service()
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    if args.cmd == "disable":
        result = disable_service()
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    if args.cmd == "pair-code":
        return cmd_pair_code()
    if args.cmd == "status":
        print(json.dumps(status_dict(), indent=2))
        return 0
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
