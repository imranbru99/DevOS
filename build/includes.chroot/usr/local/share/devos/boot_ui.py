#!/usr/bin/env python3
"""Fullscreen first screen — same look as the Calamares installer (photo backdrop + cards)."""

import math
import os
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

try:
    from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, QSize, pyqtSignal
    from PyQt5.QtGui import (
        QColor, QFont, QLinearGradient, QRadialGradient, QPainter, QPixmap, QPen,
        QFontMetrics,
    )
    from PyQt5.QtWidgets import (
        QApplication, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
        QSizePolicy, QFrame, QScrollArea,
    )
except Exception:
    try:
        from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QSize, pyqtSignal
        from PyQt6.QtGui import (
            QColor, QFont, QLinearGradient, QRadialGradient, QPainter, QPixmap, QPen,
            QFontMetrics,
        )
        from PyQt6.QtWidgets import (
            QApplication, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget,
            QSizePolicy, QFrame, QScrollArea,
        )
    except Exception:
        sys.exit(0)


LOG = "/tmp/devos-calamares.log"
PREF_USERTYPE = "/run/devos-preferred-usertype"
PREF_USERTYPE_FALLBACK = "/tmp/devos-preferred-usertype"
SAFE_MODE_MARK = "/run/devos-installer-safe-mode"
INSTALLED_MARK = "/run/devos-already-installed"
# Only divert to the “unplug for sign-in” screen for a few days after Done.
# After that (months/years, same version or not) the USB opens Try DevOS again.
FRESH_INSTALL_SEC = 3 * 24 * 3600
BRANDING = "/etc/calamares/branding/devos"
BG_DIR = os.path.join(BRANDING, "bg")


def _live_version_id() -> str:
    try:
        for line in open("/etc/os-release", encoding="utf-8", errors="replace"):
            if line.startswith("VERSION_ID="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "26.04"


def _is_removable_sysblock(dev: str) -> bool:
    base = os.path.basename(dev)
    if "nvme" in base and "p" in base:
        base = base.rsplit("p", 1)[0]
    elif base[-1:].isdigit():
        while base and base[-1].isdigit():
            base = base[:-1]
    path = f"/sys/block/{base}/removable"
    try:
        return open(path, encoding="utf-8").read().strip() == "1"
    except OSError:
        return False


def _parse_install_marker(text: str) -> dict:
    info = {"version": "", "installed_at": "", "fresh": False, "same_version": False}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if key == "version":
            info["version"] = val
        elif key == "installed_at":
            info["installed_at"] = val
    live = _live_version_id()
    info["same_version"] = bool(info["version"]) and info["version"] == live
    # Legacy markers were just "ok\n" — treat as fresh only for this reboot path
    # via /run cache; otherwise allow normal live boot.
    stamp = info["installed_at"]
    if stamp and stamp != "unknown":
        try:
            from datetime import datetime, timezone
            when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - when).total_seconds()
            info["fresh"] = 0 <= age <= FRESH_INSTALL_SEC
        except Exception:
            info["fresh"] = False
    return info


def probe_installed_devos() -> dict:
    """Read ESP install marker from the internal disk (not the live USB).

    Returns {} when nothing is installed. When found, includes version,
    installed_at, same_version, and fresh (recent Done — nudge to sign-in).
    """
    empty = {}
    if os.path.isfile(INSTALLED_MARK):
        try:
            cached = _parse_install_marker(open(INSTALLED_MARK, encoding="utf-8").read())
            if cached.get("fresh"):
                return cached
        except OSError:
            pass
    try:
        out = subprocess.check_output(
            ["blkid", "-o", "device", "-t", "TYPE=vfat"],
            text=True, stderr=subprocess.DEVNULL, timeout=8,
        )
    except Exception:
        return empty
    for dev in out.splitlines():
        dev = dev.strip()
        if not dev or _is_removable_sysblock(dev):
            continue
        mnt = f"/run/devos-esp-check-{os.path.basename(dev)}"
        try:
            os.makedirs(mnt, exist_ok=True)
            subprocess.run(["mount", "-o", "ro", dev, mnt], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            for rel in ("EFI/DevOS/.installed", "EFI/BOOT/.devos-installed"):
                path = os.path.join(mnt, rel)
                if not os.path.isfile(path):
                    continue
                try:
                    raw = open(path, encoding="utf-8", errors="replace").read()
                except OSError:
                    continue
                info = _parse_install_marker(raw)
                try:
                    open(INSTALLED_MARK, "w", encoding="utf-8").write(raw if raw.strip() else "version=\n")
                except OSError:
                    pass
                subprocess.run(["umount", "-l", mnt], check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return info
        except Exception:
            pass
        finally:
            subprocess.run(["umount", "-l", mnt], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                os.rmdir(mnt)
            except OSError:
                pass
    return empty


def detect_installed_devos() -> bool:
    """True only for a *fresh* install (few days) — not forever."""
    info = probe_installed_devos()
    return bool(info.get("fresh"))

PHASES = (
    ("Starting DevOS", "Loading the live session and installer shell."),
    ("Preparing the display", "Bringing up a smooth desktop for install."),
    ("Opening the disk installer", "You can erase a disk or keep dual-boot — nothing writes until you confirm Install."),
)

# Same options as before; laid out like Calamares list cards instead of a game menu.
OPTIONS = (
    {
        "id": "try",
        "badge": "RECOMMENDED",
        "title": "Try DevOS",
        "subtitle": "Open the installer. Explore, then install when you are ready — your disk stays untouched until you confirm.",
        "accent": (56, 189, 248),
        "mark": "▶",
        "recommended": True,
        "safe_graphics": False,
        "usertype": "",
    },
    {
        "id": "graphics",
        "badge": "COMPATIBILITY",
        "title": "Safe Graphics",
        "subtitle": "Software rendering for blank screens, old GPUs, or broken drivers. Same installer, safer display path.",
        "accent": (52, 211, 153),
        "mark": "◈",
        "recommended": False,
        "safe_graphics": True,
        "usertype": "",
    },
    {
        "id": "premium",
        "badge": "PREMIUM",
        "title": "Premium Setup",
        "subtitle": "Full DevOS experience with every app ready to tick. Family Safety stays off until you turn it on.",
        "accent": (125, 211, 252),
        "mark": "★",
        "recommended": False,
        "safe_graphics": False,
        "usertype": "premium",
    },
    {
        "id": "premium_safe",
        "badge": "PREMIUM · SAFE",
        "title": "Premium + Safe Graphics",
        "subtitle": "Premium app set with software graphics — best when you want everything and the display is unreliable.",
        "accent": (186, 230, 253),
        "mark": "✦",
        "recommended": False,
        "safe_graphics": True,
        "usertype": "premium",
    },
)

WELCOME_CHIPS = (
    "Erase & format disk",
    "Windows apps",
    "Android apps",
    "Local AI",
    "Voice Typing",
    "Developer tools",
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


def write_usertype_pref(usertype):
    for path in (PREF_USERTYPE, PREF_USERTYPE_FALLBACK):
        try:
            folder = os.path.dirname(path)
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write((usertype or "").strip() + "\n")
            return
        except OSError:
            continue


def clear_usertype_pref():
    for path in (PREF_USERTYPE, PREF_USERTYPE_FALLBACK):
        try:
            os.remove(path)
        except OSError:
            pass


def load_backgrounds():
    """Same scenic plates Calamares InstallerBackground uses."""
    paths = []
    if os.path.isdir(BG_DIR):
        for name in ("02.jpg", "03.jpg", "04.jpg", "05.jpg", "06.jpg", "01.jpg"):
            path = os.path.join(BG_DIR, name)
            if os.path.isfile(path):
                paths.append(path)
    for name in ("wallpaper.jpg", "welcome.png", "installer-background.svg"):
        path = os.path.join(BRANDING, name)
        if os.path.isfile(path) and path not in paths:
            paths.append(path)
    pixmaps = []
    for path in paths:
        pix = QPixmap(path)
        if not pix.isNull():
            pixmaps.append(pix)
    return pixmaps


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


class OptionCard(QPushButton):
    """Installer-style row — matches Calamares usertype / AI cards."""

    chosen = pyqtSignal(dict)

    def __init__(self, option, parent=None):
        super().__init__(parent)
        self.option = option
        self._hover = False
        self._focus = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.setMinimumHeight(72)
        self.setMaximumWidth(640)
        self.clicked.connect(lambda: self.chosen.emit(self.option))

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def focusInEvent(self, event):
        self._focus = True
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._focus = False
        self.update()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.chosen.emit(self.option)
            return
        super().keyPressEvent(event)

    def sizeHint(self):
        bf = QFont("Segoe UI", 9, QFont.DemiBold)
        subf = QFont("Segoe UI", 11)
        sm = QFontMetrics(subf)
        badge_w = QFontMetrics(bf).horizontalAdvance(self.option["badge"]) + 14
        text_w = max(240, 640 - 90 - badge_w)
        sub_h = sm.boundingRect(0, 0, text_w, 2000, Qt.TextWordWrap, self.option["subtitle"]).height()
        return QSize(640, max(78, 46 + sub_h))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = self.option["accent"]
        selected = self._hover or self._focus or self.option.get("recommended")

        fill = QColor("#0c2338" if selected else ("#111c31" if self._hover else "#0f172a"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 16, 16)

        border = QColor(*accent) if selected else QColor("#1e293b")
        painter.setPen(QPen(border, 2.0 if selected else 1.0))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 16, 16)

        # Mark tile (same idea as Calamares type cards)
        mark_r = QRectF(rect.left() + 12, rect.center().y() - 18, 36, 36)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#083044" if selected else "#111827"))
        painter.drawRoundedRect(mark_r, 11, 11)
        painter.setPen(QColor(*accent) if selected else QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        painter.drawText(mark_r, Qt.AlignCenter, self.option["mark"])

        # Badge
        badge = self.option["badge"]
        bf = QFont("Segoe UI", 9, QFont.DemiBold)
        painter.setFont(bf)
        metrics = QFontMetrics(bf)
        bw = metrics.horizontalAdvance(badge) + 14
        bh = metrics.height() + 4
        badge_r = QRectF(rect.right() - bw - 12, rect.top() + 10, bw, bh)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(accent[0], accent[1], accent[2], 40))
        painter.drawRoundedRect(badge_r, bh / 2.0, bh / 2.0)
        painter.setPen(QColor(*accent))
        painter.drawText(badge_r, Qt.AlignCenter, badge)

        # Title + subtitle
        painter.setPen(QColor("#f8fafc"))
        painter.setFont(QFont("Segoe UI", 14, QFont.Bold))
        title_r = QRectF(rect.left() + 60, rect.top() + 10, rect.width() - 90 - bw, 22)
        painter.drawText(title_r, Qt.AlignVCenter | Qt.AlignLeft, self.option["title"])

        painter.setPen(QColor("#94a3b8"))
        painter.setFont(QFont("Segoe UI", 11))
        sub_r = QRectF(rect.left() + 60, rect.top() + 34, rect.width() - 76, rect.height() - 42)
        painter.drawText(sub_r, Qt.TextWordWrap | Qt.AlignTop | Qt.AlignLeft, self.option["subtitle"])
        painter.end()


class Chip(QFrame):
    def __init__(self, text, highlight=False, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)
        label = QLabel(text)
        label.setStyleSheet(
            "color: %s; background: transparent; font-size: 14px;"
            % ("#7dd3fc" if highlight else "#e2e8f0")
        )
        layout.addWidget(label)
        self.setStyleSheet(
            "QFrame { background: rgba(15, 23, 42, 210); border: 1px solid %s; border-radius: 17px; }"
            % ("#38bdf8" if highlight else "#334a6e")
        )


class Starter(QWidget):
    CHOOSER_TIMEOUT_SEC = 12
    # Plymouth FB splash is blank on some Intel TVs — real motion happens here in X11.
    INTRO_SEC = 4.5

    def __init__(self):
        super().__init__()
        self.phase = 0.0
        self.stage = 0
        self.proc = None
        self.installer_was_visible = False
        self.kwin = None
        self.alive_for = 0
        self.failed = False
        self.safe_graphics = False
        self.auto_safe_retried = False
        self.install_info = probe_installed_devos()
        self.already_installed = bool(self.install_info.get("fresh"))
        self.mode = "intro"  # intro | chooser | launching | failed | installed
        self.selected = OPTIONS[0]
        self.countdown = self.CHOOSER_TIMEOUT_SEC
        self._intro_left = self.INTRO_SEC
        self._bgs = load_backgrounds()
        self._bg_index = 0
        self._bg_accum = 0.0
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet("background: #070a12;")
        self.setFocusPolicy(Qt.StrongFocus)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Centered scroll column — short screens must still reach every option.
        column = QWidget()
        column.setStyleSheet("background: transparent;")
        column.setMaximumWidth(720)
        column.setMinimumWidth(420)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 4px; }"
            "QScrollBar::handle:vertical { background: rgba(56,189,248,140); border-radius: 5px; min-height: 28px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.scroll_body = QWidget()
        self.scroll_body.setStyleSheet("background: transparent;")
        body = QVBoxLayout(self.scroll_body)
        body.setContentsMargins(28, 24, 28, 24)
        body.setSpacing(0)

        # Welcome header (hidden while launching / on failure).
        self.header_wrap = QWidget()
        self.header_wrap.setStyleSheet("background: transparent;")
        header = QVBoxLayout(self.header_wrap)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(0)

        logo = QLabel()
        logo.setAlignment(Qt.AlignHCenter)
        logo.setStyleSheet("background: transparent;")
        pixmap = QPixmap(os.path.join(BRANDING, "logo.png"))
        if pixmap.isNull():
            pixmap = QPixmap("/usr/share/pixmaps/devos-logo.png")
        if not pixmap.isNull():
            logo.setPixmap(pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        header.addWidget(logo)
        header.addSpacing(12)

        eyebrow = QLabel("WELCOME")
        eyebrow.setAlignment(Qt.AlignHCenter)
        eyebrow.setStyleSheet(
            "color: #38bdf8; background: transparent; font-size: 11px; "
            "font-weight: 600; letter-spacing: 2.4px;"
        )
        title = QLabel("How do you want to start?")
        title.setAlignment(Qt.AlignHCenter)
        title.setWordWrap(True)
        title.setStyleSheet(
            "color: #f8fafc; background: transparent; font-size: 28px; font-weight: 700;"
        )
        lead = QLabel(
            "One fast desktop for Linux, Windows and Android apps, with a private AI assistant built in. "
            "Pick a path below — the installer that opens next uses the same look."
        )
        lead.setAlignment(Qt.AlignHCenter)
        lead.setWordWrap(True)
        lead.setStyleSheet("color: #94a3b8; background: transparent; font-size: 13px;")
        header.addWidget(eyebrow)
        header.addSpacing(6)
        header.addWidget(title)
        header.addSpacing(8)
        header.addWidget(lead)
        header.addSpacing(14)

        chip_wrap = QWidget()
        chip_wrap.setStyleSheet("background: transparent;")
        chip_flow = QVBoxLayout(chip_wrap)
        chip_flow.setContentsMargins(0, 0, 0, 0)
        chip_flow.setSpacing(6)
        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        for i, text in enumerate(WELCOME_CHIPS):
            if i > 0 and i % 3 == 0:
                chip_flow.addLayout(chip_row)
                chip_row = QHBoxLayout()
                chip_row.setSpacing(8)
            chip_row.addWidget(Chip(text, highlight=(i == 0)), 0, Qt.AlignLeft)
        if chip_row.count():
            chip_row.addStretch(1)
            chip_flow.addLayout(chip_row)
        header.addWidget(chip_wrap)
        header.addSpacing(16)
        body.addWidget(self.header_wrap)

        self.chooser_wrap = QWidget()
        self.chooser_wrap.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(self.chooser_wrap)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(8)
        self.cards = []
        for option in OPTIONS:
            card = OptionCard(option)
            card.chosen.connect(self.on_option_chosen)
            self.cards.append(card)
            list_layout.addWidget(card, 0, Qt.AlignHCenter)
        body.addWidget(self.chooser_wrap)

        self.countdown_label = QLabel("")
        self.countdown_label.setAlignment(Qt.AlignHCenter)
        self.countdown_label.setStyleSheet(
            "color: #64748b; background: transparent; font-size: 12px;"
        )
        body.addSpacing(10)
        body.addWidget(self.countdown_label)
        body.addSpacing(8)

        # Launching / failure panel — centered status only (no leftover welcome chips).
        self.launch_wrap = QWidget()
        self.launch_wrap.setStyleSheet("background: transparent;")
        self.launch_wrap.setVisible(False)
        launch_layout = QVBoxLayout(self.launch_wrap)
        launch_layout.setContentsMargins(0, 16, 0, 0)
        launch_layout.addStretch(1)

        self.status = QLabel(PHASES[0][0])
        self.status.setAlignment(Qt.AlignHCenter)
        self.status.setStyleSheet(
            "color: #7dd3fc; background: transparent; font-size: 22px; font-weight: 600;"
        )
        self.detail = QLabel(PHASES[0][1])
        self.detail.setAlignment(Qt.AlignHCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: #94a3b8; background: transparent; font-size: 16px;")
        self.hint = QLabel("Erase disk · Manual dual-boot · Format extra drives — all optional until Install")
        self.hint.setAlignment(Qt.AlignHCenter)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #64748b; background: transparent; font-size: 13px;")
        self.bar = Bar(self)

        self.log = QLabel("")
        self.log.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.log.setWordWrap(True)
        self.log.setVisible(False)
        self.log.setStyleSheet(
            "color: #e2e8f0; background: rgba(8, 12, 22, 180); "
            "font-family: monospace; font-size: 13px; padding: 16px; border-radius: 12px;"
        )

        self.retry = QPushButton("Try Safe Graphics")
        self.retry.setVisible(False)
        self.retry.setCursor(Qt.PointingHandCursor)
        self.retry.setStyleSheet(
            "QPushButton { color: #041018; background: #38bdf8; border: none; "
            "border-radius: 12px; padding: 14px 26px; font-size: 16px; font-weight: 600; }"
            "QPushButton:hover { background: #7dd3fc; }"
        )
        self.retry.clicked.connect(lambda: self.launch_installer(force_safe=True))

        self.back_to_options = QPushButton("Back to options")
        self.back_to_options.setVisible(False)
        self.back_to_options.setCursor(Qt.PointingHandCursor)
        self.back_to_options.setStyleSheet(
            "QPushButton { color: #e2e8f0; background: transparent; border: 1px solid #334155; "
            "border-radius: 12px; padding: 12px 22px; font-size: 14px; }"
            "QPushButton:hover { border-color: #38bdf8; color: #7dd3fc; }"
        )
        self.back_to_options.clicked.connect(self.show_chooser)

        power_btn_style = (
            "QPushButton { color: #e2e8f0; background: #1e293b; border: 1px solid #334155; "
            "border-radius: 12px; padding: 12px 18px; font-size: 14px; }"
            "QPushButton:hover { border-color: #38bdf8; color: #7dd3fc; }"
        )
        self.reboot_btn = QPushButton("Restart")
        self.reboot_btn.setVisible(False)
        self.reboot_btn.setCursor(Qt.PointingHandCursor)
        self.reboot_btn.setStyleSheet(power_btn_style)
        self.reboot_btn.clicked.connect(lambda: self.confirm_power("reboot"))
        self.poweroff_btn = QPushButton("Shut down")
        self.poweroff_btn.setVisible(False)
        self.poweroff_btn.setCursor(Qt.PointingHandCursor)
        self.poweroff_btn.setStyleSheet(power_btn_style)
        self.poweroff_btn.clicked.connect(lambda: self.confirm_power("poweroff"))

        launch_layout.addWidget(self.status)
        launch_layout.addSpacing(6)
        launch_layout.addWidget(self.detail)
        launch_layout.addSpacing(10)
        launch_layout.addWidget(self.hint)
        launch_layout.addSpacing(26)
        launch_layout.addWidget(self.bar, alignment=Qt.AlignHCenter)
        launch_layout.addSpacing(18)
        launch_layout.addWidget(self.log)
        launch_layout.addSpacing(16)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.back_to_options)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.reboot_btn)
        btn_row.addWidget(self.poweroff_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.retry)
        btn_row.addStretch(1)
        launch_layout.addLayout(btn_row)
        launch_layout.addStretch(1)
        body.addWidget(self.launch_wrap, 1)

        self.scroll.setWidget(self.scroll_body)
        col.addWidget(self.scroll, 1)

        root.addStretch(1)
        root.addWidget(column, 0)
        root.addStretch(1)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.tick)
        self.clock.start(33)
        self._next_window_check = 0.0
        self._countdown_accum = 0.0

        self._update_countdown_label()
        # Hide chooser during the X11 motion intro (alternative to broken Plymouth).
        self.header_wrap.setVisible(False)
        self.chooser_wrap.setVisible(False)
        self.countdown_label.setVisible(False)
        self.launch_wrap.setVisible(False)
        QTimer.singleShot(400, self.start_desktop)

        if self._cmdline_wants_safe():
            # Skip intro — go straight into safe graphics install path.
            self._intro_left = 0
            self.show_chooser()
            self.on_option_chosen(OPTIONS[1])

    def _cmdline_wants_safe(self):
        try:
            with open("/proc/cmdline", "r", encoding="utf-8", errors="replace") as handle:
                cmd = handle.read().lower()
            return "nomodeset" in cmd or "safe-graphics" in cmd
        except OSError:
            return False

    def _update_countdown_label(self):
        if self.mode != "chooser":
            self.countdown_label.setText("")
            return
        self.countdown_label.setText(
            "Starting Try DevOS in %ss · press a row sooner · 1–4 or Enter"
            % max(0, int(self.countdown))
        )

    def show_chooser(self):
        if self.already_installed:
            self.show_installed()
            return
        self.mode = "chooser"
        self.failed = False
        self.countdown = self.CHOOSER_TIMEOUT_SEC
        self._countdown_accum = 0.0
        self.header_wrap.setVisible(True)
        self.chooser_wrap.setVisible(True)
        self.countdown_label.setVisible(True)
        self.launch_wrap.setVisible(False)
        self.retry.setVisible(False)
        self.back_to_options.setVisible(False)
        self.reboot_btn.setVisible(False)
        self.poweroff_btn.setVisible(False)
        self.log.setVisible(False)
        self._update_countdown_label()
        self.showFullScreen()
        self.raise_()
        if self.cards:
            self.cards[0].setFocus()

    def show_installed(self):
        """Fresh install + USB still first — nudge to sign-in, keep reinstall path."""
        self.mode = "installed"
        self.failed = False
        self.header_wrap.setVisible(False)
        self.chooser_wrap.setVisible(False)
        self.countdown_label.setVisible(False)
        self.launch_wrap.setVisible(True)
        self.retry.setVisible(False)
        self.log.setVisible(False)
        self.reboot_btn.setVisible(True)
        self.poweroff_btn.setVisible(True)
        self.back_to_options.setVisible(True)
        self.back_to_options.setText("Use live USB / Reinstall")
        try:
            self.back_to_options.clicked.disconnect()
        except TypeError:
            pass
        self.back_to_options.clicked.connect(self.continue_live_anyway)
        ver = self.install_info.get("version") or _live_version_id()
        same = self.install_info.get("same_version")
        same_txt = "same version as this USB" if same else "on this PC"
        self.status.setText("DevOS %s is already on this PC" % ver)
        self.detail.setText(
            "Install just finished, but this USB opened again instead of sign-in. "
            "Unplug the USB, then Restart for the hard-disk login (%s)."
            % same_txt
        )
        self.hint.setText(
            "Want the live installer anyway? Choose “Use live USB / Reinstall”. "
            "Months later this USB opens Try DevOS normally — the marker does not lock you out."
        )
        self.bar.setVisible(False)
        self.showFullScreen()
        self.raise_()
        self.reboot_btn.setFocus()

    def continue_live_anyway(self):
        """User explicitly wants the live USB / reinstall even with DevOS on disk."""
        self.already_installed = False
        self.install_info = {}
        try:
            if os.path.isfile(INSTALLED_MARK):
                os.remove(INSTALLED_MARK)
        except OSError:
            pass
        try:
            self.back_to_options.clicked.disconnect()
        except TypeError:
            pass
        self.back_to_options.setText("Back to options")
        self.back_to_options.clicked.connect(self.show_chooser)
        self.show_chooser()

    def confirm_power(self, op):
        """Ask before reboot/poweroff as an in-window panel (not a separate dialog).

        This starter is Frameless + WindowStaysOnTop + X11Bypass, so a normal
        QMessageBox opens *under* it and looks like the confirmation never showed.
        """
        if getattr(self, "_power_confirm", None) is not None:
            self._power_confirm.raise_()
            return

        title = "Restart this PC?" if op == "reboot" else "Shut down this PC?"
        body = (
            "This PC will restart now. Unsaved work in other windows will be lost."
            if op == "reboot"
            else "This PC will shut down now. Unsaved work in other windows will be lost."
        )
        yes_label = "Restart now" if op == "reboot" else "Shut down now"

        scrim = QWidget(self)
        scrim.setObjectName("powerConfirmScrim")
        scrim.setStyleSheet("QWidget#powerConfirmScrim { background: rgba(2, 6, 23, 200); }")
        scrim.setGeometry(self.rect())
        scrim.raise_()

        card = QFrame(scrim)
        card.setObjectName("powerConfirmCard")
        card.setStyleSheet(
            "QFrame#powerConfirmCard { background: #0f172a; border: 1px solid #1e3a5f; "
            "border-radius: 18px; }"
            "QLabel { color: #e2e8f0; background: transparent; }"
            "QPushButton { min-width: 120px; min-height: 36px; border-radius: 10px; "
            "padding: 8px 14px; font-weight: 700; background: #141b2d; color: #e2e8f0; "
            "border: 1px solid #334155; }"
            "QPushButton#powerConfirmYes { background: #7f1d1d; border-color: #b91c1c; "
            "color: #fecaca; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 22, 22, 18)
        lay.setSpacing(12)
        head = QLabel(title)
        head.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        detail = QLabel(body)
        detail.setWordWrap(True)
        detail.setStyleSheet("font-size: 14px; color: #94a3b8;")
        lay.addWidget(head)
        lay.addWidget(detail)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        yes = QPushButton(yes_label)
        yes.setObjectName("powerConfirmYes")
        row.addWidget(cancel)
        row.addWidget(yes)
        lay.addLayout(row)
        card.adjustSize()
        card.setFixedWidth(min(420, max(280, self.width() - 48)))
        card.adjustSize()
        card.move(
            max(0, (scrim.width() - card.width()) // 2),
            max(0, (scrim.height() - card.height()) // 2),
        )

        def _close():
            self._power_confirm = None
            scrim.deleteLater()

        def _yes():
            _close()
            self.force_power(op)

        cancel.clicked.connect(_close)
        yes.clicked.connect(_yes)
        self._power_confirm = scrim
        scrim.show()
        yes.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        panel = getattr(self, "_power_confirm", None)
        if panel is not None:
            panel.setGeometry(self.rect())
            for child in panel.findChildren(QFrame):
                if child.objectName() == "powerConfirmCard":
                    child.move(
                        max(0, (panel.width() - child.width()) // 2),
                        max(0, (panel.height() - child.height()) // 2),
                    )
                    break

    def force_power(self, op):
        """Force reboot/poweroff even when the session is stuck on this overlay."""
        for cmd in (
            ["systemctl", op, "--force", "--force"],
            ["systemctl", op, "--force"],
            ["/sbin/" + ("reboot" if op == "reboot" else "poweroff"), "-f"],
        ):
            try:
                subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue

    def on_option_chosen(self, option):
        self.selected = option
        self.safe_graphics = bool(option.get("safe_graphics"))
        usertype = (option.get("usertype") or "").strip()
        if usertype:
            write_usertype_pref(usertype)
        else:
            clear_usertype_pref()
        self.mode = "launching"
        self.header_wrap.setVisible(False)
        self.chooser_wrap.setVisible(False)
        self.countdown_label.setVisible(False)
        self.launch_wrap.setVisible(True)
        self.countdown_label.setText("")
        self.stage = 0
        self.status.setText(PHASES[0][0])
        self.detail.setText(PHASES[0][1])
        if self.safe_graphics and usertype == "premium":
            self.hint.setText("Premium Setup · Safe Graphics — full app set with software rendering")
        elif self.safe_graphics:
            self.hint.setText("Safe Graphics — software rendering for difficult displays")
        elif usertype == "premium":
            self.hint.setText("Premium Setup — every DevOS app available on the Choose your apps page")
        else:
            self.hint.setText("Erase disk · Manual dual-boot · Format extra drives — all optional until Install")
        self.start_desktop()
        QTimer.singleShot(350, lambda: self.launch_installer(force_safe=self.safe_graphics))

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

    def release_overlay(self):
        """Stop covering the screen so Calamares can be seen and used."""
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        except Exception:
            pass
        self.hide()
        try:
            QApplication.instance().quit()
        except Exception:
            pass

    def launch_installer(self, force_safe=False):
        if self.already_installed:
            self.show_installed()
            return
        retrying = self.failed or force_safe or self.safe_graphics
        self.failed = False
        self.alive_for = 0
        self.installer_was_visible = False
        self.retry.setVisible(False)
        self.back_to_options.setVisible(False)
        self.reboot_btn.setVisible(False)
        self.poweroff_btn.setVisible(False)
        self.log.setVisible(False)
        self.mode = "launching"
        self.header_wrap.setVisible(False)
        self.chooser_wrap.setVisible(False)
        self.countdown_label.setVisible(False)
        self.launch_wrap.setVisible(True)
        self.stage = 2
        self.status.setText(PHASES[2][0])
        if force_safe or self.safe_graphics:
            self.detail.setText("Opening with safe software graphics…")
        else:
            self.detail.setText(PHASES[2][1])
        # If Calamares is already running, just get out of the way.
        if self.calamares_running():
            self.installer_was_visible = True
            self.release_overlay()
            return
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
            self.proc = None
        # Only stop a stuck launcher — never kill a healthy Calamares window.
        subprocess.run(
            ["pkill", "-f", "/usr/local/bin/devos-install-gui"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            os.remove("/tmp/devos-installer.lock")
        except OSError:
            pass
        time.sleep(0.6)
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
            self.safe_graphics = True
            env["LIBGL_ALWAYS_SOFTWARE"] = "1"
            env["QT_QUICK_BACKEND"] = "software"
            env["QMLSCENE_DEVICE"] = "softwarecontext"
            try:
                open(SAFE_MODE_MARK, "a", encoding="utf-8").close()
            except OSError:
                pass
            log.write("==> boot_ui: launching with software graphics\n")

        try:
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
        except OSError as exc:
            log.write("Could not start calamares: %s\n" % exc)
            log.close()
            self.show_failure()
            return
        log.close()
        # Do not keep a bypass/always-on-top sheet over Calamares while it starts.
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            self.showFullScreen()
        except Exception:
            pass

    def calamares_running(self):
        try:
            return (
                subprocess.run(
                    ["pgrep", "-x", "calamares"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                ).returncode
                == 0
            )
        except (OSError, subprocess.SubprocessError):
            return False

    def installer_window_visible(self):
        if self.calamares_running() and self.alive_for > 3500:
            self.installer_was_visible = True
            return True
        try:
            out = subprocess.check_output(
                ["xwininfo", "-root", "-tree"],
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        lowered = out.lower()
        # Title is often "DevOS 26.04 LTS"; class is usually calamares.
        visible = (
            b"calamares" in lowered
            or b"devos installer" in lowered
            or b"devos 26" in lowered
            or b"devos" in lowered and b"lts" in lowered
        )
        if visible:
            self.installer_was_visible = True
        return visible

    def show_failure(self):
        self.failed = True
        self.mode = "failed"
        # If Calamares actually came up under us, never show a false failure.
        if self.calamares_running() or self.installer_window_visible():
            self.release_overlay()
            return
        self.showFullScreen()
        self.raise_()
        self.header_wrap.setVisible(False)
        self.chooser_wrap.setVisible(False)
        self.countdown_label.setVisible(False)
        self.launch_wrap.setVisible(True)
        self.status.setText("The installer did not open")
        self.detail.setText(
            "DevOS is still running. Try Safe Graphics, go back to options, or Restart this PC."
        )
        text = ""
        try:
            with open(LOG, "r", encoding="utf-8", errors="replace") as handle:
                lines = useful_log_lines(handle.readlines(), limit=18)
            text = "".join(lines).strip()
        except OSError:
            text = ""
        if not text:
            text = "No installer log was written. The display connection or calamares package is missing."
        self.log.setText(text)
        self.log.setVisible(True)
        self.retry.setVisible(True)
        self.back_to_options.setVisible(True)
        self.reboot_btn.setVisible(True)
        self.poweroff_btn.setVisible(True)

    def maybe_auto_safe_retry(self):
        """One automatic software-graphics relaunch before the failure panel."""
        if self.auto_safe_retried or self.safe_graphics or self.failed:
            return False
        self.auto_safe_retried = True
        self.safe_graphics = True
        try:
            with open(LOG, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(
                    "==> boot_ui: no Calamares window yet; auto-retrying with software graphics\n"
                )
        except OSError:
            pass
        self.status.setText("Retrying with safe graphics")
        self.detail.setText("Hardware graphics did not show the installer. Switching to software mode…")
        self.launch_installer(force_safe=True)
        return True

    def tick(self):
        self.phase += 0.033
        self._bg_accum += 0.033
        # Faster plate cross-switch so the background motion is obvious.
        if self._bg_accum >= 4.5 and self._bgs:
            self._bg_accum = 0.0
            self._bg_index = (self._bg_index + 1) % len(self._bgs)
        if self.mode == "intro":
            self._intro_left -= 0.033
            self.cover()
            self.update()
            if self._intro_left <= 0:
                self.show_chooser()
            return
        if self.mode == "chooser":
            self._countdown_accum += 0.033
            if self._countdown_accum >= 1.0:
                self._countdown_accum = 0.0
                self.countdown -= 1
                self._update_countdown_label()
                if self.countdown <= 0:
                    self.on_option_chosen(OPTIONS[0])
            self.cover()
            self.update()
            return

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
                        self.release_overlay()
                        return
                    elif self.alive_for > 15000 and not self.safe_graphics:
                        self.maybe_auto_safe_retry()
                    elif self.alive_for > 90000 and not self.failed:
                        self.show_failure()
            elif self.calamares_running() or self.installer_was_visible:
                # Launcher exited after handing off to Calamares — leave.
                self.release_overlay()
                return
            elif code == 0 and self.alive_for < 2000:
                # flock race / already-running handoff — check once more.
                self.proc = None
                if self.calamares_running():
                    self.release_overlay()
                    return
                if not self.maybe_auto_safe_retry():
                    self.show_failure()
            elif self.alive_for < 8000 or not self.installer_was_visible:
                self.proc = None
                if not self.maybe_auto_safe_retry():
                    self.show_failure()
            else:
                self.release_overlay()
                return
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

    def keyPressEvent(self, event):
        if self.mode == "intro":
            self.show_chooser()
            return
        if self.mode == "chooser":
            key = event.key()
            if key in (Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4):
                idx = key - Qt.Key_1
                if 0 <= idx < len(OPTIONS):
                    self.on_option_chosen(OPTIONS[idx])
                    return
            if key == Qt.Key_Escape:
                self.on_option_chosen(OPTIONS[0])
                return
        super().keyPressEvent(event)

    def paintEvent(self, _event):
        """Match Calamares InstallerBackground: photo plate + aurora + left veil."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        if self.mode == "intro":
            self._paint_motion_intro(painter, rect, w, h)
            painter.end()
            return

        painter.fillRect(rect, QColor("#070a12"))

        if self._bgs:
            pix = self._bgs[self._bg_index]
            # PreserveAspectCrop + strong Ken-Burns pan/zoom (motion background).
            scale = max(w / max(1, pix.width()), h / max(1, pix.height()))
            scale *= 1.12 + 0.10 * (0.5 + 0.5 * math.sin(self.phase / 3.2))
            tw, th = int(pix.width() * scale), int(pix.height() * scale)
            pan_x = int((w - tw) / 2 + math.sin(self.phase / 2.4) * (tw - w) * 0.35)
            pan_y = int((h - th) / 2 + math.cos(self.phase / 2.8) * (th - h) * 0.30)
            painter.setOpacity(0.55)
            painter.drawPixmap(pan_x, pan_y, tw, th, pix)
            # Soft trail of previous plate for crossfade feel
            if len(self._bgs) > 1:
                prev = self._bgs[(self._bg_index - 1) % len(self._bgs)]
                painter.setOpacity(0.18 * max(0.0, 1.0 - self._bg_accum / 4.5))
                painter.drawPixmap(pan_x - 24, pan_y, tw, th, prev)
            painter.setOpacity(1.0)

        # Aurora orbs — brighter drift so motion reads on camera / TVs
        for cx_f, cy_f, radius_f, color in (
            (0.78 + 0.06 * math.sin(self.phase / 2.8), -0.05 + 0.08 * math.cos(self.phase / 3.2), 0.38, QColor(14, 165, 233, 70)),
            (0.05 + 0.07 * math.cos(self.phase / 3.0), 0.70 + 0.06 * math.sin(self.phase / 2.6), 0.32, QColor(14, 165, 233, 58)),
            (0.40 + 0.05 * math.sin(self.phase / 2.2), 0.78 + 0.05 * math.sin(self.phase / 2.0), 0.24, QColor(34, 211, 238, 48)),
        ):
            cx, cy = w * cx_f, h * cy_f
            rad = max(w, h) * radius_f
            glow = QRadialGradient(cx, cy, rad)
            glow.setColorAt(0.0, color)
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        # Left readability veil
        veil = QLinearGradient(0, 0, w, 0)
        veil.setColorAt(0.0, QColor(7, 10, 18, 230))
        veil.setColorAt(0.45, QColor(7, 10, 18, 153))
        veil.setColorAt(1.0, QColor(7, 10, 18, 51))
        painter.fillRect(rect, veil)

        # Soft top/bottom vignette
        vig = QLinearGradient(0, 0, 0, h)
        vig.setColorAt(0.0, QColor(7, 10, 18, 102))
        vig.setColorAt(0.2, QColor(0, 0, 0, 0))
        vig.setColorAt(0.8, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(7, 10, 18, 136))
        painter.fillRect(rect, vig)
        painter.end()

    def _paint_motion_intro(self, painter, rect, w, h):
        """Fullscreen X11 motion splash — used because Plymouth FB often stays blank."""
        breath = 0.5 + 0.5 * math.sin(self.phase * 2.4)
        top = QColor(int(8 + 40 * breath), int(80 + 100 * breath), int(160 + 80 * breath))
        bot = QColor(int(4 + 20 * breath), int(30 + 60 * breath), int(70 + 90 * breath))
        wash = QLinearGradient(0, 0, 0, h)
        wash.setColorAt(0.0, top)
        wash.setColorAt(1.0, bot)
        painter.fillRect(rect, wash)

        for cx_f, cy_f, radius_f, rgba in (
            (0.50 + 0.18 * math.sin(self.phase * 1.1), 0.42 + 0.10 * math.cos(self.phase * 0.9), 0.42, (56, 189, 248, 110)),
            (0.22 + 0.12 * math.cos(self.phase * 1.3), 0.65 + 0.08 * math.sin(self.phase * 1.0), 0.30, (34, 211, 238, 90)),
            (0.78 + 0.10 * math.sin(self.phase * 0.8), 0.28 + 0.12 * math.cos(self.phase * 1.2), 0.34, (125, 211, 252, 80)),
        ):
            cx, cy = w * cx_f, h * cy_f
            rad = max(w, h) * radius_f
            glow = QRadialGradient(cx, cy, rad)
            glow.setColorAt(0.0, QColor(*rgba))
            glow.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.fillRect(rect, glow)

        def _text_w(font, text):
            metrics = QFontMetrics(font)
            if hasattr(metrics, "horizontalAdvance"):
                return metrics.horizontalAdvance(text)
            return metrics.width(text)

        # Brand
        painter.setPen(QColor(255, 255, 255, 230))
        font = QFont("Segoe UI", 54, QFont.Bold)
        painter.setFont(font)
        title = "DevOS"
        tw = _text_w(font, title)
        painter.drawText(int((w - tw) / 2), int(h * 0.42), title)

        painter.setPen(QColor(125, 211, 252, 255))
        mfont = QFont("Segoe UI", 22)
        mfont.setWeight(QFont.Bold)
        painter.setFont(mfont)
        motion = "DevOS Motion"
        mw = _text_w(mfont, motion)
        slide = int(math.sin(self.phase * 2.0) * w * 0.08)
        painter.drawText(int((w - mw) / 2) + slide, int(h * 0.50), motion)

        # Animated hash bar
        bar_font = QFont("Consolas", 18)
        painter.setFont(bar_font)
        filled = 1 + int((self.phase * 8) % 20)
        bar = "[ " + "#" * filled + " " * (20 - filled) + " ]"
        painter.setPen(QColor(186, 230, 253, 255))
        bw = _text_w(bar_font, bar)
        painter.drawText(int((w - bw) / 2), int(h * 0.58), bar)

        painter.setPen(QColor(148, 163, 184, 220))
        sfont = QFont("Segoe UI", 14)
        painter.setFont(sfont)
        status = "Starting DevOS..."
        sw = _text_w(sfont, status)
        painter.drawText(int((w - sw) / 2), int(h * 0.66), status)

        hint = "Press any key to continue"
        hw = _text_w(sfont, hint)
        painter.setPen(QColor(100, 116, 139, 200))
        painter.drawText(int((w - hw) / 2), int(h * 0.72), hint)


def useful_log_lines(raw_lines, limit=18):
    """Drop SELinux chcon noise so the failure panel shows real errors."""
    kept = []
    for line in raw_lines:
        lower = line.lower()
        if "chcon:" in lower or "getfilecon" in lower:
            continue
        kept.append(line)
    return kept[-limit:]


def main():
    try:
        app = QApplication(sys.argv)
        app.setFont(QFont("Segoe UI", 12))
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
