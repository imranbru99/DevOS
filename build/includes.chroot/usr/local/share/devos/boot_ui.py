#!/usr/bin/env python3
"""Fullscreen animated starter. Stays up until the disk installer is visible."""

import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt5.QtCore import Qt, QTimer, QRectF
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget


LOG = "/tmp/devos-calamares.log"
PHASES = (
    "Starting DevOS",
    "Preparing the display",
    "Opening the disk installer",
)


def display():
    d = os.environ.get("DISPLAY", "")
    if d:
        return d
    if os.path.exists("/tmp/.X11-unix/X0"):
        return ":0"
    if os.path.exists("/tmp/.X11-unix/X1"):
        return ":1"
    return ":0"


def xauthority():
    xauth = os.environ.get("XAUTHORITY", "")
    if xauth and os.path.exists(xauth):
        return xauth
    home_xauth = os.path.expanduser("~/.Xauthority")
    if os.path.exists(home_xauth):
        return home_xauth
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime_dir and os.path.isdir(runtime_dir):
        try:
            for fname in os.listdir(runtime_dir):
                if fname.startswith("xauth"):
                    full = os.path.join(runtime_dir, fname)
                    if os.path.isfile(full):
                        return full
        except OSError:
            pass
    return ""


class Bar(QWidget):
    """Short centered progress line. Its position comes from the layout."""

    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedSize(280, 8)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#1e293b"))
        painter.drawRoundedRect(QRectF(0, 2, 280, 4), 2, 2)
        travel = (self.owner.phase * 140) % 220
        painter.setBrush(QColor("#38bdf8"))
        painter.drawRoundedRect(QRectF(max(0, travel - 70), 2, 70, 4), 2, 2)
        painter.end()


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
        # Override-redirect so the window manager cannot park this window
        # in a corner. The word then stays in the middle of the screen.
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint
        )
        self.setStyleSheet("background: #070910;")

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        pixmap = QPixmap("/usr/share/pixmaps/devos-logo.png")
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(132, 132, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        title = QLabel("DevOS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #f8fafc; background: transparent; font-size: 52px; font-weight: 700;"
        )

        self.status = QLabel(PHASES[0])
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #7dd3fc; background: transparent; font-size: 20px;")

        self.detail = QLabel("The installer opens on this screen.")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #94a3b8; background: transparent; font-size: 16px;")

        self.bar = Bar(self)

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
        layout.setContentsMargins(48, 0, 48, 0)
        layout.addStretch(1)
        layout.addWidget(logo)
        layout.addSpacing(18)
        layout.addWidget(title)
        layout.addSpacing(10)
        layout.addWidget(self.status)
        layout.addSpacing(6)
        layout.addWidget(self.detail)
        layout.addSpacing(22)
        layout.addWidget(self.bar, alignment=Qt.AlignHCenter)
        layout.addSpacing(18)
        layout.addWidget(self.log)
        layout.addSpacing(16)
        layout.addWidget(self.retry, alignment=Qt.AlignHCenter)
        layout.addStretch(1)

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
            cmd = ["sudo", "-E", "-n"]
            if display():
                cmd.append("DISPLAY=" + display())
            if xauthority():
                cmd.append("XAUTHORITY=" + xauthority())
            cmd.extend([
                "QT_QPA_PLATFORM=xcb",
                # KDE palette (DevOS colours from /etc/xdg/kdeglobals): the
                # partition legend is drawn with it, not with stylesheet.qss.
                "QT_QPA_PLATFORMTHEME=kde",
                "QT_STYLE_OVERRIDE=Fusion",
                "calamares",
            ])
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
            self.cover()
            self.update()

    def cover(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.geometry()
        if self.geometry() != geo:
            self.setGeometry(geo)

    def paintEvent(self, _event):
        painter = QPainter(self)
        rect = self.rect()
        gradient = QLinearGradient(0, 0, rect.width(), rect.height())
        gradient.setColorAt(0.0, QColor("#070910"))
        gradient.setColorAt(0.55, QColor("#10182c"))
        gradient.setColorAt(1.0, QColor("#160f28"))
        painter.fillRect(rect, gradient)
        painter.end()


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Inter", 12))
    window = Starter()
    window.cover()
    window.show()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
