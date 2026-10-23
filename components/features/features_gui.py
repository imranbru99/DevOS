#!/usr/bin/env python3
"""
DevOS Features window: Windows' "Apps > Optional features" and "Default apps"
in one place.

  Apps & features  tick what you want (presets, search, categories), see the
                   download size, press "Apply changes". The work is done by
                   "pkexec devos-features set --only ..." (root); the window
                   follows it through state.json and the log.
  Default apps     pick which installed app opens documents, PDFs, links,
                   music, video and photos (xdg-mime for this account only).

Everything above the "GUI" section is plain stdlib and importable without a
display so it can be unit-tested on any OS. PyQt5 is imported only in main().
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import feature_catalog as catalog  # noqa: E402

APP_NAME = "DevOS Features"
CLI = "/usr/local/bin/devos-features"
STATE_FILE = "/var/lib/DevOS/features/state.json"
LOG_FILE = "/var/log/devos-features.log"
SYSTEM_APP_DIRS = (
    "/usr/share/applications",
    "/usr/local/share/applications",
    "/var/lib/flatpak/exports/share/applications",
)
LOG_TAIL_LINES = 14

# pkexec exits 126 when the person cancels the password prompt, 127 when
# authorisation fails; neither means anything was changed.
PKEXEC_CANCELLED = (126, 127)


# ---------------------------------------------------------------- catalog helpers

def feature_name(fid: str) -> str:
    feature = catalog.feature(fid)
    return feature["name"] if feature else fid


def format_size(mb: float) -> str:
    """650 -> "650 MB", 1536 -> "1.5 GB"."""
    if mb >= 1024:
        return f"{mb / 1024:.1f} GB"
    return f"{int(round(mb))} MB"


def cli_command(args, cli: str = CLI, here: str = HERE):
    """The devos-features command line; falls back to running the script
    next to this file when the /usr/local/bin wrapper is missing."""
    if os.path.exists(cli):
        return [cli] + list(args)
    return ["/usr/bin/python3", os.path.join(here, "features_cli.py")] + list(args)


def apply_command(selected, cli: str = CLI, here: str = HERE):
    """pkexec devos-features set --only a,b,c (catalog order, unknown ids dropped).
    "--only=" keeps an empty choice (everything unticked) a valid argument."""
    ids = catalog.parse_selection(",".join(selected))
    return ["pkexec"] + cli_command(["set", "--only=" + ",".join(ids)], cli, here)


def list_command(cli: str = CLI, here: str = HERE):
    return cli_command(["list", "--json"], cli, here)


def change_plan(selected, installed):
    """What Apply would do, plus the download size.

    Anything ticked that is not installed has to be downloaded, including a
    built-in that was removed earlier, so preinstalled items count too."""
    todo = catalog.plan(list(selected), list(installed))
    todo["download_mb"] = catalog.size_mb(todo["add"], only_downloads=False)
    return todo


def summary_text(selected, installed) -> str:
    todo = change_plan(selected, installed)
    if not todo["add"] and not todo["remove"]:
        return "No changes"
    return f"Download: {format_size(todo['download_mb'])} · Remove: {len(todo['remove'])}"


def preset_selection(preset: str, selected):
    """A preset button ticks that preset's apps on top of the current ticks.
    "Choose later" and "Minimal" keep only what is already on the PC."""
    current = set(selected)
    if preset == "later":
        return catalog.later_ids()
    if preset == "minimal":
        keep = {f["id"] for f in catalog.FEATURES if f["preinstalled"]}
        return [f["id"] for f in catalog.FEATURES if f["id"] in current & keep]
    if preset in catalog.USER_TYPE_PRESETS:
        return catalog.user_type_ids(preset)
    wanted = current | set(catalog.preset_ids(preset))
    return [f["id"] for f in catalog.FEATURES if f["id"] in wanted]


def matches(feature: dict, query: str) -> bool:
    """Search box: every word must appear in the id, name, about text,
    Windows equivalent or category title."""
    words = (query or "").lower().split()
    if not words:
        return True
    cat_title = dict(catalog.CATEGORIES).get(feature.get("category"), "")
    hay = " ".join([feature.get("id", ""), feature.get("name", ""), feature.get("about", ""),
                    feature.get("windows", ""), cat_title]).lower()
    return all(w in hay for w in words)


def grouped(features, query: str = ""):
    """[(category title, [features…]), …] in catalog order; empty groups dropped."""
    out = []
    for cat, title in catalog.CATEGORIES:
        items = [f for f in features if f.get("category") == cat and matches(f, query)]
        if items:
            out.append((title, items))
    return out


def parse_feature_list(text: str):
    """Output of "devos-features list --json" -> (installed ids, chosen ids).
    Returns (None, None) when the output is not usable."""
    try:
        rows = json.loads(text)
    except (TypeError, ValueError):
        return None, None
    if not isinstance(rows, list):
        return None, None
    installed = [r["id"] for r in rows if isinstance(r, dict) and r.get("installed")]
    chosen = [r["id"] for r in rows if isinstance(r, dict) and r.get("chosen")]
    return catalog.parse_selection(",".join(installed)), catalog.parse_selection(",".join(chosen))


# ---------------------------------------------------------------- progress state

def read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def tail_lines(path: str, count: int = LOG_TAIL_LINES):
    """Last `count` lines of a text file (reads only the end of big logs)."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 64 * 1024))
            data = handle.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    return [line for line in data.splitlines() if line.strip()][-count:]


def parse_state(state: dict) -> dict:
    """state.json -> what the window shows, with plain names instead of ids."""
    state = state if isinstance(state, dict) else {}
    pending = [p for p in state.get("pending") or [] if isinstance(p, str)]
    removing = [p for p in state.get("removing") or [] if isinstance(p, str)]
    failed = state.get("failed") or {}
    if not isinstance(failed, dict):
        failed = {}
    return {
        "running": bool(state.get("running")),
        "current": state.get("current") or "",
        "pending": pending,
        "pending_names": [feature_name(p) for p in pending],
        "removing": removing,
        "failed": [(fid, feature_name(fid), str(why)) for fid, why in failed.items()],
        "updated": state.get("updated") or 0,
    }


def progress_text(info: dict) -> str:
    if not info["running"]:
        return ""
    left = len(info["pending"])
    head = f"Working on {info['current']}…" if info["current"] else "Getting ready…"
    if left:
        return f"{head} {left} app{'s' if left != 1 else ''} left to download."
    return head


def failure_text(info: dict) -> str:
    """Plain words for what did not work, or "" when everything did."""
    if info["running"]:
        return ""
    lines = []
    for _fid, name, why in info["failed"]:
        if "removed" in why:
            lines.append(f"• {name} was kept, because removing it would also remove part of DevOS.")
        else:
            lines.append(f"• {name} could not be downloaded or installed.")
    failed_ids = {fid for fid, _n, _w in info["failed"]}
    waiting = [feature_name(p) for p in info["pending"] if p not in failed_ids]
    if waiting:
        lines.append("• Still waiting to download: " + ", ".join(waiting) + ".")
    if not lines:
        return ""
    return ("Some changes didn't finish:\n" + "\n".join(lines) +
            "\nCheck that you are connected to the internet, then press Try again. "
            "DevOS also retries downloads by itself the next time the PC starts.")


def finished_text(code: int, info: dict) -> str:
    if code in PKEXEC_CANCELLED:
        return "Nothing changed (administrator approval was cancelled)."
    if code == 0 and not info["failed"] and not info["pending"]:
        return "All done. Your apps are ready."
    return ""


# ---------------------------------------------------------------- default apps

def app_dirs(home: str = None):
    home = home if home is not None else os.path.expanduser("~")
    return list(SYSTEM_APP_DIRS) + [os.path.join(home, ".local", "share", "applications")]


def find_desktop(desktop: str, dirs):
    """Full path of the first existing desktop file, or None."""
    for folder in dirs:
        path = os.path.join(folder, desktop)
        if os.path.isfile(path):
            return path
    return None


def desktop_display_name(text: str, fallback: str) -> str:
    """Name= from the [Desktop Entry] section of a .desktop file's text."""
    section = ""
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[Desktop Entry]" and line.startswith("Name="):
            return line[5:].strip() or fallback
    return fallback


def handlers_for_role(role: str, installed, dirs):
    """[(desktop file, label), …] that can be the default for `role`: installed
    features (catalog order) then the always-there built-ins, keeping only
    desktop files that really exist in one of `dirs`."""
    candidates = []
    have = set(installed)
    for feature in catalog.FEATURES:
        if feature["id"] in have and role in feature["roles"]:
            candidates.append((feature["roles"][role], feature["name"]))
    candidates += list(catalog.BUILT_IN_HANDLERS.get(role, []))
    out, seen = [], set()
    for desktop, label in candidates:
        if desktop in seen:
            continue
        path = find_desktop(desktop, dirs)
        if not path:
            continue
        seen.add(desktop)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                label = desktop_display_name(handle.read(), label)
        except OSError:
            pass
        out.append((desktop, label))
    return out


def query_default_command(role: str):
    return ["xdg-mime", "query", "default", catalog.ROLES[role][0]]


def set_default_commands(role: str, desktop: str):
    """Commands (no root) that make `desktop` the default for every type of `role`."""
    cmds = [["xdg-mime", "default", desktop, mime] for mime in catalog.ROLES[role]]
    if role == "browser":
        cmds.append(["xdg-settings", "set", "default-web-browser", desktop])
    return cmds


def current_default(role: str) -> str:
    try:
        out = subprocess.run(query_default_command(role), capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""


def set_default(role: str, desktop: str) -> bool:
    ok = True
    for cmd in set_default_commands(role, desktop):
        try:
            ok = subprocess.run(cmd, capture_output=True, timeout=15).returncode == 0 and ok
        except (OSError, subprocess.SubprocessError):
            ok = False
    return ok


# ---------------------------------------------------------------- GUI

STYLE = """
QWidget { background: #0b0f1a; color: #e2e8f0; font-size: 14px; }
QLabel#title { font-size: 24px; font-weight: 600; color: #f8fafc; }
QLabel#section { font-size: 17px; font-weight: 600; color: #f8fafc; padding-top: 10px; }
QLabel#muted { color: #94a3b8; }
QFrame#card QLabel#tag { background: #1e293b; color: #7dd3fc; border-radius: 6px; padding: 2px 8px; font-size: 12px; }
QFrame#card QLabel#badge { background: #064e3b; color: #6ee7b7; border-radius: 6px; padding: 2px 8px; font-size: 12px; }
QLabel#size { color: #94a3b8; font-size: 13px; }
QLabel#error { color: #fca5a5; }
QFrame#card { background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; }
QFrame#footer { background: #0f172a; border-top: 1px solid #1e293b; }
QFrame#footer QLabel { background: transparent; }
QCheckBox { font-weight: 600; color: #f8fafc; spacing: 10px; }
QCheckBox::indicator { width: 18px; height: 18px; border: 2px solid #475569; border-radius: 5px; background: #0b0f1a; }
QCheckBox::indicator:hover { border-color: #38bdf8; }
QCheckBox::indicator:checked { background: #38bdf8; border-color: #38bdf8; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #334155; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QPushButton { background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 7px 14px; }
QPushButton:hover { border-color: #38bdf8; }
QPushButton#primary { background: #0284c7; border-color: #38bdf8; color: white; }
QPushButton:disabled, QPushButton#primary:disabled { color: #64748b; background: #111827; border-color: #1e293b; }
QProgressBar { background: #0f172a; border: 1px solid #1e293b; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #38bdf8; border-radius: 6px; }
QLineEdit, QComboBox { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 6px; }
QPlainTextEdit { background: #020617; border: 1px solid #1e293b; border-radius: 8px;
                 font-family: monospace; font-size: 12px; color: #cbd5e1; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #94a3b8; padding: 8px 18px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #f8fafc; border-bottom: 2px solid #38bdf8; }
QScrollArea { border: none; }
"""


def build_window(QtCore, QtWidgets):
    """The window class, built once PyQt5 is imported (keeps tests Qt-free)."""

    class FeaturesWindow(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(APP_NAME)
            self.resize(980, 780)
            self.setMinimumSize(720, 560)
            self.setStyleSheet(STYLE)
            self.installed = []
            self.selected = catalog.parse_selection(",".join(
                f["id"] for f in catalog.FEATURES if f["preinstalled"]))
            self.loaded = False
            self.proc = None
            self.list_proc = None
            self.boxes = {}
            self.cards = {}
            self.badges = {}
            self.headers = []
            self.chosen = []
            self.was_outside = False
            self.checked_old_failures = False

            root = QtWidgets.QVBoxLayout(self)
            root.setContentsMargins(0, 0, 0, 0)
            root.setSpacing(0)
            self.tabs = QtWidgets.QTabWidget()
            self.tabs.addTab(self._apps_tab(), "Apps && features")
            self.tabs.addTab(self._defaults_tab(), "Default apps")
            self.tabs.currentChanged.connect(lambda i: i == 1 and self.refresh_defaults())
            root.addWidget(self.tabs)

            self.timer = QtCore.QTimer(self)
            self.timer.timeout.connect(self.poll_state)
            self.timer.start(1500)
            self.poll_state()
            self.refresh_installed()

        # ------------------------------------------------ Apps & features
        def _apps_tab(self):
            page = QtWidgets.QWidget()
            outer = QtWidgets.QVBoxLayout(page)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)

            top = QtWidgets.QWidget()
            head = QtWidgets.QVBoxLayout(top)
            head.setContentsMargins(24, 18, 24, 8)
            title = QtWidgets.QLabel("Apps & features")
            title.setObjectName("title")
            head.addWidget(title)
            intro = QtWidgets.QLabel(
                "Tick the apps you want, or start from a category: Normal, Professional, Student, "
                "Development, Creator, Gamer, Business, Family, Normal + Islamic, or Premium. "
                "You can add an app you skipped, or remove one you don't need, and you can ask DevOS AI "
                "the same thing, for example “install Zoom” or “uninstall Spotify”. "
                "Press Apply changes to download what is new; you can keep using the PC.")
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            head.addWidget(intro)

            presets = QtWidgets.QHBoxLayout()
            presets.setSpacing(8)
            label = QtWidgets.QLabel("Quick picks:")
            label.setObjectName("muted")
            presets.addWidget(label)
            for pid, name, about in catalog.PRESETS:
                button = QtWidgets.QPushButton(name.replace(" (recommended)", ""))
                button.setToolTip(about)
                button.clicked.connect(lambda _c=False, p=pid: self.use_preset(p))
                presets.addWidget(button)
            presets.addStretch(1)
            head.addLayout(presets)

            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Search apps, e.g. word, photoshop, whatsapp…")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self.apply_filter)
            head.addWidget(self.search)
            outer.addWidget(top)

            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            body = QtWidgets.QWidget()
            self.list_layout = QtWidgets.QVBoxLayout(body)
            self.list_layout.setContentsMargins(24, 4, 24, 16)
            self.list_layout.setSpacing(8)
            for cat, title_text in catalog.CATEGORIES:
                items = [f for f in catalog.FEATURES if f["category"] == cat]
                if not items:
                    continue
                header = QtWidgets.QLabel(title_text)
                header.setObjectName("section")
                self.list_layout.addWidget(header)
                self.headers.append((header, [f["id"] for f in items]))
                for feature in items:
                    self.list_layout.addWidget(self._card(feature))
            self.no_match = QtWidgets.QLabel("No apps match your search.")
            self.no_match.setObjectName("muted")
            self.no_match.hide()
            self.list_layout.addWidget(self.no_match)
            self.list_layout.addStretch(1)
            scroll.setWidget(body)
            outer.addWidget(scroll, 1)

            outer.addWidget(self._progress_area())

            footer = QtWidgets.QFrame()
            footer.setObjectName("footer")
            row = QtWidgets.QHBoxLayout(footer)
            row.setContentsMargins(24, 12, 24, 12)
            self.summary = QtWidgets.QLabel("Checking what's installed…")
            self.summary.setObjectName("muted")
            row.addWidget(self.summary, 1)
            self.reset = QtWidgets.QPushButton("Undo my ticks")
            self.reset.clicked.connect(self.undo_ticks)
            row.addWidget(self.reset)
            self.apply_button = QtWidgets.QPushButton("Apply changes")
            self.apply_button.setObjectName("primary")
            self.apply_button.clicked.connect(self.apply_changes)
            row.addWidget(self.apply_button)
            outer.addWidget(footer)
            return page

        def _card(self, feature):
            card = QtWidgets.QFrame()
            card.setObjectName("card")
            lay = QtWidgets.QVBoxLayout(card)
            lay.setContentsMargins(14, 10, 14, 10)
            lay.setSpacing(4)
            top = QtWidgets.QHBoxLayout()
            top.setSpacing(8)
            box = QtWidgets.QCheckBox(feature["name"])
            box.setChecked(feature["id"] in self.selected)
            box.toggled.connect(lambda on, fid=feature["id"]: self.tick(fid, on))
            top.addWidget(box)
            if feature["windows"]:
                tag = QtWidgets.QLabel("Like: " + feature["windows"])
                tag.setObjectName("tag")
                top.addWidget(tag)
            badge = QtWidgets.QLabel("Installed")
            badge.setObjectName("badge")
            badge.hide()
            top.addWidget(badge)
            top.addStretch(1)
            size = QtWidgets.QLabel(format_size(feature["size_mb"]))
            size.setObjectName("size")
            top.addWidget(size)
            lay.addLayout(top)
            about = QtWidgets.QLabel(feature["about"])
            about.setObjectName("muted")
            about.setWordWrap(True)
            about.setContentsMargins(30, 0, 0, 0)
            lay.addWidget(about)
            self.boxes[feature["id"]] = box
            self.cards[feature["id"]] = card
            self.badges[feature["id"]] = badge
            return card

        def _progress_area(self):
            frame = QtWidgets.QFrame()
            frame.setObjectName("card")
            lay = QtWidgets.QVBoxLayout(frame)
            lay.setContentsMargins(16, 10, 16, 10)
            lay.setSpacing(6)
            self.progress_label = QtWidgets.QLabel("")
            self.progress_label.setWordWrap(True)
            self.progress_label.hide()
            self.progress_label.setText = self._label_setter(self.progress_label)
            lay.addWidget(self.progress_label)
            self.bar = QtWidgets.QProgressBar()
            self.bar.setRange(0, 0)
            self.bar.setTextVisible(False)
            self.bar.setMaximumHeight(10)
            lay.addWidget(self.bar)
            self.log_view = QtWidgets.QPlainTextEdit()
            self.log_view.setReadOnly(True)
            self.log_view.setFixedHeight(84)
            lay.addWidget(self.log_view)
            fail_row = QtWidgets.QHBoxLayout()
            self.fail_label = QtWidgets.QLabel("")
            self.fail_label.setObjectName("error")
            self.fail_label.setWordWrap(True)
            self.fail_label.hide()
            self.fail_label.setText = self._label_setter(self.fail_label)
            fail_row.addWidget(self.fail_label, 1)
            self.retry = QtWidgets.QPushButton("Try again")
            self.retry.clicked.connect(self.apply_changes)
            fail_row.addWidget(self.retry, 0, QtCore.Qt.AlignTop)
            lay.addLayout(fail_row)
            self.progress_frame = frame
            wrap = QtWidgets.QWidget()
            wl = QtWidgets.QVBoxLayout(wrap)
            wl.setContentsMargins(24, 6, 24, 6)
            wl.addWidget(frame)
            wrap.hide()
            self.progress_wrap = wrap
            return wrap

        @staticmethod
        def _label_setter(label):
            """setText that also hides the label while it is empty."""
            original = label.setText

            def set_text(text):
                original(text)
                label.setVisible(bool(text))
            return set_text

        def tick(self, fid, on):
            wanted = set(self.selected)
            (wanted.add if on else wanted.discard)(fid)
            self.selected = catalog.parse_selection(",".join(wanted))
            self.update_summary()

        def set_ticks(self, ids):
            self.selected = catalog.parse_selection(",".join(ids))
            for fid, box in self.boxes.items():
                box.blockSignals(True)
                box.setChecked(fid in self.selected)
                box.blockSignals(False)
            self.update_summary()

        def use_preset(self, preset):
            self.set_ticks(preset_selection(preset, self.selected))

        def undo_ticks(self):
            self.set_ticks(self.chosen if self.loaded else self.selected)

        def apply_filter(self, text):
            shown = 0
            for fid, card in self.cards.items():
                visible = matches(catalog.feature(fid), text)
                card.setVisible(visible)
                shown += visible
            for header, ids in self.headers:
                header.setVisible(any(matches(catalog.feature(i), text) for i in ids))
            self.no_match.setVisible(shown == 0)

        def busy(self):
            return self.proc is not None or parse_state(read_json(STATE_FILE))["running"]

        def update_summary(self):
            if not self.loaded:
                return
            text = summary_text(self.selected, self.installed)
            self.summary.setText(text)
            nothing = text == "No changes"
            self.apply_button.setEnabled(not nothing and not self.busy())
            self.reset.setEnabled(set(self.selected) != set(self.chosen))

        # ------------------------------------------------ installed state
        def refresh_installed(self):
            if self.list_proc is not None:
                return
            cmd = list_command()
            self.list_proc = QtCore.QProcess(self)
            self.list_proc.finished.connect(self._installed_loaded)
            self.list_proc.start(cmd[0], cmd[1:])

        def _installed_loaded(self, *_args):
            text = bytes(self.list_proc.readAllStandardOutput()).decode(errors="replace")
            self.list_proc = None
            installed, chosen = parse_feature_list(text)
            if installed is None:
                self.summary.setText("Could not check which apps are installed.")
                return
            first = not self.loaded
            self.installed, self.chosen, self.loaded = installed, chosen, True
            for fid, badge in self.badges.items():
                badge.setVisible(fid in installed)
            if first or self.proc is None:
                self.set_ticks(chosen)
            self.update_summary()
            if self.tabs.currentIndex() == 1:
                self.refresh_defaults()

        # ------------------------------------------------ apply + progress
        def apply_changes(self):
            if self.busy():
                return
            cmd = apply_command(self.selected)
            self.apply_button.setEnabled(False)
            self.retry.setEnabled(False)
            self.fail_label.setText("")
            self.progress_label.setText("Waiting for administrator approval…")
            self.progress_wrap.show()
            self.started = time.time()
            self.proc = QtCore.QProcess(self)
            self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
            self.proc.readyReadStandardOutput.connect(
                lambda: self.proc and self.proc.readAllStandardOutput())
            self.proc.finished.connect(self._applied)
            self.proc.start(cmd[0], cmd[1:])

        def _applied(self, code, _status=None):
            self.proc = None
            # New apps (Flatpaks especially) only appear in the Start menu after
            # KDE rebuilds its menu cache.
            QtCore.QProcess.startDetached("kbuildsycoca5", ["--noincremental"])
            info = parse_state(read_json(STATE_FILE))
            self.retry.setEnabled(True)
            done = finished_text(code, info)
            fail = "" if code in PKEXEC_CANCELLED else failure_text(info)
            if not fail and code not in (0,) + PKEXEC_CANCELLED:
                fail = ("Something went wrong while applying your changes. "
                        "Press Try again, or see the details above.")
            self.progress_label.setText(done)
            self.fail_label.setText(fail)
            self.bar.hide()
            self.retry.setVisible(bool(fail))
            self.log_view.setVisible(bool(fail))
            if not done and not fail:
                self.progress_wrap.hide()
            self.refresh_installed()

        def poll_state(self):
            info = parse_state(read_json(STATE_FILE))
            outside = info["running"] and self.proc is None
            if self.proc is not None or outside:
                self.progress_wrap.show()
                self.bar.show()
                self.log_view.show()
                self.retry.hide()
                self.fail_label.setText("")
                text = progress_text(info)
                if outside:
                    text = ("DevOS is still setting up the apps you picked during install. "
                            "You can change your choice when it is done.\n" + text)
                if text:
                    self.progress_label.setText(text)
                lines = tail_lines(LOG_FILE)
                joined = "\n".join(lines)
                if joined != self.log_view.toPlainText():
                    self.log_view.setPlainText(joined)
                    bar = self.log_view.verticalScrollBar()
                    bar.setValue(bar.maximum())
                self.was_outside = outside
            elif self.was_outside:
                # A first-boot download finished while the window was open.
                self.was_outside = False
                self.bar.hide()
                fail = failure_text(info)
                self.progress_label.setText("" if fail else "All done. Your apps are ready.")
                self.fail_label.setText(fail)
                self.retry.setVisible(bool(fail))
                self.refresh_installed()
            elif not self.checked_old_failures:
                # Opening the window after a failed run: say so right away.
                self.checked_old_failures = True
                fail = failure_text(info)
                if fail:
                    self.progress_wrap.show()
                    self.bar.hide()
                    self.log_view.hide()
                    self.fail_label.setText(fail)
                    self.retry.show()
            self.update_summary()

        # ------------------------------------------------ Default apps
        def _defaults_tab(self):
            page = QtWidgets.QWidget()
            outer = QtWidgets.QVBoxLayout(page)
            outer.setContentsMargins(0, 0, 0, 0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            body = QtWidgets.QWidget()
            lay = QtWidgets.QVBoxLayout(body)
            lay.setContentsMargins(24, 18, 24, 18)
            lay.setSpacing(10)
            title = QtWidgets.QLabel("Default apps")
            title.setObjectName("title")
            lay.addWidget(title)
            intro = QtWidgets.QLabel(
                "Choose which app opens each kind of file or link. This only changes your account. "
                "Only installed apps are listed; add more in Apps & features.")
            intro.setObjectName("muted")
            intro.setWordWrap(True)
            lay.addWidget(intro)
            self.combos = {}
            for role, name in catalog.ROLE_NAMES.items():
                card = QtWidgets.QFrame()
                card.setObjectName("card")
                row = QtWidgets.QHBoxLayout(card)
                row.setContentsMargins(16, 10, 16, 10)
                label = QtWidgets.QLabel(name)
                label.setStyleSheet("font-weight: 600; color: #f8fafc; background: transparent;")
                row.addWidget(label, 1)
                combo = QtWidgets.QComboBox()
                combo.setMinimumWidth(320)
                combo.activated.connect(lambda _i, r=role: self.default_changed(r))
                row.addWidget(combo)
                self.combos[role] = combo
                lay.addWidget(card)
            self.default_status = QtWidgets.QLabel("")
            self.default_status.setObjectName("muted")
            self.default_status.setWordWrap(True)
            lay.addWidget(self.default_status)
            lay.addStretch(1)
            scroll.setWidget(body)
            outer.addWidget(scroll)
            return page

        def refresh_defaults(self):
            dirs = app_dirs()
            for role, combo in self.combos.items():
                handlers = handlers_for_role(role, self.installed, dirs)
                current = current_default(role)
                if current and current not in [d for d, _l in handlers]:
                    path = find_desktop(current, dirs)
                    label = current[:-8] if current.endswith(".desktop") else current
                    if path:
                        try:
                            with open(path, encoding="utf-8", errors="replace") as handle:
                                label = desktop_display_name(handle.read(), label)
                        except OSError:
                            pass
                    handlers.insert(0, (current, label))
                combo.blockSignals(True)
                combo.clear()
                if not handlers:
                    combo.addItem("No app installed for this", "")
                    combo.setEnabled(False)
                else:
                    combo.setEnabled(True)
                    for desktop, label in handlers:
                        combo.addItem(label, desktop)
                    index = combo.findData(current)
                    if index < 0:
                        combo.insertItem(0, "Not set", "")
                        index = 0
                    combo.setCurrentIndex(index)
                combo.blockSignals(False)

        def default_changed(self, role):
            desktop = self.combos[role].currentData()
            if not desktop:
                return
            name = self.combos[role].currentText()
            if set_default(role, desktop):
                self.default_status.setText(f"{catalog.ROLE_NAMES[role]} now open with {name}.")
            else:
                self.default_status.setText(f"Could not make {name} the default for "
                                            f"{catalog.ROLE_NAMES[role]}.")
            self.refresh_defaults()

    return FeaturesWindow


def main():
    from PyQt5 import QtCore, QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-features")
    app.setApplicationDisplayName("DevOS Features")
    app.setDesktopFileName("devos-features")
    window = build_window(QtCore, QtWidgets)()
    window.show()
    if os.environ.get("DEVOS_FEATURES_SCREENSHOT"):
        def grab():
            window.grab().save(os.environ["DEVOS_FEATURES_SCREENSHOT"])
            if os.environ.get("DEVOS_FEATURES_SCREENSHOT2"):
                window.tabs.setCurrentIndex(1)
                app.processEvents()
                window.grab().save(os.environ["DEVOS_FEATURES_SCREENSHOT2"])
            app.quit()
        QtCore.QTimer.singleShot(2500, grab)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
