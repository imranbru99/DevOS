#!/usr/bin/env python3
"""
DevOS AI - the voice overlay and the hands-free tray icon (PyQt5).

VoiceOverlay is a frameless, translucent, always-on-top pill at the bottom
centre of the screen. It never takes the keyboard focus, so "type ..."
commands still go to the window the user was working in.

    listening    animated waveform that follows the microphone level
    thinking     "Understanding…"
    heard        “what you said”
    result       a tick or a warning, the result in one line, and
                 "Open in DevOS AI" when the answer is worth reading
    confirm      "Shut down this PC now?"  [Yes, do it] [Cancel]

It hides itself 3 s after a result (longer when it shows a button).
"""

import math
import threading

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

import assistant as ui      # colours and painted icons of the DevOS AI window
import listen

PILL_W = 560
PILL_H = 76
BOTTOM_GAP = 56
CONFIRM_TIMEOUT_S = 20


class Bridge(QtCore.QObject):
    """Thread-safe hops from worker threads to the GUI thread."""
    level = QtCore.pyqtSignal(float)
    event = QtCore.pyqtSignal(str, object)
    confirm_request = QtCore.pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._answer = False
        self._got = threading.Event()

    def ask_confirm(self, question: str, label: str) -> bool:
        """Called from a worker thread: shows the question and waits for a click."""
        self._got.clear()
        self._answer = False
        self.confirm_request.emit(question, label)
        self._got.wait(CONFIRM_TIMEOUT_S + 1)
        return self._answer

    def answer_confirm(self, yes: bool):
        self._answer = bool(yes)
        self._got.set()


class Bars(QtWidgets.QWidget):
    """Listening waveform: rounded bars that breathe with the voice level."""

    def __init__(self, n=11):
        super().__init__()
        self.n = n
        self.level = 0.0
        self.shown = 0.0
        self.phase = 0.0
        self.setFixedSize(n * 7 + 4, 34)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.timer.start()
        self.show()

    def stop(self):
        self.timer.stop()

    def set_level(self, v):
        self.level = max(0.0, min(1.0, float(v)))

    def _tick(self):
        self.shown += (self.level - self.shown) * 0.35
        self.phase += 0.22
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        h = self.height()
        grad = ui.accent_gradient(0, 0, self.width(), 0)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QBrush(grad))
        for i in range(self.n):
            mid = 1.0 - abs(i - (self.n - 1) / 2) / ((self.n - 1) / 2 + 0.5)
            wave = 0.5 + 0.5 * math.sin(self.phase + i * 0.75)
            amp = 0.16 + 0.84 * min(1.0, self.shown * 1.4) * (0.45 + 0.55 * mid) * (0.55 + 0.45 * wave)
            amp = max(amp, 0.14 + 0.06 * wave)
            bh = max(4.0, h * amp)
            x = 2 + i * 7
            p.drawRoundedRect(QtCore.QRectF(x, (h - bh) / 2, 4, bh), 2, 2)
        p.end()


class Badge(QtWidgets.QWidget):
    """Round gradient badge on the left: mic, spinner, tick or warning."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(44, 44)
        self.kind = "mic"
        self.angle = 0
        self.pulse = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def _tick(self):
        self.angle = (self.angle + 9) % 360
        self.pulse = (self.pulse + 0.045) % 1.0
        if self.kind in ("mic", "spin"):
            self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(4, 4, 36, 36)
        if self.kind == "mic":
            ring = QtGui.QColor(ui.ACCENT)
            ring.setAlpha(int(110 * (1 - self.pulse)))
            p.setPen(Qt.NoPen)
            p.setBrush(ring)
            g = 18 + 4 * self.pulse
            p.drawEllipse(QtCore.QPointF(22, 22), g, g)
        if self.kind == "warn":
            p.setPen(Qt.NoPen)
            p.setBrush(ui.qcolor(ui.WARN, 38))
            p.drawEllipse(r)
            ui.draw_icon(p, "warn", r.adjusted(8, 8, -8, -8), ui.WARN, 1.9)
        elif self.kind == "ok":
            p.setPen(Qt.NoPen)
            p.setBrush(ui.qcolor(ui.OK, 40))
            p.drawEllipse(r)
            ui.draw_icon(p, "check", r.adjusted(8, 8, -8, -8), ui.OK, 2.2)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QBrush(ui.accent_gradient(r.left(), r.top(), r.right(), r.bottom())))
            p.drawEllipse(r)
            if self.kind == "spin":
                pen = QtGui.QPen(QtGui.QColor("#ffffff"), 2.4)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawArc(r.adjusted(9, 9, -9, -9), -self.angle * 16, 250 * 16)
            else:
                ui.draw_icon(p, "mic", r.adjusted(8, 8, -8, -8), QtGui.QColor("#ffffff"), 2.0)
        p.end()


class PillButton(QtWidgets.QPushButton):
    def __init__(self, text, primary=False):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(32)
        bg = "qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 %s, stop:1 %s)" % (ui.ACCENT, ui.ACCENT_2) if primary \
            else "rgba(255,255,255,0.08)"
        fg = "#04121a" if primary else ui.TEXT_STRONG
        self.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid rgba(255,255,255,0.10);"
            f" border-radius: 16px; padding: 0 14px; font-weight: 600; font-size: 13px; }}"
            f"QPushButton:hover {{ border-color: rgba(255,255,255,0.28); }}")


class VoiceOverlay(QtWidgets.QWidget):
    open_in_app = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    confirm_answer = QtCore.pyqtSignal(bool)

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowDoesNotAcceptFocus | Qt.X11BypassWindowManagerHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("DevOS AI voice")
        self.state = "idle"
        self._heard = ""
        self._open_text = ""
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 20, 14)
        lay.setSpacing(14)
        self.badge = Badge()
        lay.addWidget(self.badge, 0, Qt.AlignVCenter)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(2)
        self.title = QtWidgets.QLabel()
        self.title.setStyleSheet(f"color: {ui.MUTED}; font-size: 12px; font-weight: 600; letter-spacing: 0.3px;")
        self.text = QtWidgets.QLabel()
        self.text.setWordWrap(True)
        self.text.setStyleSheet(f"color: {ui.TEXT_STRONG}; font-size: 15px;")
        self.text.setTextFormat(Qt.PlainText)
        col.addWidget(self.title)
        col.addWidget(self.text)
        lay.addLayout(col, 1)
        self.bars = Bars()
        lay.addWidget(self.bars, 0, Qt.AlignVCenter)
        self.btn_row = QtWidgets.QHBoxLayout()
        self.btn_row.setSpacing(8)
        lay.addLayout(self.btn_row)
        self.open_btn = PillButton(listen.OPEN_IN_APP_LABEL, primary=True)
        self.open_btn.clicked.connect(self._open_clicked)
        self.yes_btn = PillButton("Yes, do it", primary=True)
        self.no_btn = PillButton("Cancel")
        self.yes_btn.clicked.connect(lambda: self._answer(True))
        self.no_btn.clicked.connect(lambda: self._answer(False))
        for b in (self.open_btn, self.yes_btn, self.no_btn):
            self.btn_row.addWidget(b)
            b.hide()
        self.hide_timer = QtCore.QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)
        self.confirm_timer = QtCore.QTimer(self)
        self.confirm_timer.setSingleShot(True)
        self.confirm_timer.timeout.connect(lambda: self._answer(False))
        self._fade = None
        self.setFixedWidth(PILL_W)

    # -- geometry / painting ---------------------------------------------------

    def _place(self):
        self.adjustSize()
        h = max(PILL_H, self.sizeHint().height())
        self.setFixedHeight(h)
        scr = QtWidgets.QApplication.primaryScreen()
        if scr is None:
            return
        g = scr.availableGeometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + g.height() - h - BOTTOM_GAP)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        rad = min(r.height() / 2, 38)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(11, 14, 22, 236))
        p.drawRoundedRect(r, rad, rad)
        edge = ui.accent_gradient(r.left(), 0, r.right(), 0, 120 if self.state in ("listening", "thinking") else 46)
        pen = QtGui.QPen(QtGui.QBrush(edge), 1.2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, rad, rad)
        p.end()

    def _show(self):
        if self._fade is not None:
            self._fade.stop()
            self._fade = None
        self.setWindowOpacity(1.0)
        self._place()
        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()

    def fade_out(self):
        a = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        a.setDuration(220)
        a.setStartValue(self.windowOpacity())
        a.setEndValue(0.0)
        a.finished.connect(self._done)
        a.start()
        self._fade = a

    def _done(self):
        self.hide()
        self.state = "idle"
        self.finished.emit()

    def _buttons(self, *show):
        for b in (self.open_btn, self.yes_btn, self.no_btn):
            b.setVisible(b in show)

    # -- states ------------------------------------------------------------------

    def set_level(self, v):
        self.bars.set_level(v)

    def listening(self, prompt="Say a command"):
        self.state = "listening"
        self.hide_timer.stop()
        self.badge.set_kind("mic")
        self.title.setText("LISTENING…")
        self.text.setText(prompt)
        self.bars.start()
        self._buttons()
        self._show()

    def thinking(self):
        self.state = "thinking"
        self.badge.set_kind("spin")
        self.bars.stop()
        self.bars.hide()
        self.title.setText("UNDERSTANDING…")
        self.text.setText(self._heard and f"“{self._heard}”" or "One moment")
        self._buttons()
        self._show()

    def heard(self, text):
        self._heard = text
        self.state = "thinking"
        self.badge.set_kind("spin")
        self.bars.stop()
        self.bars.hide()
        self.title.setText("HEARD")
        self.text.setText(f"“{text}”")
        self._buttons()
        self._show()

    def result(self, outcome):
        self.state = "result"
        self.bars.stop()
        self.bars.hide()
        heard = getattr(outcome, "heard", "") or self._heard
        ok = getattr(outcome, "ok", True)
        self.badge.set_kind("ok" if ok else "warn")
        self.title.setText(f"HEARD: “{_elide(heard, 48)}”" if heard else ("DONE" if ok else "VOICE COMMAND"))
        self.text.setText(getattr(outcome, "text", "") or ("Done." if ok else listen.NOTHING_HEARD_TEXT))
        self._open_text = heard
        show_open = bool(getattr(outcome, "open_in_app", False) and heard)
        self._buttons(*( [self.open_btn] if show_open else []))
        self._show()
        self.hide_timer.start(listen.HIDE_AFTER_BUTTON_MS if show_open else listen.HIDE_AFTER_MS)

    def ask_confirm(self, question, label=""):
        self.state = "confirm"
        self.hide_timer.stop()
        self.bars.stop()
        self.bars.hide()
        self.badge.set_kind("warn")
        self.title.setText((label or "Please confirm").upper())
        self.text.setText(question)
        self._buttons(self.yes_btn, self.no_btn)
        self._show()
        self.confirm_timer.start(CONFIRM_TIMEOUT_S * 1000)

    def _answer(self, yes):
        self.confirm_timer.stop()
        self._buttons()
        self.badge.set_kind("spin")
        self.title.setText("WORKING…" if yes else "CANCELLED")
        self.text.setText("" if yes else "Okay, nothing was done.")
        self.confirm_answer.emit(bool(yes))

    def _open_clicked(self):
        self.open_in_app.emit(self._open_text)
        self.hide_timer.start(300)

    def handle_event(self, kind, payload):
        if kind == "listening":
            self.listening()
        elif kind == "thinking":
            self.thinking()
        elif kind == "heard":
            self.heard(str(payload))
        elif kind == "result":
            self.result(payload)
        elif kind == "timeout":
            if self.state == "listening":
                self.fade_out()


def _elide(s, n):
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def mic_pixmap(size=64, paused=False):
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    r = QtCore.QRectF(2, 2, size - 4, size - 4)
    p.setPen(Qt.NoPen)
    if paused:
        p.setBrush(QtGui.QColor(100, 116, 139))
    else:
        p.setBrush(QtGui.QBrush(ui.accent_gradient(0, 0, size, size)))
    p.drawEllipse(r)
    ui.draw_icon(p, "mic", r.adjusted(size * 0.2, size * 0.2, -size * 0.2, -size * 0.2), QtGui.QColor("#ffffff"),
                 size / 14)
    if paused:
        pen = QtGui.QPen(QtGui.QColor("#ffffff"), size / 14)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QtCore.QPointF(size * 0.25, size * 0.25), QtCore.QPointF(size * 0.75, size * 0.75))
    p.end()
    return pm


class HandsFreeTray(QtWidgets.QSystemTrayIcon):
    """Shows that the microphone is listening for "Hey DevOS"."""
    pause_toggled = QtCore.pyqtSignal(bool)
    turn_off = QtCore.pyqtSignal()
    open_app = QtCore.pyqtSignal()

    def __init__(self, paused=False):
        super().__init__()
        self.menu = QtWidgets.QMenu()
        self.a_pause = self.menu.addAction("Pause hands-free")
        self.a_pause.triggered.connect(lambda: self.pause_toggled.emit(not self.paused))
        self.a_open = self.menu.addAction("Open DevOS AI")
        self.a_open.triggered.connect(self.open_app.emit)
        self.menu.addSeparator()
        self.a_off = self.menu.addAction("Turn off")
        self.a_off.triggered.connect(self.turn_off.emit)
        self.setContextMenu(self.menu)
        self.activated.connect(lambda reason: self.open_app.emit()
                               if reason == QtWidgets.QSystemTrayIcon.Trigger else None)
        self.set_paused(paused)

    def set_paused(self, on):
        self.paused = bool(on)
        self.setIcon(QtGui.QIcon(mic_pixmap(64, self.paused)))
        self.a_pause.setText("Resume hands-free" if self.paused else "Pause hands-free")
        self.setToolTip("DevOS AI: hands-free is paused" if self.paused
                        else "DevOS AI is listening for “Hey DevOS”")
