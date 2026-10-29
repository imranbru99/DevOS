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

import ctypes
import math
import os
import subprocess
import sys
import time
import urllib.parse
from PyQt5 import QtCore, QtGui, QtWidgets, QtDBus


class X11Pointer:
    """Ultra-fast, zero-overhead mouse pointer and button state tracker via XQueryPointer."""

    def __init__(self):
        try:
            self.x11 = ctypes.cdll.LoadLibrary("libX11.so.6")
            self.display = self.x11.XOpenDisplay(None)
            if self.display:
                self.root = self.x11.XDefaultRootWindow(self.display)
                self.root_ret = ctypes.c_ulong()
                self.child_ret = ctypes.c_ulong()
                self.root_x = ctypes.c_int()
                self.root_y = ctypes.c_int()
                self.win_x = ctypes.c_int()
                self.win_y = ctypes.c_int()
                self.mask = ctypes.c_uint()
        except Exception:
            self.display = None

    def get_state(self):
        if not self.display:
            return None, None, False, False
        try:
            self.x11.XQueryPointer(
                self.display, self.root,
                ctypes.byref(self.root_ret), ctypes.byref(self.child_ret),
                ctypes.byref(self.root_x), ctypes.byref(self.root_y),
                ctypes.byref(self.win_x), ctypes.byref(self.win_y),
                ctypes.byref(self.mask)
            )
            x = self.root_x.value
            y = self.root_y.value
            left_down = bool(self.mask.value & 256)   # Button 1
            right_down = bool(self.mask.value & 1024) # Button 3
            return x, y, left_down, right_down
        except Exception:
            return None, None, False, False


_global_pointer = X11Pointer()


def get_pointer_coordinates():
    """Returns (x, y) coordinates of mouse cursor near the selection."""
    try:
        x, y, _, _ = _global_pointer.get_state()
        if x is not None and (x > 0 or y > 0):
            return x, y
    except Exception:
        pass

    try:
        pos = QtGui.QCursor.pos()
        if pos.x() > 0 and pos.y() > 0:
            return pos.x(), pos.y()
    except Exception:
        pass

    return None


class WaylandPrimaryWatcher(QtCore.QThread):
    """Event-driven mouse drag selection watcher with zero-interference click handling."""

    selection_changed = QtCore.pyqtSignal(str, int, int)
    dismiss_requested = QtCore.pyqtSignal()

    def __init__(self, pointer: X11Pointer, pill: QtWidgets.QWidget, parent=None):
        super().__init__(parent)
        self.pointer = pointer
        self.pill = pill
        self._running = True
        self._last_text = ""

    def stop(self):
        self._running = False
        self.quit()
        self.wait(500)

    def run(self):
        was_down = False
        press_x = 0
        press_y = 0
        max_dist = 0
        last_up_time = 0

        while self._running and not self.isInterruptionRequested():
            try:
                x, y, left_down, right_down = self.pointer.get_state()
                if x is None:
                    time.sleep(0.05)
                    continue

                # 1. Dismiss pill immediately if user clicks outside of it
                if (left_down or right_down) and self.pill.isVisible():
                    geom = self.pill.geometry()
                    if not (geom.left() <= x <= geom.right() and geom.top() <= y <= geom.bottom()):
                        self.dismiss_requested.emit()

                # 2. Track mouse drag vs single click
                is_selection_event = False
                if left_down and not was_down:
                    was_down = True
                    press_x = x
                    press_y = y
                    max_dist = 0
                elif left_down and was_down:
                    dist = math.hypot(x - press_x, y - press_y)
                    if dist > max_dist:
                        max_dist = dist
                elif not left_down and was_down:
                    was_down = False
                    now = time.time()
                    if max_dist >= 14:
                        # Genuine text drag selection
                        is_selection_event = True
                    elif now - last_up_time < 0.35 and max_dist < 8:
                        # Genuine double-click selection
                        is_selection_event = True
                    last_up_time = now

                # 3. ONLY query clipboard when a genuine selection interaction occurred!
                # Clicks on Chrome switcher, bookmarks, buttons NEVER trigger this!
                if is_selection_event:
                    time.sleep(0.06)  # Small settling pause for app to commit selection
                    res = subprocess.run(
                        ["wl-paste", "--primary"],
                        capture_output=True,
                        text=True,
                        timeout=0.3
                    )
                    if res.returncode == 0:
                        text = res.stdout.strip()
                        if text and len(text) >= 2:
                            self._last_text = text
                            self.selection_changed.emit(text, x, y)

            except Exception:
                pass
            time.sleep(0.03)  # Fast 30ms responsive loop with zero subprocess overhead


class SelectionPill(QtWidgets.QWidget):
    """Modern floating quick-action pill."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_text = ""

        # ToolTip + WindowStaysOnTopHint ensures the pill appears directly on screen
        # above the selected text without ever appearing as an app icon in KDE taskbar
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.ToolTip |
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

    def popup_for_text(self, text, x=None, y=None):
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
        if x is None or y is None or x <= 0 or y <= 0:
            coords = get_pointer_coordinates()
            if coords:
                x, y = coords

        if x is not None and y is not None and x > 0 and y > 0:
            # Put the Copy button (left edge of pill) right next to cursor x so user doesn't have to move mouse
            pos_x = min(screen.right() - w - 10, max(screen.left() + 10, x - 25))
            pos_y = y - h - 10
            if pos_y < screen.top() + 8:
                pos_y = y + 18
        else:
            # Fallback to Top-Center HUD
            pos_x = screen.left() + (screen.width() - w) // 2
            pos_y = screen.top() + 30

        self.move(pos_x, pos_y)
        self.show()
        self.raise_()
        self._ensure_skip_taskbar()

        # Auto hide after 6 seconds of inactivity
        self.auto_hide_timer.start(6000)

    def _ensure_skip_taskbar(self):
        """Explicitly add _NET_WM_STATE_SKIP_TASKBAR and _NET_WM_STATE_SKIP_PAGER via X11."""
        try:
            win_id = int(self.winId())
            if _global_pointer.display and _global_pointer.x11:
                disp = _global_pointer.display
                x11 = _global_pointer.x11
                atom_skip_taskbar = x11.XInternAtom(disp, b"_NET_WM_STATE_SKIP_TASKBAR", False)
                atom_skip_pager = x11.XInternAtom(disp, b"_NET_WM_STATE_SKIP_PAGER", False)
                atom_state = x11.XInternAtom(disp, b"_NET_WM_STATE", False)
                atoms = (ctypes.c_ulong * 2)(atom_skip_taskbar, atom_skip_pager)
                # Mode 2 is PropModeAppend
                x11.XChangeProperty(disp, win_id, atom_state, 4, 32, 2, ctypes.cast(atoms, ctypes.c_char_p), 2)
                x11.XFlush(disp)
        except Exception:
            pass

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
        self.wayland_watcher = WaylandPrimaryWatcher(_global_pointer, self.pill, self)
        self.wayland_watcher.selection_changed.connect(self._handle_new_text)
        self.wayland_watcher.dismiss_requested.connect(self.pill.hide_pill)
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
                if text and text != self.last_handled_text and len(text) >= 2:
                    self.last_handled_text = text
                    self.pill.popup_for_text(text)
        except Exception:
            pass

    def _handle_new_text(self, text, x, y):
        if not text or len(text) < 2:
            return
        self.last_handled_text = text
        self.pill.popup_for_text(text, x, y)


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("devos-quick-selection")
    app.setQuitOnLastWindowClosed(False)

    pill = SelectionPill()
    daemon = QuickSelectionDaemon(pill)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
