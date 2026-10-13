#!/usr/bin/env python3
"""
DevOS Notepad - a tabbed plain-text editor modelled on Windows 11 Notepad.

Every tab (including unsaved "Untitled" text and unsaved edits to opened
files) is continuously persisted to ~/.local/share/devos/notepad so that the
next start restores the exact previous state, even after a crash, kill -9 or
power cut.

The storage layer (atomic writes, session store, encoding / line-ending
handling) is plain Python and importable without a display; PyQt5 is only
imported when the GUI is started.
"""

import datetime
import hashlib
import json
import os
import signal
import sys
import tempfile
import time
import uuid

APP_TITLE = "Notepad"
APP_VERSION = "1.0"
SESSION_VERSION = 1
SESSION_FILE = "session.json"
BACKUP_FILE = "session.json.bak"
SETTINGS_FILE = "settings.json"

STARTUP_CONTINUE = "continue"
STARTUP_NEW = "new"

DEFAULT_SETTINGS = {
    "startup": STARTUP_CONTINUE,
    "word_wrap": True,
    "status_bar": True,
    "zoom": 100,
    "geometry": None,
}

EOL_LF, EOL_CRLF, EOL_CR = "\n", "\r\n", "\r"
EOL_TO_NAME = {EOL_LF: "LF", EOL_CRLF: "CRLF", EOL_CR: "CR"}
NAME_TO_EOL = {v: k for k, v in EOL_TO_NAME.items()}
EOL_LABELS = {EOL_LF: "Unix (LF)", EOL_CRLF: "Windows (CRLF)", EOL_CR: "Macintosh (CR)"}

ENC_UTF8 = "utf-8"
ENC_UTF8_BOM = "utf-8-sig"
ENC_UTF16LE = "utf-16-le"
ENC_UTF16BE = "utf-16-be"
ENC_LATIN1 = "latin-1"
ENCODING_LABELS = {
    ENC_UTF8: "UTF-8",
    ENC_UTF8_BOM: "UTF-8 with BOM",
    ENC_UTF16LE: "UTF-16 LE",
    ENC_UTF16BE: "UTF-16 BE",
    ENC_LATIN1: "Latin-1",
}
_BOMS = (
    (b"\xef\xbb\xbf", ENC_UTF8_BOM),
    (b"\xff\xfe", ENC_UTF16LE),
    (b"\xfe\xff", ENC_UTF16BE),
)

_UMASK = os.umask(0)
os.umask(_UMASK)


# --------------------------------------------------------------------------
# Atomic file writing
# --------------------------------------------------------------------------

def fsync_dir(directory):
    """Flush a directory entry to disk so a rename survives a power cut."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError:
        return  # not supported on this platform (e.g. Windows)
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path, data, mode=None):
    """Write `data` to `path` so that readers only ever see the old or the new
    content: temp file in the same directory -> fsync -> os.replace -> fsync dir.
    """
    path = os.path.abspath(path)
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    if mode is None:
        try:
            mode = os.stat(path).st_mode & 0o7777
        except FileNotFoundError:
            mode = 0o666 & ~_UMASK
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                               suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(directory)


def atomic_write_text(path, text, mode=None):
    atomic_write_bytes(path, text.encode("utf-8", "surrogatepass"), mode)


# --------------------------------------------------------------------------
# Encoding and line endings
# --------------------------------------------------------------------------

class FileFormat:
    """How a file was stored on disk, so it can be written back the same way."""

    def __init__(self, encoding=ENC_UTF8, eol=EOL_LF, fallback=False):
        self.encoding = encoding
        self.eol = eol
        self.fallback = fallback  # True when the file was not valid Unicode

    def __repr__(self):
        return "FileFormat(%r, %r, fallback=%r)" % (self.encoding, self.eol, self.fallback)


def detect_eol(text):
    crlf = text.count("\r\n")
    cr = text.count("\r") - crlf
    lf = text.count("\n") - crlf
    best = max((crlf, EOL_CRLF), (lf, EOL_LF), (cr, EOL_CR), key=lambda x: x[0])
    return best[1] if best[0] > 0 else EOL_LF


def normalize_eol(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_bytes(data):
    """Return (text with '\\n' line endings, FileFormat)."""
    encoding = None
    payload = data
    for bom, enc in _BOMS:
        if data.startswith(bom):
            encoding, payload = enc, data[len(bom):]
            break
    fallback = False
    if encoding is None:
        encoding = ENC_UTF8
    codec = "utf-8" if encoding in (ENC_UTF8, ENC_UTF8_BOM) else encoding
    try:
        text = payload.decode(codec)
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        encoding, fallback = ENC_LATIN1, True
    eol = detect_eol(text)
    return normalize_eol(text), FileFormat(encoding, eol, fallback)


def encode_text(text, encoding=ENC_UTF8, eol=EOL_LF):
    """Encode editor text ('\\n' line endings) for disk. May raise
    UnicodeEncodeError for Latin-1 files containing other characters."""
    body = normalize_eol(text)
    if eol != EOL_LF:
        body = body.replace("\n", eol)
    if encoding == ENC_UTF8_BOM:
        return b"\xef\xbb\xbf" + body.encode("utf-8")
    if encoding == ENC_UTF16LE:
        return b"\xff\xfe" + body.encode("utf-16-le")
    if encoding == ENC_UTF16BE:
        return b"\xfe\xff" + body.encode("utf-16-be")
    if encoding == ENC_LATIN1:
        return body.encode("latin-1")
    return body.encode("utf-8")


def read_text_file(path):
    """Return (text, FileFormat, mtime_ns, size)."""
    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        data = fh.read()
    text, fmt = decode_bytes(data)
    return text, fmt, st.st_mtime_ns, st.st_size


def write_text_file(path, text, encoding=ENC_UTF8, eol=EOL_LF):
    """Atomically save a document. Returns (mtime_ns, size) of the new file."""
    data = encode_text(text, encoding, eol)
    real = os.path.realpath(path)  # keep symlinks intact
    atomic_write_bytes(real, data)
    st = os.stat(real)
    return st.st_mtime_ns, st.st_size


# --------------------------------------------------------------------------
# Session model
# --------------------------------------------------------------------------

class TabState:
    """Serializable state of one tab."""

    def __init__(self, id=None, title="Untitled", path=None, dirty=False,
                 content="", cursor=0, anchor=None, scroll=0, wrap=True,
                 encoding=ENC_UTF8, eol=EOL_LF, disk_mtime=None, disk_size=None,
                 fallback=False, generation=None):
        self.id = id or uuid.uuid4().hex
        self.title = title
        self.path = path
        self.dirty = bool(dirty)
        self.content = content  # str, or a zero-arg callable returning str
        self.cursor = int(cursor or 0)
        self.anchor = self.cursor if anchor is None else int(anchor)
        self.scroll = int(scroll or 0)
        self.wrap = bool(wrap)
        self.encoding = encoding
        self.eol = eol
        self.disk_mtime = disk_mtime
        self.disk_size = disk_size
        self.fallback = bool(fallback)
        self.generation = generation  # edit counter supplied by the GUI
        self.disk_status = None  # transient: None / "changed" / "missing" / "unreadable"

    def get_content(self):
        c = self.content
        if callable(c):
            c = c()
        return c or ""

    @property
    def needs_content(self):
        """Unsaved text is stored for untitled tabs and tabs with edits."""
        return self.dirty or not self.path

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "path": self.path,
            "dirty": self.dirty,
            "has_content": self.needs_content,
            "cursor": self.cursor,
            "anchor": self.anchor,
            "scroll": self.scroll,
            "wrap": self.wrap,
            "encoding": self.encoding,
            "eol": EOL_TO_NAME.get(self.eol, "LF"),
            "disk_mtime": self.disk_mtime,
            "disk_size": self.disk_size,
            "fallback": self.fallback,
        }

    @classmethod
    def from_dict(cls, d):
        tid = str(d["id"])
        if not tid or any(ch in tid for ch in "/\\.") or len(tid) > 64:
            raise ValueError("bad tab id")
        enc = d.get("encoding") or ENC_UTF8
        if enc not in ENCODING_LABELS:
            enc = ENC_UTF8
        return cls(id=tid, title=d.get("title") or "Untitled", path=d.get("path"),
                   dirty=d.get("dirty", False), content=None,
                   cursor=d.get("cursor", 0), anchor=d.get("anchor"),
                   scroll=d.get("scroll", 0), wrap=d.get("wrap", True),
                   encoding=enc, eol=NAME_TO_EOL.get(d.get("eol"), EOL_LF),
                   disk_mtime=d.get("disk_mtime"), disk_size=d.get("disk_size"),
                   fallback=d.get("fallback", False))


class SessionData:
    def __init__(self, tabs, active, source):
        self.tabs = tabs
        self.active = active
        self.source = source  # "main" or "backup"


def data_dir():
    return os.path.join(os.path.expanduser("~"), ".local", "share", "devos", "notepad")


class SessionStore:
    """Crash-safe persistence of open tabs.

    Layout of the store directory:
      session.json      - tab list and metadata (current generation)
      session.json.bak  - previous valid generation (fallback)
      tab-<id>.txt      - unsaved text of a tab (UTF-8, '\\n' line endings)
      settings.json     - user preferences
    """

    def __init__(self, base_dir=None):
        self.base_dir = base_dir or data_dir()
        self._written = {}  # tab id -> (generation, sha1) of the stored content
        self._last_session_bytes = None
        self.last_written_ids = []

    # paths ---------------------------------------------------------------
    @property
    def session_path(self):
        return os.path.join(self.base_dir, SESSION_FILE)

    @property
    def backup_path(self):
        return os.path.join(self.base_dir, BACKUP_FILE)

    @property
    def settings_path(self):
        return os.path.join(self.base_dir, SETTINGS_FILE)

    def content_path(self, tab_id):
        return os.path.join(self.base_dir, "tab-%s.txt" % tab_id)

    # settings ------------------------------------------------------------
    def load_settings(self):
        settings = dict(DEFAULT_SETTINGS)
        try:
            with open(self.settings_path, "rb") as fh:
                data = json.loads(fh.read().decode("utf-8"))
            if isinstance(data, dict):
                settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass
        if settings.get("startup") not in (STARTUP_CONTINUE, STARTUP_NEW):
            settings["startup"] = STARTUP_CONTINUE
        return settings

    def save_settings(self, settings):
        data = {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
        atomic_write_bytes(self.settings_path,
                           json.dumps(data, indent=1, sort_keys=True).encode("utf-8"), 0o600)

    # loading -------------------------------------------------------------
    @staticmethod
    def _parse_session(raw):
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("tabs"), list):
            raise ValueError("invalid session file")
        return data

    @staticmethod
    def _digest(text):
        return hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()

    def _remove_stale_temp_files(self):
        try:
            names = os.listdir(self.base_dir)
        except OSError:
            return
        for name in names:
            if name.startswith(".") and name.endswith(".tmp"):
                try:
                    os.unlink(os.path.join(self.base_dir, name))
                except OSError:
                    pass

    def load(self):
        """Load the stored session (falls back to session.json.bak if the main
        file is unreadable). Returns SessionData or None."""
        self._remove_stale_temp_files()
        for source, path in (("main", self.session_path), ("backup", self.backup_path)):
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                data = self._parse_session(raw)
            except (OSError, ValueError):
                continue
            tabs = []
            seen = set()
            for d in data["tabs"]:
                try:
                    tab = TabState.from_dict(d)
                except (KeyError, TypeError, ValueError):
                    continue
                if tab.id in seen:
                    continue
                seen.add(tab.id)
                if d.get("has_content"):
                    try:
                        with open(self.content_path(tab.id), "rb") as fh:
                            tab.content = fh.read().decode("utf-8", "surrogatepass")
                        self._written[tab.id] = (None, self._digest(tab.content))
                    except (OSError, UnicodeDecodeError):
                        tab.content = ""
                tabs.append(tab)
            if source == "main":
                self._last_session_bytes = raw
            active = data.get("active")
            if active not in seen:
                active = tabs[0].id if tabs else None
            return SessionData(tabs, active, source)
        return None

    @staticmethod
    def check_disk(tab):
        """Compare a file tab with what is on disk now.
        Returns None (unchanged / not a file), "changed" or "missing"."""
        if not tab.path:
            return None
        try:
            st = os.stat(tab.path)
        except FileNotFoundError:
            return "missing" if tab.disk_mtime is not None else None
        except OSError:
            return None
        if tab.disk_mtime is None:
            return "changed"  # file appeared while we were away
        if st.st_mtime_ns != tab.disk_mtime or st.st_size != tab.disk_size:
            return "changed"
        return None

    def restore(self, settings=None):
        """Tabs to open at startup: (list of TabState, active id).
        Clean file tabs are re-read from disk; dirty ones get disk_status."""
        settings = settings if settings is not None else self.load_settings()
        if settings.get("startup") == STARTUP_NEW:
            return [], None
        session = self.load()
        if session is None:
            return [], None
        for tab in session.tabs:
            if tab.path and not tab.dirty:
                try:
                    text, fmt, mtime, size = read_text_file(tab.path)
                    tab.content = text
                    tab.encoding, tab.eol, tab.fallback = fmt.encoding, fmt.eol, fmt.fallback
                    tab.disk_mtime, tab.disk_size = mtime, size
                except FileNotFoundError:
                    tab.content, tab.disk_status = "", "missing"
                except OSError:
                    tab.content, tab.disk_status = "", "unreadable"
            elif tab.path:
                tab.disk_status = self.check_disk(tab)
            if tab.content is None:
                tab.content = ""
        return session.tabs, session.active

    # saving --------------------------------------------------------------
    def _rotate_backup(self):
        """Copy the current session.json to .bak, but only if it is valid."""
        try:
            with open(self.session_path, "rb") as fh:
                raw = fh.read()
            self._parse_session(raw)
        except (OSError, ValueError):
            return
        atomic_write_bytes(self.backup_path, raw, 0o600)

    def _referenced_ids(self, path):
        try:
            with open(path, "rb") as fh:
                data = self._parse_session(fh.read())
            return {str(t.get("id")) for t in data["tabs"]
                    if isinstance(t, dict) and t.get("has_content")}
        except (OSError, ValueError):
            return set()

    def _cleanup(self, keep):
        keep = set(keep) | self._referenced_ids(self.backup_path)
        try:
            names = os.listdir(self.base_dir)
        except OSError:
            return
        for name in names:
            if name.startswith("tab-") and name.endswith(".txt"):
                tid = name[4:-4]
                if tid not in keep:
                    try:
                        os.unlink(os.path.join(self.base_dir, name))
                    except OSError:
                        pass
                    self._written.pop(tid, None)

    def save(self, tabs, active_id=None):
        """Persist tabs. Only tabs whose content changed are rewritten.
        Returns the list of tab ids whose content file was written."""
        os.makedirs(self.base_dir, exist_ok=True)
        written = []
        entries = []
        for tab in tabs:
            entry = tab.to_dict()
            if tab.needs_content:
                cpath = self.content_path(tab.id)
                prev = self._written.get(tab.id)
                exists = prev is not None and os.path.exists(cpath)
                if not (exists and tab.generation is not None and prev[0] == tab.generation):
                    text = tab.get_content()
                    digest = self._digest(text)
                    if not (exists and prev[1] == digest):
                        atomic_write_bytes(cpath, text.encode("utf-8", "surrogatepass"), 0o600)
                        written.append(tab.id)
                    self._written[tab.id] = (tab.generation, digest)
            entries.append(entry)
        session = {"version": SESSION_VERSION, "active": active_id, "tabs": entries}
        raw = json.dumps(session, indent=1, sort_keys=True).encode("utf-8")
        if raw != self._last_session_bytes:
            self._rotate_backup()
            atomic_write_bytes(self.session_path, raw, 0o600)
            self._last_session_bytes = raw
            self._cleanup(e["id"] for e in entries if e["has_content"])
        self.last_written_ids = written
        return written


# --------------------------------------------------------------------------
# Helpers shared by the GUI
# --------------------------------------------------------------------------

def socket_path():
    runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return os.path.join(runtime, "devos-notepad-%d.sock" % uid)


def format_time_date(now=None):
    """Windows Notepad F5 format: 'h:mm AM M/D/YYYY'."""
    now = now or datetime.datetime.now()
    hour = now.hour % 12 or 12
    return "%d:%02d %s %d/%d/%d" % (hour, now.minute, "AM" if now.hour < 12 else "PM",
                                    now.month, now.day, now.year)


def same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


# --------------------------------------------------------------------------
# GUI (PyQt5 is imported lazily)
# --------------------------------------------------------------------------

C_WINDOW = "#0b0f19"
C_EDITOR = "#0f1525"
C_TEXT = "#e5e7eb"
C_MUTED = "#94a3b8"
C_SELECT = "#1d4ed8"
C_PANEL = "#111827"
C_BORDER = "#1f2937"
C_ACCENT = "#38bdf8"

STYLESHEET = """
QMainWindow, QWidget#central { background: %(win)s; }
QPlainTextEdit#editor {
    background: %(editor)s; color: %(text)s; border: none;
    selection-background-color: %(sel)s; selection-color: #ffffff;
}
QMenuBar { background: %(win)s; color: %(muted)s; padding: 4px 6px 0 6px; }
QMenuBar::item { background: transparent; padding: 6px 12px; border-radius: 6px; }
QMenuBar::item:selected { background: #1e293b; color: %(text)s; }
QMenuBar::item:pressed { background: #1e293b; color: %(text)s; }
QMenu { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s;
        border-radius: 10px; padding: 6px; }
QMenu { min-width: 250px; }
QMenu::item { padding: 7px 18px 7px 30px; border-radius: 6px; background: transparent; }
QMenu::item:selected { background: #1e293b; }
QMenu::item:disabled { color: #475569; }
QMenu::separator { height: 1px; background: %(border)s; margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 8px; }
QMenu::indicator:checked { image: url(%(check)s); }
QTabBar { background: %(win)s; }
QTabBar::tab {
    background: transparent; color: %(muted)s;
    padding: 7px 6px 7px 14px; margin: 6px 2px 0 0;
    border-top: 2px solid transparent;
    border-top-left-radius: 8px; border-top-right-radius: 8px;
    min-width: 110px; max-width: 230px;
}
QTabBar::tab:selected { background: %(panel)s; color: %(text)s; border-top: 2px solid %(accent)s; }
QTabBar::tab:hover:!selected { background: #0f1626; color: %(text)s; }
QTabBar::scroller { width: 26px; }
QTabBar QToolButton { background: %(win)s; color: %(muted)s; border: none; }
QToolButton#tabClose {
    background: transparent; color: %(muted)s; border: none; border-radius: 5px;
    font-size: 13pt; padding: 0; min-width: 22px; max-width: 22px; min-height: 22px; max-height: 22px;
}
QToolButton#tabClose:hover { background: #1e293b; color: %(text)s; }
QToolButton#newTab {
    background: transparent; color: %(muted)s; border: none; border-radius: 6px;
    font-size: 15pt; min-width: 30px; min-height: 30px; margin-top: 6px;
}
QToolButton#gear {
    background: transparent; color: %(muted)s; border: none; border-radius: 6px;
    padding: 6px 12px; margin: 0 6px 0 0;
}
QToolButton#newTab:hover, QToolButton#gear:hover { background: #1e293b; color: %(text)s; }
QWidget#tabStrip { background: %(win)s; }
QFrame#editorTop { background: %(panel)s; min-height: 0; max-height: 1px; border: none; }
QFrame#infoBar { background: #0c1a33; border: none; border-bottom: 1px solid #1e3a5f; }
QFrame#infoBar QLabel { color: %(text)s; }
QLabel#infoIcon { color: %(accent)s; font-weight: bold; }
QFrame#findBar { background: %(panel)s; border: none; border-bottom: 1px solid %(border)s; }
QLabel#findStatus { color: %(muted)s; }
QLineEdit {
    background: %(win)s; color: %(text)s; border: 1px solid %(border)s; border-radius: 6px;
    padding: 5px 8px; selection-background-color: %(sel)s;
}
QLineEdit:focus { border: 1px solid %(accent)s; }
QPushButton {
    background: #1f2937; color: %(text)s; border: none; border-radius: 6px; padding: 6px 14px;
}
QPushButton:hover { background: #273449; }
QPushButton:pressed { background: #334155; }
QPushButton#primary, QPushButton:default { background: #2563eb; color: #ffffff; }
QPushButton#primary:hover, QPushButton:default:hover { background: #3b82f6; }
QToolButton#findBtn {
    background: transparent; color: %(muted)s; border: none; border-radius: 6px;
    min-width: 28px; min-height: 28px; font-size: 11pt;
}
QToolButton#findBtn:hover { background: #1e293b; color: %(text)s; }
QToolButton#findBtn:checked { background: #1e293b; color: %(accent)s; }
QStatusBar { background: %(win)s; color: %(muted)s; border-top: 1px solid %(panel)s; }
QStatusBar::item { border: none; }
QStatusBar QLabel { color: %(muted)s; padding: 3px 14px; border-left: 1px solid %(border)s; }
QStatusBar QLabel#first { border-left: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle { background: #283548; border-radius: 4px; }
QScrollBar::handle:vertical { min-height: 32px; }
QScrollBar::handle:horizontal { min-width: 32px; }
QScrollBar::handle:hover { background: #3b4a63; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QAbstractScrollArea::corner { background: %(editor)s; }
QDialog, QMessageBox, QInputDialog { background: %(panel)s; }
QDialog QLabel, QMessageBox QLabel { color: %(text)s; }
QLabel#dialogTitle { font-size: 14pt; font-weight: 600; color: %(text)s; }
QLabel#dialogHint { color: %(muted)s; }
QFrame#card { background: %(win)s; border: 1px solid %(border)s; border-radius: 10px; }
QRadioButton, QCheckBox { color: %(text)s; spacing: 8px; }
QSpinBox { background: %(win)s; color: %(text)s; border: 1px solid %(border)s;
           border-radius: 6px; padding: 4px 8px; }
QToolTip { background: %(panel)s; color: %(text)s; border: 1px solid %(border)s; padding: 4px 8px; }
"""

_GUI = None


def _load_gui():
    """Import PyQt5 and build the GUI classes (only when a display is used)."""
    global _GUI
    if _GUI is not None:
        return _GUI

    from PyQt5.QtCore import Qt, QTimer, QEvent, QByteArray, QPointF
    from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QIcon, QKeySequence,
                             QPainter, QPalette, QPen, QPixmap, QTextCursor,
                             QTextDocument, QTextOption)
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    from PyQt5.QtWidgets import (QAction, QApplication, QButtonGroup, QCheckBox,
                                 QDialog, QFileDialog, QFrame, QGridLayout,
                                 QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                                 QMainWindow, QMessageBox, QPlainTextEdit,
                                 QPushButton, QRadioButton, QStackedWidget,
                                 QTabBar, QToolButton, QVBoxLayout, QWidget)

    def pick_family(candidates, fallback):
        families = set(QFontDatabase().families())
        for fam in candidates:
            if fam in families:
                return fam
        return fallback

    def make_check_icon():
        cache = os.path.join(os.path.expanduser("~"), ".cache", "devos", "notepad")
        path = os.path.join(cache, "check.png")
        if not os.path.exists(path):
            try:
                os.makedirs(cache, exist_ok=True)
                pm = QPixmap(28, 28)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                pen = QPen(QColor(C_ACCENT), 3.2)
                pen.setCapStyle(Qt.RoundCap)
                pen.setJoinStyle(Qt.RoundJoin)
                p.setPen(pen)
                p.drawPolyline(*[QPointF(x, y)
                                 for x, y in ((6, 15), (11.5, 20.5), (22, 8))])
                p.end()
                pm.save(path, "PNG")
            except Exception:
                return ""
        return path.replace("\\", "/")

    class Editor(QPlainTextEdit):
        def __init__(self, win, state):
            super().__init__()
            self.win = win
            self.setObjectName("editor")
            self.setFrameShape(QFrame.NoFrame)
            self.setCursorWidth(2)
            self.document().setDocumentMargin(14)
            self.tab_id = state.id
            self.path = state.path
            self.encoding = state.encoding
            self.eol = state.eol
            self.fallback = state.fallback
            self.disk_mtime = state.disk_mtime
            self.disk_size = state.disk_size
            self.info = None  # (kind, message) shown in the info bar
            self.generation = 0
            self.pending_scroll = None
            self.setPlainText(state.get_content())
            self.document().setModified(bool(state.dirty or (not state.path and state.get_content())))
            n = self.document().characterCount() - 1
            cur = QTextCursor(self.document())
            cur.setPosition(max(0, min(state.anchor, n)))
            cur.setPosition(max(0, min(state.cursor, n)), QTextCursor.KeepAnchor)
            self.setTextCursor(cur)
            self.pending_scroll = state.scroll
            self.set_wrap(state.wrap)
            self.document().contentsChange.connect(self._on_change)

        def _on_change(self, *_):
            self.generation += 1
            self.win.on_text_changed(self)

        def text(self):
            # toRawText keeps non-breaking spaces (toPlainText converts them)
            return self.document().toRawText().replace(" ", "\n").replace(" ", "\n")

        def set_wrap(self, on):
            self.setLineWrapMode(QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)
            self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)

        def wraps(self):
            return self.lineWrapMode() != QPlainTextEdit.NoWrap

        def scroll_value(self):
            if self.pending_scroll is not None:
                return self.pending_scroll
            return self.verticalScrollBar().value()

        def showEvent(self, e):
            super().showEvent(e)
            if self.pending_scroll is not None:
                QTimer.singleShot(0, self._apply_scroll)

        def _apply_scroll(self):
            if self.pending_scroll is not None:
                self.verticalScrollBar().setValue(self.pending_scroll)
                self.pending_scroll = None

        def keyPressEvent(self, e):
            if e.key() in (Qt.Key_Tab, Qt.Key_Backtab) and e.modifiers() & Qt.ControlModifier:
                back = e.key() == Qt.Key_Backtab or bool(e.modifiers() & Qt.ShiftModifier)
                self.win.cycle_tab(-1 if back else 1)
                return
            super().keyPressEvent(e)

        def wheelEvent(self, e):
            if e.modifiers() & Qt.ControlModifier:
                self.win.zoom_step(1 if e.angleDelta().y() > 0 else -1)
                e.accept()
                return
            super().wheelEvent(e)

        def canInsertFromMimeData(self, source):
            return source.hasUrls() or super().canInsertFromMimeData(source)

        def insertFromMimeData(self, source):
            if source.hasUrls():
                files = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
                if files:
                    self.win.open_files(files)
                    return
            super().insertFromMimeData(source)

    class InfoBar(QFrame):
        def __init__(self, win):
            super().__init__()
            self.win = win
            self.setObjectName("infoBar")
            lay = QHBoxLayout(self)
            lay.setContentsMargins(16, 8, 10, 8)
            lay.setSpacing(10)
            icon = QLabel("i")
            icon.setObjectName("infoIcon")
            self.label = QLabel()
            self.label.setWordWrap(True)
            self.btn_reload = QPushButton("Reload")
            self.btn_reload.setObjectName("primary")
            self.btn_keep = QPushButton("Keep my version")
            self.btn_dismiss = QPushButton("Dismiss")
            for b in (self.btn_reload, self.btn_keep, self.btn_dismiss):
                b.setCursor(Qt.PointingHandCursor)
                b.setFocusPolicy(Qt.NoFocus)
            lay.addWidget(icon)
            lay.addWidget(self.label, 1)
            lay.addWidget(self.btn_reload)
            lay.addWidget(self.btn_keep)
            lay.addWidget(self.btn_dismiss)
            self.btn_reload.clicked.connect(lambda: win.resolve_info("reload"))
            self.btn_keep.clicked.connect(lambda: win.resolve_info("keep"))
            self.btn_dismiss.clicked.connect(lambda: win.resolve_info("dismiss"))
            self.hide()

        def show_for(self, editor):
            if editor is None or not editor.info:
                self.hide()
                return
            kind, msg = editor.info
            self.label.setText(msg)
            changed = kind == "changed"
            self.btn_reload.setVisible(changed)
            self.btn_keep.setVisible(changed)
            self.btn_dismiss.setVisible(not changed)
            self.show()

    class FindBar(QFrame):
        def __init__(self, win):
            super().__init__()
            self.win = win
            self.setObjectName("findBar")
            grid = QGridLayout(self)
            grid.setContentsMargins(14, 8, 10, 8)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)

            self.toggle = QToolButton()
            self.toggle.setObjectName("findBtn")
            self.toggle.setText("›")
            self.toggle.setToolTip("Show replace")
            self.toggle.setCheckable(True)
            self.find_edit = QLineEdit()
            self.find_edit.setPlaceholderText("Find")
            self.find_edit.setClearButtonEnabled(True)
            self.status = QLabel("")
            self.status.setObjectName("findStatus")
            self.prev_btn = self._tool("↑", "Previous match (Shift+F3)")
            self.next_btn = self._tool("↓", "Next match (F3)")
            self.case = QCheckBox("Match case")
            self.case.setFocusPolicy(Qt.NoFocus)
            self.close_btn = self._tool("×", "Close (Esc)")
            self.replace_edit = QLineEdit()
            self.replace_edit.setPlaceholderText("Replace")
            self.replace_btn = QPushButton("Replace")
            self.replace_all_btn = QPushButton("Replace all")
            for b in (self.replace_btn, self.replace_all_btn):
                b.setFocusPolicy(Qt.NoFocus)

            grid.addWidget(self.toggle, 0, 0)
            grid.addWidget(self.find_edit, 0, 1)
            grid.addWidget(self.status, 0, 2)
            grid.addWidget(self.prev_btn, 0, 3)
            grid.addWidget(self.next_btn, 0, 4)
            grid.addWidget(self.case, 0, 5)
            grid.addWidget(self.close_btn, 0, 7)
            grid.addWidget(self.replace_edit, 1, 1)
            grid.addWidget(self.replace_btn, 1, 3, 1, 2)
            grid.addWidget(self.replace_all_btn, 1, 5)
            grid.setColumnStretch(1, 0)
            grid.setColumnStretch(6, 1)
            self.find_edit.setMinimumWidth(320)
            self.replace_edit.setMinimumWidth(320)

            self.toggle.toggled.connect(self.set_replace_visible)
            self.find_edit.textEdited.connect(lambda _t: win.find(incremental=True))
            self.find_edit.returnPressed.connect(lambda: win.find())
            self.replace_edit.returnPressed.connect(win.replace_one)
            self.prev_btn.clicked.connect(lambda: win.find(backward=True))
            self.next_btn.clicked.connect(lambda: win.find())
            self.close_btn.clicked.connect(win.hide_find)
            self.replace_btn.clicked.connect(win.replace_one)
            self.replace_all_btn.clicked.connect(win.replace_all)
            self.set_replace_visible(False)
            self.hide()

        def _tool(self, text, tip):
            b = QToolButton()
            b.setObjectName("findBtn")
            b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            return b

        def set_replace_visible(self, on):
            if self.toggle.isChecked() != on:
                self.toggle.setChecked(on)
            self.toggle.setText("⌄" if on else "›")
            for w in (self.replace_edit, self.replace_btn, self.replace_all_btn):
                w.setVisible(on)

        def keyPressEvent(self, e):
            if e.key() == Qt.Key_Escape:
                self.win.hide_find()
                return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ShiftModifier:
                self.win.find(backward=True)
                return
            super().keyPressEvent(e)

    class SettingsDialog(QDialog):
        def __init__(self, win):
            super().__init__(win)
            self.win = win
            self.setWindowTitle("Settings")
            self.setMinimumWidth(460)
            lay = QVBoxLayout(self)
            lay.setContentsMargins(24, 22, 24, 20)
            lay.setSpacing(12)
            title = QLabel("Settings")
            title.setObjectName("dialogTitle")
            lay.addWidget(title)
            card = QFrame()
            card.setObjectName("card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(16, 14, 16, 14)
            cl.setSpacing(8)
            head = QLabel("When Notepad starts")
            head.setStyleSheet("font-weight: 600;")
            cl.addWidget(head)
            self.rb_continue = QRadioButton("Continue previous session")
            self.rb_new = QRadioButton("Start a new session and discard unsaved changes")
            group = QButtonGroup(self)
            group.addButton(self.rb_continue)
            group.addButton(self.rb_new)
            cl.addWidget(self.rb_continue)
            cl.addWidget(self.rb_new)
            if win.settings.get("startup") == STARTUP_NEW:
                self.rb_new.setChecked(True)
            else:
                self.rb_continue.setChecked(True)
            hint = QLabel("With “Continue previous session”, Notepad keeps every tab "
                          "and unsaved change, even if it closes unexpectedly.")
            hint.setObjectName("dialogHint")
            hint.setWordWrap(True)
            cl.addWidget(hint)
            lay.addWidget(card)
            about = QLabel("DevOS Notepad %s" % APP_VERSION)
            about.setObjectName("dialogHint")
            row = QHBoxLayout()
            row.addWidget(about)
            row.addStretch(1)
            ok = QPushButton("Done")
            ok.setDefault(True)
            ok.clicked.connect(self.accept)
            row.addWidget(ok)
            lay.addLayout(row)
            self.rb_continue.toggled.connect(self._changed)

        def _changed(self, _on):
            self.win.settings["startup"] = STARTUP_CONTINUE if self.rb_continue.isChecked() else STARTUP_NEW
            self.win.save_settings()

    class NotepadWindow(QMainWindow):
        def __init__(self, store, settings):
            super().__init__()
            self.store = store
            self.settings = settings
            self.editors = {}  # tab id -> Editor
            self._closing = False
            self._force_quit = False
            self.loading = True  # no session writes until the restore is complete
            self.pending_signal = None
            self.last_save_error = None

            self.editor_family = pick_family(
                ["JetBrains Mono", "Noto Sans Mono", "DejaVu Sans Mono", "Liberation Mono"], "monospace")

            self.setWindowIcon(QIcon.fromTheme("accessories-text-editor"))
            self.resize(1100, 720)
            self._build_ui()
            self._build_menus()
            self._build_statusbar()

            self.debounce = QTimer(self)
            self.debounce.setSingleShot(True)
            self.debounce.setInterval(1000)
            self.debounce.timeout.connect(self.autosave)
            self.maxwait = QTimer(self)
            self.maxwait.setSingleShot(True)
            self.maxwait.setInterval(3000)
            self.maxwait.timeout.connect(self.autosave)
            self.signal_timer = QTimer(self)
            self.signal_timer.setInterval(200)
            self.signal_timer.timeout.connect(self._poll_signal)
            self.signal_timer.start()

            QApplication.instance().applicationStateChanged.connect(self._app_state_changed)
            geo = self.settings.get("geometry")
            if geo:
                try:
                    self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
                except Exception:
                    pass

        # ---------------------------------------------------------- layout
        def _build_ui(self):
            central = QWidget()
            central.setObjectName("central")
            v = QVBoxLayout(central)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(0)

            strip = QWidget()
            strip.setObjectName("tabStrip")
            h = QHBoxLayout(strip)
            h.setContentsMargins(8, 0, 8, 0)
            h.setSpacing(4)
            self.tabbar = QTabBar()
            self.tabbar.setMovable(True)
            self.tabbar.setExpanding(False)
            self.tabbar.setDrawBase(False)
            self.tabbar.setDocumentMode(True)
            self.tabbar.setElideMode(Qt.ElideRight)
            self.tabbar.setUsesScrollButtons(True)
            self.tabbar.setFocusPolicy(Qt.NoFocus)
            self.tabbar.currentChanged.connect(self._current_changed)
            self.tabbar.tabMoved.connect(lambda *_: self.schedule_autosave())
            self.tabbar.installEventFilter(self)
            self.new_btn = QToolButton()
            self.new_btn.setObjectName("newTab")
            self.new_btn.setText("+")
            self.new_btn.setToolTip("New tab (Ctrl+T)")
            self.new_btn.setCursor(Qt.PointingHandCursor)
            self.new_btn.setFocusPolicy(Qt.NoFocus)
            self.new_btn.clicked.connect(lambda: self.new_tab())
            h.addWidget(self.tabbar, 0, Qt.AlignBottom)
            h.addWidget(self.new_btn, 0, Qt.AlignVCenter)
            h.addStretch(1)
            v.addWidget(strip)

            top = QFrame()
            top.setObjectName("editorTop")
            top.setFixedHeight(1)
            v.addWidget(top)
            self.infobar = InfoBar(self)
            v.addWidget(self.infobar)
            self.findbar = FindBar(self)
            v.addWidget(self.findbar)
            self.stack = QStackedWidget()
            v.addWidget(self.stack, 1)
            self.setCentralWidget(central)

        def _act(self, menu, text, slot, shortcut=None, checkable=False):
            a = QAction(text, self)
            if shortcut:
                if isinstance(shortcut, (list, tuple)):
                    a.setShortcuts([QKeySequence(s) for s in shortcut])
                else:
                    a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _c=False: slot())
            menu.addAction(a)
            return a

        def _build_menus(self):
            mb = self.menuBar()
            m = mb.addMenu("File")
            self._act(m, "New tab", self.new_tab, "Ctrl+T")
            self._act(m, "Open…", self.open_dialog, "Ctrl+O")
            m.addSeparator()
            self._act(m, "Save", lambda: self.save_editor(self.current_editor()), "Ctrl+S")
            self._act(m, "Save as…", lambda: self.save_editor(self.current_editor(), True), "Ctrl+Shift+S")
            self._act(m, "Save all", self.save_all, "Ctrl+Alt+S")
            m.addSeparator()
            self._act(m, "Print…", self.print_current, "Ctrl+P")
            m.addSeparator()
            self._act(m, "Close tab", lambda: self.close_tab(self.tabbar.currentIndex()), ["Ctrl+W", "Ctrl+F4"])
            self._act(m, "Exit", self.close)

            m = mb.addMenu("Edit")
            self.act_undo = self._act(m, "Undo", lambda: self._ed("undo"), "Ctrl+Z")
            self.act_redo = self._act(m, "Redo", lambda: self._ed("redo"), ["Ctrl+Y", "Ctrl+Shift+Z"])
            m.addSeparator()
            self._act(m, "Cut", lambda: self._ed("cut"), "Ctrl+X")
            self._act(m, "Copy", lambda: self._ed("copy"), "Ctrl+C")
            self._act(m, "Paste", lambda: self._ed("paste"), "Ctrl+V")
            self._act(m, "Delete", self._delete_selection, "Del")
            m.addSeparator()
            self._act(m, "Find", self.show_find, "Ctrl+F")
            self._act(m, "Find next", lambda: self.find(), "F3")
            self._act(m, "Find previous", lambda: self.find(backward=True), "Shift+F3")
            self._act(m, "Replace", lambda: self.show_find(replace=True), "Ctrl+H")
            self._act(m, "Go to line", self.go_to_line, "Ctrl+G")
            m.addSeparator()
            self._act(m, "Select all", lambda: self._ed("selectAll"), "Ctrl+A")
            self._act(m, "Time/Date", self.insert_time_date, "F5")

            m = mb.addMenu("View")
            z = m.addMenu("Zoom")
            self._act(z, "Zoom in", lambda: self.zoom_step(1), ["Ctrl+=", "Ctrl++"])
            self._act(z, "Zoom out", lambda: self.zoom_step(-1), "Ctrl+-")
            self._act(z, "Restore default zoom", self.zoom_reset, "Ctrl+0")
            m.addSeparator()
            self.act_status = self._act(m, "Status bar", self.set_status_visible, None, True)
            self.act_wrap = self._act(m, "Word wrap", self.set_word_wrap, None, True)

            nxt = QAction(self)
            nxt.setShortcut(QKeySequence("Ctrl+Tab"))
            nxt.triggered.connect(lambda: self.cycle_tab(1))
            prv = QAction(self)
            prv.setShortcuts([QKeySequence("Ctrl+Shift+Tab"), QKeySequence("Ctrl+Backtab")])
            prv.triggered.connect(lambda: self.cycle_tab(-1))
            self.addAction(nxt)
            self.addAction(prv)

            gear = QToolButton()
            gear.setObjectName("gear")
            gear.setText("Settings")
            gear.setToolTip("Settings")
            gear.setCursor(Qt.PointingHandCursor)
            gear.setFocusPolicy(Qt.NoFocus)
            gear.clicked.connect(self.show_settings)
            mb.setCornerWidget(gear, Qt.TopRightCorner)

        def _build_statusbar(self):
            sb = self.statusBar()
            sb.setSizeGripEnabled(False)
            self.lbl_pos = QLabel("Ln 1, Col 1")
            self.lbl_pos.setObjectName("first")
            self.lbl_chars = QLabel("0 characters")
            self.lbl_zoom = QLabel("100%")
            self.lbl_eol = QLabel(EOL_LABELS[EOL_LF])
            self.lbl_enc = QLabel("UTF-8")
            sb.addWidget(self.lbl_pos)
            sb.addWidget(self.lbl_chars)
            sb.addPermanentWidget(self.lbl_zoom)
            sb.addPermanentWidget(self.lbl_eol)
            sb.addPermanentWidget(self.lbl_enc)
            self.lbl_chars.setMinimumWidth(130)

        # ------------------------------------------------------- settings
        def apply_settings(self):
            self.act_wrap.blockSignals(True)
            self.act_wrap.setChecked(bool(self.settings.get("word_wrap", True)))
            self.act_wrap.blockSignals(False)
            self.act_status.blockSignals(True)
            self.act_status.setChecked(bool(self.settings.get("status_bar", True)))
            self.act_status.blockSignals(False)
            self.statusBar().setVisible(bool(self.settings.get("status_bar", True)))
            self.apply_zoom()

        def save_settings(self):
            try:
                self.store.save_settings(self.settings)
            except OSError as e:
                sys.stderr.write("notepad: cannot save settings: %s\n" % e)

        def show_settings(self):
            SettingsDialog(self).exec_()

        # ----------------------------------------------------------- tabs
        def current_editor(self):
            i = self.tabbar.currentIndex()
            return self.editor_at(i)

        def editor_at(self, index):
            if index < 0:
                return None
            return self.editors.get(self.tabbar.tabData(index))

        def index_of(self, editor):
            for i in range(self.tabbar.count()):
                if self.tabbar.tabData(i) == editor.tab_id:
                    return i
            return -1

        def all_editors(self):
            return [self.editor_at(i) for i in range(self.tabbar.count())]

        def display_name(self, ed):
            return os.path.basename(ed.path) if ed.path else "Untitled"

        def new_tab(self, state=None, activate=True):
            if state is None:
                state = TabState(wrap=bool(self.settings.get("word_wrap", True)))
            ed = Editor(self, state)
            ed.setFont(self.editor_font())
            self._tab_stops(ed)
            self.editors[ed.tab_id] = ed
            self.stack.addWidget(ed)
            ed.document().modificationChanged.connect(lambda _m, e=ed: self.refresh_title(e))
            ed.cursorPositionChanged.connect(lambda e=ed: self._cursor_moved(e))
            ed.verticalScrollBar().valueChanged.connect(lambda _v: self.debounce.start())
            idx = self.tabbar.addTab(self.display_name(ed))
            self.tabbar.setTabData(idx, ed.tab_id)
            close = QToolButton()
            close.setObjectName("tabClose")
            close.setText("×")
            close.setToolTip("Close tab (Ctrl+W)")
            close.setCursor(Qt.PointingHandCursor)
            close.setFocusPolicy(Qt.NoFocus)
            close.clicked.connect(lambda _c=False, e=ed: self.close_tab(self.index_of(e)))
            self.tabbar.setTabButton(idx, QTabBar.RightSide, close)
            self.refresh_title(ed)
            if activate:
                self.tabbar.setCurrentIndex(idx)
                ed.setFocus()
            self.schedule_autosave()
            return ed

        def refresh_title(self, ed):
            i = self.index_of(ed)
            if i < 0:
                return
            name = self.display_name(ed)
            dirty = ed.document().isModified()
            self.tabbar.setTabText(i, name + ("  •" if dirty else ""))
            self.tabbar.setTabToolTip(i, ed.path or name)
            if ed is self.current_editor():
                self.setWindowTitle("%s - %s" % (name, APP_TITLE))

        def _current_changed(self, index):
            ed = self.editor_at(index)
            if ed is None:
                return
            self.stack.setCurrentWidget(ed)
            ed.setFocus()
            self.refresh_title(ed)
            self.infobar.show_for(ed)
            self.update_status()
            if not self._closing:
                self.autosave()  # tab switch

        def cycle_tab(self, step):
            n = self.tabbar.count()
            if n > 1:
                self.tabbar.setCurrentIndex((self.tabbar.currentIndex() + step) % n)

        def eventFilter(self, obj, ev):
            if obj is self.tabbar and ev.type() == QEvent.MouseButtonRelease \
                    and ev.button() == Qt.MiddleButton:
                i = self.tabbar.tabAt(ev.pos())
                if i >= 0:
                    self.close_tab(i)
                    return True
            return super().eventFilter(obj, ev)

        def close_tab(self, index):
            ed = self.editor_at(index)
            if ed is None:
                return
            if self.tabbar.count() == 1:
                # Closing the last tab closes the window; content stays in the session.
                self.close()
                return
            if ed.document().isModified() and (ed.path or ed.text()):
                r = self.ask_save(ed)
                if r == "cancel":
                    return
                if r == "save" and not self.save_editor(ed):
                    return
            self.tabbar.removeTab(self.index_of(ed))
            self.stack.removeWidget(ed)
            del self.editors[ed.tab_id]
            ed.deleteLater()
            self.autosave()

        def ask_save(self, ed):
            box = QMessageBox(self)
            box.setWindowTitle(APP_TITLE)
            box.setIcon(QMessageBox.NoIcon)
            box.setText("Do you want to save changes to %s?" % (ed.path or self.display_name(ed)))
            save = box.addButton("Save", QMessageBox.AcceptRole)
            dont = box.addButton("Don't save", QMessageBox.DestructiveRole)
            cancel = box.addButton("Cancel", QMessageBox.RejectRole)
            save.setObjectName("primary")
            box.setDefaultButton(save)
            box.setEscapeButton(cancel)
            box.exec_()
            clicked = box.clickedButton()
            if clicked is save:
                return "save"
            if clicked is dont:
                return "dont"
            return "cancel"

        # ------------------------------------------------------ open/save
        def open_dialog(self):
            cur = self.current_editor()
            start = os.path.dirname(cur.path) if cur and cur.path else os.path.expanduser("~")
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Open", start, "Text documents (*.txt);;All files (*)", "All files (*)")
            if paths:
                self.open_files(paths)

        def open_files(self, paths):
            last = None
            for p in paths:
                ed = self.open_path(p)
                last = ed or last
            if last is not None:
                self.tabbar.setCurrentIndex(self.index_of(last))
                last.setFocus()

        def find_open(self, path):
            for ed in self.all_editors():
                if ed.path and (ed.path == path or same_file(ed.path, path)):
                    return ed
            return None

        def open_path(self, path):
            path = os.path.abspath(os.path.expanduser(path))
            existing = self.find_open(path)
            if existing is not None:
                self.tabbar.setCurrentIndex(self.index_of(existing))
                return existing
            state = TabState(path=path, wrap=bool(self.settings.get("word_wrap", True)))
            if os.path.exists(path):
                if os.path.isdir(path):
                    return None
                try:
                    text, fmt, mtime, size = read_text_file(path)
                except OSError as e:
                    self.error("Notepad can't open %s.\n\n%s" % (path, e.strerror or e))
                    return None
                state.content = text
                state.encoding, state.eol, state.fallback = fmt.encoding, fmt.eol, fmt.fallback
                state.disk_mtime, state.disk_size = mtime, size
            # Reuse a pristine empty Untitled tab, like Windows Notepad.
            cur = self.current_editor()
            reuse = cur is not None and not cur.path and not cur.document().isModified() \
                and not cur.text() and self.tabbar.count() == 1
            ed = self.new_tab(state)
            if reuse:
                self.tabbar.removeTab(self.index_of(cur))
                self.stack.removeWidget(cur)
                del self.editors[cur.tab_id]
                cur.deleteLater()
            if state.fallback:
                ed.info = ("fallback", "This file isn't valid UTF-8, so it was opened as Latin-1. "
                                       "It will be saved as Latin-1.")
            self.infobar.show_for(self.current_editor())
            return ed

        def save_editor(self, ed, save_as=False):
            if ed is None:
                return False
            path = ed.path
            if save_as or not path:
                start = path or os.path.join(os.path.expanduser("~"), "Untitled.txt")
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save as", start, "Text documents (*.txt);;All files (*)")
                if not path:
                    return False
            text = ed.text()
            enc = ed.encoding
            try:
                encode_text(text, enc, ed.eol)
            except UnicodeEncodeError:
                r = QMessageBox.question(
                    self, APP_TITLE,
                    "This document contains characters that can't be saved as %s.\n"
                    "Save it as UTF-8 instead?" % ENCODING_LABELS.get(enc, enc),
                    QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes)
                if r != QMessageBox.Yes:
                    return False
                enc = ENC_UTF8
            try:
                mtime, size = write_text_file(path, text, enc, ed.eol)
            except OSError as e:
                self.error("Notepad can't save %s.\n\n%s" % (path, e.strerror or e))
                return False
            ed.path = os.path.abspath(path)
            ed.encoding = enc
            ed.fallback = False
            ed.disk_mtime, ed.disk_size = mtime, size
            if ed.info and ed.info[0] in ("changed", "missing", "fallback"):
                ed.info = None
            ed.document().setModified(False)
            self.refresh_title(ed)
            if ed is self.current_editor():
                self.infobar.show_for(ed)
            self.update_status()
            self.autosave()
            return True

        def save_all(self):
            for ed in self.all_editors():
                if ed.document().isModified():
                    self.tabbar.setCurrentIndex(self.index_of(ed))
                    if not self.save_editor(ed):
                        return

        def print_current(self):
            ed = self.current_editor()
            if ed is None:
                return
            try:
                from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
            except ImportError:
                self.error("Printing isn't available on this system.")
                return
            printer = QPrinter(QPrinter.HighResolution)
            dlg = QPrintDialog(printer, self)
            dlg.setWindowTitle("Print")
            if dlg.exec_() == QDialog.Accepted:
                ed.print_(printer)

        def error(self, msg):
            QMessageBox.warning(self, APP_TITLE, msg)

        # ------------------------------------------------- disk changes
        def check_disk_changes(self):
            for ed in self.all_editors():
                if not ed.path or (ed.info and ed.info[0] == "changed"):
                    continue
                probe = TabState(path=ed.path, disk_mtime=ed.disk_mtime, disk_size=ed.disk_size)
                status = SessionStore.check_disk(probe)
                if status == "changed":
                    if not ed.document().isModified():
                        self.reload_editor(ed)
                    else:
                        ed.info = ("changed", "This file was changed by another app.")
                elif status == "missing" and not (ed.info and ed.info[0] == "missing"):
                    ed.info = ("missing", "This file no longer exists. Save to create it again.")
                    ed.disk_mtime = None
            self.infobar.show_for(self.current_editor())

        def reload_editor(self, ed):
            try:
                text, fmt, mtime, size = read_text_file(ed.path)
            except OSError as e:
                self.error("Notepad can't open %s.\n\n%s" % (ed.path, e.strerror or e))
                return
            cur = ed.textCursor().position()
            scroll = ed.verticalScrollBar().value()
            ed.setPlainText(text)
            ed.encoding, ed.eol, ed.fallback = fmt.encoding, fmt.eol, fmt.fallback
            ed.disk_mtime, ed.disk_size = mtime, size
            ed.document().setModified(False)
            c = ed.textCursor()
            c.setPosition(min(cur, ed.document().characterCount() - 1))
            ed.setTextCursor(c)
            ed.verticalScrollBar().setValue(scroll)
            ed.info = None
            self.refresh_title(ed)

        def resolve_info(self, action):
            ed = self.current_editor()
            if ed is None:
                return
            if action == "reload" and ed.path:
                self.reload_editor(ed)
            elif action == "keep" and ed.path:
                try:
                    st = os.stat(ed.path)
                    ed.disk_mtime, ed.disk_size = st.st_mtime_ns, st.st_size
                except OSError:
                    ed.disk_mtime = ed.disk_size = None
                ed.info = None
            else:
                ed.info = None
            self.infobar.show_for(ed)
            self.update_status()
            self.autosave()
            ed.setFocus()

        # --------------------------------------------------------- session
        def collect_states(self):
            states = []
            for ed in self.all_editors():
                c = ed.textCursor()
                states.append(TabState(
                    id=ed.tab_id, title=self.display_name(ed), path=ed.path,
                    dirty=ed.document().isModified(), content=ed.text,
                    cursor=c.position(), anchor=c.anchor(), scroll=ed.scroll_value(),
                    wrap=ed.wraps(), encoding=ed.encoding, eol=ed.eol,
                    disk_mtime=ed.disk_mtime, disk_size=ed.disk_size,
                    fallback=ed.fallback, generation=ed.generation))
            return states

        def save_session(self):
            if self.loading:
                return
            cur = self.current_editor()
            try:
                self.store.save(self.collect_states(), cur.tab_id if cur else None)
                self.last_save_error = None
            except OSError as e:
                if str(e) != self.last_save_error:
                    sys.stderr.write("notepad: autosave failed: %s\n" % e)
                self.last_save_error = str(e)

        def schedule_autosave(self):
            self.debounce.start()
            if not self.maxwait.isActive():
                self.maxwait.start()

        def autosave(self):
            self.debounce.stop()
            self.maxwait.stop()
            self.save_session()

        def on_text_changed(self, ed):
            self.schedule_autosave()
            if ed is self.current_editor():
                self.update_status()

        def _cursor_moved(self, ed):
            if ed is self.current_editor():
                self.update_status()
            self.debounce.start()

        def restore_session(self, states, active):
            for st in states:
                ed = self.new_tab(st, activate=False)
                if st.disk_status == "changed":
                    ed.info = ("changed", "This file was changed by another app.")
                elif st.disk_status == "missing":
                    ed.info = ("missing", "This file no longer exists. Save to create it again.")
                    ed.disk_mtime = None
                elif st.disk_status == "unreadable":
                    ed.info = ("missing", "Notepad couldn't read this file.")
                elif st.fallback:
                    ed.info = ("fallback", "This file isn't valid UTF-8, so it was opened as Latin-1. "
                                           "It will be saved as Latin-1.")
            if active in self.editors:
                self.tabbar.setCurrentIndex(self.index_of(self.editors[active]))
            self.infobar.show_for(self.current_editor())

        def _app_state_changed(self, state):
            if state != Qt.ApplicationActive:
                self.autosave()  # focus loss
            elif not self._closing:
                self.check_disk_changes()

        def _poll_signal(self):
            if self.pending_signal is not None:
                self.pending_signal = None
                self.autosave()
                self._force_quit = True
                self.close()
                QApplication.instance().quit()

        def closeEvent(self, e):
            if self.settings.get("startup") == STARTUP_NEW and not self._force_quit:
                for ed in self.all_editors():
                    if ed.document().isModified() and (ed.path or ed.text()):
                        self.tabbar.setCurrentIndex(self.index_of(ed))
                        r = self.ask_save(ed)
                        if r == "cancel" or (r == "save" and not self.save_editor(ed)):
                            e.ignore()
                            return
            self._closing = True
            self.autosave()
            self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.save_settings()
            e.accept()

        def changeEvent(self, e):
            if e.type() == QEvent.ActivationChange and not self.isActiveWindow() and not self._closing:
                self.autosave()
            super().changeEvent(e)

        # ------------------------------------------------------------ edit
        def _ed(self, method):
            ed = self.current_editor()
            if ed is not None:
                getattr(ed, method)()

        def _delete_selection(self):
            ed = self.current_editor()
            if ed is not None:
                c = ed.textCursor()
                if c.hasSelection():
                    c.removeSelectedText()
                else:
                    c.deleteChar()

        def insert_time_date(self):
            ed = self.current_editor()
            if ed is not None:
                ed.insertPlainText(format_time_date())

        def go_to_line(self):
            ed = self.current_editor()
            if ed is None:
                return
            n = ed.document().blockCount()
            line, ok = QInputDialog.getInt(self, "Go to line", "Line number",
                                           ed.textCursor().blockNumber() + 1, 1, n, 1)
            if ok:
                block = ed.document().findBlockByNumber(line - 1)
                c = ed.textCursor()
                c.setPosition(block.position())
                ed.setTextCursor(c)
                ed.centerCursor()
                ed.setFocus()

        def show_find(self, replace=False):
            ed = self.current_editor()
            fb = self.findbar
            if ed is not None:
                sel = ed.textCursor().selectedText()
                if sel and " " not in sel:
                    fb.find_edit.setText(sel)
            fb.set_replace_visible(replace or fb.toggle.isChecked() and fb.isVisible())
            fb.show()
            fb.find_edit.setFocus()
            fb.find_edit.selectAll()

        def hide_find(self):
            self.findbar.hide()
            ed = self.current_editor()
            if ed is not None:
                ed.setFocus()

        def _find_flags(self, backward=False):
            flags = QTextDocument.FindFlags()
            if backward:
                flags |= QTextDocument.FindBackward
            if self.findbar.case.isChecked():
                flags |= QTextDocument.FindCaseSensitively
            return flags

        def find(self, backward=False, incremental=False):
            ed = self.current_editor()
            needle = self.findbar.find_edit.text()
            if ed is None:
                return False
            if not needle:
                if not self.findbar.isVisible():
                    self.show_find()
                self.findbar.status.setText("")
                return False
            flags = self._find_flags(backward)
            if incremental:
                c = ed.textCursor()
                c.setPosition(c.selectionStart())
                ed.setTextCursor(c)
            if ed.find(needle, flags):
                self.findbar.status.setText("")
                return True
            saved = ed.textCursor()
            c = ed.textCursor()
            c.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            ed.setTextCursor(c)
            if ed.find(needle, flags):
                self.findbar.status.setText("")
                return True
            ed.setTextCursor(saved)
            self.findbar.status.setText("No results")
            return False

        def _selection_matches(self, ed, needle):
            sel = ed.textCursor().selectedText()
            if self.findbar.case.isChecked():
                return sel == needle
            return sel.lower() == needle.lower()

        def replace_one(self):
            ed = self.current_editor()
            needle = self.findbar.find_edit.text()
            if ed is None or not needle:
                return
            if self._selection_matches(ed, needle):
                ed.textCursor().insertText(self.findbar.replace_edit.text())
            self.find()

        def replace_all(self):
            ed = self.current_editor()
            needle = self.findbar.find_edit.text()
            if ed is None or not needle:
                return
            doc = ed.document()
            flags = self._find_flags()
            repl = self.findbar.replace_edit.text()
            count = 0
            edit = QTextCursor(doc)
            edit.beginEditBlock()
            c = doc.find(needle, 0, flags)
            while not c.isNull():
                c.insertText(repl)
                count += 1
                c = doc.find(needle, c.position(), flags)
            edit.endEditBlock()
            self.findbar.status.setText("%d replaced" % count if count else "No results")

        # ------------------------------------------------------------ view
        def editor_font(self):
            f = QFont(self.editor_family)
            f.setStyleHint(QFont.Monospace)
            f.setPointSizeF(max(2.0, 12.0 * int(self.settings.get("zoom", 100)) / 100.0))
            return f

        def _tab_stops(self, ed):
            ed.setTabStopDistance(ed.fontMetrics().horizontalAdvance(" ") * 8)

        def apply_zoom(self):
            f = self.editor_font()
            for ed in self.editors.values():
                ed.setFont(f)
                self._tab_stops(ed)
            self.lbl_zoom.setText("%d%%" % int(self.settings.get("zoom", 100)))

        def zoom_step(self, direction):
            z = int(self.settings.get("zoom", 100)) + 10 * direction
            self.settings["zoom"] = max(10, min(500, z))
            self.apply_zoom()
            self.save_settings()

        def zoom_reset(self):
            self.settings["zoom"] = 100
            self.apply_zoom()
            self.save_settings()

        def set_word_wrap(self, on):
            self.settings["word_wrap"] = bool(on)
            for ed in self.editors.values():
                ed.set_wrap(on)
            self.save_settings()
            self.schedule_autosave()

        def set_status_visible(self, on):
            self.settings["status_bar"] = bool(on)
            self.statusBar().setVisible(on)
            self.save_settings()

        def update_status(self):
            ed = self.current_editor()
            if ed is None:
                return
            c = ed.textCursor()
            self.lbl_pos.setText("Ln %d, Col %d" % (c.blockNumber() + 1, c.positionInBlock() + 1))
            n = ed.document().characterCount() - 1
            self.lbl_chars.setText("%s character%s" % (format(n, ","), "" if n == 1 else "s"))
            self.lbl_eol.setText(EOL_LABELS.get(ed.eol, "Unix (LF)"))
            self.lbl_enc.setText(ENCODING_LABELS.get(ed.encoding, "UTF-8"))

        def bring_to_front(self):
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()

    def apply_theme(app):
        app.setStyle("Fusion")
        pal = QPalette()
        roles = {
            QPalette.Window: C_WINDOW, QPalette.WindowText: C_TEXT,
            QPalette.Base: C_EDITOR, QPalette.AlternateBase: C_PANEL,
            QPalette.Text: C_TEXT, QPalette.Button: "#1f2937",
            QPalette.ButtonText: C_TEXT, QPalette.Highlight: C_SELECT,
            QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: C_PANEL,
            QPalette.ToolTipText: C_TEXT, QPalette.PlaceholderText: "#64748b",
            QPalette.Link: C_ACCENT, QPalette.Light: "#334155",
            QPalette.Midlight: "#273449", QPalette.Mid: "#1f2937",
            QPalette.Dark: "#0b0f19", QPalette.Shadow: "#000000",
        }
        for role, color in roles.items():
            pal.setColor(role, QColor(color))
        pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#475569"))
        pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#475569"))
        pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#475569"))
        app.setPalette(pal)
        ui = pick_family(["Inter", "Noto Sans", "DejaVu Sans", "Liberation Sans"], "sans-serif")
        f = QFont(ui)
        f.setPointSizeF(10)
        app.setFont(f)
        app.setStyleSheet(STYLESHEET % {
            "win": C_WINDOW, "editor": C_EDITOR, "text": C_TEXT, "muted": C_MUTED,
            "sel": C_SELECT, "panel": C_PANEL, "border": C_BORDER, "accent": C_ACCENT,
            "check": make_check_icon(),
        })

    class SingleInstance:
        """Forward file arguments to an already running Notepad."""

        def __init__(self):
            self.path = socket_path()
            self.server = None
            self.window = None
            self._buffers = {}

        def forward(self, files):
            sock = QLocalSocket()
            sock.connectToServer(self.path)
            if not sock.waitForConnected(500):
                return False
            sock.write(json.dumps({"files": files}).encode("utf-8") + b"\n")
            sock.flush()
            sock.waitForBytesWritten(1000)
            sock.waitForReadyRead(2000)
            sock.disconnectFromServer()
            return True

        def listen(self, window):
            self.window = window
            QLocalServer.removeServer(self.path)  # stale socket after a crash
            self.server = QLocalServer()
            self.server.setSocketOptions(QLocalServer.UserAccessOption)
            if not self.server.listen(self.path):
                sys.stderr.write("notepad: single-instance socket unavailable: %s\n"
                                 % self.server.errorString())
                return
            self.server.newConnection.connect(self._accept)

        def _accept(self):
            while self.server.hasPendingConnections():
                sock = self.server.nextPendingConnection()
                self._buffers[sock] = b""
                sock.readyRead.connect(lambda s=sock: self._read(s))
                sock.disconnected.connect(lambda s=sock: self._drop(s))

        def _drop(self, sock):
            self._buffers.pop(sock, None)
            sock.deleteLater()

        def _read(self, sock):
            if sock not in self._buffers:
                return
            self._buffers[sock] += bytes(sock.readAll())
            if b"\n" not in self._buffers[sock]:
                return
            line = self._buffers[sock].split(b"\n", 1)[0]
            self._buffers[sock] = b""
            try:
                files = json.loads(line.decode("utf-8")).get("files") or []
            except (ValueError, AttributeError):
                files = []
            files = [f for f in files if isinstance(f, str)]
            if files:
                self.window.open_files(files)
            self.window.bring_to_front()
            sock.write(b"ok\n")
            sock.flush()

    _GUI = {
        "QApplication": QApplication, "NotepadWindow": NotepadWindow,
        "SingleInstance": SingleInstance, "apply_theme": apply_theme,
    }
    return _GUI


def create_app(argv=None, store=None):
    """Build the application. Returns (app, window), or (app, None) when the
    files were handed to an already running instance."""
    argv = list(sys.argv if argv is None else argv)
    files = [os.path.abspath(os.path.expanduser(a)) for a in argv[1:] if not a.startswith("-")]
    gui = _load_gui()
    app = gui["QApplication"].instance() or gui["QApplication"](argv)
    instance = gui["SingleInstance"]()
    if instance.forward(files):
        return app, None

    store = store or SessionStore()
    settings = store.load_settings()
    gui["apply_theme"](app)
    win = gui["NotepadWindow"](store, settings)
    win.single_instance = instance
    states, active = store.restore(settings)
    win.restore_session(states, active)
    if files:
        win.open_files(files)
    if win.tabbar.count() == 0:
        win.new_tab()
    win.apply_settings()
    win.update_status()
    win.loading = False

    def on_signal(signum, _frame):
        win.pending_signal = signum  # handled on the GUI thread by a QTimer

    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), on_signal)
    app.aboutToQuit.connect(win.autosave)
    instance.listen(win)
    win.show()
    win.autosave()
    return app, win


def main(argv=None):
    app, win = create_app(argv)
    if win is None:
        return 0
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
