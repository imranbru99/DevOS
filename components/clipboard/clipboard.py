#!/usr/bin/env python3
"""
Clipboard history, the Windows Win+V habit.

KDE already remembers what you copy. This window shows that list (and a
small local copy) so a click puts one back and pastes it into the app you
were using. Nothing is uploaded.

    devos-clipboard            the window (Meta+V)
    devos-clipboard --list     print the saved clips
"""

import json
import os
import subprocess
import sys

MAX_ITEMS = 25
MAX_CHARS = 20000
STORE_NAME = "clipboard-history.json"


def add_entry(history, text):
    """Newest first. Blank and repeats of the newest clip are ignored."""
    raw = (text or "").replace("\x00", "").strip()
    if not raw:
        return list(history or [])
    if len(raw) > MAX_CHARS:
        raw = raw[:MAX_CHARS]
    items = [item for item in (history or []) if item != raw]
    items.insert(0, raw)
    return items[:MAX_ITEMS]


def merge_history(current, klipper, saved):
    """Klipper is newest-first. The live clipboard wins the top spot."""
    items = list(saved or [])
    for text in reversed(list(klipper or [])):
        items = add_entry(items, text)
    return add_entry(items, current)


def preview(text, width=80):
    one = " ".join((text or "").split())
    if len(one) <= width:
        return one
    return one[: width - 1] + "…"


def store_path(home=None):
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".local", "share", "DevOS", STORE_NAME)


def load_saved(home=None):
    try:
        with open(store_path(home), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, str) and item.strip()][:MAX_ITEMS]


def save_history(items, home=None):
    path = store_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"items": list(items)[:MAX_ITEMS]}, handle, ensure_ascii=False)
    os.replace(tmp, path)


def read_klipper(run):
    """Lines from the desktop's own clipboard, or [] when it is not there."""
    for exe in ("qdbus6", "qdbus", "qdbus-qt6"):
        try:
            result = run([exe, "org.kde.klipper", "/klipper", "getClipboardHistoryMenu"])
        except OSError:
            continue
        if result and getattr(result, "returncode", 1) == 0:
            text = getattr(result, "stdout", "") or ""
            return [line.strip() for line in text.splitlines() if line.strip()]
    return []


def read_clipboard(run):
    try:
        result = run(["xclip", "-selection", "clipboard", "-o"])
    except OSError:
        return ""
    if not result or getattr(result, "returncode", 1) != 0:
        return ""
    return getattr(result, "stdout", "") or ""


def active_window(run):
    try:
        result = run(["xdotool", "getactivewindow"])
    except OSError:
        return ""
    if not result or getattr(result, "returncode", 1) != 0:
        return ""
    return (getattr(result, "stdout", "") or "").strip()


def paste_commands(window_id):
    """Bring the previous app forward, then paste. Empty when we have no window."""
    if not window_id:
        return []
    return [
        ["xdotool", "windowactivate", "--sync", str(window_id)],
        ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
    ]


def set_clipboard_command(text):
    return ["xclip", "-selection", "clipboard"]


def refresh(home, run):
    items = merge_history(read_clipboard(run), read_klipper(run), load_saved(home))
    save_history(items, home)
    return items


def _run(argv, input_text=None):
    return subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=3)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--list" in argv:
        for i, text in enumerate(load_saved(), 1):
            print(f"{i}. {preview(text)}")
        return 0
    window = active_window(_run)
    items = refresh(None, _run)
    try:
        from PyQt5 import QtCore, QtGui, QtWidgets
    except ImportError:
        if not items:
            print("Nothing copied yet.")
        for i, text in enumerate(items, 1):
            print(f"{i}. {preview(text)}")
        return 0
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-clipboard")
    app.setApplicationDisplayName("Clipboard")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("devos-clipboard")
    win = _Window(items, window, QtCore, QtGui, QtWidgets)
    win.show()
    return app.exec_()


class _Window:
    """Filled in main() once PyQt5 is imported. Placeholder for the class built there."""


def _build_window(QtCore, QtGui, QtWidgets, items, window_id):
    class Window(QtWidgets.QDialog):
        def __init__(self):
            super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
            self.setWindowTitle("Clipboard")
            self.setStyleSheet(
                "QDialog{background:#0b0f1a;color:#e2e8f0;}"
                "QListWidget{background:#111827;border:1px solid #334155;border-radius:12px;padding:4px;}"
                "QListWidget::item{padding:8px;border-radius:8px;}"
                "QListWidget::item:selected{background:#1d4ed8;}"
                "QLabel{color:#94a3b8;}")
            self.resize(420, 360)
            layout = QtWidgets.QVBoxLayout(self)
            title = QtWidgets.QLabel("Clipboard")
            title.setStyleSheet("color:#e2e8f0;font-size:16px;font-weight:700;")
            layout.addWidget(title)
            self.list = QtWidgets.QListWidget()
            for text in items:
                item = QtWidgets.QListWidgetItem(preview(text, 90))
                item.setData(QtCore.Qt.UserRole, text)
                item.setToolTip(preview(text, 400))
                self.list.addItem(item)
            if not items:
                self.list.addItem("Nothing copied yet")
            self.list.itemActivated.connect(self._pick)
            layout.addWidget(self.list)
            layout.addWidget(QtWidgets.QLabel("Enter pastes into the app you were using. Esc closes."))
            if self.list.count() and items:
                self.list.setCurrentRow(0)
            geo = QtWidgets.QApplication.primaryScreen().availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)

        def keyPressEvent(self, event):
            if event.key() == QtCore.Qt.Key_Escape:
                self.close()
                return
            if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                self._pick(self.list.currentItem())
                return
            super().keyPressEvent(event)

        def _pick(self, item):
            if item is None:
                return
            text = item.data(QtCore.Qt.UserRole)
            if not text:
                return
            try:
                subprocess.run(set_clipboard_command(text), input=text, text=True, timeout=3)
            except OSError:
                pass
            self.close()
            for cmd in paste_commands(window_id):
                try:
                    subprocess.run(cmd, timeout=3)
                except OSError:
                    break

    return Window()


# Rebuild the placeholder so `main` can call one function.
def _Window(items, window_id, QtCore, QtGui, QtWidgets):
    return _build_window(QtCore, QtGui, QtWidgets, items, window_id)


if __name__ == "__main__":
    sys.exit(main())
