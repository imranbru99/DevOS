#!/usr/bin/env python3
"""
Emoji panel, the Windows Win+. habit.

A search box and the emoji people actually send. The choice is copied and
pasted into the app you were using. The list lives on this PC.

    devos-emoji            the window (Meta+.)
    devos-emoji --search heart
"""

import json
import os
import subprocess
import sys

# (emoji, search words). Order is the default grid: most used first.
CATALOG = (
    ("😀", "smile happy grin"),
    ("😁", "smile happy teeth"),
    ("😂", "joy laugh lol cry"),
    ("🤣", "rofl laugh lol"),
    ("😊", "blush smile happy"),
    ("😍", "love heart eyes"),
    ("😘", "kiss love"),
    ("😎", "cool sunglasses"),
    ("🤩", "star eyes wow"),
    ("🤔", "think thinking"),
    ("😅", "sweat smile nervous"),
    ("😢", "cry sad tear"),
    ("😭", "sob cry sad"),
    ("😡", "angry mad"),
    ("🥺", "please puppy eyes"),
    ("😴", "sleep tired"),
    ("🤗", "hug"),
    ("👍", "yes ok like thumb up"),
    ("👎", "no dislike thumb down"),
    ("👏", "clap applause"),
    ("🙏", "thanks please pray"),
    ("👌", "ok perfect"),
    ("👋", "wave hello bye"),
    ("💪", "strong muscle"),
    ("✌️", "peace victory"),
    ("🤝", "handshake deal"),
    ("❤️", "heart love red"),
    ("🧡", "heart orange love"),
    ("💛", "heart yellow love"),
    ("💚", "heart green love"),
    ("💙", "heart blue love"),
    ("💜", "heart purple love"),
    ("🖤", "heart black"),
    ("💔", "heart broken"),
    ("💕", "hearts love"),
    ("🔥", "fire lit hot"),
    ("✨", "sparkle star"),
    ("⭐", "star"),
    ("🎉", "party celebrate tada"),
    ("🎂", "cake birthday"),
    ("🎁", "gift present"),
    ("🌹", "rose flower"),
    ("🌸", "flower blossom"),
    ("☀️", "sun sunny weather"),
    ("🌙", "moon night"),
    ("☔", "rain umbrella weather"),
    ("❄️", "snow cold"),
    ("🍕", "pizza food"),
    ("🍔", "burger food"),
    ("🍟", "fries food"),
    ("☕", "coffee tea drink"),
    ("🍵", "tea cha drink"),
    ("🍚", "rice food"),
    ("🍛", "curry rice food"),
    ("🍰", "cake sweet"),
    ("🍫", "chocolate"),
    ("⚽", "football soccer"),
    ("🏀", "basketball"),
    ("🎮", "game controller"),
    ("🎵", "music note song"),
    ("🎧", "headphones music"),
    ("📷", "camera photo"),
    ("📱", "phone mobile"),
    ("💻", "laptop computer"),
    ("💡", "idea light"),
    ("📚", "books study"),
    ("✏️", "pencil write"),
    ("📌", "pin"),
    ("📎", "paperclip"),
    ("✅", "check done yes"),
    ("❌", "cross no"),
    ("⚠️", "warning"),
    ("💯", "100 hundred perfect"),
    ("🚀", "rocket launch"),
    ("🏠", "home house"),
    ("🚗", "car"),
    ("✈️", "plane flight travel"),
    ("🇧🇩", "bangladesh flag bd"),
    ("🏳️", "flag white"),
    ("😀", "grin"),
)

# The first grin is enough; drop the duplicate at the end of the tuple above
# by building a unique list once.
def _unique(catalog):
    seen = set()
    out = []
    for glyph, words in catalog:
        if glyph in seen:
            continue
        seen.add(glyph)
        out.append((glyph, words))
    return tuple(out)


CATALOG = _unique(CATALOG)
RECENT_MAX = 16
STORE_NAME = "emoji-recent.json"


def search(query, catalog=CATALOG, limit=48):
    q = (query or "").strip().lower()
    if not q:
        return [glyph for glyph, _words in catalog][:limit]
    hits = []
    for glyph, words in catalog:
        if q in words or q in glyph:
            hits.append(glyph)
        if len(hits) >= limit:
            break
    return hits


def visible(query, recent=(), catalog=CATALOG, limit=42):
    """Recents first when the box is empty. A search looks through the catalog."""
    if (query or "").strip():
        return search(query, catalog, limit)
    glyphs = []
    for glyph in recent or []:
        if glyph not in glyphs:
            glyphs.append(glyph)
    for glyph, _words in catalog:
        if glyph not in glyphs:
            glyphs.append(glyph)
        if len(glyphs) >= limit:
            break
    return glyphs[:limit]


def remember(recent, glyph):
    items = [item for item in (recent or []) if item != glyph]
    items.insert(0, glyph)
    return items[:RECENT_MAX]


def store_path(home=None):
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".local", "share", "DevOS", STORE_NAME)


def load_recent(home=None):
    try:
        with open(store_path(home), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    items = data.get("recent") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, str)][:RECENT_MAX]


def save_recent(items, home=None):
    path = store_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"recent": list(items)[:RECENT_MAX]}, handle, ensure_ascii=False)
    os.replace(tmp, path)


def _run(argv, input_text=None):
    return subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=3)


def _active_window():
    try:
        result = _run(["xdotool", "getactivewindow"])
    except OSError:
        return ""
    if not result or result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _deliver(glyph, window_id):
    try:
        subprocess.run(["xclip", "-selection", "clipboard"], input=glyph, text=True, timeout=3)
    except OSError:
        pass
    if not window_id:
        return
    for cmd in (
        ["xdotool", "windowactivate", "--sync", str(window_id)],
        ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
    ):
        try:
            subprocess.run(cmd, timeout=3)
        except OSError:
            break


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    query = ""
    if "--search" in argv:
        at = argv.index("--search")
        query = argv[at + 1] if at + 1 < len(argv) else ""
        for glyph in search(query):
            print(glyph, end=" ")
        print()
        return 0
    window = _active_window()
    recent = load_recent()
    try:
        from PyQt5 import QtCore, QtWidgets
    except ImportError:
        print(" ".join(visible("", recent)))
        return 0
    app = QtWidgets.QApplication(sys.argv)
    win = _panel(QtCore, QtWidgets, recent, window)
    win.show()
    return app.exec_()


def _panel(QtCore, QtWidgets, recent, window_id):
    class Panel(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
            self.setWindowTitle("Emoji")
            self.setStyleSheet(
                "QDialog{background:#0b0f1a;color:#e2e8f0;}"
                "QLineEdit{background:#111827;border:1px solid #334155;border-radius:10px;padding:8px;color:#e2e8f0;}"
                "QToolButton{font-size:22px;background:transparent;border-radius:8px;padding:4px;}"
                "QToolButton:hover{background:#1e293b;}"
                "QLabel{color:#94a3b8;}")
            self.resize(420, 340)
            self.recent = list(recent)
            layout = QtWidgets.QVBoxLayout(self)
            title = QtWidgets.QLabel("Emoji")
            title.setStyleSheet("color:#e2e8f0;font-size:16px;font-weight:700;")
            layout.addWidget(title)
            self.box = QtWidgets.QLineEdit()
            self.box.setPlaceholderText("Search: love, laugh, bd, food…")
            self.box.textChanged.connect(self._fill)
            layout.addWidget(self.box)
            self.grid_host = QtWidgets.QWidget()
            self.grid = QtWidgets.QGridLayout(self.grid_host)
            self.grid.setSpacing(2)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.grid_host)
            scroll.setStyleSheet("QScrollArea{border:0;}")
            layout.addWidget(scroll)
            layout.addWidget(QtWidgets.QLabel("Click one to paste it. Esc closes."))
            self._fill("")
            self.box.setFocus()
            geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Escape:
                self.close()
                return
            super().keyPressEvent(event)

        def _fill(self, query):
            while self.grid.count():
                child = self.grid.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            glyphs = visible(query, self.recent)
            if not glyphs:
                empty = QtWidgets.QLabel("No emoji for that.")
                self.grid.addWidget(empty, 0, 0)
                return
            for index, glyph in enumerate(glyphs):
                button = QtWidgets.QToolButton()
                button.setText(glyph)
                button.clicked.connect(lambda _checked=False, g=glyph: self._choose(g))
                self.grid.addWidget(button, index // 8, index % 8)

        def _choose(self, glyph):
            self.recent = remember(self.recent, glyph)
            save_recent(self.recent)
            self.close()
            _deliver(glyph, window_id)

    return Panel()


if __name__ == "__main__":
    sys.exit(main())
