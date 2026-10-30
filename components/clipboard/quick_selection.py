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


def get_primary_text():
    """Retrieve text currently in Wayland/X11 primary selection."""
    try:
        res = subprocess.run(
            ["wl-paste", "--primary"],
            capture_output=True,
            text=True,
            timeout=0.25,
        )
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def clear_primary_text():
    """Clear Wayland/X11 primary selection so old selections do not persist."""
    try:
        subprocess.run(
            ["wl-copy", "--clear", "--primary"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=0.2,
        )
    except Exception:
        pass


class WaylandPrimaryWatcher(QtCore.QThread):
    """Event-driven mouse selection watcher with strict drag/double-click gating."""

    selection_changed = QtCore.pyqtSignal(str, int, int)
    dismiss_requested = QtCore.pyqtSignal()

    def __init__(self, pointer: X11Pointer, pill: QtWidgets.QWidget, parent=None):
        super().__init__(parent)
        self.pointer = pointer
        self.pill = pill
        self._running = True
        self._last_text = ""
        self._text_before_press = ""

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
        consecutive_clicks = 0

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
                        clear_primary_text()
                        self._last_text = ""
                        self._text_before_press = ""

                # 2. Track mouse drag vs click
                if left_down and not was_down:
                    was_down = True
                    press_x = x
                    press_y = y
                    max_dist = 0
                    now = time.time()
                    if now - last_up_time < 0.4:
                        consecutive_clicks += 1
                    else:
                        consecutive_clicks = 1
                        # Capture text in buffer before click starts
                        self._text_before_press = get_primary_text()

                elif left_down and was_down:
                    dist = math.hypot(x - press_x, y - press_y)
                    if dist > max_dist:
                        max_dist = dist

                elif not left_down and was_down:
                    was_down = False
                    now = time.time()
                    last_up_time = now

                    # CASE A: Genuine text drag selection (mouse moved >= 12px while held)
                    if max_dist >= 12:
                        consecutive_clicks = 0
                        time.sleep(0.06)  # Settling pause for application to commit selection
                        text = get_primary_text()
                        if text and len(text) >= 1:
                            self._last_text = text
                            self.selection_changed.emit(text, x, y)

                    # CASE B: Double-click or Triple-click on a word/line
                    elif consecutive_clicks >= 2 and max_dist < 8:
                        time.sleep(0.07)  # Settling pause for application to highlight word
                        text = get_primary_text()
                        # CRITICAL: Only trigger if text was ACTUALLY selected!
                        # Double-clicking on empty space, desktop icons, or folders puts NOTHING into primary.
                        # If text is empty or unchanged from before the click, nothing was selected.
                        if text and len(text) >= 1:
                            if text != self._text_before_press:
                                self._last_text = text
                                self.selection_changed.emit(text, x, y)

                # Periodic cleanup of stale buffer on idle after a single click without drag
                elif not left_down and not was_down:
                    if consecutive_clicks == 1 and (time.time() - last_up_time) > 0.45:
                        consecutive_clicks = 0
                        clear_primary_text()
                        self._text_before_press = ""

            except Exception:
                pass
            time.sleep(0.03)


class SelectionPill(QtWidgets.QWidget):
    """Modern floating quick-action Copy pill."""

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
        main_layout.setContentsMargins(6, 6, 6, 6)

        self.frame = QtWidgets.QFrame(self)
        self.frame.setObjectName("pillFrame")
        self.frame.setStyleSheet("""
            #pillFrame {
                background-color: rgba(15, 23, 42, 0.94);
                border: 1px solid rgba(56, 189, 248, 0.6);
                border-radius: 18px;
            }
            QPushButton {
                background: transparent;
                color: #f8fafc;
                font-family: 'Inter', -apple-system, sans-serif;
                font-size: 10pt;
                font-weight: 600;
                padding: 6px 14px;
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(56, 189, 248, 0.25);
                color: #38bdf8;
            }
            QPushButton:pressed {
                background-color: rgba(56, 189, 248, 0.45);
            }
            #closeBtn {
                color: #94a3b8;
                font-size: 9pt;
                padding: 6px 10px;
                margin-left: 2px;
            }
            #closeBtn:hover {
                background-color: rgba(239, 68, 68, 0.25);
                color: #ef4444;
            }
        """)

        # Drop shadow
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(16)
        shadow.setColor(QtGui.QColor(0, 0, 0, 180))
        shadow.setOffset(0, 3)
        self.frame.setGraphicsEffect(shadow)

        layout = QtWidgets.QHBoxLayout(self.frame)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(2)

        # 1. Copy button
        self.btn_copy = QtWidgets.QPushButton("📋 Copy")
        self.btn_copy.setToolTip("Copy to clipboard (Ctrl+V anywhere)")
        self.btn_copy.clicked.connect(self.on_copy)
        layout.addWidget(self.btn_copy)

        # 2. Close / Dismiss button
        self.btn_close = QtWidgets.QPushButton("✕")
        self.btn_close.setObjectName("closeBtn")
        self.btn_close.setToolTip("Dismiss")
        self.btn_close.clicked.connect(self.hide_pill)
        layout.addWidget(self.btn_close)

        main_layout.addWidget(self.frame)

    def popup_for_text(self, text, x=None, y=None):
        """Position and display the pill near cursor or above selection."""
        self.selected_text = text
        self.btn_copy.setText("📋 Copy")
        self.btn_copy.setStyleSheet("")

        self.adjustSize()
        w = self.sizeHint().width()
        h = self.sizeHint().height()

        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        if x is None or y is None or x <= 0 or y <= 0:
            coords = get_pointer_coordinates()
            if coords:
                x, y = coords

        if x is not None and y is not None and x > 0 and y > 0:
            # Place the Copy pill right above cursor centered horizontally
            pos_x = min(screen.right() - w - 10, max(screen.left() + 10, x - (w // 2)))
            pos_y = y - h - 10
            if pos_y < screen.top() + 8:
                pos_y = y + 20
        else:
            # Fallback to Top-Center HUD
            pos_x = screen.left() + (screen.width() - w) // 2
            pos_y = screen.top() + 30

        self.move(pos_x, pos_y)
        self.show()
        self.raise_()
        self._ensure_skip_taskbar()

        # Auto hide after 5 seconds of inactivity
        self.auto_hide_timer.start(5000)

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

    def deselect_text(self):
        """Immediately clears the active selection and collapses highlight in the source window."""
        # 1. Clear Wayland primary selection
        try:
            subprocess.run(
                ["wl-copy", "--clear", "--primary"],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

        # 2. Clear Qt selection
        try:
            QtWidgets.QApplication.clipboard().clear(QtGui.QClipboard.Selection)
        except Exception:
            pass

        # 3. Clear X11 primary selection via XSetSelectionOwner
        try:
            if _global_pointer.display and _global_pointer.x11:
                disp = _global_pointer.display
                x11 = _global_pointer.x11
                atom_primary = x11.XInternAtom(disp, b"PRIMARY", False)
                x11.XSetSelectionOwner(disp, atom_primary, 0, 0)
                x11.XFlush(disp)
        except Exception:
            pass

        # 4. Collapse active visual selection in target application
        try:
            subprocess.Popen(
                ["xdotool", "key", "--clearmodifiers", "Right"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except Exception:
            pass

    def on_copy(self, deselect=True):
        # Remove the button / floating pill immediately
        self.hide_pill()

        if self.selected_text:
            # 1. Push via wl-copy to regular clipboard
            try:
                subprocess.run(
                    ["wl-copy", self.selected_text],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            # 2. Push via Qt
            try:
                clip = QtWidgets.QApplication.clipboard()
                clip.setText(self.selected_text, QtGui.QClipboard.Clipboard)
            except Exception:
                pass

            # 3. Push to Klipper
            try:
                subprocess.run(
                    ["qdbus6", "org.kde.klipper", "/klipper", "setClipboardContents", self.selected_text],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

            # 4. Immediately deselect the text in the active window
            if deselect:
                self.deselect_text()

    def on_cut(self):
        self.on_copy(deselect=False)
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
        self.on_copy(deselect=True)
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
    """Monitors mouse selection events and displays the floating Copy button."""

    def __init__(self, pill: SelectionPill):
        super().__init__()
        self.pill = pill
        self.last_handled_text = ""

        # Wayland / X11 Primary Selection Watcher Thread
        self.wayland_watcher = WaylandPrimaryWatcher(_global_pointer, self.pill, self)
        self.wayland_watcher.selection_changed.connect(self._handle_new_text)
        self.wayland_watcher.dismiss_requested.connect(self.pill.hide_pill)
        self.wayland_watcher.start()

    def _handle_new_text(self, text, x, y):
        if not text or len(text) < 1:
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
