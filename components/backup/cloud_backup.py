#!/usr/bin/env python3
"""
DevOS Cloud Backup - optional copy of your personal folders to Google Drive
or OneDrive, so you can get your files from anywhere or put them back on a
new PC.

It is OFF by default. Nothing is uploaded, scheduled or even configured until
the user connects an account and turns backup on.

Cloud layout (DevOS creates these folders itself on first connect, so the
user sees them in Drive/OneDrive straight away):

    <remote>:DevOS/<device name>/Documents
                                 /Desktop
                                 /Pictures
                                 /Downloads

All transfers go through the `rclone` command (Ubuntu noble ships 1.60.x, so
only flags that exist in 1.60 are used). DevOS never asks for or stores the
user's password: sign-in happens in the browser and rclone keeps the OAuth
token in its own config (~/.config/rclone/rclone.conf, mode 600).

CLI:
  cloud_backup.py [gui]                     open the Cloud Backup window (default)
  cloud_backup.py connect gdrive|onedrive   sign in and create the DevOS folders
  cloud_backup.py disconnect                forget the account, stop automatic backup
  cloud_backup.py run [--now] [--progress]  back up the chosen folders once
  cloud_backup.py restore [--device X] [--folders a,b] [--progress]
  cloud_backup.py status                    print settings and state as JSON
  cloud_backup.py enable | disable          turn automatic backup on / off

Everything above the "GUI" section is plain stdlib and importable without a
display (or even on Windows) so it can be unit-tested. PyQt5 is imported
lazily in the GUI path.
"""

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

APP_NAME = "Cloud Backup"
SETTINGS_VERSION = 1

PROVIDERS = {
    "gdrive": {
        "label": "Google Drive",
        "remote": "devos-gdrive",
        "type": "drive",
        # drive.file: rclone (and so DevOS) can only see files it created
        # itself. The user's other Drive files stay invisible to us.
        "create_args": ["scope=drive.file"],
        "web": "https://drive.google.com",
        "probe_host": "www.googleapis.com",
    },
    "onedrive": {
        "label": "OneDrive",
        "remote": "devos-onedrive",
        "type": "onedrive",
        # OneDrive asks which kind of drive to use after sign-in. Answering
        # "onedrive" (personal or business account's own drive) up front
        # means rclone picks the user's main drive instead of stopping.
        "create_args": ["config_type=onedrive"],
        "web": "https://onedrive.live.com",
        "probe_host": "graph.microsoft.com",
    },
}
DEFAULT_PROVIDER = "gdrive"

# Folder key -> (xdg-user-dir name, fallback folder in $HOME, name in the cloud)
FOLDERS = (
    ("documents", "DOCUMENTS", "Documents", "Documents"),
    ("desktop", "DESKTOP", "Desktop", "Desktop"),
    ("pictures", "PICTURES", "Pictures", "Pictures"),
    ("downloads", "DOWNLOAD", "Downloads", "Downloads"),
)
FOLDER_KEYS = tuple(f[0] for f in FOLDERS)

# Never upload half-finished downloads, editor lock files or rebuildable
# developer junk: they waste the user's cloud space and change constantly.
BUILTIN_EXCLUDES = (
    "*.partial",
    "*.crdownload",
    "*.part",
    "*.tmp",
    ".~lock*",
    "node_modules/**",
    ".cache/**",
    ".git/**",
)
PARTIAL_SUFFIXES = (".partial", ".crdownload", ".part")

MAX_FILE_SIZE = "10G"
TRANSFERS = 4
STATS_INTERVAL = "2s"
QUIET_SECONDS = 60          # files must stop changing this long before upload
MAX_QUIET_WAIT = 15 * 60    # ...but never postpone a backup longer than this
NET_TIMEOUT_S = 3

UNITS = ("devos-backup.timer", "devos-backup.path")

INTRO_TEXT = "Optional. Your files stay on this PC; backup only starts if you turn it on."
GDRIVE_SCOPE_TEXT = ("DevOS can only see the files it puts in your Google Drive. "
                     "Your other Drive files stay private, even from DevOS.")
ONEDRIVE_MANUAL_STEPS = """\
DevOS could not finish the OneDrive sign-in on its own. A terminal will open
with rclone's setup. Please answer like this:

  n   (new remote)
  name> devos-onedrive
  Storage> onedrive
  client_id / client_secret / region: just press Enter
  Edit advanced config? n
  Use auto config? y        (your browser opens - sign in there)
  Your choice> 1            (OneDrive Personal or Business)
  pick your drive, then  y  to confirm, then  q  to quit

The window closes after q and DevOS then checks the connection.
"""
GDRIVE_MANUAL_STEPS = """\
DevOS could not finish the Google Drive sign-in on its own. A terminal will
open with rclone's setup. Please answer like this:

  n   (new remote)
  name> devos-gdrive
  Storage> drive
  client_id / client_secret: just press Enter
  scope> drive.file         (DevOS only sees files it creates)
  everything else: just press Enter
  Use auto config? y        (your browser opens - sign in there)
  Configure as a Shared Drive? n,  then  y  to confirm, then  q  to quit

The window closes after q and DevOS then checks the connection.
"""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def home_dir():
    return os.path.expanduser("~")


def human_size(num):
    num = float(max(0, num or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            if unit in ("B", "KB"):
                return "%d %s" % (int(num), unit)
            return "%.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f TB" % num


def runtime_dir():
    return os.environ.get("XDG_RUNTIME_DIR") or "/tmp"


def default_device_name():
    try:
        return clean_device_name(socket.gethostname()) or "My PC"
    except OSError:
        return "My PC"


def clean_device_name(name):
    """Device names become a folder in the cloud, so drop path separators and
    characters Drive/OneDrive reject, and never allow '.' or '..'."""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", str(name or "")).strip(" .")
    return name[:64]


# ---------------------------------------------------------------------------
# Settings (~/.config/devos/backup.json)
# ---------------------------------------------------------------------------

def settings_path(home=None):
    base = os.environ.get("XDG_CONFIG_HOME") if home is None else None
    if not base:
        base = os.path.join(home or home_dir(), ".config")
    return os.path.join(base, "devos", "backup.json")


def default_settings():
    return {
        "version": SETTINGS_VERSION,
        "enabled": False,               # opt-in: nothing happens until the user says so
        "provider": DEFAULT_PROVIDER,
        "remote": PROVIDERS[DEFAULT_PROVIDER]["remote"],
        "folders": {k: True for k in FOLDER_KEYS},
        "device": default_device_name(),
        "last_run": 0,
        "last_result": "",
        "ever_succeeded": False,
    }


def normalize_settings(data):
    cfg = default_settings()
    if isinstance(data, dict):
        for key in cfg:
            if key in data:
                cfg[key] = data[key]
    cfg["enabled"] = cfg["enabled"] is True
    if cfg["provider"] not in PROVIDERS:
        cfg["provider"] = DEFAULT_PROVIDER
    # The remote name always follows the provider so a hand-edited file can
    # never point DevOS at some other rclone remote the user set up.
    cfg["remote"] = PROVIDERS[cfg["provider"]]["remote"]
    folders = cfg["folders"] if isinstance(cfg["folders"], dict) else {}
    cfg["folders"] = {k: bool(folders.get(k, True)) for k in FOLDER_KEYS}
    cfg["device"] = clean_device_name(cfg["device"]) or default_device_name()
    try:
        cfg["last_run"] = float(cfg["last_run"])
    except (TypeError, ValueError):
        cfg["last_run"] = 0
    cfg["last_result"] = str(cfg["last_result"] or "")
    cfg["ever_succeeded"] = bool(cfg["ever_succeeded"])
    cfg["version"] = SETTINGS_VERSION
    return cfg


def load_settings(path=None):
    path = path or settings_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return normalize_settings(json.load(fh))
    except (OSError, ValueError):
        return normalize_settings(None)


def save_settings(cfg, path=None):
    path = path or settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(normalize_settings(cfg), fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def set_provider(cfg, provider):
    if provider not in PROVIDERS:
        raise ValueError("Unknown provider: %s" % provider)
    cfg["provider"] = provider
    cfg["remote"] = PROVIDERS[provider]["remote"]
    return cfg


# ---------------------------------------------------------------------------
# Folder resolution
# ---------------------------------------------------------------------------

def _xdg_user_dir(name):
    try:
        out = subprocess.run(["xdg-user-dir", name], capture_output=True, text=True,
                             timeout=3)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_folder(key, home=None, lookup=None):
    """Real location of a folder key. xdg-user-dir knows about renamed or
    translated folders; when it is missing or just answers $HOME (its way of
    saying "not set") we fall back to the usual ~/Documents style name."""
    home = home or home_dir()
    lookup = lookup or _xdg_user_dir
    for fkey, xdg, fallback, _cloud in FOLDERS:
        if fkey != key:
            continue
        found = (lookup(xdg) or "").strip()
        if found and os.path.normpath(found) != os.path.normpath(home):
            return found
        return os.path.join(home, fallback)
    raise KeyError(key)


def resolve_folders(home=None, lookup=None):
    return {k: resolve_folder(k, home, lookup) for k in FOLDER_KEYS}


def cloud_name(key):
    for fkey, _xdg, _fallback, cloud in FOLDERS:
        if fkey == key:
            return cloud
    raise KeyError(key)


def key_for_name(name):
    """Accept 'documents', 'Documents' or 'download' style names from the CLI."""
    n = str(name).strip().lower()
    for fkey, xdg, _fallback, cloud in FOLDERS:
        if n in (fkey, xdg.lower(), cloud.lower()):
            return fkey
    raise KeyError(name)


def enabled_folder_keys(cfg):
    return [k for k in FOLDER_KEYS if cfg["folders"].get(k)]


# ---------------------------------------------------------------------------
# Cloud paths + rclone command lines (pure: easy to test)
# ---------------------------------------------------------------------------

def cloud_root(remote):
    return "%s:DevOS" % remote


def device_path(remote, device):
    return "%s/%s" % (cloud_root(remote), device)


def cloud_path(remote, device, key):
    return "%s/%s" % (device_path(remote, device), cloud_name(key))


def exclude_rules():
    return list(BUILTIN_EXCLUDES)


def write_exclude_file(path):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(exclude_rules()) + "\n")
    return path


def _progress_flags():
    return ["--log-level", "INFO", "--stats-one-line", "--stats", STATS_INTERVAL]


def backup_command(local, remote, device, key, exclude_file):
    # `copy`, never `sync`: deleting a file on the PC must never delete the
    # cloud copy. --update skips files that are already newer in the cloud.
    return (["rclone", "copy", local, cloud_path(remote, device, key),
             "--update", "--create-empty-src-dirs",
             "--exclude-from", exclude_file,
             "--max-size", MAX_FILE_SIZE,
             "--transfers", str(TRANSFERS)] + _progress_flags())


def restore_command(remote, device, key, local):
    # --update: a file that is newer on this PC is never overwritten.
    return (["rclone", "copy", cloud_path(remote, device, key), local,
             "--update", "--transfers", str(TRANSFERS)] + _progress_flags())


def connect_command(provider):
    p = PROVIDERS[provider]
    return ["rclone", "config", "create", p["remote"], p["type"]] + list(p["create_args"])


def mkdir_commands(remote, device):
    return [["rclone", "mkdir", cloud_path(remote, device, k)] for k in FOLDER_KEYS]


def list_devices_command(remote):
    return ["rclone", "lsf", cloud_root(remote), "--dirs-only"]


def about_command(remote):
    return ["rclone", "about", "%s:" % remote, "--json"]


def parse_lsf_dirs(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip().rstrip("/")
        if line:
            out.append(line)
    return sorted(set(out), key=str.lower)


# rclone --stats-one-line, e.g.
#   2026/10/14 12:00:00 INFO  :    1.234 MiB / 10.000 MiB, 12%, 1.000 MiB/s, ETA 9s
#   ...INFO  :          0 B / 0 B, -, 0 B/s, ETA -
_SIZE = r"\d+(?:\.\d+)?\s*[KMGTPE]?i?B(?:ytes)?"
STATS_RE = re.compile(
    r"(?P<done>%s)\s*/\s*(?P<total>%s),\s*(?P<pct>\d+%%|-),\s*"
    r"(?P<speed>%s/s),\s*ETA\s*(?P<eta>\S+)" % (_SIZE, _SIZE, _SIZE))


def parse_stats_line(line):
    """Turn one rclone one-line stats message into a dict, or None."""
    m = STATS_RE.search(line or "")
    if not m:
        return None
    pct = m.group("pct")
    return {
        "done": re.sub(r"\s+", " ", m.group("done")),
        "total": re.sub(r"\s+", " ", m.group("total")),
        "percent": int(pct[:-1]) if pct.endswith("%") else None,
        "speed": re.sub(r"\s+", " ", m.group("speed")),
        "eta": m.group("eta").rstrip(","),
    }


def overall_percent(index, count, folder_percent):
    """index is 0-based; each folder gets an equal slice of the bar."""
    if count <= 0:
        return 100
    p = max(0, min(100, folder_percent or 0))
    return int(round((index + p / 100.0) * 100.0 / count))


def parse_about(text):
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: data.get(k) for k in ("total", "used", "free", "trashed") if k in data}


def parse_config_dump(text):
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def remote_looks_ready(dump, remote, provider):
    """A remote is usable once it has a token; OneDrive also needs a drive."""
    conf = dump.get(remote)
    if not isinstance(conf, dict) or not conf.get("token"):
        return False
    if provider == "onedrive" and not conf.get("drive_id"):
        return False
    return True


# ---------------------------------------------------------------------------
# Debounce: wait until files stop changing
# ---------------------------------------------------------------------------

def seconds_until_quiet(mtimes, now, quiet_s=QUIET_SECONDS, busy=False):
    """How much longer to wait before the folders count as quiet. A folder
    that holds a half-finished download is never quiet."""
    if busy:
        return quiet_s
    newest = max(mtimes) if mtimes else 0
    return max(0.0, quiet_s - (now - newest))


def snapshot_folders(paths):
    """mtimes of each folder and its direct entries (the same level the
    systemd .path unit watches), plus whether a partial download exists."""
    mtimes, busy = [], False
    for path in paths:
        try:
            mtimes.append(os.stat(path).st_mtime)
            with os.scandir(path) as it:
                for entry in it:
                    if entry.name.endswith(PARTIAL_SUFFIXES):
                        busy = True
                    try:
                        mtimes.append(entry.stat(follow_symlinks=False).st_mtime)
                    except OSError:
                        pass
        except OSError:
            continue
    return mtimes, busy


def wait_for_quiet(paths, quiet_s=QUIET_SECONDS, max_wait_s=MAX_QUIET_WAIT,
                   clock=time.time, sleep=time.sleep):
    start = clock()
    while True:
        mtimes, busy = snapshot_folders(paths)
        left = seconds_until_quiet(mtimes, clock(), quiet_s, busy)
        if left <= 0:
            return True
        if clock() - start >= max_wait_s:
            # Excludes still keep *.part & co. out, so carry on.
            return False
        sleep(min(left, 15))


# ---------------------------------------------------------------------------
# Lock: two backup runs must never overlap
# ---------------------------------------------------------------------------

def lock_path():
    return os.path.join(runtime_dir(), "devos-backup.lock")


class RunLock(object):
    """flock on Linux (released automatically if the process dies); an
    exclusive-create file elsewhere so the logic stays testable."""

    def __init__(self, path=None):
        self.path = path or lock_path()
        self.fh = None
        self.fd = None

    def acquire(self):
        try:
            import fcntl
        except ImportError:
            fcntl = None
        if fcntl is not None:
            fh = open(self.path, "a+")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                return False
            self.fh = fh
            return True
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            return True
        except OSError:
            return False

    def release(self):
        if self.fh is not None:
            self.fh.close()
            self.fh = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


# ---------------------------------------------------------------------------
# System side effects (rclone, systemctl, notify-send)
# ---------------------------------------------------------------------------

def have_rclone():
    return shutil.which("rclone") is not None


def _run(cmd, timeout=60):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.returncode, out.stdout, out.stderr
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def online(host, port=443, timeout=NET_TIMEOUT_S):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def list_remotes():
    rc, out, _ = _run(["rclone", "listremotes"], timeout=10)
    if rc != 0:
        return []
    return [l.strip().rstrip(":") for l in out.splitlines() if l.strip()]


def is_connected(cfg):
    return have_rclone() and cfg["remote"] in list_remotes()


def rclone_config_file():
    rc, out, _ = _run(["rclone", "config", "file"], timeout=10)
    if rc == 0:
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if lines and lines[-1].startswith("/"):
            return lines[-1]
    return os.path.join(home_dir(), ".config", "rclone", "rclone.conf")


def protect_rclone_config():
    # The OAuth token lives in this file: only the user may read it.
    path = rclone_config_file()
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def notify(title, body, error=False):
    if not shutil.which("notify-send"):
        return
    cmd = ["notify-send", "-a", APP_NAME, "-i",
           "dialog-error" if error else "folder-cloud", title, body]
    _run(cmd, timeout=5)


def systemctl_user(*args):
    return _run(["systemctl", "--user"] + list(args), timeout=30)


def timers_enabled():
    rc, out, _ = systemctl_user("is-enabled", UNITS[0])
    return rc == 0 and out.strip() == "enabled"


def emit(progress, **event):
    """Machine-readable progress for the GUI (one JSON object per line)."""
    if progress:
        sys.stdout.write(json.dumps(event) + "\n")
        sys.stdout.flush()


def say(progress, text):
    if not progress:
        print(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_connect(provider, settings_file=None):
    if provider not in PROVIDERS:
        print("Choose gdrive or onedrive.")
        return 2
    if not have_rclone():
        print("rclone is not installed. Install it with: sudo apt install rclone")
        return 1
    p = PROVIDERS[provider]
    cfg = set_provider(load_settings(settings_file), provider)
    save_settings(cfg, settings_file)
    remote = p["remote"]

    print("Opening your browser to sign in to %s..." % p["label"])
    print("DevOS never sees your password; sign-in happens on the %s website." % p["label"])
    if provider == "gdrive":
        print(GDRIVE_SCOPE_TEXT)
    # Start clean so an expired or half-finished earlier attempt can't linger.
    if remote in list_remotes():
        _run(["rclone", "config", "delete", remote], timeout=30)
    # Not --non-interactive: rclone then takes the default answer for every
    # question and opens the browser for the OAuth sign-in.
    rc, _out, err = _run(connect_command(provider), timeout=15 * 60)
    ready = rc == 0 and remote_looks_ready(
        parse_config_dump(_run(["rclone", "config", "dump"], timeout=30)[1]), remote, provider)

    if not ready and shutil.which("konsole"):
        # Fall back to rclone's own guided setup in a terminal.
        if remote in list_remotes():
            _run(["rclone", "config", "delete", remote], timeout=30)
        steps = ONEDRIVE_MANUAL_STEPS if provider == "onedrive" else GDRIVE_MANUAL_STEPS
        print(steps)
        notify("Finish signing in", "Follow the steps in the terminal window that just opened.")
        # Show the steps inside the terminal too: when this runs from the
        # window, our own output is not visible. --separate keeps konsole in
        # the foreground so we know when the user has finished.
        steps_file = os.path.join(runtime_dir(), "devos-backup-steps.txt")
        with open(steps_file, "w", encoding="utf-8") as fh:
            fh.write(steps)
        _run(["konsole", "--separate", "-e", "sh", "-c", 'cat "$1"; echo; rclone config',
              "sh", steps_file], timeout=60 * 60)
        ready = remote_looks_ready(
            parse_config_dump(_run(["rclone", "config", "dump"], timeout=30)[1]), remote, provider)

    if not ready:
        print("Could not connect to %s. %s" % (p["label"], (err or "").strip()[-300:]))
        return 1

    protect_rclone_config()
    # Create the folder layout now so it shows up in the user's cloud right away.
    for cmd in mkdir_commands(remote, cfg["device"]):
        _run(cmd, timeout=120)
    print("Connected to %s. Your files will go to DevOS/%s/ there." % (p["label"], cfg["device"]))
    return 0


def cmd_enable(settings_file=None):
    cfg = load_settings(settings_file)
    if not is_connected(cfg):
        print("Connect Google Drive or OneDrive first.")
        return 1
    rc, _o, err = systemctl_user("enable", "--now", *UNITS)
    if rc != 0:
        print("Could not turn on automatic backup: %s" % err.strip())
        return 1
    cfg["enabled"] = True
    save_settings(cfg, settings_file)
    print("Automatic backup is on.")
    return 0


def cmd_disable(settings_file=None, quiet=False):
    systemctl_user("disable", "--now", *UNITS)
    cfg = load_settings(settings_file)
    cfg["enabled"] = False
    save_settings(cfg, settings_file)
    if not quiet:
        print("Automatic backup is off. Nothing will be uploaded.")
    return 0


def cmd_disconnect(settings_file=None):
    cmd_disable(settings_file, quiet=True)
    cfg = load_settings(settings_file)
    for p in PROVIDERS.values():
        if p["remote"] in list_remotes():
            _run(["rclone", "config", "delete", p["remote"]], timeout=30)
    cfg["last_result"] = ""
    save_settings(cfg, settings_file)
    print("Disconnected. Files already in the cloud were left untouched.")
    return 0


def _stream_rclone(cmd, progress, index, count, label):
    """Run rclone, forwarding its one-line stats as progress events."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                text=True, errors="replace")
    except OSError as exc:
        return 1, str(exc)
    last_error = ""
    for line in proc.stderr:
        stats = parse_stats_line(line)
        if stats:
            emit(progress, event="stats", folder=label, index=index, count=count,
                 overall=overall_percent(index, count, stats["percent"]), **stats)
        elif "ERROR" in line or "Failed" in line:
            last_error = line.strip()
    return proc.wait(), last_error


def _finish(cfg, settings_file, result, progress, ok):
    first = ok and not cfg["ever_succeeded"]
    cfg["last_run"] = time.time()
    cfg["last_result"] = result
    if ok:
        cfg["ever_succeeded"] = True
    save_settings(cfg, settings_file)
    emit(progress, event="done", ok=ok, result=result)
    say(progress, result)
    return first


def cmd_run(now=False, progress=False, settings_file=None, lock_file=None):
    cfg = load_settings(settings_file)
    if not cfg["enabled"] and not now:
        say(progress, "Backup is off. Nothing to do.")
        emit(progress, event="done", ok=True, result="Backup is off")
        return 0
    if not have_rclone():
        _finish(cfg, settings_file, "rclone is not installed", progress, False)
        return 1

    lock = RunLock(lock_file)
    if not lock.acquire():
        say(progress, "A backup is already running.")
        emit(progress, event="done", ok=True, result="A backup is already running")
        return 0
    with lock:
        if cfg["remote"] not in list_remotes():
            _finish(cfg, settings_file, "Not connected", progress, False)
            return 1
        # Offline is normal on a laptop: skip silently, the timer retries.
        if not online(PROVIDERS[cfg["provider"]]["probe_host"]):
            _finish(cfg, settings_file, "Offline - will try again later", progress, False)
            return 0

        folders = resolve_folders()
        keys = [k for k in enabled_folder_keys(cfg) if os.path.isdir(folders[k])]
        if not now:
            # Triggered by a new file (the .path unit) or the timer: give
            # downloads and saves a minute to finish first.
            wait_for_quiet([folders[k] for k in keys])

        exclude_file = write_exclude_file(os.path.join(runtime_dir(), "devos-backup.excludes"))
        errors = []
        for i, key in enumerate(keys):
            emit(progress, event="folder", folder=cloud_name(key), index=i, count=len(keys),
                 overall=overall_percent(i, len(keys), 0))
            say(progress, "Backing up %s..." % cloud_name(key))
            cmd = backup_command(folders[key], cfg["remote"], cfg["device"], key, exclude_file)
            rc, err = _stream_rclone(cmd, progress, i, len(keys), cloud_name(key))
            if rc != 0:
                errors.append("%s: %s" % (cloud_name(key), err or "rclone exit %d" % rc))

        if errors:
            result = "Some files were not backed up. " + "; ".join(errors)[:400]
            _finish(cfg, settings_file, result, progress, False)
            notify("Cloud Backup had a problem", result, error=True)
            return 1
        result = "Backed up %d folder%s" % (len(keys), "" if len(keys) == 1 else "s")
        if _finish(cfg, settings_file, result, progress, True):
            notify("Your files are backed up",
                   "Find them in %s under DevOS/%s." % (
                       PROVIDERS[cfg["provider"]]["label"], cfg["device"]))
        return 0


def list_devices(remote):
    rc, out, err = _run(list_devices_command(remote), timeout=120)
    if rc != 0:
        raise RuntimeError(err.strip() or "Could not list devices")
    return parse_lsf_dirs(out)


def cmd_restore(device=None, folders=None, progress=False, settings_file=None):
    cfg = load_settings(settings_file)
    if not is_connected(cfg):
        say(progress, "Connect Google Drive or OneDrive first.")
        emit(progress, event="done", ok=False, result="Not connected")
        return 1
    device = clean_device_name(device) if device else cfg["device"]
    try:
        keys = [key_for_name(f) for f in folders] if folders else list(FOLDER_KEYS)
    except KeyError as exc:
        say(progress, "Unknown folder: %s" % exc)
        return 2
    local = resolve_folders()
    errors = []
    for i, key in enumerate(keys):
        os.makedirs(local[key], exist_ok=True)
        emit(progress, event="folder", folder=cloud_name(key), index=i, count=len(keys),
             overall=overall_percent(i, len(keys), 0))
        say(progress, "Restoring %s from %s..." % (cloud_name(key), device))
        rc, err = _stream_rclone(restore_command(cfg["remote"], device, key, local[key]),
                                 progress, i, len(keys), cloud_name(key))
        # A folder that was never backed up from that device is not an error.
        if rc != 0 and "directory not found" not in (err or "").lower():
            errors.append("%s: %s" % (cloud_name(key), err or "rclone exit %d" % rc))
    ok = not errors
    result = "Restore finished" if ok else "Some files were not restored. " + "; ".join(errors)[:400]
    emit(progress, event="done", ok=ok, result=result)
    say(progress, result)
    return 0 if ok else 1


def get_space(remote):
    rc, out, _ = _run(about_command(remote), timeout=60)
    return parse_about(out) if rc == 0 else None


def status_dict(settings_file=None):
    cfg = load_settings(settings_file)
    connected = is_connected(cfg)
    folders = resolve_folders()
    return {
        "enabled": cfg["enabled"],
        "provider": cfg["provider"],
        "remote": cfg["remote"],
        "connected": connected,
        "device": cfg["device"],
        "cloud_folder": device_path(cfg["remote"], cfg["device"]),
        "folders": {k: {"enabled": cfg["folders"][k], "path": folders[k],
                        "cloud": cloud_path(cfg["remote"], cfg["device"], k)}
                    for k in FOLDER_KEYS},
        "timers_enabled": timers_enabled(),
        "last_run": cfg["last_run"],
        "last_result": cfg["last_result"],
        "rclone_installed": have_rclone(),
    }


def cmd_status():
    print(json.dumps(status_dict(), indent=2))
    return 0


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

STYLE = """
QWidget#root, QDialog { background: #0b0f1a; color: #e5e7eb;
  font-family: "Inter", "Noto Sans", sans-serif; font-size: 10.5pt; }
QFrame#card { background: #111827; border-radius: 12px; border: 1px solid #1f2937; }
QLabel { color: #e5e7eb; background: transparent; }
QLabel#title { font-size: 18pt; font-weight: 600; color: #f9fafb; }
QLabel#intro { color: #38bdf8; font-weight: 600; }
QLabel#muted { color: #9ca3af; font-size: 9.5pt; }
QLabel#section { color: #f3f4f6; font-weight: 600; font-size: 11pt; }
QCheckBox, QRadioButton { color: #f3f4f6; spacing: 10px; background: transparent; }
QCheckBox::indicator, QRadioButton::indicator { width: 18px; height: 18px;
  border: 1px solid #374151; background: #0b0f1a; }
QCheckBox::indicator { border-radius: 5px; }
QRadioButton::indicator { border-radius: 9px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
  background: #38bdf8; border-color: #38bdf8; }
QCheckBox::indicator:disabled { background: #1f2937; }
QCheckBox#toggle { font-size: 12pt; font-weight: 600; }
QCheckBox#toggle::indicator { width: 40px; height: 22px; border-radius: 11px; }
QLineEdit, QComboBox { background: #0b0f1a; color: #e5e7eb; border: 1px solid #374151;
  border-radius: 8px; padding: 6px 8px; }
QComboBox QAbstractItemView { background: #111827; color: #e5e7eb;
  selection-background-color: #1f2937; }
QPushButton { background: #1f2937; color: #e5e7eb; border: none; border-radius: 10px;
  padding: 8px 16px; }
QPushButton:hover { background: #273449; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #38bdf8; color: #0b0f1a; font-weight: 600; }
QPushButton#primary:hover { background: #7dd3fc; }
QPushButton#primary:disabled { background: #1f2937; color: #6b7280; }
QProgressBar { background: #1f2937; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #38bdf8; border-radius: 4px; }
QScrollBar:vertical { background: #0b0f1a; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #1f2937; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
"""


def format_when(ts):
    if not ts:
        return "Never"
    return time.strftime("%d %b %Y, %H:%M", time.localtime(ts))


def run_gui():
    from PyQt5 import QtCore, QtGui, QtWidgets

    script = os.path.abspath(__file__)

    class Worker(QtCore.QThread):
        """Runs a plain function off the UI thread (rclone can be slow)."""
        done = QtCore.pyqtSignal(object)

        def __init__(self, fn, parent=None):
            super().__init__(parent)
            self.fn = fn

        def run(self):
            try:
                self.done.emit(self.fn())
            except Exception as exc:  # show it, never crash the window
                self.done.emit(exc)

    def finish_threads(widget, threads):
        # A QThread destroyed while running aborts the whole app, so let any
        # quick rclone lookup finish (the window is hidden meanwhile).
        widget.hide()
        for t in list(threads):
            t.wait()

    def card():
        frame = QtWidgets.QFrame()
        frame.setObjectName("card")
        lay = QtWidgets.QVBoxLayout(frame)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        return frame, lay

    def muted(text=""):
        lbl = QtWidgets.QLabel(text)
        lbl.setObjectName("muted")
        lbl.setWordWrap(True)
        return lbl

    class JobRunner(QtCore.QObject):
        """Runs `cloud_backup.py <args>` and turns its JSON lines into signals,
        so the GUI and the systemd timer share one code path and one lock."""
        event = QtCore.pyqtSignal(dict)
        finished = QtCore.pyqtSignal(int, str)

        def __init__(self, parent=None):
            super().__init__(parent)
            self.proc = None
            self.buf = b""

        def busy(self):
            return self.proc is not None

        def start(self, args):
            self.buf = b""
            self.proc = QtCore.QProcess(self)
            self.proc.readyReadStandardOutput.connect(self._read)
            self.proc.finished.connect(self._done)
            self.proc.start(sys.executable, [script] + list(args))

        def _read(self):
            self.buf += bytes(self.proc.readAllStandardOutput())
            while b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                try:
                    data = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if isinstance(data, dict):
                    self.event.emit(data)

        def _done(self, code, _status):
            out = bytes(self.proc.readAllStandardError()).decode("utf-8", "replace")
            out = (out + bytes(self.proc.readAllStandardOutput()).decode("utf-8", "replace"))
            self.proc.deleteLater()
            self.proc = None
            self.finished.emit(int(code), out.strip())

    class RestoreDialog(QtWidgets.QDialog):
        def __init__(self, cfg, parent=None):
            super().__init__(parent)
            self.cfg = cfg
            self.setWindowTitle("Restore files")
            self.setStyleSheet(STYLE)
            self.resize(480, 420)
            self.threads = []
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(20, 18, 20, 18)
            lay.setSpacing(12)
            t = QtWidgets.QLabel("Restore files")
            t.setObjectName("title")
            lay.addWidget(t)
            lay.addWidget(muted("Copies files from the cloud back to this PC. Files that are "
                                "newer on this PC are never overwritten, and nothing is deleted."))
            lay.addWidget(QtWidgets.QLabel("Restore from which PC's backup?"))
            self.device = QtWidgets.QComboBox()
            self.device.addItem("Looking in the cloud…")
            self.device.setEnabled(False)
            lay.addWidget(self.device)
            lay.addWidget(QtWidgets.QLabel("Folders to restore"))
            self.checks = {}
            for key in FOLDER_KEYS:
                cb = QtWidgets.QCheckBox(cloud_name(key))
                cb.setChecked(True)
                self.checks[key] = cb
                lay.addWidget(cb)
            self.bar = QtWidgets.QProgressBar()
            self.bar.setTextVisible(False)
            self.bar.hide()
            lay.addWidget(self.bar)
            self.status = muted("")
            lay.addWidget(self.status)
            lay.addStretch(1)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            close = QtWidgets.QPushButton("Close")
            self.go = QtWidgets.QPushButton("Restore")
            self.go.setObjectName("primary")
            self.go.setEnabled(False)
            row.addWidget(close)
            row.addWidget(self.go)
            lay.addLayout(row)
            close.clicked.connect(self.reject)
            self.go.clicked.connect(self.restore)
            self.job = JobRunner(self)
            self.job.event.connect(self.on_event)
            self.job.finished.connect(self.on_finished)
            w = Worker(lambda: list_devices(cfg["remote"]), self)
            w.done.connect(self.on_devices)
            self.threads.append(w)
            w.start()

        def reject(self):
            # Closing mid-restore would cut rclone off half way through a file.
            if self.job.busy():
                self.status.setText("Please wait until the restore finishes.")
                return
            finish_threads(self, self.threads)
            super().reject()

        def on_devices(self, result):
            self.device.clear()
            if isinstance(result, Exception) or not result:
                self.device.addItem("No backups found yet")
                self.status.setText("" if not isinstance(result, Exception)
                                    else "Could not reach the cloud: %s" % result)
                return
            for name in result:
                self.device.addItem(name)
            idx = self.device.findText(self.cfg["device"])
            if idx >= 0:
                self.device.setCurrentIndex(idx)
            self.device.setEnabled(True)
            self.go.setEnabled(True)

        def restore(self):
            keys = [k for k, cb in self.checks.items() if cb.isChecked()]
            if not keys or self.job.busy():
                return
            self.go.setEnabled(False)
            self.bar.setValue(0)
            self.bar.show()
            self.status.setText("Starting…")
            self.job.start(["restore", "--progress", "--device", self.device.currentText(),
                            "--folders", ",".join(keys)])

        def on_event(self, ev):
            if "overall" in ev:
                self.bar.setValue(int(ev["overall"]))
            if ev.get("event") == "stats":
                self.status.setText("%s: %s of %s · %s" % (
                    ev.get("folder"), ev.get("done"), ev.get("total"), ev.get("speed")))
            elif ev.get("event") == "folder":
                self.status.setText("Restoring %s…" % ev.get("folder"))
            elif ev.get("event") == "done":
                self.status.setText(ev.get("result", ""))

        def on_finished(self, code, text):
            self.go.setEnabled(True)
            self.bar.setValue(100 if code == 0 else self.bar.value())
            if code != 0 and text and not self.status.text():
                self.status.setText(text[-300:])

    class BackupWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setObjectName("root")
            self.setWindowTitle(APP_NAME)
            self.setWindowIcon(QtGui.QIcon.fromTheme("folder-cloud",
                                                     QtGui.QIcon.fromTheme("cloud-upload")))
            self.setStyleSheet(STYLE)
            self.resize(620, 880)
            self.cfg = load_settings()
            self.connected = False
            self.threads = []

            # Content sits in a scroll area so word-wrapped text keeps its full
            # height on small screens instead of being squashed.
            top = QtWidgets.QVBoxLayout(self)
            top.setContentsMargins(0, 0, 0, 0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setStyleSheet("QScrollArea { background: #0b0f1a; border: none; }")
            holder = QtWidgets.QWidget()
            holder.setObjectName("root")
            scroll.setWidget(holder)
            top.addWidget(scroll)
            outer = QtWidgets.QVBoxLayout(holder)
            outer.setContentsMargins(22, 18, 22, 18)
            outer.setSpacing(12)
            intro = QtWidgets.QLabel(INTRO_TEXT)
            intro.setObjectName("intro")
            intro.setWordWrap(True)
            outer.addWidget(intro)
            title = QtWidgets.QLabel(APP_NAME)
            title.setObjectName("title")
            outer.addWidget(title)
            outer.addWidget(muted("Keeps a copy of your Documents, Desktop, Pictures and Downloads "
                                  "in Google Drive or OneDrive, so you can open them anywhere or "
                                  "put them back on a new PC. Deleting a file here never deletes "
                                  "it from the cloud."))

            # --- account ---------------------------------------------------
            acc, al = card()
            sec = QtWidgets.QLabel("Where to back up")
            sec.setObjectName("section")
            al.addWidget(sec)
            prow = QtWidgets.QHBoxLayout()
            self.radio = {}
            group = QtWidgets.QButtonGroup(self)
            for pid in ("gdrive", "onedrive"):
                rb = QtWidgets.QRadioButton(PROVIDERS[pid]["label"])
                group.addButton(rb)
                self.radio[pid] = rb
                prow.addWidget(rb)
            prow.addStretch(1)
            al.addLayout(prow)
            self.radio[self.cfg["provider"]].setChecked(True)
            self.account_label = muted("Checking…")
            al.addWidget(self.account_label)
            self.scope_label = muted(GDRIVE_SCOPE_TEXT)
            al.addWidget(self.scope_label)
            self.space_label = muted("")
            al.addWidget(self.space_label)
            brow = QtWidgets.QHBoxLayout()
            self.connect_btn = QtWidgets.QPushButton("Connect")
            self.connect_btn.setObjectName("primary")
            self.web_btn = QtWidgets.QPushButton("Open in browser")
            brow.addWidget(self.connect_btn)
            brow.addWidget(self.web_btn)
            brow.addStretch(1)
            al.addLayout(brow)
            al.addWidget(muted("Signing in happens in your web browser. DevOS never sees or "
                               "stores your password."))
            outer.addWidget(acc)

            # --- on/off + folders ------------------------------------------
            fc, fl = card()
            self.toggle = QtWidgets.QCheckBox("Back up automatically")
            self.toggle.setObjectName("toggle")
            fl.addWidget(self.toggle)
            fl.addWidget(muted("When on, new and changed files are copied about every 30 "
                               "minutes and shortly after a download finishes."))
            self.folder_checks = {}
            paths = resolve_folders()
            for key in FOLDER_KEYS:
                cb = QtWidgets.QCheckBox("%s  —  %s" % (cloud_name(key), paths[key]))
                cb.setChecked(self.cfg["folders"][key])
                cb.toggled.connect(self.save_folders)
                self.folder_checks[key] = cb
                fl.addWidget(cb)
            drow = QtWidgets.QHBoxLayout()
            drow.addWidget(QtWidgets.QLabel("This PC's name in the cloud"))
            self.device_edit = QtWidgets.QLineEdit(self.cfg["device"])
            self.device_edit.setMaxLength(64)
            drow.addWidget(self.device_edit, 1)
            fl.addLayout(drow)
            outer.addWidget(fc)

            # --- run / restore ---------------------------------------------
            rc_, rl = card()
            self.last_label = QtWidgets.QLabel("")
            self.last_label.setWordWrap(True)
            rl.addWidget(self.last_label)
            self.bar = QtWidgets.QProgressBar()
            self.bar.setTextVisible(False)
            self.bar.hide()
            rl.addWidget(self.bar)
            self.progress_label = muted("")
            rl.addWidget(self.progress_label)
            row = QtWidgets.QHBoxLayout()
            self.run_btn = QtWidgets.QPushButton("Back up now")
            self.run_btn.setObjectName("primary")
            self.restore_btn = QtWidgets.QPushButton("Restore files…")
            row.addWidget(self.run_btn)
            row.addWidget(self.restore_btn)
            row.addStretch(1)
            rl.addLayout(row)
            outer.addWidget(rc_)
            outer.addStretch(1)

            for b in (self.connect_btn, self.web_btn, self.run_btn, self.restore_btn):
                b.setCursor(QtCore.Qt.PointingHandCursor)

            self.job = JobRunner(self)
            self.job.event.connect(self.on_event)
            self.job.finished.connect(self.on_job_finished)
            self.job_kind = ""

            group.buttonClicked.connect(self.on_provider)
            self.connect_btn.clicked.connect(self.on_connect)
            self.web_btn.clicked.connect(self.open_web)
            self.toggle.clicked.connect(self.on_toggle)
            self.device_edit.editingFinished.connect(self.save_device)
            self.run_btn.clicked.connect(self.backup_now)
            self.restore_btn.clicked.connect(self.open_restore)
            self.refresh()

        # -- helpers -------------------------------------------------------
        def _bg(self, fn, cb):
            w = Worker(fn, self)
            w.done.connect(cb)
            w.finished.connect(lambda t=w: self.threads.remove(t) if t in self.threads else None)
            self.threads.append(w)
            w.start()

        def closeEvent(self, event):
            if self.job.busy() and self.job_kind == "run":
                ans = QtWidgets.QMessageBox.question(
                    self, APP_NAME, "A backup is running. Stop it and close? "
                    "It will continue at the next automatic backup.")
                if ans != QtWidgets.QMessageBox.Yes:
                    event.ignore()
                    return
            finish_threads(self, self.threads)
            super().closeEvent(event)

        def provider(self):
            return "onedrive" if self.radio["onedrive"].isChecked() else "gdrive"

        def refresh(self):
            self.cfg = load_settings()
            self._bg(lambda: is_connected(self.cfg), self.on_connected_state)
            self.update_ui()

        def on_connected_state(self, connected):
            self.connected = connected is True
            self.update_ui()
            if self.connected:
                self._bg(lambda: get_space(self.cfg["remote"]), self.on_space)

        def on_space(self, space):
            if isinstance(space, dict) and space.get("used") is not None:
                text = "Used %s" % human_size(space.get("used"))
                if space.get("free") is not None:
                    text += " · %s free" % human_size(space.get("free"))
                self.space_label.setText(text)
            else:
                self.space_label.setText("")

        def update_ui(self):
            label = PROVIDERS[self.provider()]["label"]
            busy = self.job.busy()
            if not have_rclone():
                self.account_label.setText("rclone is missing. Install it with: "
                                           "sudo apt install rclone")
            elif self.connected:
                self.account_label.setText("Connected to %s. Files go to DevOS/%s/ there."
                                           % (label, self.cfg["device"]))
            else:
                self.account_label.setText("Not connected. Nothing is uploaded until you "
                                           "connect and turn backup on.")
            self.scope_label.setVisible(self.provider() == "gdrive")
            self.connect_btn.setText("Disconnect" if self.connected else "Connect %s" % label)
            self.connect_btn.setObjectName("" if self.connected else "primary")
            self.connect_btn.setStyle(self.connect_btn.style())
            self.connect_btn.setEnabled(not busy and have_rclone())
            for rb in self.radio.values():
                rb.setEnabled(not self.connected and not busy)
            self.toggle.setEnabled(self.connected and not busy)
            self.toggle.setChecked(self.cfg["enabled"])
            self.run_btn.setEnabled(self.connected and not busy)
            self.restore_btn.setEnabled(self.connected and not busy)
            if not self.connected:
                self.space_label.setText("")
            state = "on" if self.cfg["enabled"] else "off"
            last = "Last backup: %s" % format_when(self.cfg["last_run"])
            if self.cfg["last_result"]:
                last += " — %s" % self.cfg["last_result"]
            self.last_label.setText("Automatic backup is %s.\n%s" % (state, last))

        # -- actions -------------------------------------------------------
        def on_provider(self, *_):
            cfg = set_provider(load_settings(), self.provider())
            save_settings(cfg)
            self.refresh()

        def on_connect(self):
            if self.connected:
                ans = QtWidgets.QMessageBox.question(
                    self, "Disconnect",
                    "Stop backing up and forget this account on this PC?\n\n"
                    "Files already in the cloud stay there.")
                if ans != QtWidgets.QMessageBox.Yes:
                    return
                self.start_job("disconnect", ["disconnect"], "Disconnecting…")
            else:
                self.start_job("connect", ["connect", self.provider()],
                               "Finish signing in in your web browser…")

        def on_toggle(self):
            self.start_job("toggle", ["enable" if self.toggle.isChecked() else "disable"], "")

        def save_folders(self, *_):
            cfg = load_settings()
            cfg["folders"] = {k: cb.isChecked() for k, cb in self.folder_checks.items()}
            save_settings(cfg)
            self.cfg = cfg

        def save_device(self):
            name = clean_device_name(self.device_edit.text()) or default_device_name()
            self.device_edit.setText(name)
            cfg = load_settings()
            if cfg["device"] == name:
                return
            cfg["device"] = name
            save_settings(cfg)
            self.cfg = cfg
            if self.connected:
                # Make the new folder layout appear in the cloud right away.
                remote = cfg["remote"]
                self._bg(lambda: [_run(c, timeout=120) for c in mkdir_commands(remote, name)],
                         lambda *_: None)
            self.update_ui()

        def open_web(self):
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(PROVIDERS[self.provider()]["web"]))

        def backup_now(self):
            self.save_device()
            self.bar.setValue(0)
            self.bar.show()
            self.start_job("run", ["run", "--now", "--progress"], "Checking for new files…")

        def open_restore(self):
            RestoreDialog(load_settings(), self).exec_()

        def start_job(self, kind, args, text):
            if self.job.busy():
                return
            self.job_kind = kind
            self.progress_label.setText(text)
            self.job.start(args)
            self.update_ui()

        def on_event(self, ev):
            if "overall" in ev:
                self.bar.setValue(int(ev["overall"]))
            if ev.get("event") == "stats":
                eta = ev.get("eta")
                self.progress_label.setText("%s: %s of %s · %s%s" % (
                    ev.get("folder"), ev.get("done"), ev.get("total"), ev.get("speed"),
                    "" if eta in (None, "-", "0s") else " · about %s left" % eta))
            elif ev.get("event") == "folder":
                self.progress_label.setText("Backing up %s…" % ev.get("folder"))
            elif ev.get("event") == "done":
                self.progress_label.setText(ev.get("result", ""))

        def on_job_finished(self, code, text):
            kind, self.job_kind = self.job_kind, ""
            if kind == "run":
                self.bar.setValue(100 if code == 0 else self.bar.value())
            elif kind in ("connect", "disconnect", "toggle"):
                last = text.strip().splitlines()[-1] if text.strip() else ""
                self.progress_label.setText(last)
            self.refresh()

    qapp = QtWidgets.QApplication(sys.argv)
    qapp.setApplicationName(APP_NAME)
    font = QtGui.QFont("Inter")
    if not QtGui.QFontInfo(font).exactMatch():
        font = QtGui.QFont("Noto Sans")
    qapp.setFont(font)
    win = BackupWindow()
    win.show()
    return qapp.exec_()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("gui", help="open the Cloud Backup window (default)")
    p = sub.add_parser("connect", help="sign in to Google Drive or OneDrive")
    p.add_argument("provider", choices=sorted(PROVIDERS))
    sub.add_parser("disconnect", help="forget the account and stop automatic backup")
    p = sub.add_parser("run", help="back up the chosen folders once")
    p.add_argument("--now", action="store_true",
                   help="run even if automatic backup is off, without waiting for files to settle")
    p.add_argument("--progress", action="store_true", help="print JSON progress lines")
    p = sub.add_parser("restore", help="copy files from the cloud back to this PC")
    p.add_argument("--device", help="which PC's backup to restore (default: this PC)")
    p.add_argument("--folders", help="comma list, e.g. documents,pictures (default: all)")
    p.add_argument("--progress", action="store_true", help="print JSON progress lines")
    sub.add_parser("status", help="print settings and state as JSON")
    sub.add_parser("enable", help="turn automatic backup on")
    sub.add_parser("disable", help="turn automatic backup off")
    args = parser.parse_args(argv)

    cmd = args.cmd or "gui"
    if cmd == "gui":
        return run_gui()
    if cmd == "connect":
        return cmd_connect(args.provider)
    if cmd == "disconnect":
        return cmd_disconnect()
    if cmd == "run":
        return cmd_run(now=args.now, progress=args.progress)
    if cmd == "restore":
        folders = [f for f in (args.folders or "").split(",") if f.strip()] or None
        return cmd_restore(args.device, folders, progress=args.progress)
    if cmd == "status":
        return cmd_status()
    if cmd == "enable":
        return cmd_enable()
    if cmd == "disable":
        return cmd_disable()
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
