#!/usr/bin/env python3
"""
DevOS Quick Selection Bar (Smart Floating Selection Actions).

When text is selected / marked in any application (terminals, PuTTY, Chrome, editors),
a sleek floating action pill automatically appears offering:
  - 📋 Copy (syncs to clipboard & Klipper, shows checkmark)
  - ✂️ Cut (copies & deletes selected text)
  - 📸 Capture (launches area screenshot)
  - 🤖 Ask AI (routes text to DevOS AI Assistant)
  - 🔍 Search (web search in browser)
  - ✕ Cancel (dismisses)

Author: Imran Ahmed <me@imrandev.bd>
https://imrandev.bd
"""

import os
import subprocess
import sys
import time
import urllib.parse
from PyQt5 import QtCore, QtGui, QtWidgets, QtDBus


def get_pointer_coordinates():
    """Returns (x, y) coordinates of mouse cursor near the selection."""
    try:
        pos = QtGui.QCursor.pos()
        if pos.x() > 0 and pos.y() > 0:
            return pos.x(), pos.y()
    except Exception:
        pass

    try:
        out = subprocess.check_output(
            ["xdotool", "getmouselocation"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.25
        )
        parts = {}
        for token in out.strip().split():
            if ":" in token:
                k, v = token.split(":", 1)
                parts[k] = int(v)
        if "x" in parts and "y" in parts and (parts["x"] > 0 or parts["y"] > 0):
            return parts["x"], parts["y"]
    except Exception:
        pass

    return None


class WaylandPrimaryWatcher(QtCore.QThread):
    """Watches Wayland primary selection for changes in real-time."""

    selection_changed = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._last_text = ""

    def stop(self):
        self._running = False
        self.quit()
        self.wait(500)

    def run(self):
        while self._running and not self.isInterruptionRequested():
            try:
                res = subprocess.run(
                    ["wl-paste", "--primary"],
                    capture_output=True,
                    text=True,
                    timeout=0.5
                )
                if res.returncode == 0:
                    text = res.stdout.strip()
                    if text and text != self._last_text and len(text) >= 2:
                        self._last_text = text
                        self.selection_changed.emit(text)
            except Exception:
                pass
            time.sleep(0.15)


class SelectionPill(QtWidgets.QWidget):
    """Modern floating quick-action pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_text = ""

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool |
            QtCore.Qt.WindowDoesNotAcceptFocus
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
                background-color: rgba(16, 24, 40, 0.95);
                border: 1px solid rgba(56, 189, 248, 0.5);
                border-radius: 20px;
            }
            QPushButton {
                background: transparent;
                color: #e2e8f0;
                font-family: 'Inter', -apple-system, sans-serif;
                font-size: 10pt;
                font-weight: 600;
                padding: 6px 12px;
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
                padding: 6px 10px;
            }
            #closeBtn:hover {
                background-color: rgba(239, 68, 68, 0.22);
                color: #ef4444;
            }
            .divider {
                background-color: rgba(255, 255, 255, 0.15);
                width: 1px;
                max-width: 1px;
                margin: 4px 1px;
            }
        """)

        # Drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(18)
        shadow.setColor(QtGui.QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        self.frame.setGraphicsEffect(shadow)

        layout = QtWidgets.QHBoxLayout(self.frame)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

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

    def popup_for_text(self, text):
        """Position and display the pill near cursor or at top center."""
        self.selected_text = text
        self.btn_copy.setText("📋 Copy")
        self.btn_copy.setStyleSheet("")
        self.btn_cut.setText("✂️ Cut")
        self.btn_cut.setStyleSheet("")

        self.adjustSize()
        w = self.sizeHint().width()
        h = self.sizeHint().height()

        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        coords = get_pointer_coordinates()

        if coords and coords[0] > 0 and coords[1] > 0:
            x, y = coords
            pos_x = max(screen.left() + 8, min(screen.right() - w - 8, x - w // 2))
            pos_y = y - h - 10
            if pos_y < screen.top() + 8:
                pos_y = y + 20
        else:
            # Fallback to Top-Center HUD
            pos_x = screen.left() + (screen.width() - w) // 2
            pos_y = screen.top() + 30

        self.move(pos_x, pos_y)
        self.show()

        # Auto hide after 5 seconds of inactivity
        self.auto_hide_timer.start(5000)

    def enterEvent(self, event):
        self.auto_hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.auto_hide_timer.start(3500)
        super().leaveEvent(event)

    def hide_pill(self):
        self.auto_hide_timer.stop()
        self.hide()

    def on_copy(self):
        if self.selected_text:
            # 1. Push via wl-copy
            try:
                subprocess.run(
                    ["wl-copy", self.selected_text],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            # 2. Push via Qt
            clip = QtWidgets.QApplication.clipboard()
            clip.setText(self.selected_text, QtGui.QClipboard.Clipboard)

            # 3. Push to Klipper
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
        try:
            subprocess.Popen(["xdotool", "key", "BackSpace"])
        except Exception:
            pass

    def on_screenshot(self):
        self.hide_pill()
        try:
            subprocess.Popen(["spectacle", "-r"])
        except Exception:
            pass

    def on_ai(self):
        self.on_copy()
        self.hide_pill()
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
    """Monitors selection changes across both Wayland (wl-paste + Klipper) and Qt."""

    def __init__(self, pill: SelectionPill):
        super().__init__()
        self.pill = pill
        self.last_handled_text = ""

        # 1. Wayland Primary Watcher Thread
        self.wayland_watcher = WaylandPrimaryWatcher(self)
        self.wayland_watcher.selection_changed.connect(self._handle_new_text)
        self.wayland_watcher.start()

        # 2. KDE Klipper D-Bus connection as fallback
        try:
            self.bus = QtDBus.QDBusConnection.sessionBus()
            self.bus.connect(
                "org.kde.klipper", "/klipper", "org.kde.klipper.klipper",
                "clipboardHistoryUpdated", self._on_klipper_updated
            )
        except Exception:
            pass

    @QtCore.pyqtSlot()
    def _on_klipper_updated(self):
        try:
            msg = QtDBus.QDBusMessage.createMethodCall(
                "org.kde.klipper", "/klipper", "org.kde.klipper.klipper", "getClipboardContents"
            )
            reply = self.bus.call(msg)
            if reply.type() == QtDBus.QDBusMessage.ReplyMessage and reply.arguments():
                text = str(reply.arguments()[0]).strip()
                self._handle_new_text(text)
        except Exception:
            pass

    def _handle_new_text(self, text):
        if not text or len(text) < 2:
            return
        if text == self.last_handled_text:
            return

        self.last_handled_text = text
        self.pill.popup_for_text(text)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-quick-selection")
    app.setQuitOnLastWindowClosed(False)

    pill = SelectionPill()
    daemon = QuickSelectionDaemon(pill)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
