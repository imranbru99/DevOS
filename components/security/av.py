#!/usr/bin/env python3
"""
DevOS Security - virus protection (ClamAV).

What it does
  * Scans every finished download: ~/Downloads (and the XDG download folder
    when it is somewhere else), ~/Desktop, Telegram's download folder and
    Flatpak apps' ~/.var/app/*/Downloads. Partial files (.crdownload, .part,
    .partial, .tmp, ...) are skipped; the browser renames them when the
    download is complete and the rename triggers the scan.
  * Scans USB drives when they are mounted under /media/$USER (risky file
    types first, bounded so a 1 TB disk does not run for hours).
  * Scans Windows .exe/.msi and Android .apk files right before they run
    (components/apphub/safety_scanner.py calls scan_for_launch()).
  * Archives (zip, rar, 7z, ...) are scanned inside: clamscan's default.

How it stays cheap
  * A look-alike / phishing-page check (linkguard.py) runs first and reads at
    most 64 KB. An obvious phishing page is quarantined without loading the
    virus signatures. Ordinary files are not read by that check.
  * Watching costs no RAM when idle: systemd --user path units
    (devos-av-watch.path, devos-av-usb.path) use inotify inside the user's
    systemd, which is running anyway. They start "devos-security av
    watch-run" only when something changes; it scans and exits.
  * PCs with 8 GB RAM or more use clamd (clamav-daemon) + clamdscan: the
    signatures stay loaded (about 1-1.5 GB), so a scan is instant.
  * Smaller PCs batch new files and run "nice ionice clamscan": it loads the
    signatures (about 1 GB, 10-30 s) only while scanning, then frees them.

Quarantine
  * /var/lib/DevOS/quarantine (root, 0700). Files are stored without any
    execute or read permission for users, renamed *.quarantined, with a
    metadata JSON next to them.
  * The watcher runs as the user, so it cannot write there. It moves the
    file into ~/.local/share/devos-security/pending (0700, file mode 000)
    and drops a request into /run/devos-security/inbox; the root
    devos-security-quarantine.path unit picks it up and checks that the
    request, the staged file and the user all match before moving it.
  * Restore writes the file back as its owner (never as root), so a
    symlink planted at the old path cannot redirect it.

Honest limits: ClamAV finds known threats by signature. It is very good at
Windows/Android malware and phishing documents, weaker against brand-new
threats. Files over ClamAV's size limits (100 MB by default) are only
partly checked.
"""

import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seccommon as common  # noqa: E402

QUARANTINE_DIR = "/var/lib/DevOS/quarantine"
INDEX_DIR = common.DATA_DIR + "/quarantine-index"      # per-uid list, readable by that user
INBOX = common.RUN_DIR + "/inbox"                      # 1733, like /tmp
ALLOWLIST = common.DATA_DIR + "/allowlist.json"        # sha256 restored by an administrator
HISTORY = common.DATA_DIR + "/history.json"            # scans run as root
CLAMAV_DB = "/var/lib/clamav"
CLAMD_SOCKETS = ("/run/clamav/clamd.ctl", "/var/run/clamav/clamd.ctl")
CLAMD_MIN_RAM = 8 * common.GB
SETTLE_S = 3            # a file written in the last 3 s may still be growing
BATCH_WAIT_S = 8        # clamscan: wait for more files so signatures load once
MAX_ROUNDS = 30
SEEN_LIMIT = 5000
LOG_LIMIT = 200
USB_MAX_FILES = 3000
USB_MAX_DEPTH = 5
USB_MAX_FILE = 100 * common.MB

# Browsers and download tools write here first and rename when finished.
PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".tmp", ".download", ".opdownload",
                    ".aria2", ".!qb", ".!ut", ".filepart", ".dtapart", ".temp")
PARTIAL_PREFIXES = (".com.google.chrome.", ".org.chromium.chromium.", ".goutputstream-",
                    ".~lock.", "~$")

RISKY_EXTS = (".exe", ".msi", ".dll", ".scr", ".com", ".bat", ".cmd", ".ps1", ".vbs", ".js",
              ".jse", ".wsf", ".hta", ".lnk", ".jar", ".apk", ".xapk", ".apks", ".appimage",
              ".deb", ".sh", ".run", ".bin", ".iso", ".img", ".zip", ".rar", ".7z", ".gz",
              ".tar", ".cab", ".docm", ".xlsm", ".pptm", ".doc", ".xls", ".rtf", ".pdf",
              ".html", ".htm", ".svg", ".py", ".inf")
LAUNCH_EXTS = (".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".apk", ".xapk", ".apks")


def now():
    return time.time()


def getuid():
    return os.getuid() if hasattr(os, "getuid") else 0


# ---------------------------------------------------------------- file rules

def is_partial(name):
    """True for files a download tool is still writing."""
    low = os.path.basename(name).lower()
    if low.endswith(PARTIAL_SUFFIXES):
        return True
    return low.startswith(PARTIAL_PREFIXES)


def is_risky(name):
    return os.path.basename(name).lower().endswith(RISKY_EXTS) or name.lower() == "autorun.inf"


def needs_launch_scan(path):
    return path.lower().endswith(LAUNCH_EXTS)


def parse_user_dirs(text, home):
    """~/.config/user-dirs.dirs -> {"DOWNLOAD": "/home/u/Downloads", ...}."""
    out = {}
    for line in (text or "").splitlines():
        m = re.match(r'\s*XDG_([A-Z]+)_DIR\s*=\s*"(.*)"\s*$', line)
        if m:
            out[m.group(1)] = m.group(2).replace("$HOME", home)
    return out


def watch_dirs(home, existing_only=True):
    """Folders where new files are scanned (not recursive)."""
    user_dirs = parse_user_dirs(common.read_text(os.path.join(home, ".config", "user-dirs.dirs"), ""), home)
    dirs = [os.path.join(home, "Downloads"), os.path.join(home, "Desktop")]
    for key in ("DOWNLOAD", "DESKTOP"):
        if user_dirs.get(key) and os.path.normpath(user_dirs[key]) != os.path.normpath(home):
            dirs.append(user_dirs[key])
    for base in list(dirs[:1]) + ([user_dirs["DOWNLOAD"]] if user_dirs.get("DOWNLOAD") else []):
        dirs.append(os.path.join(base, "Telegram Desktop"))      # Telegram (deb and Flatpak)
    var_app = os.path.join(home, ".var", "app")
    try:
        for app in sorted(os.listdir(var_app)):
            dirs.append(os.path.join(var_app, app, "Downloads"))  # Flatpak apps' own folder
    except OSError:
        pass
    out = []
    for d in dirs:
        d = os.path.normpath(d)
        if d not in out and (not existing_only or os.path.isdir(d)):
            out.append(d)
    return out


def path_unit_dropin(dirs):
    lines = ["# Written by \"devos-security av watch-setup\" at sign-in: the folders",
             "# where new files are scanned (XDG download folder, Flatpak apps).",
             "[Path]"]
    lines += ["PathChanged=%s" % d.replace("%", "%%") for d in dirs]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- engine

def clamd_socket():
    for path in CLAMD_SOCKETS:
        if os.path.exists(path):
            return path
    return None


def choose_engine(mem_total, have=None, socket_present=None):
    """'clamdscan' (RAM >= 8 GB and clamd running), 'clamscan', or None."""
    have = have or common.which
    if socket_present is None:
        socket_present = clamd_socket() is not None
    if mem_total >= CLAMD_MIN_RAM and socket_present and have("clamdscan"):
        return "clamdscan"
    if have("clamscan"):
        return "clamscan"
    return None


def scanner_command(engine, list_file, recursive=False):
    override = os.environ.get("DEVOS_CLAMSCAN")  # tests: a fake scanner
    if override:
        base = shlex.split(override)
    elif engine == "clamdscan":
        base = ["clamdscan", "--fdpass"]
    else:
        base = common.low_priority_prefix() + ["clamscan"]
        if recursive:
            base.append("--recursive")
    return base + ["--no-summary", "--infected", "--stdout", "--file-list=" + list_file]


def parse_clam_output(text):
    """Lines "path: Threat FOUND" -> {path: threat}; "path: ... ERROR" -> errors."""
    infected, errors = {}, []
    for line in (text or "").splitlines():
        line = line.rstrip()
        if line.endswith(" FOUND") and ": " in line:
            path, threat = line[:-len(" FOUND")].rsplit(": ", 1)
            infected[path] = threat.strip()
        elif line.endswith(" ERROR") and ": " in line:
            errors.append(line)
    return infected, errors


def db_version():
    """Newest signature file time: changes whenever freshclam updates."""
    newest = 0
    try:
        for name in os.listdir(CLAMAV_DB):
            if name.endswith((".cvd", ".cld", ".cud")):
                newest = max(newest, int(os.stat(os.path.join(CLAMAV_DB, name)).st_mtime))
    except OSError:
        pass
    return newest


def signatures_age_days(now_ts=None):
    version = db_version()
    if not version:
        return None
    return max(0.0, ((now_ts or now()) - version) / 86400.0)


def wait_for_memory(need=900 * common.MB, timeout=120, sleep=time.sleep):
    """clamscan needs ~1 GB while it runs: wait (bounded) for free memory."""
    end = now() + timeout
    while now() < end:
        mem = common.read_meminfo()
        if not mem.get("total") or mem.get("available", need) >= need:
            return True  # enough free, or unknown (no /proc/meminfo)
        sleep(5)
        if sleep is not time.sleep:
            return False  # tests: do not spin
    return False


def scan_paths(paths, engine=None, runner=None, recursive=False):
    """Scan files (or folders with recursive=True) in one engine run.
    Returns {"engine", "scanned", "infected": {path: threat}, "errors", "ok"}."""
    paths = [p for p in paths if p]
    result = {"engine": engine, "scanned": len(paths), "infected": {}, "errors": [], "ok": False}
    if not paths:
        result["ok"] = True
        return result
    if engine is None:
        engine = choose_engine(common.read_meminfo().get("total", 0))
        result["engine"] = engine
    if engine is None and not os.environ.get("DEVOS_CLAMSCAN"):
        result["errors"].append("ClamAV is not installed")
        return result
    fd, list_file = tempfile.mkstemp(prefix="devos-av-", suffix=".list")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(paths) + "\n")
        cmd = scanner_command(engine, list_file, recursive)
        code, out = (runner or common.run)(cmd, timeout=6 * 3600)
    finally:
        try:
            os.remove(list_file)
        except OSError:
            pass
    infected, errors = parse_clam_output(out)
    result["infected"] = infected
    result["errors"] = errors
    # 0 = clean, 1 = found; 2 = an error (no signatures, unreadable file...)
    result["ok"] = code in (0, 1) or (code == 2 and bool(infected))
    if not result["ok"] and not errors:
        result["errors"].append((out.strip().splitlines() or ["scanner failed (%s)" % code])[-1])
    return result


def sha256_file(path, limit=None):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        read = 0
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
            if limit and read >= limit:
                break
    return digest.hexdigest()


# ---------------------------------------------------------------- allowlist

def allowed_hashes(home=None):
    hashes = set()
    for path in (ALLOWLIST, os.path.join(common.user_state_dir(home), "allowlist.json")):  # noqa
        data = common.read_json(path, [])
        if isinstance(data, list):
            hashes.update(h for h in data if isinstance(h, str))
    return hashes


def add_allowed(sha, path):
    data = common.read_json(path, [])
    if not isinstance(data, list):
        data = []
    if sha not in data:
        data.append(sha)
    common.write_json(path, data[-2000:], 0o644)


# ---------------------------------------------------------------- quarantine

def new_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()


def _write_as(uid, gid, dest, src_path, mode):
    """Create dest (never following a symlink, never overwriting) as uid."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)

    def copy():
        out = os.open(dest, flags, mode & 0o7777)
        with open(src_path, "rb") as src, os.fdopen(out, "wb") as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)

    if not common.is_root() or uid == 0:
        copy()
        return True
    src_fd = os.open(src_path, os.O_RDONLY)
    pid = os.fork()
    if pid == 0:  # child: become the owner, then write
        code = 1
        try:
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)
            out = os.open(dest, flags, mode & 0o7777)
            with os.fdopen(src_fd, "rb") as src, os.fdopen(out, "wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            code = 0
        except Exception:
            code = 1
        os._exit(code)
    os.close(src_fd)
    _pid, status = os.waitpid(pid, 0)
    return os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0


def free_name(path):
    if not os.path.lexists(path):
        return path
    base, ext = os.path.splitext(path)
    for n in range(1, 1000):
        candidate = "%s (restored %d)%s" % (base, n, ext)
        if not os.path.lexists(candidate):
            return candidate
    return "%s (restored %s)%s" % (base, new_id(), ext)


def _move(src, dest):
    try:
        os.rename(src, dest)
    except OSError:
        import shutil
        shutil.copyfile(src, dest)
        os.remove(src)


class Quarantine(object):
    """Root quarantine. Every path is a parameter so tests use temp folders."""

    def __init__(self, folder=None, index_dir=None, allowlist=None):
        self.folder = folder or QUARANTINE_DIR
        self.index_dir = index_dir if index_dir is not None else INDEX_DIR
        self.allowlist = allowlist or ALLOWLIST

    def _ensure(self):
        os.makedirs(self.folder, exist_ok=True)
        try:
            os.chmod(self.folder, 0o700)
        except OSError:
            pass

    def meta_path(self, qid):
        return os.path.join(self.folder, qid + ".json")

    def blob_path(self, qid):
        return os.path.join(self.folder, qid + ".quarantined")

    def store(self, path, threat, source="scan", uid=None, original=None, mode=None):
        """Move `path` into quarantine; returns the metadata dict."""
        self._ensure()
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            raise OSError("not a regular file: %s" % path)
        qid = new_id()
        meta = {
            "id": qid, "original": original or os.path.abspath(path), "threat": threat,
            "time": int(now()), "uid": st.st_uid if uid is None else uid,
            "mode": stat.S_IMODE(st.st_mode) if mode is None else mode, "size": st.st_size,
            "sha256": sha256_file(path), "source": source, "status": "quarantined",
        }
        blob = self.blob_path(qid)
        _move(path, blob)
        os.chmod(blob, 0o600)
        if common.is_root():
            os.chown(blob, 0, 0)
        common.write_json(self.meta_path(qid), meta, 0o600)
        self.write_index(meta["uid"])
        return meta

    def items(self, uid=None):
        out = []
        try:
            names = sorted(os.listdir(self.folder), reverse=True)
        except OSError:
            return out
        for name in names:
            if name.endswith(".json"):
                meta = common.read_json(os.path.join(self.folder, name))
                if isinstance(meta, dict) and (uid is None or meta.get("uid") == uid):
                    out.append(meta)
        return out

    def write_index(self, uid):
        """Per-user copy of the list so the window can show it without root."""
        if self.index_dir is None:
            return
        try:
            os.makedirs(self.index_dir, exist_ok=True)
            os.chmod(self.index_dir, 0o711)
            path = os.path.join(self.index_dir, "%d.json" % uid)
            common.write_json(path, self.items(uid), 0o600)
            if common.is_root():
                os.chown(path, uid, -1)
        except OSError:
            pass

    def get(self, qid):
        if not re.match(r"^[0-9A-Za-z-]+$", qid or ""):
            return None
        meta = common.read_json(self.meta_path(qid))
        return meta if isinstance(meta, dict) else None

    def restore(self, qid, allow=True):
        """Put the file back (as its owner). Returns the restored path."""
        meta = self.get(qid)
        if not meta:
            raise KeyError(qid)
        dest = free_name(meta["original"])
        uid = int(meta.get("uid", getuid()))
        gid = uid
        try:
            import pwd
            gid = pwd.getpwuid(uid).pw_gid
        except (ImportError, KeyError):
            pass
        if not _write_as(uid, gid, dest, self.blob_path(qid), int(meta.get("mode", 0o644)) & 0o777):
            raise OSError("could not write %s as its owner" % dest)
        if allow:
            add_allowed(meta["sha256"], self.allowlist)
        os.remove(self.blob_path(qid))
        os.remove(self.meta_path(qid))
        self.write_index(uid)
        return dest

    def delete(self, qid):
        meta = self.get(qid)
        if not meta:
            raise KeyError(qid)
        for path in (self.blob_path(qid), self.meta_path(qid)):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        self.write_index(int(meta.get("uid", 0)))
        return True


def pending_dir(home=None):
    return os.path.join(home or os.path.expanduser("~"), ".local", "share", "devos-security", "pending")


def stage(path, threat, source="scan", home=None, inbox=None):
    """User side: neutralise the file at once (move + mode 000) and ask the
    root service to take it into the quarantine."""
    folder = pending_dir(home)
    os.makedirs(folder, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:
        pass
    st = os.lstat(path)
    qid = new_id()
    staged = os.path.join(folder, qid + ".quarantined")
    _move(path, staged)
    os.chmod(staged, 0)
    meta = {"id": qid, "original": os.path.abspath(path), "threat": threat, "time": int(now()),
            "uid": st.st_uid, "mode": stat.S_IMODE(st.st_mode), "size": st.st_size,
            "source": source, "status": "pending", "staged": staged}
    common.write_json(os.path.join(folder, qid + ".json"), meta, 0o600)
    inbox = INBOX if inbox is None else inbox
    if inbox and os.path.isdir(inbox):
        try:
            common.write_json(os.path.join(inbox, "%d-%s.json" % (getuid(), qid)), meta, 0o600)
        except OSError:
            pass
    return meta


def pending_items(home=None):
    folder = pending_dir(home)
    out = []
    try:
        names = sorted(os.listdir(folder), reverse=True)
    except OSError:
        return out
    for name in names:
        if name.endswith(".json"):
            meta = common.read_json(os.path.join(folder, name))
            if isinstance(meta, dict) and os.path.exists(os.path.join(folder, meta.get("id", "") + ".quarantined")):
                out.append(meta)
    return out


def restore_pending(qid, home=None):
    folder = pending_dir(home)
    meta = common.read_json(os.path.join(folder, qid + ".json"))
    if not isinstance(meta, dict):
        raise KeyError(qid)
    staged = os.path.join(folder, qid + ".quarantined")
    os.chmod(staged, 0o600)
    dest = free_name(meta["original"])
    _move(staged, dest)
    os.chmod(dest, int(meta.get("mode", 0o644)) & 0o777)
    add_allowed(sha256_file(dest), os.path.join(common.user_state_dir(home), "allowlist.json"))
    os.remove(os.path.join(folder, qid + ".json"))
    return dest


def delete_pending(qid, home=None):
    folder = pending_dir(home)
    for suffix in (".quarantined", ".json"):
        try:
            os.remove(os.path.join(folder, qid + suffix))
        except FileNotFoundError:
            pass
    return True


def validate_request(req_path, req, home_of=None):
    """Root side: may this request be honoured? Returns the staged path or None.
    The request file, the staged file and the pending folder must all belong
    to the same user, the staged file must be a single-link regular file."""
    home_of = home_of or _home_of
    try:
        req_st = os.lstat(req_path)
        uid = req_st.st_uid
        if not isinstance(req, dict) or not re.match(r"^[0-9A-Za-z-]+$", str(req.get("id", ""))):
            return None
        home = home_of(uid)
        if not home:
            return None
        folder = os.path.realpath(pending_dir(home))
        staged = os.path.join(folder, req["id"] + ".quarantined")
        if os.path.realpath(staged) != staged:
            return None
        st = os.lstat(staged)
        if not stat.S_ISREG(st.st_mode) or st.st_uid != uid or st.st_nlink != 1:
            return None
        if os.lstat(folder).st_uid != uid:
            return None
        return staged
    except (OSError, KeyError, TypeError):
        return None


def _home_of(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_dir
    except (ImportError, KeyError):
        return None


def ingest(inbox=None, quarantine=None, home_of=None):
    """Root: move staged files named in the inbox into the quarantine."""
    quarantine = quarantine or Quarantine()
    inbox = inbox or INBOX
    done = []
    try:
        names = sorted(os.listdir(inbox))
    except OSError:
        return done
    for name in names:
        req_path = os.path.join(inbox, name)
        req = common.read_json(req_path)
        staged = validate_request(req_path, req, home_of)
        uid = None
        try:
            uid = os.lstat(req_path).st_uid
        except OSError:
            pass
        try:
            os.remove(req_path)
        except OSError:
            pass
        if not staged:
            common.log("quarantine: ignored request %s" % name)
            continue
        try:
            mode = int(req.get("mode", 0o644)) & 0o777
        except (TypeError, ValueError):
            mode = 0o644
        try:
            meta = quarantine.store(staged, str(req.get("threat", "unknown"))[:200],
                                    source=str(req.get("source", "scan"))[:40], uid=uid,
                                    original=str(req.get("original", ""))[:4096] or None, mode=mode)
        except OSError as exc:
            common.log("quarantine: could not take %s: %s" % (name, exc))
            continue
        try:
            os.remove(os.path.join(os.path.dirname(staged), req["id"] + ".json"))
        except OSError:
            pass
        done.append(meta)
        common.log("quarantine: %s (%s) from %s" % (meta["original"], meta["threat"], meta["uid"]))
    return done


def quarantine_file(path, threat, source="scan", home=None):
    if common.is_root():
        return Quarantine().store(path, threat, source)
    return stage(path, threat, source, home)


def is_quarantine_path(path, home=None):
    """Files inside the quarantine or the pending folder must never run."""
    real = os.path.realpath(path)
    for root in (QUARANTINE_DIR, pending_dir(home)):
        root = os.path.realpath(root)
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return True
    return real.endswith(".quarantined")


def user_quarantine(home=None):
    """What this user may see: their pending items + their quarantine index."""
    items = pending_items(home)
    if common.is_root():
        items += Quarantine().items()
    else:
        data = common.read_json(os.path.join(INDEX_DIR, "%d.json" % getuid()), [])
        if isinstance(data, list):
            items += [m for m in data if isinstance(m, dict)]
    return sorted(items, key=lambda m: m.get("time", 0), reverse=True)


# ---------------------------------------------------------------- logs

def append_log(path, entries, limit=LOG_LIMIT):
    data = common.read_json(path, [])
    if not isinstance(data, list):
        data = []
    data.extend(entries)
    common.write_json(path, data[-limit:], 0o600)


def downloads_log_path(home=None):
    return os.path.join(common.user_state_dir(home), "downloads.json")


def history_path(home=None):
    return HISTORY if common.is_root() else os.path.join(common.user_state_dir(home), "history.json")


def recent_downloads(home=None, limit=30):
    data = common.read_json(downloads_log_path(home), [])
    return list(reversed(data[-limit:])) if isinstance(data, list) else []


def scan_history(home=None, limit=50):
    data = common.read_json(history_path(home), [])
    return list(reversed(data[-limit:])) if isinstance(data, list) else []


# ---------------------------------------------------------------- watcher

def file_key(st):
    return [st.st_size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))]


def find_candidates(dirs, seen, now_ts):
    """New or changed finished files. Returns (ready, waiting)."""
    ready, waiting = [], []
    for folder in dirs:
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for name in names:
            path = os.path.join(folder, name)
            if is_partial(name):
                continue
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size == 0:
                continue  # Firefox creates an empty placeholder first
            if seen.get(path) == file_key(st):
                continue
            if now_ts - st.st_mtime < SETTLE_S:
                waiting.append(path)
            else:
                ready.append(path)
    return ready, waiting


def prune_seen(seen):
    for path in [p for p in seen if not os.path.exists(p)]:
        del seen[path]
    if len(seen) > SEEN_LIMIT:
        for path in list(seen)[:len(seen) - SEEN_LIMIT]:
            del seen[path]
    return seen


def screen_links(paths, home=None, source="download", where="Downloads"):
    """Catch an obvious phishing page before ClamAV loads its signatures.

    Returns (log entries, paths still to scan). Ordinary files are not read.
    A failure here never hides a file from the virus scanner."""
    try:
        import linkguard
    except Exception:
        return [], list(paths)
    entries = []
    skip = set()
    allowed = allowed_hashes(home)
    for path in paths:
        try:
            verdict = linkguard.inspect_path(path)
        except Exception:
            continue
        if verdict.get("level") != "block":
            continue
        entry = {"time": int(now()), "path": path, "name": os.path.basename(path),
                 "engine": "linkguard", "source": source, "threat": verdict.get("threat") or "DevOS.Phishing.Page"}
        try:
            if sha256_file(path) in allowed:
                entry["result"] = "allowed"
                skip.add(path)
            else:
                quarantine_file(path, entry["threat"], source, home)
                entry["result"] = "quarantined"
                notify_threat(entry["name"], entry["threat"], where)
                skip.add(path)
        except OSError as exc:
            entry.update(result="threat (not moved)", error=str(exc))
            common.notify("Threat found", "%s looks like a phishing page and could not be moved (%s). "
                          "Do not open it." % (entry["name"], exc),
                          icon="security-low", urgency="critical")
        entries.append(entry)
    return entries, [path for path in paths if path not in skip]


def notify_threat(name, threat, where="Downloads"):
    common.notify("Threat removed", "%s in %s contained %s. It was moved to quarantine; "
                  "you can review it in DevOS Security." % (name, where, threat),
                  icon="security-low", urgency="critical")


def handle_results(paths, result, home=None, source="download", notify_safe=False, where="Downloads"):
    """Quarantine what was found; return log entries."""
    entries = []
    allowed = allowed_hashes(home)
    for path in paths:
        entry = {"time": int(now()), "path": path, "name": os.path.basename(path),
                 "engine": result.get("engine") or "", "source": source}
        threat = result["infected"].get(path)
        if threat is None:
            for found_path, found in result["infected"].items():   # archive members: "a.zip!x.exe"
                if found_path.startswith(path + "!") or found_path.startswith(path + "/"):
                    threat = found
                    break
        if threat:
            try:
                if sha256_file(path) in allowed:
                    entry.update(result="allowed", threat=threat)
                    entries.append(entry)
                    continue
                quarantine_file(path, threat, source, home)
                entry.update(result="quarantined", threat=threat)
                notify_threat(entry["name"], threat, where)
            except OSError as exc:
                entry.update(result="threat (not moved)", threat=threat, error=str(exc))
                common.notify("Threat found", "%s contains %s and could not be moved (%s). "
                              "Do not open it." % (entry["name"], threat, exc),
                              icon="security-low", urgency="critical")
        elif result.get("ok"):
            entry["result"] = "clean"
        else:
            entry.update(result="not scanned", error="; ".join(result.get("errors", []))[:300])
        entries.append(entry)
    clean = [e for e in entries if e["result"] == "clean"]
    if notify_safe and clean:
        names = ", ".join(e["name"] for e in clean[:3]) + ("…" if len(clean) > 3 else "")
        common.notify("Download is safe", "No threats found in %s." % names, icon="security-high")
    return entries


def watch_run(home=None, engine=None, runner=None, sleep=time.sleep, dirs=None, max_rounds=MAX_ROUNDS):
    """Scan everything new in the watched folders, then exit."""
    home = home or os.path.expanduser("~")
    dirs = dirs if dirs is not None else watch_dirs(home)
    seen_path = os.path.join(common.user_state_dir(home), "seen.json")
    seen = common.read_json(seen_path, {}) or {}
    cfg = common.load_user_config(home)
    if engine is None:
        engine = choose_engine(common.read_meminfo().get("total", 0))
    all_entries = []
    batched = False
    for _round in range(max_rounds):
        ready, waiting = find_candidates(dirs, seen, now())
        if not ready and not waiting:
            break
        if engine == "clamscan" and not batched:
            batched = True
            sleep(BATCH_WAIT_S)  # let a burst of downloads finish: one signature load
            continue
        if not ready:
            sleep(SETTLE_S)
            continue
        keys = {}
        for p in ready:
            try:
                keys[p] = file_key(os.lstat(p))
            except OSError:
                pass
        guarded, rest = screen_links(list(keys), home, where="Downloads")
        entries = list(guarded)
        if rest:
            # Signatures stay unloaded when every new file was already quarantined.
            if engine == "clamscan":
                wait_for_memory(sleep=sleep)
            result = scan_paths(rest, engine=engine, runner=runner)
            entries += handle_results(rest, result, home, notify_safe=cfg.get("notify_safe_downloads"))
        for p, key in keys.items():
            seen[p] = key
        all_entries += entries
    common.write_json(seen_path, prune_seen(seen), 0o600)
    if all_entries:
        append_log(downloads_log_path(home), all_entries)
    return all_entries


def usb_files(mount, max_files=USB_MAX_FILES, max_depth=USB_MAX_DEPTH):
    """Risky file types first, then the rest, bounded."""
    risky, other = [], []
    base_depth = mount.rstrip(os.sep).count(os.sep)
    for root, dirs, files in os.walk(mount):
        if root.count(os.sep) - base_depth >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in ("System Volume Information", "$RECYCLE.BIN", ".Trash-1000")]
        for name in files:
            path = os.path.join(root, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode) or st.st_size == 0 or st.st_size > USB_MAX_FILE:
                continue
            (risky if is_risky(name) else other).append(path)
        if len(risky) >= max_files:
            break
    return (risky + other)[:max_files]


def usb_run(home=None, user=None, engine=None, runner=None, media_root=None):
    """Scan USB drives mounted since the last run."""
    home = home or os.path.expanduser("~")
    user = user or os.environ.get("USER") or os.path.basename(home)
    media = media_root or os.path.join("/media", user)
    state_path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or common.user_state_dir(home),
                              "devos-security-usb.json")
    seen = common.read_json(state_path, {}) or {}
    current = {}
    try:
        mounts = [os.path.join(media, m) for m in sorted(os.listdir(media))]
    except OSError:
        mounts = []
    cfg = common.load_user_config(home)
    entries = []
    for mount in mounts:
        if not os.path.ismount(mount) and media_root is None:
            continue
        try:
            key = str(os.stat(mount).st_dev)
        except OSError:
            continue
        current[mount] = key
        if seen.get(mount) == key:
            continue
        files = usb_files(mount)
        if engine is None:
            engine = choose_engine(common.read_meminfo().get("total", 0))
        where = "the USB drive %s" % os.path.basename(mount)
        guarded, rest = screen_links(files, home, source="usb", where=where)
        if rest:
            result = scan_paths(rest, engine=engine, runner=runner)
            found = handle_results(rest, result, home, source="usb", where=where)
        else:
            result = {"infected": {}, "ok": True, "errors": [], "engine": "linkguard"}
            found = []
        found = guarded + found
        bad = [e for e in found if e["result"] != "clean"]
        entries += bad
        record_history("usb", [mount], len(files), result, home)
        if result.get("ok") and not result["infected"] and not guarded and cfg.get("notify_safe_downloads"):
            common.notify("USB drive checked", "No threats found on %s (%d files)."
                          % (os.path.basename(mount), len(files)))
    common.write_json(state_path, current, 0o600)
    if entries:
        append_log(downloads_log_path(home), entries)
    return entries


def watch_setup(home=None, reload=True):
    """Sign-in: point devos-av-watch.path at this user's real folders."""
    home = home or os.path.expanduser("~")
    dirs = watch_dirs(home, existing_only=False)
    dirs = [d for d in dirs if os.path.isdir(d) or d in (os.path.join(home, "Downloads"),
                                                         os.path.join(home, "Desktop"))]
    path = os.path.join(home, ".config", "systemd", "user", "devos-av-watch.path.d", "50-folders.conf")
    text = path_unit_dropin(dirs)
    if common.read_text(path) == text:
        return False
    common.write_text(path, text, 0o644)
    if reload and common.which("systemctl"):
        common.run(["systemctl", "--user", "daemon-reload"], timeout=30)
        common.run(["systemctl", "--user", "restart", "devos-av-watch.path"], timeout=30)
    return True


# ---------------------------------------------------------------- scans

def quick_targets(home):
    user = os.path.basename(home)
    targets = watch_dirs(home)
    for extra in (os.path.join(home, ".config", "autostart"), os.path.join(home, ".local", "bin"),
                  os.path.join(home, ".local", "share", "applications"), os.path.join("/media", user)):
        if os.path.isdir(extra):
            targets.append(extra)
    return targets


def record_history(kind, targets, count, result, home=None, seconds=0.0):
    append_log(history_path(home), [{
        "time": int(now()), "kind": kind, "targets": targets[:5], "files": count,
        "threats": len(result.get("infected", {})), "engine": result.get("engine") or "",
        "ok": bool(result.get("ok")), "seconds": round(seconds, 1),
        "errors": result.get("errors", [])[:3],
    }], limit=100)


def run_scan(kind, path=None, home=None, engine=None, runner=None):
    """quick | full | path. Folders are scanned recursively, archives inside."""
    home = home or os.path.expanduser("~")
    if kind == "quick":
        targets = quick_targets(home)
    elif kind == "full":
        targets = [home] + ([os.path.join("/media", os.path.basename(home))]
                            if os.path.isdir(os.path.join("/media", os.path.basename(home))) else [])
    else:
        targets = [os.path.abspath(os.path.expanduser(path or "."))]
    started = now()
    if engine is None:
        engine = choose_engine(common.read_meminfo().get("total", 0))
    result = scan_paths(targets, engine=engine, runner=runner, recursive=True)
    moved = []
    for found_path, threat in result["infected"].items():
        real = found_path.split("!")[0]
        if os.path.isfile(real) and not is_quarantine_path(real, home):
            try:
                quarantine_file(real, threat, "scan:" + kind, home)
                moved.append({"path": real, "threat": threat})
                notify_threat(os.path.basename(real), threat, os.path.dirname(real))
            except OSError as exc:
                moved.append({"path": real, "threat": threat, "error": str(exc)})
    record_history(kind, targets, len(targets), result, home, now() - started)
    return {"kind": kind, "targets": targets, "engine": result["engine"], "ok": result["ok"],
            "threats": moved, "errors": result["errors"], "seconds": round(now() - started, 1)}


# ---------------------------------------------------------------- launch check

def cache_path(home=None):
    return os.path.join(common.user_state_dir(home), "launch-cache.json")


def scan_for_launch(path, home=None, engine=None, runner=None, quarantine=True):
    """Called before a Windows/Android app runs. Never raises.
    {"av_scanned": bool, "infected": bool, "threat", "engine", "error"}."""
    out = {"av_scanned": False, "infected": False, "threat": None, "engine": None, "error": None}
    try:
        sha = sha256_file(path)
    except OSError as exc:
        out["error"] = str(exc)
        return out
    if sha in allowed_hashes(home):
        out.update(av_scanned=True, engine="allowlist")
        return out
    version = db_version()
    cache = common.read_json(cache_path(home), {}) or {}
    hit = cache.get(sha)
    if hit and version and hit.get("db") == version and hit.get("result") == "clean":
        out.update(av_scanned=True, engine=hit.get("engine", "cache"))
        return out
    result = scan_paths([path], engine=engine, runner=runner)
    out["engine"] = result["engine"]
    threat = result["infected"].get(path) or next(iter(result["infected"].values()), None)
    if threat:
        out.update(av_scanned=True, infected=True, threat=threat)
        if quarantine:
            try:
                quarantine_file(path, threat, "launch", home)
                out["quarantined"] = True
                notify_threat(os.path.basename(path), threat, os.path.dirname(path))
            except OSError as exc:
                out["quarantine_error"] = str(exc)
        return out
    if not result["ok"]:
        out["error"] = "; ".join(result["errors"]) or "scan failed"
        return out
    out["av_scanned"] = True
    cache[sha] = {"result": "clean", "db": version, "engine": result["engine"], "time": int(now())}
    if len(cache) > 500:
        for key in sorted(cache, key=lambda k: cache[k].get("time", 0))[:len(cache) - 500]:
            del cache[key]
    try:
        common.write_json(cache_path(home), cache, 0o600)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- status

def status(home=None, mem_total=None):
    home = home or os.path.expanduser("~")
    mem_total = common.read_meminfo().get("total", 0) if mem_total is None else mem_total
    installed = bool(common.which("clamscan"))
    age = signatures_age_days()
    engine = choose_engine(mem_total) if installed else None
    watching = common.systemctl_state("devos-av-watch.path", user=True)
    if installed:
        updater = ("daemon" if common.systemctl_state("clamav-freshclam.service") == "active" else
                   "scheduled" if common.systemctl_state("devos-freshclam.timer") == "active" else "off")
    else:
        updater = "off"
    return {
        "installed": installed,
        "daemon_installed": bool(common.which("clamdscan")),
        "engine": engine,
        "ram_gb": round(mem_total / common.GB, 1),
        "mode": "clamd" if mem_total >= CLAMD_MIN_RAM else "on-demand",
        "signatures_age_days": None if age is None else round(age, 1),
        "signature_updates": updater,
        "watching": watching,
        "quarantine": len(user_quarantine(home)),
        "recent_downloads": recent_downloads(home, 10),
    }
