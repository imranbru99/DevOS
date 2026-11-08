#!/usr/bin/env python3
"""Fullscreen premium animated starter. Stays up until the disk installer is visible."""

import math
import os
import random
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

try:
    from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF
    from PyQt5.QtGui import (
        QColor, QFont, QLinearGradient, QRadialGradient, QPainter, QPixmap, QPen, QPainterPath,
    )
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
except Exception:
    try:
        from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
        from PyQt6.QtGui import (
            QColor, QFont, QLinearGradient, QRadialGradient, QPainter, QPixmap, QPen, QPainterPath,
        )
        from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
    except Exception:
        sys.exit(0)


LOG = "/tmp/devos-calamares.log"
PHASES = (
    ("Starting DevOS", "Loading the live session and installer shell."),
    ("Preparing the display", "Bringing up a smooth desktop for install."),
    ("Opening the disk installer", "You can erase a disk or keep dual-boot — nothing writes until you confirm Install."),
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
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setFixedSize(320, 10)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#152033"))
        painter.drawRoundedRect(QRectF(0, 1, 320, 8), 4, 4)
        travel = (self.owner.phase * 160) % 280
        glow = QLinearGradient(max(0, travel - 90), 0, travel + 20, 0)
        glow.setColorAt(0.0, QColor(56, 189, 248, 40))
        glow.setColorAt(0.45, QColor(125, 211, 252, 230))
        glow.setColorAt(1.0, QColor(34, 211, 238, 40))
        painter.setBrush(glow)
        painter.drawRoundedRect(QRectF(max(0, travel - 90), 1, 110, 8), 4, 4)
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
        self._stars = [
            {
                "x": random.random(),
                "y": random.random(),
                "r": random.uniform(0.8, 2.4),
                "s": random.uniform(0.4, 1.4),
                "a": random.randint(40, 160),
            }
            for _ in range(48)
        ]
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("background: #070910;")

        logo = QLabel()
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        pixmap = QPixmap("/usr/share/pixmaps/devos-logo.png")
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(148, 148, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        eyebrow = QLabel("INSTALLER")
        eyebrow.setAlignment(Qt.AlignCenter)
        eyebrow.setStyleSheet(
            "color: #38bdf8; background: transparent; font-size: 13px; "
            "font-weight: 700; letter-spacing: 4px;"
        )

        title = QLabel("DevOS")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #f8fafc; background: transparent; font-size: 56px; font-weight: 700;"
        )

        self.status = QLabel(PHASES[0][0])
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setStyleSheet("color: #7dd3fc; background: transparent; font-size: 22px; font-weight: 600;")

        self.detail = QLabel(PHASES[0][1])
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #94a3b8; background: transparent; font-size: 16px;")

        self.hint = QLabel("Erase disk · Manual dual-boot · Format extra drives — all optional until Install")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #64748b; background: transparent; font-size: 13px;")

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
            "border-radius: 12px; padding: 14px 26px; font-size: 16px; font-weight: 600; }"
            "QPushButton:hover { background: #7dd3fc; }"
        )
        self.retry.clicked.connect(self.launch_installer)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(56, 0, 56, 0)
        layout.addStretch(1)
        layout.addWidget(logo)
        layout.addSpacing(10)
        layout.addWidget(eyebrow)
        layout.addSpacing(4)
        layout.addWidget(title)
        layout.addSpacing(14)
        layout.addWidget(self.status)
        layout.addSpacing(6)
        layout.addWidget(self.detail)
        layout.addSpacing(10)
        layout.addWidget(self.hint)
        layout.addSpacing(26)
        layout.addWidget(self.bar, alignment=Qt.AlignHCenter)
        layout.addSpacing(18)
        layout.addWidget(self.log)
        layout.addSpacing(16)
        layout.addWidget(self.retry, alignment=Qt.AlignHCenter)
        layout.addStretch(1)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self.clock.start(33)
        self._next_window_check = 0.0
        QTimer.singleShot(400, self.start_desktop)
        QTimer.singleShot(900, self.launch_installer)

    def start_desktop(self):
        if self.kwin is not None:
            return
        kwin = "/usr/bin/kwin_x11"
        existing = subprocess.run(
            ["pgrep", "-x", "kwin_x11"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2
        )
        if existing.returncode != 0 and os.path.isfile(kwin) and os.access(kwin, os.X_OK):
            self.kwin = subprocess.Popen(
                [kwin, "--replace"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        self.raise_()
        self.activateWindow()

    def launch_installer(self):
        retrying = self.failed
        self.failed = False
        self.alive_for = 0
        self.installer_was_visible = False
        self.retry.setVisible(False)
        self.log.setVisible(False)
        self.stage = 2
        self.status.setText(PHASES[2][0])
        self.detail.setText(PHASES[2][1])
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
        cmd = ["/usr/local/bin/devos-install-gui"]
        if retrying:
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"
            env["QT_QUICK_BACKEND"] = "software"
            env["QMLSCENE_DEVICE"] = "softwarecontext"

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
        self.phase += 0.033
        if not self.failed and self.stage < 2 and self.phase > 0.85:
            self.stage = 1
            self.status.setText(PHASES[1][0])
            self.detail.setText(PHASES[1][1])
        if self.proc is not None:
            code = self.proc.poll()
            if code is None:
                self.alive_for += 33
                now = time.monotonic()
                if now >= self._next_window_check:
                    self._next_window_check = now + 0.5
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
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        base = QLinearGradient(0, 0, w, h)
        base.setColorAt(0.0, QColor("#060912"))
        base.setColorAt(0.45, QColor("#0c1528"))
        base.setColorAt(1.0, QColor("#0a1622"))
        painter.fillRect(rect, base)

        # Slow aurora ribbons
        for i, (hue, amp, speed) in enumerate((
            (QColor(14, 165, 233, 55), 0.18, 0.55),
            (QColor(34, 211, 238, 40), 0.24, 0.38),
            (QColor(56, 189, 248, 28), 0.30, 0.28),
        )):
            path = QPainterPath()
            y0 = h * (0.25 + i * 0.18)
            path.moveTo(-40, y0)
            steps = 28
            for s in range(steps + 1):
                x = (w + 80) * s / steps - 40
                y = y0 + math.sin(self.phase * speed + s * 0.35 + i) * h * amp
                path.lineTo(x, y)
            path.lineTo(w + 40, h + 40)
            path.lineTo(-40, h + 40)
            path.closeSubpath()
            painter.fillPath(path, hue)

        # Soft orbs
        for cx_f, cy_f, radius_f, color in (
            (0.78 + 0.04 * math.sin(self.phase / 6), 0.28 + 0.05 * math.cos(self.phase / 8), 0.42, QColor(14, 165, 233, 70)),
            (0.18 + 0.03 * math.cos(self.phase / 7), 0.72 + 0.04 * math.sin(self.phase / 9), 0.34, QColor(56, 189, 248, 45)),
            (0.55, 0.55 + 0.03 * math.sin(self.phase / 5), 0.22, QColor(125, 211, 252, 28)),
        ):
            cx, cy = w * cx_f, h * cy_f
            rad = max(w, h) * radius_f
            glow = QRadialGradient(cx, cy, rad)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        # Star field
        painter.setPen(Qt.NoPen)
        for star in self._stars:
            twinkle = 0.55 + 0.45 * math.sin(self.phase * star["s"] + star["x"] * 12)
            painter.setBrush(QColor(226, 232, 240, int(star["a"] * twinkle)))
            x = (star["x"] * w + self.phase * 8 * star["s"]) % w
            y = (star["y"] * h + math.sin(self.phase * 0.2 + star["x"]) * 6) % h
            painter.drawEllipse(QPointF(x, y), star["r"], star["r"])

        # Orbital rings around center brand area
        cx, cy = w * 0.5, h * 0.38
        painter.setBrush(Qt.NoBrush)
        for i, radius in enumerate((160, 220, 300)):
            alpha = 28 + int(18 * math.sin(self.phase * 0.7 + i))
            painter.setPen(QPen(QColor(125, 211, 252, alpha), 1.2))
            painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
            ang = self.phase * (0.4 + i * 0.15) + i
            px = cx + math.cos(ang) * radius
            py = cy + math.sin(ang) * radius
            painter.setBrush(QColor(125, 211, 252, 180))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(px, py), 3.2, 3.2)
            painter.setBrush(Qt.NoBrush)

        # Vignette
        vignette = QRadialGradient(w * 0.5, h * 0.45, max(w, h) * 0.75)
        vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
        vignette.setColorAt(1.0, QColor(4, 8, 16, 160))
        painter.fillRect(rect, vignette)
        painter.end()


def main():
    try:
        app = QApplication(sys.argv)
        app.setFont(QFont("Inter", 12))
        window = Starter()
        window.cover()
        window.show()
        window.raise_()
        return app.exec_()
    except Exception as exc:
        sys.stderr.write(f"DevOS starter exception: {exc}\n")
        sys.stderr.flush()
        return 1


if __name__ == "__main__":
    sys.exit(main())
