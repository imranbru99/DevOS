#!/usr/bin/env python3
"""
DevOS Notes - notebooks, notes and sticky notes (Windows Sticky Notes + a
little OneNote), stored as plain Markdown files.

Storage
    ~/Documents/DevOS Notes/<Notebook>/<Title>.md    one file per note
    ~/Documents/DevOS Notes/.devos-notes.json         small index: pinned,
                                                      colour, sticky window,
                                                      created time
    Every write is atomic (temp file -> fsync -> rename, the same code as
    DevOS Notepad), so a crash or power cut never leaves half a note. The
    files are ordinary Markdown in Documents, so Cloud Backup keeps them and
    any editor can open them. Deleted notes go to "DevOS Notes/.trash".
    The first line of a note is its title (and its file name).

App
    notes.py                    the Notes window (single instance)
    notes.py --new              the window with a new note
    notes.py --new-sticky       a new sticky note on the desktop
    notes.py --stickies         reopen the sticky notes that were open
                                (login autostart; exits at once when none)

Editor: Markdown with live highlighting and a preview / split view,
search, pin, colours, sticky-note windows, voice notes (offline dictation
from DevOS Voice Typing) and DevOS AI buttons (Summarize, Make to-do list,
Continue writing, Translate) that run on this PC. Export to PDF.

Everything above the GUI line imports without PyQt5 (tests run headless).
"""

import argparse
import datetime
import json
import os
import re
import shutil
import sys
import time
import uuid
from typing import Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = os.path.dirname(HERE)
for _p in (HERE, os.path.join(COMPONENTS, "notepad")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from notepad import atomic_write_text  # noqa: E402  (crash-safe writes, shared with DevOS Notepad)

APP_NAME = "DevOS Notes"
FOLDER_NAME = "DevOS Notes"
INDEX_FILE = ".devos-notes.json"
TRASH_DIR = ".trash"
DEFAULT_NOTEBOOK = "Quick Notes"
UNTITLED = "Untitled note"
INDEX_VERSION = 1
TITLE_MAX = 80
FILENAME_MAX = 64

# name -> (card / sticky background, accent stripe)
COLORS: Dict[str, Tuple[str, str]] = {
    "default": ("#0f172a", "#38bdf8"),
    "yellow": ("#2a2410", "#facc15"),
    "green": ("#0f2a1c", "#34d399"),
    "blue": ("#0f1f3a", "#60a5fa"),
    "pink": ("#2d1426", "#f472b6"),
    "purple": ("#1f1636", "#a78bfa"),
    "orange": ("#2d1a0e", "#fb923c"),
}
COLOR_NAMES = tuple(COLORS)

STICKY_DEFAULT = {"open": False, "x": None, "y": None, "w": 280, "h": 260, "on_top": True}


# ---------------------------------------------------------------------------
# Locations and names
# ---------------------------------------------------------------------------


def documents_dir(home: Optional[str] = None) -> str:
    """The XDG Documents folder (renamed / translated folders too), else ~/Documents."""
    home = home or os.path.expanduser("~")
    try:
        with open(os.path.join(home, ".config", "user-dirs.dirs"), "r", encoding="utf-8") as fh:
            for line in fh:
                m = re.match(r'\s*XDG_DOCUMENTS_DIR\s*=\s*"(.*)"\s*$', line)
                if m:
                    path = os.path.normpath(m.group(1).replace("$HOME", home))
                    if os.path.normpath(path) != os.path.normpath(home):
                        return path
    except OSError:
        pass
    return os.path.join(home, "Documents")


def notes_root(home: Optional[str] = None) -> str:
    return os.path.join(documents_dir(home), FOLDER_NAME)


_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def title_of(body: str) -> str:
    """First non-empty line, without Markdown heading / list / checkbox marks."""
    for line in (body or "").splitlines():
        t = line.strip()
        if not t:
            continue
        t = re.sub(r"^#{1,6}\s*", "", t)
        t = re.sub(r"^(?:[-*+]\s+)?(?:\[[ xX]\]\s+)?", "", t)
        t = re.sub(r"[*_`~]+", "", t).strip()
        if t:
            return t[:TITLE_MAX].rstrip()
    return UNTITLED


def safe_name(name: str, limit: int = FILENAME_MAX) -> str:
    """A file / folder name from a title: no path characters, no leading dots, not empty."""
    n = _BAD_CHARS.sub(" ", name or "")
    n = " ".join(n.split()).strip(" .")
    if len(n) > limit:
        n = n[:limit].rstrip(" .")
    return n or UNTITLED


def snippet_of(body: str, limit: int = 120) -> str:
    lines = [ln.strip() for ln in (body or "").splitlines() if ln.strip()]
    rest = " ".join(lines[1:]) if lines else ""
    rest = re.sub(r"^#{1,6}\s*|[*_`]+", "", rest)
    rest = re.sub(r"\s*[-*+]\s+\[[ xX]\]\s+", " · ", rest)
    rest = " ".join(rest.split())
    return rest if len(rest) <= limit else rest[: limit - 1].rstrip() + "…"


def pdf_filename(title: str) -> str:
    return safe_name(title) + ".pdf"


def checklist_progress(body: str) -> Tuple[int, int]:
    """(done, total) of "- [ ]" / "- [x]" items."""
    done = len(re.findall(r"^\s*[-*+]\s+\[[xX]\]", body or "", re.M))
    total = done + len(re.findall(r"^\s*[-*+]\s+\[ \]", body or "", re.M))
    return done, total


def toggle_checkbox(body: str, line_no: int) -> str:
    lines = (body or "").split("\n")
    if 0 <= line_no < len(lines):
        ln = lines[line_no]
        if re.match(r"^\s*[-*+]\s+\[ \]", ln):
            lines[line_no] = re.sub(r"\[ \]", "[x]", ln, count=1)
        elif re.match(r"^\s*[-*+]\s+\[[xX]\]", ln):
            lines[line_no] = re.sub(r"\[[xX]\]", "[ ]", ln, count=1)
    return "\n".join(lines)


def relative_time(ts: float, now: Optional[float] = None) -> str:
    now = time.time() if now is None else now
    d = max(0, now - ts)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    t = datetime.datetime.fromtimestamp(ts)
    n = datetime.datetime.fromtimestamp(now)
    if t.date() == n.date():
        return t.strftime("%H:%M")
    if (n.date() - t.date()).days == 1:
        return "Yesterday"
    if t.year == n.year:
        return t.strftime("%d %b")
    return t.strftime("%d %b %Y")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class Note:
    __slots__ = ("id", "path", "body", "pinned", "color", "created", "modified", "sticky")

    def __init__(self, id: str, path: str, body: str = "", pinned: bool = False, color: str = "default",
                 created: float = 0.0, modified: float = 0.0, sticky: Optional[dict] = None):
        self.id = id
        self.path = path                # relative to the store root, "/" separated
        self.body = body
        self.pinned = pinned
        self.color = color if color in COLORS else "default"
        self.created = created
        self.modified = modified
        self.sticky = dict(STICKY_DEFAULT, **(sticky or {}))

    @property
    def title(self) -> str:
        return title_of(self.body)

    @property
    def notebook(self) -> str:
        d = os.path.dirname(self.path)
        return d if d else DEFAULT_NOTEBOOK

    @property
    def snippet(self) -> str:
        return snippet_of(self.body)

    def meta(self) -> dict:
        return {"path": self.path, "pinned": self.pinned, "color": self.color, "created": self.created,
                "modified": self.modified, "sticky": self.sticky}

    def __repr__(self):
        return f"Note({self.id!r}, {self.path!r})"


class NoteStore:
    def __init__(self, root: Optional[str] = None, clock=time.time):
        self.root = os.path.abspath(root or notes_root())
        self.clock = clock
        self.notes: Dict[str, Note] = {}
        self.notebook_order: List[str] = []

    # -- paths -------------------------------------------------------------------
    @property
    def index_path(self) -> str:
        return os.path.join(self.root, INDEX_FILE)

    def abspath(self, note_or_rel) -> str:
        rel = note_or_rel.path if isinstance(note_or_rel, Note) else note_or_rel
        return os.path.join(self.root, *rel.split("/"))

    def notebook_dir(self, notebook: str) -> str:
        return os.path.join(self.root, safe_name(notebook))

    # -- load / save -------------------------------------------------------------
    def load(self) -> "NoteStore":
        os.makedirs(self.root, exist_ok=True)
        index = {}
        try:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                index = data
        except (OSError, ValueError):
            pass
        metas = index.get("notes") if isinstance(index.get("notes"), dict) else {}
        by_path = {}
        for nid, m in metas.items():
            if isinstance(m, dict) and isinstance(m.get("path"), str):
                by_path[m["path"]] = (nid, m)
        self.notes = {}
        for rel in self._scan():
            nid, m = by_path.get(rel, (None, {}))
            full = self.abspath(rel)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    body = fh.read()
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            nid = nid or uuid.uuid4().hex[:12]
            modified = float(m.get("modified") or 0) or mtime
            if mtime > modified + 1:            # edited outside the app
                modified = mtime
            self.notes[nid] = Note(nid, rel, body, bool(m.get("pinned", False)), str(m.get("color", "default")),
                                   float(m.get("created") or mtime), modified,
                                   m.get("sticky") if isinstance(m.get("sticky"), dict) else None)
        order = index.get("notebooks") if isinstance(index.get("notebooks"), list) else []
        found = self._scan_notebooks()
        self.notebook_order = [n for n in order if isinstance(n, str) and n in found]
        self.notebook_order += sorted((n for n in found if n not in self.notebook_order), key=str.lower)
        if DEFAULT_NOTEBOOK not in self.notebook_order:
            self.notebook_order.insert(0, DEFAULT_NOTEBOOK)
        return self

    def _scan_notebooks(self) -> List[str]:
        out = []
        try:
            for e in os.scandir(self.root):
                if e.is_dir() and not e.name.startswith("."):
                    out.append(e.name)
        except OSError:
            pass
        return out

    def _scan(self) -> List[str]:
        rels = []
        try:
            entries = list(os.scandir(self.root))
        except OSError:
            return rels
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_file() and e.name.lower().endswith(".md"):
                rels.append(e.name)
            elif e.is_dir():
                try:
                    for f in os.scandir(e.path):
                        if f.is_file() and f.name.lower().endswith(".md") and not f.name.startswith("."):
                            rels.append(e.name + "/" + f.name)
                except OSError:
                    pass
        return rels

    def save_index(self) -> None:
        data = {"version": INDEX_VERSION, "notebooks": self.notebook_order,
                "notes": {n.id: n.meta() for n in self.notes.values()}}
        atomic_write_text(self.index_path, json.dumps(data, indent=1, ensure_ascii=False) + "\n")

    # -- notebooks ---------------------------------------------------------------
    def notebooks(self) -> List[str]:
        return list(self.notebook_order)

    def create_notebook(self, name: str) -> str:
        name = safe_name(name)
        if name.lower() in (n.lower() for n in self.notebook_order):
            raise ValueError(f"A notebook called “{name}” already exists.")
        os.makedirs(self.notebook_dir(name), exist_ok=True)
        self.notebook_order.append(name)
        self.save_index()
        return name

    def rename_notebook(self, old: str, new: str) -> str:
        new = safe_name(new)
        if old == new:
            return new
        if old == DEFAULT_NOTEBOOK:
            raise ValueError(f"“{DEFAULT_NOTEBOOK}” is the default notebook and keeps its name.")
        if new.lower() in (n.lower() for n in self.notebook_order if n != old):
            raise ValueError(f"A notebook called “{new}” already exists.")
        src = self.notebook_dir(old)
        if os.path.isdir(src):
            os.replace(src, self.notebook_dir(new))
        else:
            os.makedirs(self.notebook_dir(new), exist_ok=True)
        for n in self.notes.values():
            if os.path.dirname(n.path) == old:
                n.path = new + "/" + os.path.basename(n.path)
        self.notebook_order = [new if n == old else n for n in self.notebook_order]
        self.save_index()
        return new

    def delete_notebook(self, name: str) -> None:
        """Only an empty notebook can be deleted (notes are never lost silently)."""
        if any(n.notebook == name for n in self.notes.values()):
            raise ValueError("Move or delete the notes in this notebook first.")
        if name == DEFAULT_NOTEBOOK:
            raise ValueError(f"“{DEFAULT_NOTEBOOK}” is the default notebook.")
        try:
            os.rmdir(self.notebook_dir(name))
        except OSError:
            pass
        self.notebook_order = [n for n in self.notebook_order if n != name]
        self.save_index()

    # -- notes -------------------------------------------------------------------
    def _free_rel(self, notebook: str, title: str, keep: Optional[str] = None) -> str:
        folder = safe_name(notebook)
        if keep is not None and os.path.dirname(keep):
            folder = os.path.dirname(keep)
        base = safe_name(title)
        taken = {n.path.lower() for n in self.notes.values() if n.path != keep}
        i = 1
        while True:
            name = base if i == 1 else f"{base} ({i})"
            rel = f"{folder}/{name}.md"
            if rel.lower() not in taken and (rel == keep or not os.path.exists(self.abspath(rel))):
                return rel
            i += 1

    def new_note(self, notebook: str = DEFAULT_NOTEBOOK, body: str = "", color: str = "default") -> Note:
        notebook = notebook or DEFAULT_NOTEBOOK
        if notebook not in self.notebook_order:
            self.notebook_order.append(notebook)
        now = self.clock()
        rel = self._free_rel(notebook, title_of(body))
        note = Note(uuid.uuid4().hex[:12], rel, body, False, color, now, now)
        atomic_write_text(self.abspath(rel), body)
        self.notes[note.id] = note
        self.save_index()
        return note

    def save(self, note: Note, body: str) -> Note:
        """Write the body (atomically) and keep the file name in step with the title."""
        changed = body != note.body
        if changed:
            atomic_write_text(self.abspath(note), body)
            note.body = body
            note.modified = self.clock()
        folder = os.path.dirname(note.path)
        want = self._free_rel(folder or DEFAULT_NOTEBOOK, note.title, keep=note.path)
        if not folder:                      # a file the user dropped in the top folder: leave it there
            want = note.path
        if want != note.path:
            try:
                os.replace(self.abspath(note), self.abspath(want))
                note.path = want
                changed = True
            except OSError:
                pass
        if changed:
            self.save_index()
        return note

    def move(self, note: Note, notebook: str) -> Note:
        if note.notebook == notebook:
            return note
        if notebook not in self.notebook_order:
            self.notebook_order.append(notebook)
        os.makedirs(self.notebook_dir(notebook), exist_ok=True)
        want = self._free_rel(notebook, note.title)
        os.replace(self.abspath(note), self.abspath(want))
        note.path = want
        self.save_index()
        return note

    def delete(self, note: Note) -> str:
        """Moves the file to DevOS Notes/.trash (it can be restored by hand). Returns the trash path."""
        trash = os.path.join(self.root, TRASH_DIR)
        os.makedirs(trash, exist_ok=True)
        stamp = datetime.datetime.fromtimestamp(self.clock()).strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(trash, f"{stamp} {os.path.basename(note.path)}")
        try:
            os.replace(self.abspath(note), dest)
        except FileNotFoundError:
            dest = ""
        self.notes.pop(note.id, None)
        self.save_index()
        return dest

    def discard_if_empty(self, note: Note) -> bool:
        """A new note left without any text is removed (not trashed) so empty files don't pile up."""
        if note.body.strip() or note.sticky.get("open") or note.id not in self.notes:
            return False
        try:
            os.remove(self.abspath(note))
        except FileNotFoundError:
            pass
        except OSError:
            return False
        self.notes.pop(note.id, None)
        self.save_index()
        return True

    def set_pinned(self, note: Note, on: bool) -> None:
        note.pinned = bool(on)
        self.save_index()

    def set_color(self, note: Note, color: str) -> None:
        note.color = color if color in COLORS else "default"
        self.save_index()

    def set_sticky(self, note: Note, **state) -> None:
        for k, v in state.items():
            if k in STICKY_DEFAULT:
                note.sticky[k] = v
        self.save_index()

    def open_stickies(self) -> List[Note]:
        return [n for n in self.sorted(self.notes.values()) if n.sticky.get("open")]

    def get(self, nid: str) -> Optional[Note]:
        return self.notes.get(nid)

    # -- lists and search --------------------------------------------------------
    @staticmethod
    def sorted(notes) -> List[Note]:
        return sorted(notes, key=lambda n: (not n.pinned, -n.modified, n.title.lower()))

    def list(self, notebook: Optional[str] = None, pinned_only: bool = False) -> List[Note]:
        out = [n for n in self.notes.values()
               if (notebook is None or n.notebook == notebook) and (not pinned_only or n.pinned)]
        return self.sorted(out)

    def search(self, query: str, notebook: Optional[str] = None) -> List[Tuple[Note, str]]:
        """Notes containing every word of the query (title matches first), with a snippet around the hit."""
        words = [w.lower() for w in (query or "").split() if w.strip()]
        if not words:
            return [(n, n.snippet) for n in self.list(notebook)]
        hits = []
        for n in self.notes.values():
            if notebook is not None and n.notebook != notebook:
                continue
            hay = (n.body + "\n" + n.notebook).lower()
            if not all(w in hay for w in words):
                continue
            title_hit = all(w in n.title.lower() for w in words)
            hits.append((not title_hit, not n.pinned, -n.modified, n, search_snippet(n.body, words[0])))
        hits.sort(key=lambda h: h[:3])
        return [(h[3], h[4]) for h in hits]


def search_snippet(body: str, word: str, width: int = 110) -> str:
    flat = " ".join((body or "").split())
    i = flat.lower().find(word.lower())
    if i < 0:
        return snippet_of(body)
    start = max(0, i - width // 3)
    s = flat[start:start + width]
    return ("…" if start > 0 else "") + s + ("…" if start + width < len(flat) else "")


# ---------------------------------------------------------------------------
# GUI (PyQt5, imported lazily)
# ---------------------------------------------------------------------------

AUTOSAVE_MS = 700

STYLE = """
QMainWindow, QWidget#root { background: #0b0f1a; }
QWidget { color: #e2e8f0; font-size: 14px; }
QWidget#sidebar { background: #080b14; border-right: 1px solid #141b2d; }
QWidget#listpane { background: #0b0f1a; border-right: 1px solid #141b2d; }
QWidget#editorpane { background: #0b0f1a; }
QLabel#brand { font-size: 17px; font-weight: 700; color: #f8fafc; }
QLabel#section { color: #64748b; font-size: 10.5px; font-weight: 800; letter-spacing: 1.1px; padding: 6px 4px 2px 4px; }
QLabel#muted { color: #94a3b8; font-size: 12px; }
QLabel#paneTitle { font-size: 20px; font-weight: 700; color: #f8fafc; }
QLabel#aiBadge { color: #04121a; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #38bdf8, stop:1 #818cf8);
                 border-radius: 8px; padding: 1px 7px; font-size: 10px; font-weight: 800; letter-spacing: .6px; }
QLineEdit#search { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 7px 10px 7px 30px;
                   color: #e2e8f0; }
QLineEdit#search:focus { border-color: #38bdf8; }
QListWidget { background: transparent; border: none; outline: none; }
QListWidget#books::item { color: #cbd5e1; padding: 7px 10px; border-radius: 8px; margin: 1px 0; }
QListWidget#books::item:hover { background: #0f172a; }
QListWidget#books::item:selected { background: #10213a; color: #f8fafc; }
QListWidget#notes::item { border: none; margin: 0; padding: 0; }
QListWidget#notes::item:selected { background: transparent; }
QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 6px 12px; color: #e2e8f0; }
QPushButton:hover { border-color: #38bdf8; }
QPushButton#primary { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #38bdf8, stop:1 #818cf8);
                      color: #04121a; border: none; font-weight: 700; border-radius: 10px; padding: 8px 14px; }
QPushButton#flat, QToolButton#flat { background: transparent; border: 1px solid transparent; border-radius: 8px;
                      padding: 5px 9px; color: #cbd5e1; }
QPushButton#flat:hover, QToolButton#flat:hover { background: #111a2e; border-color: #1e293b; color: #f8fafc; }
QPushButton#flat:checked, QToolButton#flat:checked { background: #10213a; border-color: #1d4ed8; color: #f8fafc; }
QToolButton#flat::menu-indicator { image: none; }
QPushButton#ai { background: #0f172a; border: 1px solid #1e3a5f; border-radius: 14px; padding: 5px 12px;
                 color: #bae6fd; font-weight: 600; }
QPushButton#ai:hover { background: #10213a; border-color: #38bdf8; color: #f0f9ff; }
QPushButton#ai:disabled { color: #475569; border-color: #1e293b; }
QPushButton#ai::menu-indicator { image: none; width: 0; }
QPushButton#seg { background: transparent; border: none; border-radius: 7px; padding: 4px 10px; color: #94a3b8;
                  font-weight: 600; }
QPushButton#seg:checked { background: #1e293b; color: #f8fafc; }
QWidget#segbox { background: #0f172a; border: 1px solid #1e293b; border-radius: 9px; }
QPlainTextEdit#editor { background: #0b0f1a; border: none; color: #e2e8f0; font-size: 15px;
                        selection-background-color: #0369a1; padding: 4px 0; }
QTextBrowser#preview { background: #0d1324; border: none; border-left: 1px solid #141b2d; color: #e2e8f0;
                       font-size: 15px; padding: 6px 14px; }
QFrame#aiPanel { background: #0d1628; border: 1px solid #1e3a5f; border-radius: 14px; }
QPlainTextEdit#aiText { background: transparent; border: none; color: #e2e8f0; font-size: 14px; }
QFrame#toolbar { background: transparent; border-bottom: 1px solid #141b2d; }
QStatusBar, QLabel#status { color: #64748b; font-size: 12px; }
QMenu { background: #0f172a; border: 1px solid #1e293b; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 18px; border-radius: 6px; color: #e2e8f0; }
QMenu::item:selected { background: #10213a; }
QMenu::separator { height: 1px; background: #1e293b; margin: 5px 8px; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #263248; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #334155; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal { height: 0; }
QSplitter::handle { background: #141b2d; }
QToolTip { background: #0f172a; color: #e2e8f0; border: 1px solid #1e293b; padding: 5px; }
"""

PREVIEW_CSS = """
h1 { font-size: 24px; color: #f8fafc; margin: 4px 0 10px 0; }
h2 { font-size: 19px; color: #f1f5f9; margin: 14px 0 6px 0; }
h3 { font-size: 16px; color: #e2e8f0; }
p, li { color: #e2e8f0; line-height: 150%; }
a { color: #7dd3fc; }
code { background-color: #111a2e; color: #fbcfe8; font-family: 'JetBrains Mono', 'Noto Sans Mono', monospace; }
pre { background-color: #0b1220; padding: 8px; }
blockquote { color: #94a3b8; margin-left: 12px; }
"""

PRINT_CSS = """
body { color: #0f172a; font-family: 'Inter', 'Noto Sans', 'Noto Sans Bengali', sans-serif; }
h1 { font-size: 22pt; color: #0b0f1a; } h2 { font-size: 16pt; } h3 { font-size: 13pt; }
p, li { font-size: 11pt; line-height: 140%; } a { color: #0369a1; }
code { background-color: #f1f5f9; font-family: 'JetBrains Mono', 'Noto Sans Mono', monospace; }
blockquote { color: #475569; }
"""


def _socket_name() -> str:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return f"devos-notes-{uid}"


def _load_gui():  # noqa: C901 - one place for all widget classes
    import threading
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtCore import Qt
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket

    sys.path.insert(0, os.path.join(COMPONENTS, "aiactions"))
    sys.path.insert(0, os.path.join(COMPONENTS, "voicetype"))
    sys.path.insert(0, os.path.join(COMPONENTS, "assistant"))
    import assistant as ui      # painted icons + logo of DevOS AI

    def icon(kind, color="#cbd5e1", size=18):
        return ui.make_icon(kind, color, size)

    # -- painted bits ------------------------------------------------------------
    def color_dot_icon(name, size=16, selected=False):
        pm = QtGui.QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        bg, accent = COLORS[name]
        p.setPen(QtGui.QPen(QtGui.QColor("#f8fafc" if selected else "#334155"), 1.6 if selected else 1))
        p.setBrush(QtGui.QColor(accent if name != "default" else "#475569"))
        p.drawEllipse(QtCore.QRectF(2, 2, size - 4, size - 4))
        p.end()
        return QtGui.QIcon(pm)

    def paint_pin(p, rect, color):
        """A small push-pin (24-unit grid scaled into rect)."""
        p.save()
        p.translate(rect.topLeft())
        k = rect.width() / 24.0
        p.scale(k, k)
        pen = QtGui.QPen(QtGui.QColor(color), 2.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtGui.QColor(color))
        path = QtGui.QPainterPath()
        path.moveTo(9, 3)
        path.lineTo(15, 3)
        path.lineTo(14, 9)
        path.lineTo(18, 13)
        path.lineTo(6, 13)
        path.lineTo(10, 9)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QtCore.QPointF(12, 13), QtCore.QPointF(12, 21))
        p.restore()

    def pin_icon(color="#cbd5e1", size=16):
        pm = QtGui.QPixmap(size * 2, size * 2)
        pm.setDevicePixelRatio(2)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        paint_pin(p, QtCore.QRectF(0, 0, size, size), color)
        p.end()
        return QtGui.QIcon(pm)

    # -- markdown highlighting ---------------------------------------------------
    class MarkdownHighlighter(QtGui.QSyntaxHighlighter):
        """Markdown colours; the first line (the note's title) is always bold."""

        def __init__(self, doc, title_size=None):
            super().__init__(doc)
            self.title_size = title_size

            def fmt(color=None, bold=False, italic=False, size=None, strike=False, mono=False, bg=None):
                f = QtGui.QTextCharFormat()
                if color:
                    f.setForeground(QtGui.QColor(color))
                if bold:
                    f.setFontWeight(QtGui.QFont.Bold)
                if italic:
                    f.setFontItalic(True)
                if size:
                    f.setFontPointSize(size)
                if strike:
                    f.setFontStrikeOut(True)
                if mono:
                    f.setFontFamily("JetBrains Mono")
                    f.setFontFixedPitch(True)
                if bg:
                    f.setBackground(QtGui.QColor(bg))
                return f
            self.f_h = [fmt("#f8fafc", True, size=s) for s in (19, 16.5, 14.5, 13, 12, 12)]
            self.f_mark = fmt("#38bdf8", True)
            self.f_bold = fmt("#f8fafc", True)
            self.f_italic = fmt("#e2e8f0", italic=True)
            self.f_code = fmt("#fbcfe8", mono=True, bg="#111a2e")
            self.f_done = fmt("#64748b", strike=True)
            self.f_box = fmt("#38bdf8", True)
            self.f_quote = fmt("#94a3b8", italic=True)
            self.f_link = fmt("#7dd3fc")
            self.f_dim = fmt("#475569")
            self.f_title = fmt("#f8fafc", True, size=title_size)

        def highlightBlock(self, text):
            if self.currentBlock().blockNumber() == 0 and not text.startswith("#"):
                self.setFormat(0, len(text), self.f_title)
                return
            m = re.match(r"^(#{1,6})\s+.*$", text)
            if m:
                self.setFormat(0, len(text), self.f_h[len(m.group(1)) - 1])
                self.setFormat(0, len(m.group(1)), self.f_dim)
                return
            m = re.match(r"^(\s*[-*+]\s+)\[([ xX])\](.*)$", text)
            if m:
                self.setFormat(0, len(m.group(1)), self.f_mark)
                self.setFormat(len(m.group(1)), 3, self.f_box)
                if m.group(2) in "xX":
                    self.setFormat(len(m.group(1)) + 3, len(m.group(3)), self.f_done)
                    return
            else:
                m = re.match(r"^(\s*(?:[-*+]|\d+[.)])\s+)", text)
                if m:
                    self.setFormat(0, len(m.group(1)), self.f_mark)
            if text.lstrip().startswith(">"):
                self.setFormat(0, len(text), self.f_quote)
            for rx, f in ((r"\*\*[^*]+\*\*|__[^_]+__", self.f_bold), (r"(?<![*\w])\*[^*\s][^*]*\*(?!\*)", self.f_italic),
                          (r"`[^`]+`", self.f_code), (r"\[[^\]]+\]\([^)]+\)|https?://\S+", self.f_link)):
                for mm in re.finditer(rx, text):
                    self.setFormat(mm.start(), mm.end() - mm.start(), f)

    class Editor(QtWidgets.QPlainTextEdit):
        """Markdown editor: Enter continues lists and checklists, Ctrl+B/I wrap the selection."""

        def keyPressEvent(self, e):
            if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() & Qt.ShiftModifier:
                cur = self.textCursor()
                line = cur.block().text()
                m = re.match(r"^(\s*)([-*+]\s+\[[ xX]\]\s+|[-*+]\s+|(\d+)([.)])\s+)", line)
                if m and cur.positionInBlock() == len(line):
                    if line.strip() == m.group(0).strip():        # empty item: end the list
                        cur.select(QtGui.QTextCursor.LineUnderCursor)
                        cur.removeSelectedText()
                        return
                    if m.group(3):
                        nxt = f"{int(m.group(3)) + 1}{m.group(4)} "
                    elif "[" in m.group(2):
                        nxt = m.group(2)[0] + " [ ] "
                    else:
                        nxt = m.group(2)
                    self.insertPlainText("\n" + m.group(1) + nxt)
                    return
            super().keyPressEvent(e)

        def wrap(self, left, right=None):
            right = left if right is None else right
            cur = self.textCursor()
            t = cur.selectedText()
            cur.insertText(f"{left}{t}{right}")
            if not t:
                cur.movePosition(QtGui.QTextCursor.Left, n=len(right))
                self.setTextCursor(cur)
            self.setFocus()

        def prefix_lines(self, prefix):
            cur = self.textCursor()
            start, end = cur.selectionStart(), cur.selectionEnd()
            doc = self.document()
            b = doc.findBlock(start)
            last = doc.findBlock(end)
            cur.beginEditBlock()
            while b.isValid():
                c = QtGui.QTextCursor(b)
                text = b.text()
                if prefix.startswith("#"):
                    stripped = re.sub(r"^#{1,6}\s*", "", text)
                    c.select(QtGui.QTextCursor.LineUnderCursor)
                    c.insertText((prefix + stripped) if not text.startswith(prefix) else stripped)
                elif not text.startswith(prefix):
                    c.insertText(prefix)
                if b == last:
                    break
                b = b.next()
            cur.endEditBlock()
            self.setFocus()

    # -- note list card ---------------------------------------------------------
    class NoteCard(QtWidgets.QWidget):
        def __init__(self, note, snippet, selected=False):
            super().__init__()
            self.note = note
            self.snippet = snippet
            self.selected = selected
            self.hover = False
            self.setAttribute(Qt.WA_Hover)
            self.setFixedHeight(92)

        def enterEvent(self, _e):
            self.hover = True
            self.update()

        def leaveEvent(self, _e):
            self.hover = False
            self.update()

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            r = QtCore.QRectF(self.rect()).adjusted(8, 4, -8, -4)
            bg, accent = COLORS[self.note.color]
            base = QtGui.QColor(bg if self.note.color != "default" else "#0f172a")
            if self.selected:
                base = base.lighter(135)
            elif self.hover:
                base = base.lighter(118)
            p.setPen(QtGui.QPen(QtGui.QColor("#38bdf8" if self.selected else "#1a2338"), 1.2 if self.selected else 1))
            p.setBrush(base)
            p.drawRoundedRect(r, 12, 12)
            if self.note.color != "default":
                p.setPen(Qt.NoPen)
                p.setBrush(QtGui.QColor(accent))
                p.drawRoundedRect(QtCore.QRectF(r.left() + 6, r.top() + 12, 3.5, r.height() - 24), 2, 2)
            x = r.left() + 18
            w = r.width() - 30
            f = QtGui.QFont(self.font())
            f.setPixelSize(14)
            f.setWeight(QtGui.QFont.DemiBold)
            p.setFont(f)
            p.setPen(QtGui.QColor("#f8fafc"))
            title = QtGui.QFontMetrics(f).elidedText(self.note.title, Qt.ElideRight, int(w - (20 if self.note.pinned else 0)))
            p.drawText(QtCore.QRectF(x, r.top() + 10, w, 20), Qt.AlignLeft | Qt.AlignVCenter, title)
            if self.note.pinned:
                paint_pin(p, QtCore.QRectF(r.right() - 26, r.top() + 12, 16, 16), "#38bdf8")
            f2 = QtGui.QFont(self.font())
            f2.setPixelSize(13)
            p.setFont(f2)
            p.setPen(QtGui.QColor("#94a3b8"))
            fm = QtGui.QFontMetrics(f2)
            snip = self.snippet or "No more text"
            line1 = fm.elidedText(snip, Qt.ElideRight, int(w))
            p.drawText(QtCore.QRectF(x, r.top() + 32, w, 20), Qt.AlignLeft | Qt.AlignVCenter, line1)
            f3 = QtGui.QFont(self.font())
            f3.setPixelSize(11)
            p.setFont(f3)
            p.setPen(QtGui.QColor("#64748b"))
            done, total = checklist_progress(self.note.body)
            meta = relative_time(self.note.modified) + "  ·  " + self.note.notebook
            if total:
                meta += f"  ·  ☑ {done}/{total}"
            if self.note.sticky.get("open"):
                meta += "  ·  on desktop"
            p.drawText(QtCore.QRectF(x, r.bottom() - 26, w, 18), Qt.AlignLeft | Qt.AlignVCenter, meta)
            p.end()

    # -- AI result panel ---------------------------------------------------------
    class AiBridge(QtCore.QObject):
        delta = QtCore.pyqtSignal(int, str)
        done = QtCore.pyqtSignal(int, str, str)

    class AiPanel(QtWidgets.QFrame):
        insert = QtCore.pyqtSignal(str)
        append = QtCore.pyqtSignal(str)
        replace = QtCore.pyqtSignal(str)

        def __init__(self):
            super().__init__()
            self.setObjectName("aiPanel")
            self.bridge = AiBridge()
            self.bridge.delta.connect(self._delta)
            self.bridge.done.connect(self._done)
            self.run_id = 0
            self.cancel = None
            self.text = ""
            self.mode = ""
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(14, 10, 14, 12)
            lay.setSpacing(6)
            head = QtWidgets.QHBoxLayout()
            badge = QtWidgets.QLabel("AI")
            badge.setObjectName("aiBadge")
            head.addWidget(badge)
            self.title = QtWidgets.QLabel("")
            self.title.setStyleSheet("font-weight: 700; color: #f8fafc;")
            head.addWidget(self.title)
            head.addStretch(1)
            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("muted")
            head.addWidget(self.status)
            close = QtWidgets.QPushButton("✕")
            close.setObjectName("flat")
            close.setToolTip("Discard")
            close.clicked.connect(self.discard)
            head.addWidget(close)
            lay.addLayout(head)
            self.out = QtWidgets.QPlainTextEdit()
            self.out.setObjectName("aiText")
            self.out.setMinimumHeight(90)
            self.out.setMaximumHeight(180)
            self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
            lay.addWidget(self.out)
            row = QtWidgets.QHBoxLayout()
            note = QtWidgets.QLabel("Written by DevOS AI on this PC · check it before you use it")
            note.setObjectName("muted")
            note.setStyleSheet("color: #64748b; font-size: 11px;")
            row.addWidget(note)
            row.addStretch(1)
            self.b_replace = QtWidgets.QPushButton("Replace note")
            self.b_replace.setObjectName("flat")
            self.b_replace.clicked.connect(lambda: self._use(self.replace))
            self.b_insert = QtWidgets.QPushButton("Insert at cursor")
            self.b_insert.setObjectName("flat")
            self.b_insert.clicked.connect(lambda: self._use(self.insert))
            self.b_append = QtWidgets.QPushButton("Add to note")
            self.b_append.setObjectName("primary")
            self.b_append.clicked.connect(lambda: self._use(self.append))
            for b in (self.b_replace, self.b_insert, self.b_append):
                b.setCursor(Qt.PointingHandCursor)
                row.addWidget(b)
            lay.addLayout(row)
            self.hide()

        def start(self, key, label, body):
            import aiactions
            import engine
            if self.cancel is not None:
                self.cancel.stop()
            self.run_id += 1
            rid = self.run_id
            self.cancel = engine.StreamHandle()
            cancel = self.cancel
            self.mode = key
            self.text = ""
            self.title.setText(label)
            self.status.setText("Writing…")
            self.out.setPlainText("")
            self.out.setPlaceholderText("DevOS AI is writing…")
            self.b_replace.setVisible(key in ("to_bn", "to_en"))
            for b in (self.b_replace, self.b_insert, self.b_append):
                b.setEnabled(False)
            self.show()

            def job():
                try:
                    out = aiactions.run_action(key, body, on_delta=lambda d: self.bridge.delta.emit(rid, d),
                                               cancel=cancel)
                    self.bridge.done.emit(rid, out, "")
                except Exception as exc:
                    self.bridge.done.emit(rid, "", str(exc) or "DevOS AI didn't answer.")
            threading.Thread(target=job, daemon=True).start()

        def _delta(self, rid, piece):
            if rid == self.run_id:
                self.text += piece
                self.out.setPlainText(self.text.lstrip())
                self.out.moveCursor(QtGui.QTextCursor.End)

        def _done(self, rid, text, error):
            if rid != self.run_id:
                return
            if error and not self.text:
                self.status.setText("")
                self.out.setPlaceholderText(error)
                return
            import aiactions
            self.out.setPlainText(text or aiactions.clean_output(self.text))
            self.status.setText("Done")
            for b in (self.b_replace, self.b_insert, self.b_append):
                b.setEnabled(True)

        def _use(self, signal):
            t = self.out.toPlainText().strip()
            if t:
                signal.emit(t)
            self.discard()

        def discard(self):
            if self.cancel is not None:
                self.cancel.stop()
            self.run_id += 1
            self.hide()

    # -- voice note --------------------------------------------------------------
    class VoiceBridge(QtCore.QObject):
        level = QtCore.pyqtSignal(float)
        result = QtCore.pyqtSignal(str, str)

    class MicButton(QtWidgets.QPushButton):
        def __init__(self):
            super().__init__()
            self.setObjectName("ai")
            self.setCursor(Qt.PointingHandCursor)
            self.recording = False
            self.level = 0.0
            self.phase = 0.0
            self.setText("  Voice note")
            self.setIcon(icon("mic", "#bae6fd", 16))
            self.timer = QtCore.QTimer(self)
            self.timer.setInterval(40)
            self.timer.timeout.connect(self._tick)

        def set_recording(self, on):
            self.recording = on
            self.setText("  Listening… click to stop" if on else "  Voice note")
            self.setIcon(icon("stop" if on else "mic", "#fecaca" if on else "#bae6fd", 16))
            self.setStyleSheet("QPushButton { border-color: #ef4444; color: #fecaca; background: #2a1215; }"
                               if on else "")
            (self.timer.start if on else self.timer.stop)()
            self.update()

        def _tick(self):
            self.phase += 0.15
            self.update()

        def paintEvent(self, e):
            super().paintEvent(e)
            if self.recording:
                p = QtGui.QPainter(self)
                p.setRenderHint(QtGui.QPainter.Antialiasing)
                a = int(60 + 120 * min(1.0, self.level * 1.3))
                p.setPen(QtGui.QPen(QtGui.QColor(239, 68, 68, a), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1), 14, 14)
                p.end()

    # -- sticky note window ------------------------------------------------------
    class StickyWindow(QtWidgets.QWidget):
        closed = QtCore.pyqtSignal(str)
        open_in_app = QtCore.pyqtSignal(str)
        new_sticky = QtCore.pyqtSignal()

        def __init__(self, app_ctl, note):
            flags = Qt.FramelessWindowHint | Qt.Tool
            if note.sticky.get("on_top", True):
                flags |= Qt.WindowStaysOnTopHint
            super().__init__(None, flags)
            self.ctl = app_ctl
            self.note = note
            self.setAttribute(Qt.WA_TranslucentBackground)
            self.setWindowTitle(note.title + " — Sticky note")
            self.setMinimumSize(200, 160)
            self._drag = None
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 10)
            lay.setSpacing(4)
            head = QtWidgets.QHBoxLayout()
            head.setSpacing(2)

            def tb(text, tip, slot):
                b = QtWidgets.QToolButton()
                b.setText(text)
                b.setToolTip(tip)
                b.setAutoRaise(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("QToolButton { color: rgba(248,250,252,0.75); border: none; border-radius: 6px;"
                                " padding: 2px 6px; font-size: 14px; background: transparent; }"
                                "QToolButton:hover { background: rgba(255,255,255,0.12); color: #fff; }")
                b.clicked.connect(slot)
                head.addWidget(b)
                return b
            tb("+", "New sticky note", self.new_sticky.emit)
            head.addStretch(1)
            self.pin_btn = tb("⤒", "Keep on top", self.toggle_on_top)
            tb("⧉", "Open in DevOS Notes", lambda: self.open_in_app.emit(self.note.id))
            self.color_btn = tb("●", "Colour", self.pick_color)
            self._btn_style = self.color_btn.styleSheet()
            self.apply_color()
            tb("✕", "Close sticky note (the note is kept)", self.close)
            lay.addLayout(head)
            self.edit = Editor()
            self.edit.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.edit.setPlainText(note.body)
            self.edit.setStyleSheet("QPlainTextEdit { background: transparent; border: none; color: #f8fafc;"
                                    " font-size: 14px; selection-background-color: rgba(255,255,255,0.25); }")
            self.highlighter = MarkdownHighlighter(self.edit.document(), 12)
            self.edit.textChanged.connect(self._changed)
            lay.addWidget(self.edit, 1)
            grip_row = QtWidgets.QHBoxLayout()
            grip_row.addStretch(1)
            grip = QtWidgets.QSizeGrip(self)
            grip_row.addWidget(grip)
            lay.addLayout(grip_row)
            self.save_timer = QtCore.QTimer(self)
            self.save_timer.setSingleShot(True)
            self.save_timer.timeout.connect(self.save)
            st = note.sticky
            self.resize(int(st.get("w") or 280), int(st.get("h") or 260))
            if st.get("x") is not None and st.get("y") is not None:
                self.move(int(st["x"]), int(st["y"]))
            self._apply_pin_look()

        def apply_color(self):
            accent = COLORS[self.note.color if self.note.color != "default" else "yellow"][1]
            self.color_btn.setStyleSheet(self._btn_style + "QToolButton { color: %s; }" % accent)
            self.update()

        def _apply_pin_look(self):
            on = bool(self.note.sticky.get("on_top", True))
            self.pin_btn.setText("⤒" if on else "⤓")
            self.pin_btn.setToolTip("Keeps on top (click to let windows cover it)" if on else "Keep on top")

        def paintEvent(self, _e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            _bg, accent = COLORS[self.note.color if self.note.color != "default" else "yellow"]
            r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
            g = QtGui.QLinearGradient(r.topLeft(), r.bottomRight())
            c1 = QtGui.QColor(accent)
            c1.setAlpha(255)
            base = QtGui.QColor("#101626")

            def mix(a, b, t):
                return QtGui.QColor(int(a.red() * (1 - t) + b.red() * t), int(a.green() * (1 - t) + b.green() * t),
                                    int(a.blue() * (1 - t) + b.blue() * t), 246)
            g.setColorAt(0, mix(base, c1, 0.30))
            g.setColorAt(1, mix(base, c1, 0.14))
            edge = QtGui.QColor(accent)
            edge.setAlpha(150)
            p.setPen(QtGui.QPen(edge, 1))
            p.setBrush(QtGui.QBrush(g))
            p.drawRoundedRect(r, 12, 12)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(accent))
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(r, 12, 12)
            p.setClipPath(clip)
            p.drawRect(QtCore.QRectF(r.left(), r.top(), r.width(), 5))
            p.end()

        def mousePressEvent(self, e):
            if e.button() == Qt.LeftButton:
                self._drag = e.globalPos() - self.frameGeometry().topLeft()

        def mouseMoveEvent(self, e):
            if self._drag is not None and e.buttons() & Qt.LeftButton:
                self.move(e.globalPos() - self._drag)

        def mouseReleaseEvent(self, _e):
            if self._drag is not None:
                self._drag = None
                self.remember_geometry()

        def resizeEvent(self, e):
            super().resizeEvent(e)
            if self.isVisible():
                self.save_timer.start(AUTOSAVE_MS)

        def remember_geometry(self):
            g = self.geometry()
            self.ctl.store.set_sticky(self.note, open=True, x=g.x(), y=g.y(), w=g.width(), h=g.height())

        def _changed(self):
            self.save_timer.start(AUTOSAVE_MS)

        def save(self):
            body = self.edit.toPlainText()
            if body != self.note.body:
                self.ctl.store.save(self.note, body)
                self.ctl.note_changed(self.note, source=self)
            self.remember_geometry()

        def reload(self):
            if self.edit.toPlainText() != self.note.body:
                cur = self.edit.textCursor().position()
                self.edit.blockSignals(True)
                self.edit.setPlainText(self.note.body)
                self.edit.blockSignals(False)
                c = self.edit.textCursor()
                c.setPosition(min(cur, len(self.note.body)))
                self.edit.setTextCursor(c)
            self.update()

        def toggle_on_top(self):
            on = not bool(self.note.sticky.get("on_top", True))
            self.ctl.store.set_sticky(self.note, on_top=on)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
            self.show()
            self._apply_pin_look()

        def pick_color(self):
            m = ui.make_menu(self) if hasattr(ui, "make_menu") else QtWidgets.QMenu(self)
            for name in COLOR_NAMES:
                a = m.addAction(color_dot_icon(name, selected=name == self.note.color), name.capitalize())
                a.triggered.connect(lambda _c=False, n=name: self.ctl.set_color(self.note, n))
            m.exec_(QtGui.QCursor.pos())

        def closeEvent(self, e):
            self.save_timer.stop()
            body = self.edit.toPlainText()
            if body != self.note.body:
                self.ctl.store.save(self.note, body)
            if not self.ctl.quitting:
                self.ctl.store.set_sticky(self.note, open=False)
            self.closed.emit(self.note.id)
            super().closeEvent(e)

    # -- main window --------------------------------------------------------------
    class NotesWindow(QtWidgets.QMainWindow):
        def __init__(self, ctl):
            super().__init__()
            self.ctl = ctl
            self.store = ctl.store
            self.current = None
            self.filter_book = None         # None: all notes
            self.filter_pinned = False
            self.mode = "edit"
            self.setWindowTitle(APP_NAME)
            self.setWindowIcon(QtGui.QIcon(ui.logo_pixmap(64)))
            self.resize(1240, 780)
            self.setStyleSheet(STYLE)
            self.save_timer = QtCore.QTimer(self)
            self.save_timer.setSingleShot(True)
            self.save_timer.timeout.connect(self.save_now)
            self.preview_timer = QtCore.QTimer(self)
            self.preview_timer.setSingleShot(True)
            self.preview_timer.timeout.connect(self.update_preview)
            self.voice_bridge = VoiceBridge()
            self.voice_bridge.result.connect(self._voice_result)
            self.voice_bridge.level.connect(self._voice_level)
            self.dictation = None
            self._build()
            self.refresh_books()
            self.refresh_list()
            notes = self.store.list()
            if notes:
                self.open_note(notes[0])
            else:
                self.show_empty()

        # ---- layout ----
        def _build(self):
            root = QtWidgets.QWidget()
            root.setObjectName("root")
            self.setCentralWidget(root)
            h = QtWidgets.QHBoxLayout(root)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(0)

            # sidebar
            side = QtWidgets.QWidget()
            side.setObjectName("sidebar")
            side.setFixedWidth(232)
            sl = QtWidgets.QVBoxLayout(side)
            sl.setContentsMargins(14, 16, 12, 14)
            sl.setSpacing(8)
            brand = QtWidgets.QHBoxLayout()
            logo = QtWidgets.QLabel()
            logo.setPixmap(ui.logo_pixmap(30))
            brand.addWidget(logo)
            bl = QtWidgets.QLabel("Notes")
            bl.setObjectName("brand")
            brand.addWidget(bl)
            brand.addStretch(1)
            sl.addLayout(brand)
            sl.addSpacing(4)
            self.search = QtWidgets.QLineEdit()
            self.search.setObjectName("search")
            self.search.setPlaceholderText("Search notes")
            self.search.setClearButtonEnabled(True)
            self.search.addAction(icon("search", "#64748b", 16), QtWidgets.QLineEdit.LeadingPosition)
            self.search.setStyleSheet("padding-left: 8px;")
            self.search.textChanged.connect(lambda _t: self.refresh_list())
            sl.addWidget(self.search)
            newb = QtWidgets.QPushButton("  New note")
            newb.setObjectName("primary")
            newb.setIcon(icon("plus", "#04121a", 16))
            newb.setCursor(Qt.PointingHandCursor)
            newb.clicked.connect(self.new_note)
            sl.addWidget(newb)
            stick = QtWidgets.QPushButton("  New sticky note")
            stick.setObjectName("flat")
            stick.setIcon(icon("new", "#cbd5e1", 16))
            stick.setCursor(Qt.PointingHandCursor)
            stick.clicked.connect(lambda: self.ctl.new_sticky())
            sl.addWidget(stick)
            lab = QtWidgets.QLabel("LIBRARY")
            lab.setObjectName("section")
            sl.addWidget(lab)
            self.lib = QtWidgets.QListWidget()
            self.lib.setObjectName("books")
            self.lib.setFixedHeight(84)
            self.lib.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            for text, key, ic in (("All notes", "all", "file"), ("Pinned", "pinned", "spark")):
                it = QtWidgets.QListWidgetItem(icon(ic, "#94a3b8", 16), "  " + text)
                it.setData(Qt.UserRole, key)
                self.lib.addItem(it)
            self.lib.itemClicked.connect(self._lib_clicked)
            sl.addWidget(self.lib)
            bh = QtWidgets.QHBoxLayout()
            lab2 = QtWidgets.QLabel("NOTEBOOKS")
            lab2.setObjectName("section")
            bh.addWidget(lab2)
            bh.addStretch(1)
            addb = QtWidgets.QToolButton()
            addb.setObjectName("flat")
            addb.setIcon(icon("plus", "#94a3b8", 14))
            addb.setToolTip("New notebook")
            addb.clicked.connect(self.new_notebook)
            bh.addWidget(addb)
            sl.addLayout(bh)
            self.books = QtWidgets.QListWidget()
            self.books.setObjectName("books")
            self.books.itemClicked.connect(self._book_clicked)
            self.books.setContextMenuPolicy(Qt.CustomContextMenu)
            self.books.customContextMenuRequested.connect(self._book_menu)
            sl.addWidget(self.books, 1)
            where = QtWidgets.QLabel("Saved in Documents › DevOS Notes")
            where.setObjectName("muted")
            where.setStyleSheet("color: #475569; font-size: 11px;")
            where.setWordWrap(True)
            sl.addWidget(where)
            h.addWidget(side)

            # list pane
            lp = QtWidgets.QWidget()
            lp.setObjectName("listpane")
            lp.setFixedWidth(330)
            ll = QtWidgets.QVBoxLayout(lp)
            ll.setContentsMargins(6, 18, 6, 8)
            ll.setSpacing(6)
            lh = QtWidgets.QHBoxLayout()
            lh.setContentsMargins(12, 0, 12, 0)
            self.list_title = QtWidgets.QLabel("All notes")
            self.list_title.setObjectName("paneTitle")
            lh.addWidget(self.list_title)
            lh.addStretch(1)
            self.list_count = QtWidgets.QLabel("")
            self.list_count.setObjectName("muted")
            lh.addWidget(self.list_count)
            ll.addLayout(lh)
            self.list = QtWidgets.QListWidget()
            self.list.setObjectName("notes")
            self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
            self.list.currentItemChanged.connect(self._note_selected)
            self.list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.list.customContextMenuRequested.connect(self._note_menu)
            ll.addWidget(self.list, 1)
            h.addWidget(lp)

            # editor pane
            ep = QtWidgets.QWidget()
            ep.setObjectName("editorpane")
            el = QtWidgets.QVBoxLayout(ep)
            el.setContentsMargins(26, 14, 22, 10)
            el.setSpacing(8)
            top = QtWidgets.QHBoxLayout()
            top.setSpacing(4)
            self.book_btn = QtWidgets.QToolButton()
            self.book_btn.setObjectName("flat")
            self.book_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            self.book_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.book_btn.setIcon(icon("file", "#94a3b8", 15))
            self.book_btn.setToolTip("Notebook (click to move the note)")
            self.book_menu = QtWidgets.QMenu(self)
            self.book_menu.aboutToShow.connect(self._fill_move_menu)
            self.book_btn.setMenu(self.book_menu)
            top.addWidget(self.book_btn)
            self.saved = QtWidgets.QLabel("")
            self.saved.setObjectName("muted")
            top.addWidget(self.saved)
            top.addStretch(1)
            self.color_btns = {}
            for name in COLOR_NAMES:
                b = QtWidgets.QToolButton()
                b.setAutoRaise(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setToolTip(f"Colour: {name}")
                b.setIcon(color_dot_icon(name))
                b.setIconSize(QtCore.QSize(16, 16))
                b.setStyleSheet("QToolButton { border: none; padding: 2px; border-radius: 9px; }"
                                "QToolButton:hover { background: #111a2e; }")
                b.clicked.connect(lambda _c=False, n=name: self.current and self.ctl.set_color(self.current, n))
                top.addWidget(b)
                self.color_btns[name] = b
            top.addSpacing(8)
            self.pin_btn = QtWidgets.QPushButton(" Pin")
            self.pin_btn.setIcon(pin_icon("#cbd5e1", 15))
            self.pin_btn.setObjectName("flat")
            self.pin_btn.setCheckable(True)
            self.pin_btn.setCursor(Qt.PointingHandCursor)
            self.pin_btn.toggled.connect(self.toggle_pin)
            top.addWidget(self.pin_btn)
            self.sticky_btn = QtWidgets.QPushButton("Sticky")
            self.sticky_btn.setObjectName("flat")
            self.sticky_btn.setIcon(icon("new", "#cbd5e1", 15))
            self.sticky_btn.setCheckable(True)
            self.sticky_btn.setCursor(Qt.PointingHandCursor)
            self.sticky_btn.setToolTip("Show this note as a sticky note on the desktop")
            self.sticky_btn.clicked.connect(self.toggle_sticky)
            top.addWidget(self.sticky_btn)
            more = QtWidgets.QToolButton()
            more.setObjectName("flat")
            more.setText("•••")
            more.setPopupMode(QtWidgets.QToolButton.InstantPopup)
            mm = QtWidgets.QMenu(self)
            mm.addAction("Export to PDF…", self.export_pdf)
            mm.addAction("Show file in folder", self.reveal)
            mm.addSeparator()
            mm.addAction("Delete note", self.delete_current)
            more.setMenu(mm)
            top.addWidget(more)
            el.addLayout(top)

            # formatting + view toolbar
            tbar = QtWidgets.QFrame()
            tbar.setObjectName("toolbar")
            tl = QtWidgets.QHBoxLayout(tbar)
            tl.setContentsMargins(0, 0, 0, 8)
            tl.setSpacing(2)

            def fbtn(text, tip, slot, bold=False):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("flat")
                b.setToolTip(tip)
                b.setCursor(Qt.PointingHandCursor)
                if bold:
                    b.setStyleSheet("font-weight: 800;")
                b.clicked.connect(slot)
                tl.addWidget(b)
                return b
            fbtn("H1", "Heading", lambda: self.editor.prefix_lines("# "), True)
            fbtn("H2", "Subheading", lambda: self.editor.prefix_lines("## "), True)
            fbtn("B", "Bold (Ctrl+B)", lambda: self.editor.wrap("**"), True)
            fbtn("I", "Italic (Ctrl+I)", lambda: self.editor.wrap("*")).setStyleSheet("font-style: italic;")
            fbtn("• List", "Bulleted list", lambda: self.editor.prefix_lines("- "))
            fbtn("☑ To-do", "Checklist", lambda: self.editor.prefix_lines("- [ ] "))
            fbtn("</>", "Code", lambda: self.editor.wrap("`"))
            tl.addStretch(1)
            seg = QtWidgets.QWidget()
            seg.setObjectName("segbox")
            sgl = QtWidgets.QHBoxLayout(seg)
            sgl.setContentsMargins(3, 3, 3, 3)
            sgl.setSpacing(2)
            self.seg = {}
            grp = QtWidgets.QButtonGroup(self)
            for key, text in (("edit", "Edit"), ("split", "Split"), ("preview", "Preview")):
                b = QtWidgets.QPushButton(text)
                b.setObjectName("seg")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, k=key: self.set_mode(k))
                grp.addButton(b)
                sgl.addWidget(b)
                self.seg[key] = b
            self.seg["edit"].setChecked(True)
            tl.addWidget(seg)
            el.addWidget(tbar)

            # AI row
            ai_row = QtWidgets.QWidget()
            ai = QtWidgets.QHBoxLayout(ai_row)
            ai.setContentsMargins(0, 0, 0, 0)
            ai.setSpacing(6)
            badge = QtWidgets.QLabel("AI")
            badge.setObjectName("aiBadge")
            badge.setToolTip("These buttons use DevOS AI on this PC")
            ai.addWidget(badge)
            self.ai_btns = []
            for key, label in (("summarize", "Summarize"), ("todo", "Make to-do list"),
                               ("continue", "Continue writing")):
                b = QtWidgets.QPushButton(label)
                b.setObjectName("ai")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _c=False, k=key, l=label: self.run_ai(k, l))
                ai.addWidget(b)
                self.ai_btns.append(b)
            tr = QtWidgets.QPushButton("Translate ▾")
            tr.setObjectName("ai")
            tr.setCursor(Qt.PointingHandCursor)
            tm = QtWidgets.QMenu(self)
            tm.addAction("To Bangla (বাংলা)", lambda: self.run_ai("to_bn", "Translate to Bangla"))
            tm.addAction("To English", lambda: self.run_ai("to_en", "Translate to English"))
            tr.setMenu(tm)
            ai.addWidget(tr)
            self.ai_btns.append(tr)
            ai.addStretch(1)
            self.mic = MicButton()
            self.mic.clicked.connect(self.toggle_voice)
            ai.addWidget(self.mic)
            el.addWidget(ai_row)

            self.ai_panel = AiPanel()
            self.ai_panel.insert.connect(self._ai_insert)
            self.ai_panel.append.connect(self._ai_append)
            self.ai_panel.replace.connect(self._ai_replace)

            self.split = QtWidgets.QSplitter(Qt.Horizontal)
            self.split.setChildrenCollapsible(False)
            self.split.setHandleWidth(1)
            self._split_ready = False
            self.editor = Editor()
            self.editor.setObjectName("editor")
            self.editor.setPlaceholderText("Start with a title…\n\nWrite in Markdown: # heading, **bold**, - list, "
                                           "- [ ] to-do")
            self.editor.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.highlighter = MarkdownHighlighter(self.editor.document(), 17)
            self.editor.textChanged.connect(self._text_changed)
            self.preview = QtWidgets.QTextBrowser()
            self.preview.setObjectName("preview")
            self.preview.setOpenExternalLinks(True)
            self.preview.document().setDefaultStyleSheet(PREVIEW_CSS)
            self.split.addWidget(self.editor)
            self.split.addWidget(self.preview)
            self.split.setStretchFactor(0, 1)
            self.split.setStretchFactor(1, 1)
            self.preview.hide()
            el.addWidget(self.split, 1)
            el.addWidget(self.ai_panel)
            self.empty = QtWidgets.QLabel("No note selected.\nCreate one with “New note”.")
            self.empty.setAlignment(Qt.AlignCenter)
            self.empty.setObjectName("muted")
            self.empty.setStyleSheet("font-size: 15px; color: #475569;")
            el.addWidget(self.empty, 1)
            self.empty.hide()
            sb = QtWidgets.QHBoxLayout()
            self.status = QtWidgets.QLabel("")
            self.status.setObjectName("status")
            sb.addWidget(self.status)
            sb.addStretch(1)
            el.addLayout(sb)
            self.editor_widgets = [tbar, ai_row, self.split]
            h.addWidget(ep, 1)

            for seq, slot in (("Ctrl+N", self.new_note), ("Ctrl+F", self.search.setFocus),
                              ("Ctrl+B", lambda: self.editor.wrap("**")), ("Ctrl+I", lambda: self.editor.wrap("*")),
                              ("Ctrl+S", self.save_now), ("Ctrl+P", self.export_pdf),
                              ("Ctrl+E", lambda: self.set_mode("preview" if self.mode == "edit" else "edit"))):
                QtWidgets.QShortcut(QtGui.QKeySequence(seq), self, slot)

        # ---- lists ----
        def refresh_books(self):
            self.books.clear()
            for name in self.store.notebooks():
                n = len(self.store.list(name))
                it = QtWidgets.QListWidgetItem(icon("file", "#64748b", 16), f"  {name}")
                it.setData(Qt.UserRole, name)
                it.setToolTip(f"{n} note{'s' if n != 1 else ''}")
                self.books.addItem(it)
                if self.filter_book == name:
                    it.setSelected(True)
            if self.filter_book is None:
                self.lib.setCurrentRow(1 if self.filter_pinned else 0)

        def refresh_list(self, keep=True):
            q = self.search.text().strip()
            if q:
                rows = self.store.search(q, self.filter_book)
                if self.filter_pinned:
                    rows = [r for r in rows if r[0].pinned]
                self.list_title.setText("Search")
            else:
                notes = self.store.list(self.filter_book, self.filter_pinned)
                rows = [(n, n.snippet) for n in notes]
                self.list_title.setText(self.filter_book or ("Pinned" if self.filter_pinned else "All notes"))
            self.list.blockSignals(True)
            self.list.clear()
            for note, snip in rows:
                it = QtWidgets.QListWidgetItem()
                it.setData(Qt.UserRole, note.id)
                it.setSizeHint(QtCore.QSize(300, 92))
                self.list.addItem(it)
                card = NoteCard(note, snip, selected=self.current is not None and note.id == self.current.id)
                self.list.setItemWidget(it, card)
                if self.current is not None and note.id == self.current.id:
                    self.list.setCurrentItem(it)
            self.list.blockSignals(False)
            self.list_count.setText(str(len(rows)))

        def _update_card(self, note):
            for i in range(self.list.count()):
                it = self.list.item(i)
                w = self.list.itemWidget(it)
                if w is not None:
                    w.selected = self.current is not None and w.note.id == self.current.id
                    if w.note.id == note.id:
                        w.snippet = note.snippet
                    w.update()

        def _lib_clicked(self, item):
            self.books.clearSelection()
            key = item.data(Qt.UserRole)
            self.filter_book = None
            self.filter_pinned = key == "pinned"
            self.refresh_list()

        def _book_clicked(self, item):
            self.lib.clearSelection()
            self.filter_book = item.data(Qt.UserRole)
            self.filter_pinned = False
            self.refresh_list()

        def _book_menu(self, pos):
            it = self.books.itemAt(pos)
            if it is None:
                return
            name = it.data(Qt.UserRole)
            m = QtWidgets.QMenu(self)
            m.addAction("Rename…", lambda: self.rename_notebook(name))
            m.addAction("Delete (only when empty)", lambda: self.delete_notebook(name))
            m.exec_(self.books.mapToGlobal(pos))

        def _note_menu(self, pos):
            it = self.list.itemAt(pos)
            if it is None:
                return
            note = self.store.get(it.data(Qt.UserRole))
            if note is None:
                return
            m = QtWidgets.QMenu(self)
            m.addAction("Unpin" if note.pinned else "Pin", lambda: self.ctl.set_pinned(note, not note.pinned))
            m.addAction("Open as sticky note", lambda: self.ctl.open_sticky(note))
            m.addSeparator()
            m.addAction("Delete", lambda: self.delete_note(note))
            m.exec_(self.list.mapToGlobal(pos))

        def _note_selected(self, item, _prev):
            if item is None:
                return
            note = self.store.get(item.data(Qt.UserRole))
            if note is not None and (self.current is None or note.id != self.current.id):
                self.open_note(note)

        # ---- notes ----
        def show_empty(self):
            self.current = None
            for w in self.editor_widgets:
                w.hide()
            self.empty.show()
            self.saved.setText("")
            self.book_btn.setText("")

        def open_note(self, note):
            self.save_now()
            self.ai_panel.discard()
            prev = self.current
            self.current = note
            if prev is not None and prev is not note and self.store.discard_if_empty(prev):
                self.refresh_list()
            self.empty.hide()
            for w in self.editor_widgets:
                w.show()
            self.editor.blockSignals(True)
            self.editor.setPlainText(note.body)
            self.editor.blockSignals(False)
            self.editor.moveCursor(QtGui.QTextCursor.End)
            self._show_meta()
            self.update_preview()
            self._update_card(note)
            self.setWindowTitle(f"{note.title} — {APP_NAME}")

        def _show_meta(self):
            n = self.current
            if n is None:
                return
            self.book_btn.setText(" " + n.notebook)
            self.pin_btn.blockSignals(True)
            self.pin_btn.setChecked(n.pinned)
            self.pin_btn.setText(" Pinned" if n.pinned else " Pin")
            self.pin_btn.setIcon(pin_icon("#38bdf8" if n.pinned else "#cbd5e1", 15))
            self.pin_btn.blockSignals(False)
            self.sticky_btn.setChecked(bool(n.sticky.get("open")))
            for name, b in self.color_btns.items():
                b.setIcon(color_dot_icon(name, selected=(name == n.color)))
            self.saved.setText("  ·  Saved " + relative_time(n.modified))
            words = len(n.body.split())
            done, total = checklist_progress(n.body)
            extra = f"  ·  {done}/{total} done" if total else ""
            self.status.setText(f"{words} word{'s' if words != 1 else ''}  ·  {len(n.body)} characters{extra}")

        def new_note(self):
            book = self.filter_book or DEFAULT_NOTEBOOK
            note = self.store.new_note(book, "")
            self.search.clear()
            self.open_note(note)
            self.refresh_list()
            self.refresh_books()
            self.editor.setFocus()

        def _text_changed(self):
            if self.current is None:
                return
            self.save_timer.start(AUTOSAVE_MS)
            if self.mode != "edit":
                self.preview_timer.start(250)
            self.saved.setText("  ·  Editing…")

        def save_now(self):
            self.save_timer.stop()
            if self.current is None:
                return
            body = self.editor.toPlainText()
            changed = body != self.current.body
            old_title = self.current.title
            try:
                self.store.save(self.current, body)
            except OSError as exc:
                self.saved.setText(f"  ·  Not saved: {exc.strerror or exc}")
                return
            self._show_meta()
            self._update_card(self.current)
            if self.current.title != old_title:
                self.setWindowTitle(f"{self.current.title} — {APP_NAME}")
                self.refresh_list()
            if changed:
                self.ctl.note_changed(self.current, source=self)

        def reload_current(self):
            if self.current is None:
                return
            if self.editor.toPlainText() != self.current.body:
                pos = self.editor.textCursor().position()
                self.editor.blockSignals(True)
                self.editor.setPlainText(self.current.body)
                self.editor.blockSignals(False)
                c = self.editor.textCursor()
                c.setPosition(min(pos, len(self.current.body)))
                self.editor.setTextCursor(c)
                self.update_preview()
            self._show_meta()
            self.refresh_list()

        def delete_current(self):
            if self.current is not None:
                self.delete_note(self.current)

        def delete_note(self, note):
            r = QtWidgets.QMessageBox.question(
                self, "Delete note", f"Delete “{note.title}”?\n\nIt is moved to Documents › DevOS Notes › .trash.")
            if r != QtWidgets.QMessageBox.Yes:
                return
            self.ctl.close_sticky(note)
            if self.current is not None and note.id == self.current.id:
                self.save_timer.stop()
                self.current = None
            self.store.delete(note)
            self.refresh_list()
            self.refresh_books()
            rest = self.store.list(self.filter_book, self.filter_pinned)
            if rest:
                self.open_note(rest[0])
                self.refresh_list()
            else:
                self.show_empty()

        def toggle_pin(self, on):
            if self.current is not None:
                self.ctl.set_pinned(self.current, on)

        def toggle_sticky(self):
            if self.current is None:
                return
            self.save_now()
            if self.current.sticky.get("open") and self.ctl.stickies.get(self.current.id):
                self.ctl.close_sticky(self.current)
            else:
                self.ctl.open_sticky(self.current)
            self._show_meta()

        def _fill_move_menu(self):
            self.book_menu.clear()
            if self.current is None:
                return
            for name in self.store.notebooks():
                a = self.book_menu.addAction(("✓  " if name == self.current.notebook else "     ") + name)
                a.triggered.connect(lambda _c=False, n=name: self.move_to(n))
            self.book_menu.addSeparator()
            self.book_menu.addAction("New notebook…", lambda: self.new_notebook(move_current=True))

        def move_to(self, name):
            if self.current is None:
                return
            self.save_now()
            try:
                self.store.move(self.current, name)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(self, APP_NAME, f"Couldn't move the note: {exc}")
            self._show_meta()
            self.refresh_list()
            self.refresh_books()

        def new_notebook(self, move_current=False):
            name, ok = QtWidgets.QInputDialog.getText(self, "New notebook", "Name:")
            if not ok or not name.strip():
                return
            try:
                name = self.store.create_notebook(name)
            except ValueError as exc:
                QtWidgets.QMessageBox.information(self, APP_NAME, str(exc))
                return
            if move_current:
                self.move_to(name)
            self.refresh_books()

        def rename_notebook(self, name):
            new, ok = QtWidgets.QInputDialog.getText(self, "Rename notebook", "Name:", text=name)
            if not ok or not new.strip():
                return
            try:
                new = self.store.rename_notebook(name, new)
            except (ValueError, OSError) as exc:
                QtWidgets.QMessageBox.information(self, APP_NAME, str(exc))
                return
            if self.filter_book == name:
                self.filter_book = new
            self.refresh_books()
            self.refresh_list()
            self._show_meta()

        def delete_notebook(self, name):
            try:
                self.store.delete_notebook(name)
            except ValueError as exc:
                QtWidgets.QMessageBox.information(self, APP_NAME, str(exc))
                return
            if self.filter_book == name:
                self.filter_book = None
            self.refresh_books()
            self.refresh_list()

        # ---- view modes / preview ----
        def set_mode(self, mode):
            self.mode = mode
            self.seg[mode].setChecked(True)
            self.editor.setVisible(mode in ("edit", "split"))
            self.preview.setVisible(mode in ("split", "preview"))
            if mode == "split":
                half = max(200, self.split.width() // 2)
                self.split.setSizes([half, half])
            self.update_preview()

        def update_preview(self):
            if self.mode == "edit" or self.current is None:
                return
            sb = self.preview.verticalScrollBar().value()
            self.preview.document().setDefaultStyleSheet(PREVIEW_CSS)
            self.preview.setMarkdown(self.editor.toPlainText())
            self.preview.verticalScrollBar().setValue(sb)

        # ---- export ----
        def export_pdf(self):
            if self.current is None:
                return
            self.save_now()
            from PyQt5.QtPrintSupport import QPrinter
            default = os.path.join(documents_dir(), pdf_filename(self.current.title))
            path, _f = QtWidgets.QFileDialog.getSaveFileName(self, "Export to PDF", default, "PDF (*.pdf)")
            if not path:
                return
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            ok = export_pdf_file(self.current.body, path, QPrinter)
            self.status.setText(("Exported to " + path) if ok else "Couldn't export the PDF.")

        def reveal(self):
            if self.current is not None:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(
                    os.path.dirname(self.store.abspath(self.current))))

        # ---- AI ----
        def run_ai(self, key, label):
            if self.current is None:
                return
            body = self.editor.toPlainText()
            if not body.strip():
                self.status.setText("Write something first, then ask DevOS AI.")
                return
            sel = self.editor.textCursor().selectedText().replace(" ", "\n")
            self.ai_panel.start(key, label + (" · selection" if sel.strip() else ""), sel if sel.strip() else body)

        def _ai_insert(self, text):
            c = self.editor.textCursor()
            c.insertText(text)
            self.editor.setFocus()

        def _ai_append(self, text):
            body = self.editor.toPlainText().rstrip("\n")
            key = self.ai_panel.mode
            head = {"summarize": "\n\n## Summary\n", "todo": "\n\n## To-do\n"}.get(key, "\n\n" if key != "continue"
                                                                                    else " ")
            self.editor.setPlainText(body + head + text + "\n")
            self.editor.moveCursor(QtGui.QTextCursor.End)
            self.editor.setFocus()

        def _ai_replace(self, text):
            c = self.editor.textCursor()
            if c.hasSelection():
                c.insertText(text)
            else:
                c.select(QtGui.QTextCursor.Document)
                c.insertText(text)
            self.editor.setFocus()

        # ---- voice ----
        def toggle_voice(self):
            if self.dictation is not None:
                self.dictation.stop()
                return
            import voicetype
            problem = voicetype.voice_problem()
            if problem:
                self.status.setText(problem)
                return
            cfg = voicetype.load_config()
            self.dictation = voicetype.Dictation(cfg["language"], on_level=self.voice_bridge.level.emit)
            self.mic.set_recording(True)
            d = self.dictation

            def job():
                try:
                    text, problem = d.once()
                except Exception as exc:
                    text, problem = "", f"Voice note stopped: {exc}"
                self.voice_bridge.result.emit(text, problem)
            threading.Thread(target=job, daemon=True).start()

        def _voice_level(self, v):
            self.mic.level = v

        def _voice_result(self, text, problem):
            self.dictation = None
            self.mic.set_recording(False)
            if problem and not text:
                self.status.setText(problem)
                return
            if self.current is None:
                self.new_note()
            import voicetype
            c = self.editor.textCursor()
            before = self.editor.toPlainText()[:c.position()]
            c.insertText(voicetype.join_segment(before[-1:], text))
            self.editor.setFocus()

        def closeEvent(self, e):
            self.save_now()
            if self.current is not None and self.store.discard_if_empty(self.current):
                self.current = None
            if self.dictation is not None:
                self.dictation.stop()
            self.ai_panel.discard()
            self.ctl.main_closed()
            super().closeEvent(e)

    # -- controller: one process for the window and all sticky notes ------------
    class Controller(QtCore.QObject):
        def __init__(self, app, store):
            super().__init__()
            self.app = app
            self.store = store
            self.window = None
            self.stickies = {}
            self.server = None
            self.quitting = False      # logging out: keep sticky notes marked open for the next login
            app.aboutToQuit.connect(self._quitting)
            if hasattr(app, "commitDataRequest"):
                app.commitDataRequest.connect(self._quitting)

        def _quitting(self, *_a):
            self.quitting = True

        def listen(self):
            name = _socket_name()
            QLocalServer.removeServer(name)
            self.server = QLocalServer(self)
            self.server.setSocketOptions(QLocalServer.UserAccessOption)
            self.server.newConnection.connect(self._on_conn)
            self.server.listen(name)

        def _on_conn(self):
            sock = self.server.nextPendingConnection()
            if sock is None:
                return

            def read():
                cmd = bytes(sock.readAll()).decode("utf-8", "replace").strip()
                self.command(cmd)
                sock.disconnectFromServer()
            if sock.bytesAvailable():
                read()
            else:
                sock.readyRead.connect(read)

        def command(self, cmd):
            if cmd == "new-sticky":
                self.new_sticky()
            elif cmd == "stickies":
                self.restore_stickies()
            elif cmd == "new":
                self.show_window()
                self.window.new_note()
            else:
                self.show_window()

        def show_window(self):
            if self.window is None:
                self.window = NotesWindow(self)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
            return self.window

        def main_closed(self):
            QtCore.QTimer.singleShot(0, self._maybe_quit)

        def _maybe_quit(self):
            if (self.window is None or not self.window.isVisible()) and not self.stickies:
                self.app.quit()

        def note_changed(self, note, source=None):
            sw = self.stickies.get(note.id)
            if sw is not None and sw is not source:
                sw.reload()
            if self.window is not None and source is not self.window and self.window.current is not None \
                    and self.window.current.id == note.id:
                self.window.reload_current()
            elif self.window is not None and source is not self.window:
                self.window.refresh_list()

        def set_color(self, note, color):
            self.store.set_color(note, color)
            sw = self.stickies.get(note.id)
            if sw is not None:
                sw.apply_color()
            if self.window is not None:
                if self.window.current is note:
                    self.window._show_meta()
                self.window.refresh_list()

        def set_pinned(self, note, on):
            self.store.set_pinned(note, on)
            if self.window is not None:
                if self.window.current is note:
                    self.window._show_meta()
                self.window.refresh_list()

        def open_sticky(self, note):
            sw = self.stickies.get(note.id)
            if sw is None:
                sw = StickyWindow(self, note)
                sw.closed.connect(self._sticky_closed)
                sw.open_in_app.connect(self._open_from_sticky)
                sw.new_sticky.connect(self.new_sticky)
                self.stickies[note.id] = sw
                if note.sticky.get("x") is None:
                    scr = QtWidgets.QApplication.primaryScreen()
                    if scr is not None:
                        g = scr.availableGeometry()
                        k = len(self.stickies) - 1
                        sw.move(g.right() - sw.width() - 40 - 24 * k, g.top() + 60 + 30 * k)
            self.store.set_sticky(note, open=True)
            sw.show()
            sw.raise_()
            if self.window is not None:
                self.window.refresh_list()
                if self.window.current is note:
                    self.window._show_meta()
            return sw

        def close_sticky(self, note):
            sw = self.stickies.get(note.id)
            if sw is not None:
                sw.close()

        def _sticky_closed(self, nid):
            self.stickies.pop(nid, None)
            if self.window is not None:
                self.window.refresh_list()
                if self.window.current is not None and self.window.current.id == nid:
                    self.window._show_meta()
            QtCore.QTimer.singleShot(0, self._maybe_quit)

        def _open_from_sticky(self, nid):
            w = self.show_window()
            note = self.store.get(nid)
            if note is not None:
                w.open_note(note)
                w.refresh_list()

        def new_sticky(self):
            note = self.store.new_note(DEFAULT_NOTEBOOK, "", color="yellow")
            sw = self.open_sticky(note)
            sw.edit.setFocus()
            sw.activateWindow()
            if self.window is not None:
                self.window.refresh_list()
                self.window.refresh_books()
            return sw

        def restore_stickies(self):
            for note in self.store.open_stickies():
                self.open_sticky(note)
            return len(self.stickies)

    return QtCore, QtGui, QtWidgets, QLocalSocket, NotesWindow, StickyWindow, Controller


def export_pdf_file(body: str, path: str, QPrinter=None) -> bool:
    """Markdown body -> PDF with QPrinter (needs a QApplication)."""
    from PyQt5 import QtGui
    if QPrinter is None:
        from PyQt5.QtPrintSupport import QPrinter
    doc = QtGui.QTextDocument()
    doc.setDefaultStyleSheet(PRINT_CSS)
    doc.setMarkdown(body)
    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.PdfFormat)
    printer.setOutputFileName(path)
    printer.setDocName(title_of(body))
    printer.setCreator(APP_NAME)
    doc.print_(printer)
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _send_to_running(cmd: str, QLocalSocket) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(_socket_name())
    if not sock.waitForConnected(400):
        return False
    sock.write(cmd.encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    p = argparse.ArgumentParser(description="DevOS Notes")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--new", action="store_true", help="open with a new note")
    g.add_argument("--new-sticky", action="store_true", help="a new sticky note on the desktop")
    g.add_argument("--stickies", action="store_true", help="reopen the sticky notes that were open (login)")
    ns = p.parse_args(argv[1:])
    cmd = "new-sticky" if ns.new_sticky else "stickies" if ns.stickies else "new" if ns.new else "show"

    store = NoteStore()
    if ns.stickies:
        try:
            store.load()
        except OSError:
            return 0
        if not store.open_stickies():
            return 0                    # nothing to show: no resident process at login

    QtCore, QtGui, QtWidgets, QLocalSocket, NotesWindow, StickyWindow, Controller = _load_gui()
    sys.path.insert(0, os.path.join(COMPONENTS, "assistant"))
    import listen
    app = listen.make_app(argv)
    app.setApplicationName("devos-notes")
    app.setApplicationDisplayName("Notes")
    app.setDesktopFileName("devos-notes")
    if _send_to_running(cmd, QLocalSocket):
        return 0
    store.load()
    ctl = Controller(app, store)
    ctl.listen()
    if cmd == "stickies":
        if not ctl.restore_stickies():
            return 0
    elif cmd == "new-sticky":
        ctl.new_sticky()
    else:
        ctl.restore_stickies()
        w = ctl.show_window()
        if cmd == "new":
            w.new_note()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
