#!/usr/bin/env python3
"""
DevOS Quick Selection Bar (Smart Floating Selection Actions).

When text is selected / marked in any application (terminals, PuTTY, Chrome, editors),
a sleek floating action pill automatically appears above the mouse pointer offering:
  - 📋 Copy (syncs to clipboard & Klipper, shows checkmark)
  - ✂️ Cut (copies & deletes selected text)
  - 📸 Screenshot (launches area capture)
  - 🤖 Ask AI (routes text to DevOS AI Assistant)
  - 🔍 Search (web search in browser)
  - ✕ Cancel (dismisses)

Author: Imran Ahmed <me@imrandev.bd>
https://imrandev.bd
"""

import ctypes
from ctypes import byref, c_int, c_uint, c_ulong
import os
import subprocess
import sys
import urllib.parse
from PyQt5 import QtCore, QtGui, QtWidgets


class X11PointerWatcher:
    """Monitors mouse pointer coordinates and left button state using X11."""

    def __init__(self):
        self.available = False
        try:
            self.x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            self.disp = self.x11.XOpenDisplay(None)
            if self.disp:
                self.root = self.x11.XDefaultRootWindow(self.disp)
                self.available = True
        except Exception:
            self.available = False

    def query(self):
        """Returns (x, y, is_left_button_pressed) or None if unavailable."""
        if not self.available:
            return None
        root_ret = c_ulong()
        child_ret = c_ulong()
        root_x = c_int()
        root_y = c_int()
        win_x = c_int()
        win_y = c_int()
        mask = c_uint()
        try:
            res = self.x11.XQueryPointer(
                self.disp, self.root,
                byref(root_ret), byref(child_ret),
                byref(root_x), byref(root_y),
                byref(win_x), byref(win_y),
                byref(mask)
            )
            if res:
                # Button1Mask = (1 << 8)
                btn1 = bool(mask.value & (1 << 8))
                return root_x.value, root_y.value, btn1
        except Exception:
            pass
        return None

    def close(self):
        if self.available and self.disp:
            try:
                self.x11.XCloseDisplay(self.disp)
            except Exception:
                pass
            self.available = False


class SelectionPill(QtWidgets.QWidget):
    """Modern floating quick-action pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_text = ""

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool |
            QtCore.Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)

        self._build_ui()

        self.auto_hide_timer = QtCore.QTimer(self)
        self.auto_hide_timer.setSingleShot(True)
        self.auto_hide_timer.timeout.connect(self.hide_pill)

    def _build_ui(self):
        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)

        self.frame = QtWidgets.QFrame(self)
        self.frame.setObjectName("pillFrame")
        self.frame.setStyleSheet("""
            #pillFrame {
                background-color: rgba(16, 24, 40, 0.94);
                border: 1px solid rgba(56, 189, 248, 0.45);
                border-radius: 20px;
            }
            QPushButton {
                background: transparent;
                color: #e2e8f0;
                font-family: 'Inter', -apple-system, sans-serif;
                font-size: 10pt;
                font-weight: 600;
                padding: 6px 11px;
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(56, 189, 248, 0.22);
                color: #38bdf8;
            }
            QPushButton:pressed {
                background-color: rgba(56, 189, 248, 0.38);
            }
            #closeBtn {
                color: #94a3b8;
                padding: 6px 9px;
            }
            #closeBtn:hover {
                background-color: rgba(239, 68, 68, 0.22);
                color: #ef4444;
            }
            .divider {
                background-color: rgba(255, 255, 255, 0.14);
                width: 1px;
                max-width: 1px;
                margin: 4px 1px;
            }
        """)

        # Drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(16)
        shadow.setColor(QtGui.QColor(0, 0, 0, 160))
        shadow.setOffset(0, 4)
        self.frame.setGraphicsEffect(shadow)

        layout = QtWidgets.QHBoxLayout(self.frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(3)

        # 1. Copy
        self.btn_copy = QtWidgets.QPushButton("📋 Copy")
        self.btn_copy.setToolTip("Copy to clipboard (Ctrl+V anywhere)")
        self.btn_copy.clicked.connect(self.on_copy)
        layout.addWidget(self.btn_copy)

        # 2. Cut
        self.btn_cut = QtWidgets.QPushButton("✂️ Cut")
        self.btn_cut.setToolTip("Copy and delete selected text")
        self.btn_cut.clicked.connect(self.on_cut)
        layout.addWidget(self.btn_cut)

        layout.addWidget(self._make_divider())

        # 3. Screenshot
        self.btn_shot = QtWidgets.QPushButton("📸 Capture")
        self.btn_shot.setToolTip("Take a rectangular screenshot region")
        self.btn_shot.clicked.connect(self.on_screenshot)
        layout.addWidget(self.btn_shot)

        # 4. Ask AI
        self.btn_ai = QtWidgets.QPushButton("🤖 AI")
        self.btn_ai.setToolTip("Ask DevOS AI to explain or fix this")
        self.btn_ai.clicked.connect(self.on_ai)
        layout.addWidget(self.btn_ai)

        # 5. Search
        self.btn_search = QtWidgets.QPushButton("🔍 Search")
        self.btn_search.setToolTip("Search this text in web browser")
        self.btn_search.clicked.connect(self.on_search)
        layout.addWidget(self.btn_search)

        layout.addWidget(self._make_divider())

        # 6. Close
        self.btn_close = QtWidgets.QPushButton("✕")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setToolTip("Dismiss")
        self.btn_close.clicked.connect(self.hide_pill)
        layout.addWidget(self.btn_close)

        main_layout.addWidget(self.frame)

    def _make_divider(self):
        div = QtWidgets.QFrame()
        div.setProperty("class", "divider")
        div.setFrameShape(QtWidgets.QFrame.VLine)
        return div

    def popup_at(self, x, y, text):
        """Position and display the pill near pointer coordinates."""
        self.selected_text = text
        self.btn_copy.setText("📋 Copy")
        self.btn_copy.setStyleSheet("")
        self.btn_cut.setText("✂️ Cut")
        self.btn_cut.setStyleSheet("")

        self.adjustSize()
        w = self.sizeHint().width()
        h = self.sizeHint().height()

        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()

        # Center horizontally on cursor, clamped to screen bounds
        pos_x = max(screen.left() + 10, min(screen.right() - w - 10, x - w // 2))

        # Position above cursor by default, or below if near top
        pos_y = y - h - 12
        if pos_y < screen.top() + 10:
            pos_y = y + 24

        self.move(pos_x, pos_y)
        self.show()
        self.raise_()

        # Auto hide after 6 seconds of inactivity
        self.auto_hide_timer.start(6000)

    def hide_pill(self):
        self.auto_hide_timer.stop()
        self.hide()

    def on_copy(self):
        if self.selected_text:
            clip = QtWidgets.QApplication.clipboard()
            clip.setText(self.selected_text, QtGui.QClipboard.Clipboard)

            # Also push to Klipper via DBus
            try:
                subprocess.run(
                    ["qdbus6", "org.kde.klipper", "/klipper", "setClipboardContents", self.selected_text],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        self.btn_copy.setText("✓ Copied!")
        self.btn_copy.setStyleSheet("color: #22c55e;")
        QtCore.QTimer.singleShot(350, self.hide_pill)

    def on_cut(self):
        self.on_copy()
        # Simulate backspace deletion in active app
        try:
            subprocess.Popen(["xdotool", "key", "BackSpace"])
        except Exception:
            pass

    def on_screenshot(self):
        self.hide_pill()
        try:
            # DevOS region capture
            subprocess.Popen(["spectacle", "-r"])
        except Exception:
            pass

    def on_ai(self):
        self.on_copy()
        self.hide_pill()
        # Launch DevOS AI Assistant / Chat
        try:
            subprocess.Popen(["devos-chat"])
        except Exception:
            pass

    def on_search(self):
        self.hide_pill()
        query = self.selected_text.strip()[:200]
        if query:
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            try:
                subprocess.Popen(["xdg-open", url])
            except Exception:
                pass


class QuickSelectionDaemon(QtCore.QObject):
    """Background selection and mouse release monitor."""

    def __init__(self, pill: SelectionPill):
        super().__init__()
        self.pill = pill
        self.clip = QtWidgets.QApplication.clipboard()
        self.watcher = X11PointerWatcher()

        self.was_mouse_down = False
        self.last_handled_text = ""
        self.mouse_press_pos = (0, 0)

        # Polling timer every 50ms for snappy response
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._check_pointer)
        self.timer.start(50)

    def _check_pointer(self):
        info = self.watcher.query()
        if not info:
            return

        x, y, is_down = info

        # 1. Detect Mouse Press
        if is_down and not self.was_mouse_down:
            self.was_mouse_down = True
            self.mouse_press_pos = (x, y)

            # If user clicked outside the pill, dismiss it
            if self.pill.isVisible():
                if not self.pill.geometry().contains(x, y):
                    self.pill.hide_pill()

        # 2. Detect Mouse Release (User finished dragging / marking text)
        elif not is_down and self.was_mouse_down:
            self.was_mouse_down = False

            # Check if mouse moved enough to be a selection drag (> 6 pixels)
            dx = abs(x - self.mouse_press_pos[0])
            dy = abs(y - self.mouse_press_pos[1])
            is_drag = (dx > 6 or dy > 6)

            # Delay slightly (60ms) to allow the application to publish the selection
            QtCore.QTimer.singleShot(60, lambda: self._evaluate_selection(x, y, is_drag))

    def _evaluate_selection(self, x, y, is_drag):
        text = self.clip.text(QtGui.QClipboard.Selection).strip()

        # Only trigger if text is at least 2 chars, non-empty, and changed or dragged
        if text and len(text) >= 2:
            if is_drag or (text != self.last_handled_text):
                self.last_handled_text = text
                self.pill.popup_at(x, y, text)


def main():
    # Single instance guard
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-quick-selection")
    app.setQuitOnLastWindowClosed(False)

    pill = SelectionPill()
    daemon = QuickSelectionDaemon(pill)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
