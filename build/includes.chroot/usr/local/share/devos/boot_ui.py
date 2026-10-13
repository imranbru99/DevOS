#!/usr/bin/env python3
"""Fullscreen animated starter. Stays up until the disk installer is visible."""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


LOG = "/tmp/devos-calamares.log"
PHASES = (
    "Starting DevOS",
    "Preparing the display",
    "Opening the disk installer",
)


def display():
    return os.environ.get("DISPLAY", ":0")


def xauthority():
    return os.environ.get("XAUTHORITY", "")


class Starter(QWidget):
    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.stage = 0
        self.proc = None
        self.installer_was_visible = False
        self.kwin = None
        self.alive_for = 0
        self.failed = False
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setStyleSheet("background: #070910;")

        self.status = QLabel(PHASES[0])
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #7dd3fc; background: transparent; font-size: 22px;")

        self.detail = QLabel("The installer opens on this screen. The pointer alone is not the installer.")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #94a3b8; background: transparent; font-size: 16px;")

        self.log = QLabel("")
        self.log.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.log.setWordWrap(True)
        self.log.setVisible(False)
        self.log.setStyleSheet(
            "color: #e2e8f0; background: rgba(8, 12, 22, 180); "
            "font-family: monospace; font-size: 13px; padding: 16px;"
        )

        self.retry = QPushButton("Try the installer again")
        self.retry.setVisible(False)
        self.retry.setCursor(Qt.PointingHandCursor)
        self.retry.setStyleSheet(
            "QPushButton { color: #041018; background: #38bdf8; border: none; "
            "border-radius: 8px; padding: 12px 22px; font-size: 16px; font-weight: 600; }"
            "QPushButton:hover { background: #7dd3fc; }"
        )
        self.retry.clicked.connect(self.launch_installer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 0, 80, 80)
        layout.addStretch(3)
        layout.addSpacing(220)
        layout.addWidget(self.status)
        layout.addSpacing(8)
        layout.addWidget(self.detail)
        layout.addSpacing(18)
        layout.addWidget(self.log)
        layout.addSpacing(16)
        layout.addWidget(self.retry, alignment=Qt.AlignHCenter)
        layout.addStretch(2)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self.clock.start(16)
        QTimer.singleShot(400, self.start_desktop)
        QTimer.singleShot(900, self.launch_installer)

    def start_desktop(self):
        if self.kwin is not None:
            return
        kwin = "/usr/bin/kwin_x11"
        if os.path.isfile(kwin) and os.access(kwin, os.X_OK):
            self.kwin = subprocess.Popen(
                [kwin, "--replace"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self.raise_()
        self.activateWindow()

    def launch_installer(self):
        self.failed = False
        self.alive_for = 0
        self.installer_was_visible = False
        self.retry.setVisible(False)
        self.log.setVisible(False)
        self.stage = 2
        self.status.setText(PHASES[2])
        self.detail.setText("Choose the disk on the next screen. Only that disk is erased.")
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc = None
        env = os.environ.copy()
        env["DISPLAY"] = display()
        env["QT_QPA_PLATFORM"] = "xcb"
        env["QT_QPA_PLATFORMTHEME"] = "kde"
        env["QT_STYLE_OVERRIDE"] = "Fusion"
        if xauthority():
            env["XAUTHORITY"] = xauthority()
        try:
            open(LOG, "a", encoding="utf-8").close()
        except OSError:
            pass
        log = open(LOG, "a", encoding="utf-8", errors="replace")
        if os.geteuid() == 0:
            cmd = ["calamares"]
        else:
            cmd = [
                "sudo", "-n",
                "DISPLAY=" + display(),
                "XAUTHORITY=" + xauthority(),
                "QT_QPA_PLATFORM=xcb",
                # KDE palette (DevOS colours from /etc/xdg/kdeglobals): the
                # partition legend is drawn with it, not with stylesheet.qss.
                "QT_QPA_PLATFORMTHEME=kde",
                "QT_STYLE_OVERRIDE=Fusion",
                "calamares",
            ]
        try:
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            log.write("Could not start calamares: %s\n" % exc)
            log.close()
            self.show_failure()
            return
        log.close()

    def installer_window_visible(self):
        try:
            out = subprocess.check_output(
                ["xwininfo", "-root", "-tree"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        visible = b"calamares" in out.lower()
        if visible:
            self.installer_was_visible = True
        return visible

    def show_failure(self):
        self.failed = True
        self.showFullScreen()
        self.raise_()
        self.status.setText("The installer did not open")
        self.detail.setText("DevOS is still running. Use the button below to open it again.")
        text = ""
        try:
            with open(LOG, "r", encoding="utf-8", errors="replace") as handle:
                lines = handle.readlines()[-18:]
            text = "".join(lines).strip()
        except OSError:
            text = ""
        if not text:
            text = "No installer log was written. The display connection or calamares package is missing."
        self.log.setText(text)
        self.log.setVisible(True)
        self.retry.setVisible(True)

    def tick(self):
        self.phase += 0.016
        if not self.failed and self.stage < 2 and self.phase > 0.7:
            self.stage = 1
            self.status.setText(PHASES[1])
        if self.proc is not None:
            code = self.proc.poll()
            if code is None:
                self.alive_for += 16
                if self.installer_window_visible():
                    self.hide()
                elif self.alive_for > 40000 and not self.failed:
                    self.show_failure()
            elif self.alive_for < 8000 or not self.installer_was_visible:
                self.proc = None
                self.show_failure()
            else:
                QApplication.instance().quit()
        if self.isVisible():
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        shift = (self.phase * 40) % max(rect.width(), 1)
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#070910"))
        gradient.setColorAt(0.55, QColor("#10182c"))
        gradient.setColorAt(1.0, QColor("#160f28"))
        painter.fillRect(rect, gradient)

        painter.setPen(Qt.NoPen)
        for index, color in enumerate(("#22d3ee", "#818cf8", "#38bdf8")):
            span = 180 + index * 70
            x = (shift * (1.2 + index * 0.35) + index * 220) % (rect.width() + span) - span
            y = rect.height() * (0.28 + index * 0.16)
            glow = QColor(color)
            glow.setAlpha(46)
            painter.setBrush(glow)
            painter.drawRoundedRect(QRectF(x, y, span, 10), 5, 5)

        painter.setPen(QColor("#38bdf8"))
        label = QFont("Inter", 14)
        label.setBold(True)
        label.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        painter.setFont(label)
        painter.drawText(QRectF(0, rect.height() * 0.34, rect.width(), 28), Qt.AlignCenter, "INSTALL")

        word = QFont("Inter", 64)
        word.setBold(True)
        painter.setFont(word)
        painter.setPen(QColor("#f8fafc"))
        painter.drawText(QRectF(0, rect.height() * 0.34 + 36, rect.width(), 90), Qt.AlignCenter, "DevOS")

        track = QRectF(rect.width() / 2 - 180, rect.height() * 0.34 + 250, 360, 8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1e293b"))
        painter.drawRoundedRect(track, 4, 4)
        travel = (self.phase * 140) % 280
        painter.setBrush(QColor("#38bdf8"))
        painter.drawRoundedRect(QRectF(track.x() + max(0, travel - 90), track.y(), 90, 8), 4, 4)
        painter.setPen(QPen(QColor(56, 189, 248, 90), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(track.adjusted(-6, -10, 6, 10), 8, 8)
        painter.end()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 12))
    window = Starter()
    window.showFullScreen()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
