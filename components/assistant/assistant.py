#!/usr/bin/env python3
"""
DevOS AI - the desktop assistant window.

Type or speak a request ("what is my PC config", "go to Chrome and search
HP latest laptop", "open Wi-Fi settings"), or attach a PDF / document / image
and ask about it. Requests are routed by tools.route() first; only questions
nothing can act on go to the on-device model. Everything runs on this PC.

Layout: a collapsible sidebar with past chats (engine.ChatStore), a slim
header, the conversation in a centred column, and a floating composer.
All icons and the logo are painted with QPainter (no icon theme needed).
All slow work (tools, model, OCR, voice, downloads) runs in QThreads.
"""

import math
import os
import sys
import threading
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from PyQt5 import QtCore, QtGui, QtWidgets  # noqa: E402
from PyQt5.QtCore import Qt  # noqa: E402

import documents  # noqa: E402
import engine  # noqa: E402
import markdown_lite  # noqa: E402
import tools  # noqa: E402
import listen  # noqa: E402
import vision  # noqa: E402
import voice  # noqa: E402

APP_TITLE = "DevOS AI"

# -- palette ---------------------------------------------------------------
BG = "#07090f"
SIDEBAR_BG = "#0b0e16"
DIVIDER = "#161b2a"
SURFACE = "#121725"
SURFACE_HI = "#161c2b"
BORDER = "#232a3d"
BORDER_HI = "#36415e"
USER_BG = "#1e2638"
TEXT = "#e2e8f0"
TEXT_STRONG = "#f1f5f9"
MUTED = "#94a3b8"
FAINT = "#64748b"
ACCENT = "#22d3ee"       # cyan
ACCENT_2 = "#8b5cf6"     # violet
LINK = "#7dd3fc"
# Selected text: vivid blue + white so it stands out on every bubble and on
# the background (the old dark teal looked like nothing was selected).
SELECTION = "#2563eb"
CODE_BG = "#0d1117"
DANGER = "#f87171"
RECORD = "#ef4444"
WARN = "#fbbf24"
OK = "#34d399"

# -- type and spacing (8 px grid) -------------------------------------------
FS_SMALL, FS_BODY, FS_LARGE, FS_HERO = 13, 15, 17, 28
FONT_FAMILY = "Inter, 'Noto Sans', sans-serif"
MONO = "'JetBrains Mono', 'Noto Sans Mono', monospace"
SIDEBAR_W = 260
COLUMN_MAX = 760
NARROW = 900

PLACEHOLDER = "Message DevOS AI…  (type, attach, or hold the mic)"
ATTACH_FILTER = ("Images and documents (*.png *.jpg *.jpeg *.webp *.pdf *.txt *.md *.docx);;"
                 "Images (*.png *.jpg *.jpeg *.webp);;Documents (*.pdf *.txt *.md *.docx)")
IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp)"
DOC_FILTER = "Documents (*.pdf *.txt *.md *.docx)"
ATTACH_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt", ".md", ".docx"}
MAX_ATTACH = 5

# (prompt, description, icon)
SUGGESTIONS = [
    ("What's my PC config?", "Processor, memory, disks and graphics", "chip"),
    ("How many apps are installed?", "Linux, Windows and Android apps", "grid"),
    ("Go to Chrome and search HP latest laptop", "Opens the results in your browser", "globe"),
    ("Free up space", "See what can be cleaned safely", "drive"),
]

STYLE = f"""
QWidget {{ font-family: {FONT_FAMILY}; font-size: {FS_BODY}px; color: {TEXT}; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: #1a2031; color: {TEXT}; border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
    font-size: {FS_SMALL}px; }}
QScrollArea#chatScroll, QWidget#chatHost, QWidget#column, QWidget#heroPage {{ background: transparent; border: none; }}
QScrollArea#codeScroll {{ background: transparent; border: none; }}
QScrollArea#codeScroll > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 4px 2px 4px 0; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.08); border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.18); }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0 4px 2px 4px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.10); border-radius: 3px; min-width: 36px; }}
QScrollBar::handle:horizontal:hover {{ background: rgba(255,255,255,0.20); }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QLabel#title {{ color: {TEXT_STRONG}; font-size: {FS_BODY}px; font-weight: 600; }}
QFrame#userBubble {{ background: {USER_BG}; border-radius: 18px; }}
QLabel#userText {{ color: {TEXT_STRONG}; font-size: {FS_BODY}px; }}
QLabel#botText {{ color: {TEXT}; font-size: {FS_BODY}px; }}
QLabel#noticeText {{ color: {TEXT}; font-size: 14px; }}
QLabel#meta {{ color: {FAINT}; font-size: 12px; }}
QFrame#codeBlock {{ background: {CODE_BG}; border: 1px solid #1c2333; border-radius: 12px; }}
QFrame#codeHead {{ background: transparent; border: none; border-bottom: 1px solid #1c2333; }}
QLabel#codeLang {{ color: {FAINT}; font-size: 12px; font-family: {MONO}; }}
QLabel#code {{ color: #e6edf3; font-family: {MONO}; font-size: {FS_SMALL}px; }}
QPushButton#pill {{ background: rgba(255,255,255,0.04); color: {TEXT_STRONG}; border: 1px solid #2a3248;
    border-radius: 16px; padding: 7px 14px; font-size: 14px; font-weight: 500; }}
QPushButton#pill:hover {{ background: rgba(34,211,238,0.08); border-color: rgba(34,211,238,0.45); }}
QPushButton#pill:disabled {{ color: {FAINT}; border-color: {BORDER}; background: transparent; }}
QPushButton#textBtn {{ background: transparent; color: {MUTED}; border: none; border-radius: 6px; padding: 3px 8px;
    font-size: 12px; }}
QPushButton#textBtn:hover {{ background: rgba(255,255,255,0.06); color: {TEXT_STRONG}; }}
QFrame#composer {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 24px; }}
QFrame#composer[focus="true"] {{ border: 1px solid {BORDER_HI}; }}
QPlainTextEdit#input {{ background: transparent; border: none; color: {TEXT_STRONG}; font-size: {FS_BODY}px;
    selection-background-color: {SELECTION}; selection-color: #ffffff; padding: 0; }}
QFrame#chip {{ background: #1a2031; border: 1px solid #262e44; border-radius: 12px; }}
QLabel#chipName {{ color: {TEXT_STRONG}; font-size: {FS_SMALL}px; font-weight: 500; }}
QLabel#chipMeta {{ color: {FAINT}; font-size: 12px; }}
QLabel#hint {{ color: {FAINT}; font-size: 12px; }}
QLabel#recLabel {{ color: {TEXT_STRONG}; font-size: {FS_BODY}px; font-weight: 500; }}
QLabel#recTime {{ color: {MUTED}; font-size: {FS_SMALL}px; font-family: {MONO}; }}
QLabel#heroTitle {{ color: {TEXT_STRONG}; font-size: {FS_HERO}px; font-weight: 600; }}
QLabel#heroSub {{ color: {MUTED}; font-size: {FS_BODY}px; }}
QPushButton#newChat {{ background: rgba(255,255,255,0.04); border: 1px solid #1d2335; border-radius: 12px;
    color: {TEXT_STRONG}; font-size: 14px; font-weight: 500; text-align: left; padding: 0 12px; }}
QPushButton#newChat:hover {{ background: rgba(255,255,255,0.07); border-color: #2a3248; }}
QLabel#kbd {{ color: {FAINT}; font-size: 12px; }}
QLineEdit#search {{ background: rgba(255,255,255,0.03); border: 1px solid #1a2030; border-radius: 10px;
    padding: 0 8px 0 2px; font-size: 14px; color: {TEXT}; selection-background-color: {SELECTION}; selection-color: #ffffff; }}
QLineEdit#search:focus {{ border-color: #2c3650; background: rgba(255,255,255,0.045); }}
QListWidget#chatList {{ background: transparent; border: none; outline: 0; }}
QLineEdit#renameEdit {{ background: #121725; border: 1px solid {ACCENT}; border-radius: 6px; padding: 0 6px;
    font-size: 14px; color: {TEXT_STRONG}; }}
QLabel#sideEmpty {{ color: {FAINT}; font-size: {FS_SMALL}px; }}
QLabel#smartTitle {{ color: {TEXT_STRONG}; font-size: 14px; font-weight: 500; }}
QLabel#smartSub {{ color: {FAINT}; font-size: 12px; }}
QMenu {{ background: transparent; border: none; }}
QMenu::item {{ padding: 8px 20px 8px 10px; border-radius: 8px; font-size: 14px; color: {TEXT}; margin: 0 6px; }}
QMenu::item:selected {{ background: #1c2335; color: {TEXT_STRONG}; }}
QMenu::icon {{ padding-left: 8px; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 10px; }}
QMessageBox, QDialog, QProgressDialog {{ background: {SURFACE}; }}
QMessageBox QLabel, QProgressDialog QLabel {{ color: {TEXT}; font-size: 14px; }}
QMessageBox QPushButton, QProgressDialog QPushButton {{ background: rgba(255,255,255,0.05); color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 10px; padding: 7px 16px; min-width: 76px; font-size: 14px; }}
QMessageBox QPushButton:hover, QProgressDialog QPushButton:hover {{ border-color: {BORDER_HI}; }}
QMessageBox QPushButton:default {{ background: {ACCENT}; color: #04121a; border: none; font-weight: 600; }}
QProgressBar {{ background: rgba(255,255,255,0.06); border: none; border-radius: 3px; max-height: 6px;
    text-align: center; color: transparent; }}
QProgressBar::chunk {{ border-radius: 3px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 {ACCENT}, stop:1 {ACCENT_2}); }}
"""


def qcolor(c, alpha=None):
    col = QtGui.QColor(c)
    if alpha is not None:
        col.setAlpha(int(max(0, min(255, alpha))))
    return col


def accent_gradient(x1, y1, x2, y2, alpha=255):
    g = QtGui.QLinearGradient(x1, y1, x2, y2)
    g.setColorAt(0.0, qcolor(ACCENT, alpha))
    g.setColorAt(1.0, qcolor(ACCENT_2, alpha))
    return g


# ---------------------------------------------------------------------------
# Painted icons (24-unit grid, Lucide-like strokes; no icon theme dependency)
# ---------------------------------------------------------------------------

ICON_KINDS = ("plus", "mic", "stop", "send", "copy", "refresh", "sidebar", "search", "trash", "new", "image",
              "file", "check", "close", "edit", "chip", "grid", "globe", "drive", "spark", "download", "warn",
              "info", "arrow_down", "lock", "clip")


def _star(path_cx, path_cy, r, k):
    s = QtGui.QPainterPath()
    s.moveTo(path_cx, path_cy - r)
    s.quadTo(path_cx + k, path_cy - k, path_cx + r, path_cy)
    s.quadTo(path_cx + k, path_cy + k, path_cx, path_cy + r)
    s.quadTo(path_cx - k, path_cy + k, path_cx - r, path_cy)
    s.quadTo(path_cx - k, path_cy - k, path_cx, path_cy - r)
    return s


def draw_icon(p, kind, rect, color, stroke=1.7):
    """Paint icon `kind` into QRectF `rect` with QPainter `p`."""
    rect = QtCore.QRectF(rect)
    k = rect.width() / 24.0
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.translate(rect.topLeft())
    p.scale(k, k)
    pen = QtGui.QPen(qcolor(color) if not isinstance(color, QtGui.QColor) else color)
    pen.setWidthF(stroke / k)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    P = QtCore.QPointF
    R = QtCore.QRectF

    def line(x1, y1, x2, y2):
        p.drawLine(P(x1, y1), P(x2, y2))

    def poly(*pts):
        p.drawPolyline(QtGui.QPolygonF([P(x, y) for x, y in pts]))

    def fill(path_or_rect, radius=None):
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(pen.color())
        if isinstance(path_or_rect, QtGui.QPainterPath):
            p.drawPath(path_or_rect)
        elif radius is not None:
            p.drawRoundedRect(path_or_rect, radius, radius)
        else:
            p.drawEllipse(path_or_rect)
        p.restore()

    if kind == "plus":
        line(12, 5, 12, 19)
        line(5, 12, 19, 12)
    elif kind == "minus":
        line(5, 12, 19, 12)
    elif kind == "mic":
        p.drawRoundedRect(R(9, 3, 6, 11), 3, 3)
        p.drawArc(R(5, 4, 14, 14), 180 * 16, 180 * 16)
        line(12, 18, 12, 21)
    elif kind == "stop":
        fill(R(7, 7, 10, 10), 2.5)
    elif kind == "send":
        line(12, 19, 12, 5)
        poly((6, 11), (12, 5), (18, 11))
    elif kind == "copy":
        p.drawRoundedRect(R(8.5, 8.5, 12.5, 12.5), 2.5, 2.5)
        path = QtGui.QPainterPath()
        path.moveTo(15.5, 8.5)
        path.lineTo(15.5, 5.5)
        path.quadTo(15.5, 3, 13, 3)
        path.lineTo(5.5, 3)
        path.quadTo(3, 3, 3, 5.5)
        path.lineTo(3, 13)
        path.quadTo(3, 15.5, 5.5, 15.5)
        path.lineTo(8.5, 15.5)
        p.drawPath(path)
    elif kind == "refresh":
        path = QtGui.QPainterPath()
        path.arcMoveTo(R(4, 4, 16, 16), 0)
        path.arcTo(R(4, 4, 16, 16), 0, -270)
        path.quadTo(16.5, 4, 19.5, 7.5)
        p.drawPath(path)
        poly((20, 3), (20, 8), (15, 8))
    elif kind == "sidebar":
        p.drawRoundedRect(R(3, 4, 18, 16), 3, 3)
        line(9.5, 4, 9.5, 20)
    elif kind == "search":
        p.drawEllipse(P(11, 11), 6.5, 6.5)
        line(16, 16, 20.5, 20.5)
    elif kind == "trash":
        line(4, 7, 20, 7)
        path = QtGui.QPainterPath()
        path.moveTo(6, 7)
        path.lineTo(6.8, 18.5)
        path.quadTo(7, 20.5, 9, 20.5)
        path.lineTo(15, 20.5)
        path.quadTo(17, 20.5, 17.2, 18.5)
        path.lineTo(18, 7)
        p.drawPath(path)
        poly((9, 7), (9, 5), (10, 4), (14, 4), (15, 5), (15, 7))
        line(10.2, 11, 10.2, 16.5)
        line(13.8, 11, 13.8, 16.5)
    elif kind == "new":
        path = QtGui.QPainterPath()
        path.moveTo(11, 4)
        path.lineTo(6.5, 4)
        path.quadTo(4, 4, 4, 6.5)
        path.lineTo(4, 17.5)
        path.quadTo(4, 20, 6.5, 20)
        path.lineTo(17.5, 20)
        path.quadTo(20, 20, 20, 17.5)
        path.lineTo(20, 13)
        p.drawPath(path)
        pen2 = QtGui.QPainterPath()
        pen2.moveTo(17.6, 3.4)
        pen2.lineTo(20.6, 6.4)
        pen2.lineTo(12.2, 14.8)
        pen2.lineTo(8.8, 15.2)
        pen2.lineTo(9.2, 11.8)
        pen2.closeSubpath()
        p.drawPath(pen2)
    elif kind == "image":
        p.drawRoundedRect(R(3, 4, 18, 16), 3, 3)
        p.drawEllipse(P(9, 9.5), 1.7, 1.7)
        poly((20.5, 15.5), (15.5, 10.5), (5.5, 20))
    elif kind in ("file", "clip"):
        path = QtGui.QPainterPath()
        path.moveTo(14, 3)
        path.lineTo(7, 3)
        path.quadTo(5, 3, 5, 5)
        path.lineTo(5, 19)
        path.quadTo(5, 21, 7, 21)
        path.lineTo(17, 21)
        path.quadTo(19, 21, 19, 19)
        path.lineTo(19, 8)
        path.closeSubpath()
        p.drawPath(path)
        poly((14, 3), (14, 8), (19, 8))
        if kind == "file":
            line(9, 13, 15, 13)
            line(9, 16.5, 13, 16.5)
    elif kind == "check":
        poly((5, 12.5), (10, 17), (19, 7.5))
    elif kind == "close":
        line(6.5, 6.5, 17.5, 17.5)
        line(17.5, 6.5, 6.5, 17.5)
    elif kind == "edit":
        path = QtGui.QPainterPath()
        path.moveTo(16.5, 3.5)
        path.lineTo(20.5, 7.5)
        path.lineTo(8, 20)
        path.lineTo(4, 20)
        path.lineTo(4, 16)
        path.closeSubpath()
        p.drawPath(path)
        line(14, 6, 18, 10)
    elif kind == "chip":
        p.drawRoundedRect(R(6, 6, 12, 12), 2, 2)
        p.drawRoundedRect(R(9.5, 9.5, 5, 5), 1, 1)
        for c in (10, 14):
            line(c, 2.5, c, 6)
            line(c, 18, c, 21.5)
            line(2.5, c, 6, c)
            line(18, c, 21.5, c)
    elif kind == "grid":
        for x, y in ((4, 4), (13, 4), (4, 13), (13, 13)):
            p.drawRoundedRect(R(x, y, 7, 7), 2, 2)
    elif kind == "globe":
        p.drawEllipse(P(12, 12), 9, 9)
        p.drawEllipse(R(8, 3, 8, 18))
        line(3, 12, 21, 12)
    elif kind == "drive":
        p.drawRoundedRect(R(3, 13, 18, 7), 2, 2)
        path = QtGui.QPainterPath()
        path.moveTo(3.5, 14)
        path.lineTo(6.2, 6)
        path.quadTo(6.8, 4.5, 8.4, 4.5)
        path.lineTo(15.6, 4.5)
        path.quadTo(17.2, 4.5, 17.8, 6)
        path.lineTo(20.5, 14)
        p.drawPath(path)
        fill(R(6.2, 15.6, 1.8, 1.8))
        line(11, 16.5, 17, 16.5)
    elif kind == "spark":
        fill(_star(11, 12.5, 8.5, 1.9))
        fill(_star(18.5, 5, 3, 0.7))
    elif kind == "download":
        line(12, 4, 12, 15)
        poly((7, 10), (12, 15), (17, 10))
        line(5, 20, 19, 20)
    elif kind in ("warn", "info"):
        p.drawEllipse(P(12, 12), 9, 9)
        if kind == "warn":
            line(12, 7.5, 12, 13)
            fill(R(11.05, 15.6, 1.9, 1.9))
        else:
            line(12, 11, 12, 16.5)
            fill(R(11.05, 6.8, 1.9, 1.9))
    elif kind == "arrow_down":
        line(12, 5, 12, 19)
        poly((6, 13), (12, 19), (18, 13))
    elif kind == "lock":
        p.drawRoundedRect(R(5, 11, 14, 10), 2.5, 2.5)
        path = QtGui.QPainterPath()
        path.moveTo(8, 11)
        path.lineTo(8, 8)
        path.arcTo(R(8, 4, 8, 8), 180, -180)
        path.lineTo(16, 11)
        p.drawPath(path)
    p.restore()


def make_icon(kind: str, color: str = MUTED, size: int = 20, stroke: float = 1.7) -> QtGui.QIcon:
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QtGui.QPainter(pm)
    draw_icon(p, kind, QtCore.QRectF(0, 0, size, size), color, stroke)
    p.end()
    return QtGui.QIcon(pm)


def paint_logo(p, rect, radius=0.30):
    """The DevOS AI mark: rounded square, cyan -> violet, white four-point sparkle."""
    rect = QtCore.QRectF(rect)
    size = rect.width()
    p.save()
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(accent_gradient(rect.left(), rect.top(), rect.right(), rect.bottom()))
    p.drawRoundedRect(rect, size * radius, size * radius)
    # soft top highlight
    hl = QtGui.QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    hl.setColorAt(0.0, QtGui.QColor(255, 255, 255, 46))
    hl.setColorAt(0.55, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(hl)
    p.drawRoundedRect(rect, size * radius, size * radius)
    c = QtCore.QPointF(rect.center())
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawPath(_star(c.x() - size * 0.02, c.y() + size * 0.03, size * 0.29, size * 0.065))
    p.setBrush(QtGui.QColor(255, 255, 255, 215))
    p.drawPath(_star(rect.left() + size * 0.74, rect.top() + size * 0.27, size * 0.10, size * 0.025))
    p.restore()


def logo_pixmap(size: int = 36, radius: float = 0.30) -> QtGui.QPixmap:
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    p = QtGui.QPainter(pm)
    paint_logo(p, QtCore.QRectF(0, 0, size, size), radius)
    p.end()
    return pm


def rounded_thumb(path: str, size: int, radius: float = 8.0):
    """Centre-cropped, rounded square thumbnail, or None if the image can't be read."""
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)
    src = reader.size()
    if src.isValid() and max(src.width(), src.height()) > 1600:
        reader.setScaledSize(src.scaled(1600, 1600, Qt.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return None
    dpr = 2
    side = size * dpr
    img = img.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (img.width() - side) // 2
    y = (img.height() - side) // 2
    img = img.copy(x, y, side, side)
    pm = QtGui.QPixmap(side, side)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    clip = QtGui.QPainterPath()
    clip.addRoundedRect(QtCore.QRectF(0, 0, side, side), radius * dpr, radius * dpr)
    p.setClipPath(clip)
    p.drawImage(0, 0, img)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def make_menu(parent=None):
    """A rounded, dark popup menu."""
    m = RoundMenu(parent)
    return m


class RoundMenu(QtWidgets.QMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setContentsMargins(0, 6, 0, 6)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(QtGui.QPen(qcolor(BORDER), 1))
        p.setBrush(qcolor(SURFACE))
        p.drawRoundedRect(QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.end()
        super().paintEvent(e)


def _elide(text, n):
    return text if len(text) <= n else text[: n - 9] + "…" + text[-8:]


def _fmt_time(ts):
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError):
        return ""
    return time.strftime("%I:%M %p", t).lstrip("0")


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


class Worker(QtCore.QThread):
    done = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int, int)
    level = QtCore.pyqtSignal(float)
    delta = QtCore.pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(self))
        except Exception as exc:  # never let a worker kill the window
            self.failed.emit(str(exc) or exc.__class__.__name__)


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------


class IconButton(QtWidgets.QAbstractButton):
    """Round or rounded-square icon button with a soft hover fill."""

    def __init__(self, kind, tip="", size=34, icon_size=18, color=MUTED, hover_color=TEXT_STRONG, radius=None,
                 parent=None):
        super().__init__(parent)
        self.kind = kind
        self.color = color
        self.hover_color = hover_color
        self.icon_px = icon_size
        self.radius = radius
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
        self.setFocusPolicy(Qt.TabFocus)
        self._hover = False
        self._kbd = False

    def focusInEvent(self, e):
        self._kbd = e.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self._kbd = False
        super().focusOutEvent(e)

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return self.size()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect())
        rad = self.radius if self.radius is not None else r.height() / 2
        if (self._hover or self.isDown()) and self.isEnabled():
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 22 if self.isDown() else 15))
            p.drawRoundedRect(r, rad, rad)
        if self.hasFocus() and self._kbd:
            p.setPen(QtGui.QPen(qcolor(ACCENT, 140), 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad, rad)
        col = self.hover_color if self._hover and self.isEnabled() else self.color
        if not self.isEnabled():
            col = qcolor(FAINT, 120)
        s = self.icon_px
        draw_icon(p, self.kind, QtCore.QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s), col)
        p.end()


class SendButton(QtWidgets.QAbstractButton):
    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Send (Enter)")
        self._hover = False
        self.stop_mode = False

    def set_stop(self, on):
        if on != self.stop_mode:
            self.stop_mode = on
            self.setToolTip("Stop answering (Esc)" if on else "Send (Enter)")
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        if self.stop_mode:
            p.setBrush(qcolor(TEXT_STRONG if not self._hover else "#ffffff"))
            p.drawEllipse(r)
            draw_icon(p, "stop", QtCore.QRectF(8, 8, 20, 20), qcolor(BG))
            p.end()
            return
        if self.isEnabled():
            p.setBrush(accent_gradient(r.left(), r.top(), r.right(), r.bottom()))
            p.drawEllipse(r)
            if self._hover:
                p.setBrush(QtGui.QColor(255, 255, 255, 34))
                p.drawEllipse(r)
            col = QtGui.QColor("#ffffff")
        else:
            p.setBrush(qcolor("#1f2637"))
            p.drawEllipse(r)
            col = qcolor(FAINT)
        draw_icon(p, "send", QtCore.QRectF(8, 8, 20, 20), col, 2.1)
        p.end()


class MicButton(QtWidgets.QAbstractButton):
    """Click to toggle, or hold to talk. While recording: red with a pulsing ring."""
    pressed_at = 0.0

    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.recording = False
        self.level = 0.0
        self._hover = False
        self._t = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.unavailable = ""
        self.set_recording(False)

    def set_unavailable(self, reason):
        """Dimmed with an explanation while voice can't work here; clicks still arrive (to show a hint)."""
        self.unavailable = reason or ""
        self.setCursor(Qt.ArrowCursor if self.unavailable else Qt.PointingHandCursor)
        self.set_recording(self.recording)

    def set_recording(self, on):
        self.recording = on
        if self.unavailable and not on:
            self.setToolTip(self.unavailable)
        else:
            self.setToolTip("Stop listening (Esc)" if on else "Speak a command (click, or hold to talk)")
        if on:
            self._timer.start(33)
        else:
            self._timer.stop()
        self.update()

    def set_level(self, v):
        self.level = max(0.0, min(1.0, float(v)))

    def _tick(self):
        self._t += 0.033
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect())
        c = r.center()
        p.setPen(Qt.NoPen)
        if self.recording:
            pulse = (math.sin(self._t * 4.2) + 1) / 2
            ring = 13 + 4 * pulse + 3 * self.level
            p.setBrush(qcolor(RECORD, 50 + 60 * (1 - pulse)))
            p.drawEllipse(c, ring + 1, ring + 1)
            p.setBrush(qcolor(RECORD))
            p.drawEllipse(c, 13, 13)
            draw_icon(p, "stop", QtCore.QRectF(c.x() - 9, c.y() - 9, 18, 18), QtGui.QColor("#ffffff"))
        elif self.unavailable:
            p.setOpacity(0.4)
            draw_icon(p, "mic", QtCore.QRectF(c.x() - 10, c.y() - 10, 20, 20), MUTED)
        else:
            if self._hover:
                p.setBrush(QtGui.QColor(255, 255, 255, 15))
                p.drawEllipse(r)
            draw_icon(p, "mic", QtCore.QRectF(c.x() - 10, c.y() - 10, 20, 20),
                      TEXT_STRONG if self._hover else MUTED)
        p.end()


class GradientAvatar(QtWidgets.QWidget):
    """The small logo beside assistant messages. active=True: a breathing glow while thinking."""

    def __init__(self, size=28, active=False):
        super().__init__()
        self.logo = size
        self.pad = 6
        self.setFixedSize(size + self.pad * 2, size + self.pad * 2)
        self._t = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        if active:
            self._timer.start(33)

    def _tick(self):
        self._t += 0.033
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        if self._timer.isActive():
            pulse = (math.sin(self._t * 3.2) + 1) / 2
            g = QtGui.QRadialGradient(c, self.width() / 2)
            g.setColorAt(0.45, qcolor(ACCENT_2, 40 + 90 * pulse))
            g.setColorAt(1.0, qcolor(ACCENT, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, self.width() / 2, self.height() / 2)
        s = self.logo
        if self._timer.isActive():
            s = self.logo * (0.94 + 0.06 * (math.sin(self._t * 3.2) + 1) / 2)
        paint_logo(p, QtCore.QRectF(c.x() - s / 2, c.y() - s / 2, s, s), 0.32)
        p.end()


class ShimmerLabel(QtWidgets.QWidget):
    """Text with a light sweeping across it ("Thinking…")."""

    def __init__(self, text="Thinking"):
        super().__init__()
        self.text = text
        self._t = 0.0
        f = self.font()
        f.setPixelSize(FS_BODY)
        f.setWeight(QtGui.QFont.Medium)
        self.setFont(f)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)
        self._fit()

    def _fit(self):
        fm = QtGui.QFontMetrics(self.font())
        self.setFixedSize(fm.horizontalAdvance(self.text + "…") + 6, fm.height() + 4)

    def set_text(self, t):
        self.text = t
        self._fit()
        self.update()

    def _tick(self):
        self._t = (self._t + 0.033) % 1.8
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        w = self.width()
        x = -w * 0.5 + (self._t / 1.8) * w * 2.0
        g = QtGui.QLinearGradient(x - w * 0.35, 0, x + w * 0.35, 0)
        base = qcolor(MUTED, 170)
        g.setColorAt(0.0, base)
        g.setColorAt(0.5, QtGui.QColor("#ffffff"))
        g.setColorAt(1.0, base)
        p.setPen(QtGui.QPen(QtGui.QBrush(g), 1))
        p.setFont(self.font())
        dots = "." * (1 + int(self._t * 1.7) % 3)
        p.drawText(self.rect().adjusted(0, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, self.text + dots)
        p.end()


class RichLabel(QtWidgets.QLabel):
    def __init__(self, html_text: str, obj: str):
        super().__init__()
        self.setObjectName(obj)
        self.setTextFormat(Qt.RichText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.setOpenExternalLinks(True)
        self.setText(html_text)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Minimum)
        self.setCursor(Qt.IBeamCursor)


class FlowLayout(QtWidgets.QLayout):
    """Wraps children onto new lines (attachment chips)."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QtCore.QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QtCore.QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        return s

    def _do(self, rect, test):
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            nx = x + hint.width() + self._sp
            if nx - self._sp > rect.right() + 1 and line_h > 0:
                x = rect.x()
                y += line_h + self._sp
                nx = x + hint.width() + self._sp
                line_h = 0
            if not test:
                it.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x = nx
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def file_meta(path):
    kind = documents.kind_of(path)
    ext = os.path.splitext(path)[1].lstrip(".").upper()[:4] or "FILE"
    label = {"image": "Image", "pdf": "PDF", "docx": "Word"}.get(kind, ext)
    try:
        size = tools.human_size(os.path.getsize(path))
    except OSError:
        size = ""
    return kind, ext, label, size


class FileTile(QtWidgets.QWidget):
    """40 px square: image thumbnail, or a tinted tile with a file icon."""

    COLORS = {"pdf": "#f87171", "docx": "#60a5fa", "text": "#a3e635", "image": "#c084fc"}

    def __init__(self, path, size=40):
        super().__init__()
        self.setFixedSize(size, size)
        self.kind = documents.kind_of(path)
        self.thumb = rounded_thumb(path, size, 9) if self.kind == "image" and os.path.isfile(path) else None

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect())
        if self.thumb is not None:
            p.drawPixmap(0, 0, self.thumb)
            p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 20), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), 9, 9)
        else:
            col = self.COLORS.get(self.kind, MUTED)
            p.setPen(Qt.NoPen)
            p.setBrush(qcolor(col, 34))
            p.drawRoundedRect(r, 9, 9)
            s = r.width() * 0.5
            draw_icon(p, "image" if self.kind == "image" else "file",
                      QtCore.QRectF((r.width() - s) / 2, (r.height() - s) / 2, s, s), col)
        p.end()


class Chip(QtWidgets.QFrame):
    """An attachment waiting in the composer, or displayed in the chat."""
    removed = QtCore.pyqtSignal(str)

    def __init__(self, path, removable=True):
        super().__init__()
        self.path = path
        self.removable = removable
        self.setObjectName("chip")
        self.setFixedHeight(56)
        if not removable:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"{path}\n(Click to open / view)")
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(7, 7, 6 if removable else 12, 7)
        lay.setSpacing(10)
        kind, ext, label, size = file_meta(path)
        lay.addWidget(FileTile(path, 40))
        txt = QtWidgets.QVBoxLayout()
        txt.setSpacing(1)
        txt.setContentsMargins(0, 2, 0, 2)
        name = QtWidgets.QLabel(_elide(os.path.basename(path), 24))
        name.setObjectName("chipName")
        name.setToolTip(path)
        meta = QtWidgets.QLabel(" · ".join(x for x in (label, size) if x))
        meta.setObjectName("chipMeta")
        txt.addWidget(name)
        txt.addWidget(meta)
        lay.addLayout(txt)
        if removable:
            x = IconButton("close", "Remove", size=22, icon_size=12, color=MUTED)
            x.clicked.connect(lambda: self.removed.emit(self.path))
            lay.addWidget(x, 0, Qt.AlignTop)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self.removable:
            if documents.kind_of(self.path) == "image" and os.path.isfile(self.path):
                dlg = ImagePreviewDialog(self.path, self.window())
                dlg.exec_()
            elif os.path.isfile(self.path) and shutil.which("xdg-open"):
                subprocess.Popen(["xdg-open", self.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        super().mouseReleaseEvent(e)


class ClickableThumb(QtWidgets.QLabel):
    """Rounded image thumbnail that opens a zoomable lightbox dialog on click."""

    def __init__(self, path, size=120, radius=14):
        super().__init__()
        self.path = path
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{os.path.basename(path)}\n(Click to view & zoom)")
        self._hover = False
        self._pm = rounded_thumb(path, size, radius)
        if self._pm is not None:
            self.setPixmap(self._pm)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._hover:
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.Antialiasing)
            r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
            p.setPen(QtGui.QPen(QtGui.QColor(ACCENT), 2))
            p.setBrush(QtGui.QColor(0, 0, 0, 60))
            p.drawRoundedRect(r, 14, 14)
            draw_icon(p, "search", QtCore.QRectF(r.width() - 28, r.height() - 28, 20, 20), "#ffffff", stroke=2.0)
            p.end()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            dlg = ImagePreviewDialog(self.path, self.window())
            dlg.exec_()
        super().mouseReleaseEvent(e)


class ImageCanvas(QtWidgets.QLabel):
    """Display area inside the lightbox; supports drag-panning and mouse-wheel zooming."""

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self._drag_start = None

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if delta > 0:
            self.dialog.adjust_zoom(1.18)
        elif delta < 0:
            self.dialog.adjust_zoom(0.85)
        e.accept()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_start is not None and (e.buttons() & Qt.LeftButton):
            delta = e.pos() - self._drag_start
            h_bar = self.dialog.scroll.horizontalScrollBar()
            v_bar = self.dialog.scroll.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_start = None
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            if abs(self.dialog.zoom - 1.0) < 0.05:
                self.dialog.fit_to_window()
            else:
                self.dialog.set_zoom(1.0)
        super().mouseDoubleClickEvent(e)


class ImagePreviewDialog(QtWidgets.QDialog):
    """A modal lightbox image viewer with zoom (wheel / buttons) and click-drag panning."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(f"DevOS AI · {os.path.basename(path)}")
        self.resize(1000, 750)
        self.setStyleSheet(f"QDialog {{ background: #0b0e14; }}")

        self.orig_pixmap = QtGui.QPixmap(path)
        self.zoom = 1.0

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(8)

        info_col = QtWidgets.QVBoxLayout()
        info_col.setSpacing(1)
        name_lbl = QtWidgets.QLabel(os.path.basename(path))
        name_lbl.setStyleSheet(f"color: {TEXT_STRONG}; font-size: 15px; font-weight: 600;")
        dim_str = f"{self.orig_pixmap.width()} × {self.orig_pixmap.height()} px" if not self.orig_pixmap.isNull() else ""
        size_str = ""
        try:
            sz = os.path.getsize(path)
            size_str = f" · {sz / 1024:.1f} KB" if sz < 1024 * 1024 else f" · {sz / (1024 * 1024):.1f} MB"
        except OSError:
            pass
        dim_lbl = QtWidgets.QLabel(dim_str + size_str)
        dim_lbl.setStyleSheet(f"color: {FAINT}; font-size: 12px;")
        info_col.addWidget(name_lbl)
        info_col.addWidget(dim_lbl)
        header.addLayout(info_col)
        header.addStretch(1)

        btn_out = IconButton("minus", "Zoom out (-)", size=32, icon_size=16)
        btn_out.clicked.connect(lambda: self.adjust_zoom(0.8))

        self.zoom_pct = QtWidgets.QLabel("100%")
        self.zoom_pct.setStyleSheet(f"color: {TEXT_STRONG}; font-size: 13px; font-weight: 500; min-width: 50px;")
        self.zoom_pct.setAlignment(Qt.AlignCenter)

        btn_in = IconButton("plus", "Zoom in (+)", size=32, icon_size=16)
        btn_in.clicked.connect(lambda: self.adjust_zoom(1.25))

        btn_fit = QtWidgets.QPushButton("Fit to Window")
        btn_fit.setCursor(Qt.PointingHandCursor)
        btn_fit.setStyleSheet(f"background: rgba(255,255,255,0.06); color: {TEXT}; border: 1px solid {BORDER}; "
                              f"border-radius: 8px; padding: 5px 12px; font-size: 12px;")
        btn_fit.clicked.connect(self.fit_to_window)

        btn_100 = QtWidgets.QPushButton("100%")
        btn_100.setCursor(Qt.PointingHandCursor)
        btn_100.setStyleSheet(f"background: rgba(255,255,255,0.06); color: {TEXT}; border: 1px solid {BORDER}; "
                              f"border-radius: 8px; padding: 5px 12px; font-size: 12px;")
        btn_100.clicked.connect(lambda: self.set_zoom(1.0))

        btn_open = QtWidgets.QPushButton("Open External")
        btn_open.setToolTip("Open in default system photo viewer")
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.setStyleSheet(f"background: rgba(255,255,255,0.06); color: {TEXT}; border: 1px solid {BORDER}; "
                               f"border-radius: 8px; padding: 5px 12px; font-size: 12px;")
        btn_open.clicked.connect(self.open_external)

        btn_close = IconButton("close", "Close (Esc)", size=32, icon_size=16)
        btn_close.clicked.connect(self.accept)

        header.addWidget(btn_out)
        header.addWidget(self.zoom_pct)
        header.addWidget(btn_in)
        header.addSpacing(6)
        header.addWidget(btn_fit)
        header.addWidget(btn_100)
        header.addSpacing(6)
        header.addWidget(btn_open)
        header.addSpacing(10)
        header.addWidget(btn_close)
        layout.addLayout(header)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setStyleSheet(f"QScrollArea {{ background: #06080d; border: 1px solid {BORDER}; border-radius: 12px; }}")
        self.scroll.setAlignment(Qt.AlignCenter)
        self.scroll.setWidgetResizable(False)

        self.canvas = ImageCanvas(self)
        self.scroll.setWidget(self.canvas)
        layout.addWidget(self.scroll, 1)

        hint_bar = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("💡 Use Mouse Wheel or +/- to zoom · Click and drag to pan · Double-click to toggle Fit/100%")
        hint.setStyleSheet(f"color: {FAINT}; font-size: 11px;")
        hint_bar.addWidget(hint)
        hint_bar.addStretch(1)
        layout.addLayout(hint_bar)

        QtCore.QTimer.singleShot(30, self.fit_to_window)

    def set_zoom(self, z):
        self.zoom = max(0.1, min(10.0, z))
        self.zoom_pct.setText(f"{int(round(self.zoom * 100))}%")
        self._update_display()

    def adjust_zoom(self, factor):
        self.set_zoom(self.zoom * factor)

    def fit_to_window(self):
        if self.orig_pixmap.isNull():
            return
        vw = max(100, self.scroll.viewport().width() - 24)
        vh = max(100, self.scroll.viewport().height() - 24)
        pw, ph = self.orig_pixmap.width(), self.orig_pixmap.height()
        if pw > 0 and ph > 0:
            scale = min(vw / pw, vh / ph, 1.0)
            self.set_zoom(scale)

    def _update_display(self):
        if self.orig_pixmap.isNull():
            return
        w = max(10, int(self.orig_pixmap.width() * self.zoom))
        h = max(10, int(self.orig_pixmap.height() * self.zoom))
        scaled = self.orig_pixmap.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.canvas.setPixmap(scaled)
        self.canvas.resize(w, h)

    def open_external(self):
        if os.path.isfile(self.path) and shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", self.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def animate_in(widget, layout, base_margins, dy=10, ms=180):
    """Fade + slight upward slide. Height stays constant (margins swap top->bottom)."""
    eff = QtWidgets.QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    l, t, r, b = base_margins
    layout.setContentsMargins(l, t + dy, r, max(0, b - dy) if b >= dy else b)
    anim = QtCore.QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(ms)
    anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def step(v):
        try:
            eff.setOpacity(v)
            off = int(round(dy * (1 - v)))
            layout.setContentsMargins(l, t + off, r, b + (dy - off) - dy if b >= dy else b)
        except RuntimeError:
            pass

    def finished():
        try:
            layout.setContentsMargins(l, t, r, b)
            widget.setGraphicsEffect(None)
        except RuntimeError:
            pass
    anim.valueChanged.connect(step)
    anim.finished.connect(finished)
    anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
    return anim


class ChatRow(QtWidgets.QWidget):
    MARGINS = (0, 8, 0, 8)

    def set_column_width(self, w):
        pass


class UserRow(ChatRow):
    """Right-aligned compact bubble; attachments shown above it."""

    def __init__(self, text, files=None, ts=None):
        super().__init__()
        self.role = "user"
        self.text = text or ""
        self.files = list(files or [])
        self.body = None
        lay = QtWidgets.QVBoxLayout(self)
        self.lay = lay
        lay.setContentsMargins(*self.MARGINS)
        lay.setSpacing(8)
        if self.files:
            holder = QtWidgets.QWidget()
            fl = FlowLayout(holder, 8)
            for f in self.files:
                if os.path.isfile(f) and documents.kind_of(f) == "image":
                    t = ClickableThumb(f, 120, 14)
                    fl.addWidget(t)
                    continue
                fl.addWidget(Chip(f, removable=False))
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            row.addWidget(holder, 0, Qt.AlignRight)
            self.files_holder = holder
            lay.addLayout(row)
        if self.text:
            self.bubble = QtWidgets.QFrame()
            self.bubble.setObjectName("userBubble")
            inner = QtWidgets.QVBoxLayout(self.bubble)
            inner.setContentsMargins(16, 10, 16, 10)
            self.body = RichLabel(markdown_lite.to_html(self.text, link_color=LINK, line_height=150, gap=8),
                                  "userText")
            inner.addWidget(self.body)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            row.addWidget(self.bubble, 0, Qt.AlignRight)
            lay.addLayout(row)
            if ts:
                self.bubble.setToolTip(_fmt_time(ts))

    def set_column_width(self, w):
        maxw = int(w * 0.75)
        if getattr(self, "files_holder", None) is not None:
            self.files_holder.setMaximumWidth(w)
            n = self.files_holder.layout()
            self.files_holder.setFixedWidth(min(w, max(1, self._files_width())))
            self.files_holder.setFixedHeight(n.heightForWidth(self.files_holder.width()))
        if self.body is None:
            return
        inner = maxw - 32
        self.body.ensurePolished()
        doc = QtGui.QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(self.body.font())
        doc.setHtml(self.body.text())
        doc.setTextWidth(inner)
        ideal = int(math.ceil(doc.idealWidth())) + 4
        self.body.setFixedWidth(max(16, min(inner, ideal)))

    def _files_width(self):
        lay = self.files_holder.layout()
        return sum(lay.itemAt(i).sizeHint().width() + 8 for i in range(lay.count())) - 8


class CodeBlock(QtWidgets.QFrame):
    def __init__(self, lang, code):
        super().__init__()
        self.setObjectName("codeBlock")
        self.code = code
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QtWidgets.QFrame()
        head.setObjectName("codeHead")
        head.setFixedHeight(36)
        h = QtWidgets.QHBoxLayout(head)
        h.setContentsMargins(14, 0, 8, 0)
        lab = QtWidgets.QLabel((lang or "code").lower())
        lab.setObjectName("codeLang")
        h.addWidget(lab)
        h.addStretch(1)
        self.copy_btn = QtWidgets.QPushButton(" Copy")
        self.copy_btn.setObjectName("textBtn")
        self.copy_btn.setIcon(make_icon("copy", MUTED, 14))
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy)
        h.addWidget(self.copy_btn)
        v.addWidget(head)
        self.label = QtWidgets.QLabel(code)
        self.label.setObjectName("code")
        self.label.setTextFormat(Qt.PlainText)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.label.setContentsMargins(16, 12, 16, 14)
        self.label.setCursor(Qt.IBeamCursor)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("codeScroll")
        self.scroll.setWidget(self.label)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        self.label.setAutoFillBackground(False)
        v.addWidget(self.scroll)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.label.ensurePolished()
        h = self.label.sizeHint().height()
        need_h = self.label.sizeHint().width() > self.scroll.viewport().width() + 1
        self.scroll.setFixedHeight(h + (10 if need_h else 0))

    def showEvent(self, e):
        super().showEvent(e)
        self.resizeEvent(None) if False else None
        self.label.ensurePolished()
        self.scroll.setFixedHeight(self.label.sizeHint().height())

    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.code)
        self.copy_btn.setText(" Copied")
        self.copy_btn.setIcon(make_icon("check", OK, 14))
        QtCore.QTimer.singleShot(1500, self._reset)

    def _reset(self):
        try:
            self.copy_btn.setText(" Copy")
            self.copy_btn.setIcon(make_icon("copy", MUTED, 14))
        except RuntimeError:
            pass


class NoticeCard(QtWidgets.QFrame):
    """Subtle inline notice: tinted card, coloured left accent, optional action buttons."""

    def __init__(self, text, level="warn", buttons=None, on_button=None):
        super().__init__()
        self.level = level
        self.accent = {"error": DANGER, "warn": WARN, "info": ACCENT, "ok": OK}.get(level, WARN)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(12)
        ic = QtWidgets.QLabel()
        ic.setPixmap(make_icon("check" if level == "ok" else ("info" if level == "info" else "warn"),
                               self.accent, 18).pixmap(18, 18))
        ic.setFixedSize(18, 22)
        ic.setAlignment(Qt.AlignTop)
        lay.addWidget(ic, 0, Qt.AlignTop)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(10)
        self.body = RichLabel(markdown_lite.to_html(text, link_color=LINK, line_height=150, gap=8), "noticeText")
        col.addWidget(self.body)
        self.buttons = []
        if buttons:
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            for label, payload in buttons:
                b = QtWidgets.QPushButton(label)
                b.setObjectName("pill")
                b.setCursor(Qt.PointingHandCursor)
                if on_button:
                    b.clicked.connect(lambda _=False, p=payload, btn=b: on_button(p, btn))
                row.addWidget(b)
                self.buttons.append(b)
            row.addStretch(1)
            col.addLayout(row)
        lay.addLayout(col, 1)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(qcolor(self.accent, 40), 1))
        p.setBrush(qcolor(self.accent, 14))
        p.drawRoundedRect(r, 12, 12)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(r, 12, 12)
        p.setClipPath(clip)
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(self.accent, 210))
        p.drawRect(QtCore.QRectF(r.left(), r.top(), 3, r.height()))
        p.end()


class AssistantRow(ChatRow):
    """Assistant answer: no box, text straight on the background, avatar on the left."""

    def __init__(self, text, ok=True, buttons=None, on_button=None, level=None, ts=None,
                 on_regenerate=None):
        super().__init__()
        self.role = "assistant"
        self.text = text or ""
        self.ok = ok
        self.body = None
        self.ts = ts or time.time()
        lay = QtWidgets.QHBoxLayout(self)
        self.lay = lay
        lay.setContentsMargins(*self.MARGINS)
        lay.setSpacing(10)
        av_col = QtWidgets.QVBoxLayout()
        av_col.setContentsMargins(0, 0, 0, 0)
        self.avatar = GradientAvatar(26)
        av_col.addWidget(self.avatar)
        av_col.addStretch(1)
        lay.addLayout(av_col)
        content = QtWidgets.QVBoxLayout()
        content.setContentsMargins(0, 6, 0, 0)
        content.setSpacing(12)
        self.reply_buttons = []
        if not ok:
            if level is None:
                level = "error" if self.text.startswith(("Something went wrong", "Voice input stopped")) else "warn"
            card = NoticeCard(self.text, level, buttons, on_button)
            self.body = card.body
            self.reply_buttons = card.buttons
            content.addWidget(card)
        else:
            for block in markdown_lite.split_blocks(self.text) or [("text", "")]:
                if block[0] == "code":
                    content.addWidget(CodeBlock(block[1], block[2]))
                else:
                    lab = RichLabel(markdown_lite.to_html(block[1], link_color=LINK, line_height=155, gap=12),
                                    "botText")
                    if self.body is None:
                        self.body = lab
                    content.addWidget(lab)
            if buttons:
                row = QtWidgets.QHBoxLayout()
                row.setSpacing(8)
                for label, payload in buttons:
                    b = QtWidgets.QPushButton(label)
                    b.setObjectName("pill")
                    b.setCursor(Qt.PointingHandCursor)
                    if on_button:
                        b.clicked.connect(lambda _=False, p=payload, btn=b: on_button(p, btn))
                    row.addWidget(b)
                    self.reply_buttons.append(b)
                row.addStretch(1)
                content.addLayout(row)
        # hover actions (fixed-height bar so showing it never moves anything)
        bar = QtWidgets.QWidget()
        bar.setFixedHeight(28)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(2)
        self.copy_btn = IconButton("copy", "Copy", size=28, icon_size=15, radius=8)
        self.copy_btn.clicked.connect(self.copy)
        self.regen_btn = IconButton("refresh", "Regenerate", size=28, icon_size=15, radius=8)
        if on_regenerate:
            self.regen_btn.clicked.connect(on_regenerate)
        else:
            self.regen_btn.hide()
        self.time_label = QtWidgets.QLabel(_fmt_time(self.ts))
        self.time_label.setObjectName("meta")
        bl.addWidget(self.copy_btn)
        bl.addWidget(self.regen_btn)
        bl.addSpacing(6)
        bl.addWidget(self.time_label)
        bl.addStretch(1)
        self.actions = [self.copy_btn, self.regen_btn, self.time_label]
        self.can_regenerate = on_regenerate is not None
        self.pinned = False
        content.addSpacing(-6)
        content.addWidget(bar)
        lay.addLayout(content, 1)
        self._show_actions(False)

    def _show_actions(self, on):
        on = on or self.pinned
        for w in self.actions:
            if w is self.regen_btn and not self.can_regenerate:
                w.setVisible(False)
                continue
            w.setVisible(on)

    def set_pinned(self, on):
        self.pinned = on
        self._show_actions(on)

    def set_can_regenerate(self, on):
        self.can_regenerate = on
        self._show_actions(self.underMouse())

    def enterEvent(self, e):
        self._show_actions(True)

    def leaveEvent(self, e):
        self._show_actions(False)

    def copy(self):
        QtWidgets.QApplication.clipboard().setText(self.text)
        self.copy_btn.set_kind("check")
        self.copy_btn.color = OK
        QtCore.QTimer.singleShot(1300, self._reset_copy)

    def _reset_copy(self):
        try:
            self.copy_btn.set_kind("copy")
            self.copy_btn.color = MUTED
        except RuntimeError:
            pass


# kept for compatibility: MessageRow("user"|"assistant", text, ...)
def MessageRow(role, text, files=None, ok=True, buttons=None, on_button=None):
    if role == "user":
        return UserRow(text, files)
    return AssistantRow(text, ok=ok, buttons=buttons, on_button=on_button)


class StreamingRow(ChatRow):
    """An answer that is still arriving: plain growing text next to the avatar."""

    def __init__(self):
        super().__init__()
        self.role = "assistant"
        lay = QtWidgets.QHBoxLayout(self)
        self.lay = lay
        lay.setContentsMargins(*self.MARGINS)
        lay.setSpacing(10)
        av = QtWidgets.QVBoxLayout()
        av.addWidget(GradientAvatar(26))
        av.addStretch(1)
        lay.addLayout(av)
        col = QtWidgets.QVBoxLayout()
        col.setContentsMargins(0, 6, 0, 0)
        self.body = RichLabel("", "botText")
        col.addWidget(self.body)
        col.addSpacing(22)
        lay.addLayout(col, 1)

    def set_markdown(self, md):
        html = markdown_lite.to_html(md, link_color=LINK, line_height=155, gap=12)
        cursor = f"<span style='color:{ACCENT};'>&nbsp;&#9613;</span>"
        for tail in ("</li></ul>", "</li></ol>", "</p>"):
            if html.endswith(tail):
                html = html[: -len(tail)] + cursor + tail
                break
        else:
            html += cursor
        self.body.setText(html)


class ThinkingRow(ChatRow):
    def __init__(self, text="Thinking"):
        super().__init__()
        self.role = "thinking"
        lay = QtWidgets.QHBoxLayout(self)
        self.lay = lay
        lay.setContentsMargins(*self.MARGINS)
        lay.setSpacing(10)
        self.avatar = GradientAvatar(26, active=True)
        lay.addWidget(self.avatar, 0, Qt.AlignTop)
        self.label = ShimmerLabel(text)
        lay.addWidget(self.label, 0, Qt.AlignVCenter)
        lay.addStretch(1)

    def set_text(self, text):
        self.label.set_text(text.rstrip("…."))


class Waveform(QtWidgets.QWidget):
    """Live microphone level as scrolling bars."""

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(60)
        self.setFixedHeight(28)
        self.levels = deque([0.0] * 120, maxlen=120)
        self.value = 0.0
        self.shown = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.levels.extend([0.0] * 120)
        self.timer.start(50)

    def stop(self):
        self.timer.stop()

    def set_level(self, v):
        self.value = max(0.0, min(1.0, float(v)))

    def _tick(self):
        self.shown = max(self.value, self.shown * 0.72)
        jitter = 0.85 + 0.3 * ((time.monotonic() * 7.3) % 1.0)
        self.levels.append(min(1.0, self.shown * jitter))
        self.value *= 0.6
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        w, h = self.width(), self.height()
        step = 5
        n = max(1, w // step)
        vals = list(self.levels)[-n:]
        vals = [0.0] * (n - len(vals)) + vals
        p.setBrush(accent_gradient(0, 0, w, 0, 230))
        for i, v in enumerate(vals):
            bh = max(3.0, (h - 2) * v)
            p.drawRoundedRect(QtCore.QRectF(i * step + 1, (h - bh) / 2, 3, bh), 1.5, 1.5)
        p.end()


class LevelMeter(Waveform):
    """Compatibility name for the live level display."""


class RecDot(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(14, 14)
        self._t = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.05
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        pulse = (math.sin(self._t * 4) + 1) / 2
        c = QtCore.QPointF(7, 7)
        p.setBrush(qcolor(RECORD, 60 + 70 * pulse))
        p.drawEllipse(c, 7, 7)
        p.setBrush(qcolor(RECORD))
        p.drawEllipse(c, 4, 4)
        p.end()


class RecordingBar(QtWidgets.QWidget):
    """Shown in the composer instead of the text box while listening."""

    def __init__(self):
        super().__init__()
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(12)
        self.dot = RecDot()
        self.label = QtWidgets.QLabel("Listening")
        self.label.setObjectName("recLabel")
        self.wave = Waveform()
        self.clock = QtWidgets.QLabel("0:00")
        self.clock.setObjectName("recTime")
        lay.addWidget(self.dot)
        lay.addWidget(self.label)
        lay.addWidget(self.wave, 1)
        lay.addWidget(self.clock)
        self.started = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.setFixedHeight(36)

    def start(self):
        self.started = time.monotonic()
        self.label.setText("Listening")
        self.clock.setText("0:00")
        self.wave.start()
        self.dot.timer.start(40)
        self.timer.start(200)

    def stop(self):
        self.wave.stop()
        self.dot.timer.stop()
        self.timer.stop()

    def set_level(self, v):
        self.wave.set_level(v)

    def _tick(self):
        s = int(time.monotonic() - self.started)
        self.clock.setText(f"{s // 60}:{s % 60:02d}")


class InputBox(QtWidgets.QPlainTextEdit):
    submit = QtCore.pyqtSignal()
    focus_changed = QtCore.pyqtSignal(bool)
    files_pasted = QtCore.pyqtSignal(list)
    MIN_LINES, MAX_LINES = 1, 8

    def __init__(self):
        super().__init__()
        self.setObjectName("input")
        self.setPlaceholderText(PLACEHOLDER)
        self.setTabChangesFocus(True)
        self.setAcceptDrops(False)       # the window shows its own drop overlay
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.document().setDocumentMargin(2)
        pal = self.palette()
        pal.setColor(QtGui.QPalette.PlaceholderText, qcolor(FAINT))
        pal.setColor(QtGui.QPalette.Text, qcolor(TEXT_STRONG))
        self.setPalette(pal)
        self.textChanged.connect(self._grow)
        self._grow()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.submit.emit()
            return
        super().keyPressEvent(e)

    def insertFromMimeData(self, source):
        if source.hasUrls():
            files = [u.toLocalFile() for u in source.urls() if u.isLocalFile()]
            if files:
                self.files_pasted.emit(files)
                return
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QtGui.QImage) and not img.isNull():
                d = os.path.join(engine.DATA_DIR, "pasted")
                os.makedirs(d, exist_ok=True)
                path = os.path.join(d, time.strftime("pasted-%Y%m%d-%H%M%S.png"))
                if img.save(path):
                    self.files_pasted.emit([path])
                    return
        super().insertFromMimeData(source)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._grow()

    def _grow(self):
        fm = self.fontMetrics()
        lines = max(self.MIN_LINES, min(self.MAX_LINES, int(self.document().size().height())))
        h = lines * fm.lineSpacing() + 10
        if self.height() != h:
            self.setFixedHeight(h)


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------


class SuggestionCard(QtWidgets.QWidget):
    clicked = QtCore.pyqtSignal(str)

    def __init__(self, prompt, desc, icon):
        super().__init__()
        self.prompt, self.desc, self.icon = prompt, desc, icon
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(84)
        self.setMinimumWidth(220)
        self.setFocusPolicy(Qt.TabFocus)
        self.setToolTip(prompt)
        self.h = 0.0
        self.anim = QtCore.QVariantAnimation(self)
        self.anim.setDuration(140)
        self.anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._set_h)

    def _set_h(self, v):
        self.h = float(v)
        self.update()

    def _to(self, v):
        self.anim.stop()
        self.anim.setStartValue(self.h)
        self.anim.setEndValue(float(v))
        self.anim.start()

    def enterEvent(self, e):
        self._to(1.0)

    def leaveEvent(self, e):
        self._to(0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self.clicked.emit(self.prompt)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.prompt)
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self._to(1.0)

    def focusOutEvent(self, e):
        self._to(0.0)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing)
        h = self.h
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 3.5 - 3 * h, -0.5, -0.5 - 3 * h)
        bg = QtGui.QColor(255, 255, 255, int(7 + 6 * h))
        border = QtGui.QColor(
            int(28 + (34 - 28) * h), int(34 + (211 - 34) * h * 0.55), int(50 + (238 - 50) * h * 0.55),
            int(255 * (0.9 - 0.25 * h)))
        p.setPen(QtGui.QPen(border, 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 16, 16)
        tile = QtCore.QRectF(r.left() + 16, r.top() + (r.height() - 36) / 2, 36, 36)
        p.setPen(Qt.NoPen)
        tg = accent_gradient(tile.left(), tile.top(), tile.right(), tile.bottom(), int(38 + 30 * h))
        p.setBrush(tg)
        p.drawRoundedRect(tile, 10, 10)
        draw_icon(p, self.icon, tile.adjusted(8, 8, -8, -8), QtGui.QColor("#cffafe") if h > 0.5 else qcolor("#a5f3fc"))
        tx = tile.right() + 14
        tw = r.right() - 16 - tx
        f = QtGui.QFont(self.font())
        f.setPixelSize(FS_BODY)
        f.setWeight(QtGui.QFont.Medium)
        p.setFont(f)
        fm = QtGui.QFontMetrics(f)
        p.setPen(qcolor(TEXT_STRONG))
        title = fm.elidedText(self.prompt, Qt.ElideRight, int(tw))
        p.drawText(QtCore.QRectF(tx, r.top() + 18, tw, 22), Qt.AlignLeft | Qt.AlignVCenter, title)
        f2 = QtGui.QFont(self.font())
        f2.setPixelSize(FS_SMALL)
        p.setFont(f2)
        p.setPen(qcolor(FAINT))
        fm2 = QtGui.QFontMetrics(f2)
        p.drawText(QtCore.QRectF(tx, r.top() + 42, tw, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm2.elidedText(self.desc, Qt.ElideRight, int(tw)))
        p.end()


class HeroLogo(QtWidgets.QWidget):
    def __init__(self, size=64):
        super().__init__()
        self.s = size
        self.setFixedSize(size + 80, size + 60)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        c = QtCore.QPointF(self.width() / 2, self.height() / 2)
        g = QtGui.QRadialGradient(c, self.width() / 2)
        g.setColorAt(0.0, qcolor(ACCENT_2, 70))
        g.setColorAt(0.5, qcolor(ACCENT, 18))
        g.setColorAt(1.0, qcolor(ACCENT, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, self.width() / 2, self.height() / 2)
        paint_logo(p, QtCore.QRectF(c.x() - self.s / 2, c.y() - self.s / 2, self.s, self.s), 0.30)
        p.end()


class EmptyState(QtWidgets.QWidget):
    picked = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("heroPage")
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(24, 0, 24, 0)
        outer.addStretch(1)
        col = QtWidgets.QWidget()
        col.setMaximumWidth(COLUMN_MAX - 40)
        col.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        l = QtWidgets.QVBoxLayout(col)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)
        l.addStretch(3)
        logo = HeroLogo(64)
        l.addWidget(logo, 0, Qt.AlignHCenter)
        l.addSpacing(4)
        t = QtWidgets.QLabel("How can I help you today?")
        t.setObjectName("heroTitle")
        t.setAlignment(Qt.AlignCenter)
        t.setWordWrap(True)
        l.addWidget(t)
        l.addSpacing(8)
        s = QtWidgets.QLabel("Ask about this PC, open apps and websites, or attach a photo or document. "
                             "Everything runs privately on this computer.")
        s.setObjectName("heroSub")
        s.setWordWrap(True)
        s.setAlignment(Qt.AlignCenter)
        l.addWidget(s)
        l.addSpacing(32)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setSpacing(12)
        self.cards = []
        for prompt, desc, icon in SUGGESTIONS:
            c = SuggestionCard(prompt, desc, icon)
            c.clicked.connect(self.picked)
            self.cards.append(c)
        self.cols = 0
        self.set_columns(2)
        l.addLayout(self.grid)
        l.addStretch(4)
        outer.addWidget(col, 100)
        outer.addStretch(1)

    def set_columns(self, cols):
        if cols == self.cols:
            return
        self.cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.set_columns(2 if self.width() >= 700 else 1)


# ---------------------------------------------------------------------------
# Header, sidebar, overlays
# ---------------------------------------------------------------------------


class StatusPill(QtWidgets.QWidget):
    STATES = {
        "ready": (OK, "On this PC"),
        "checking": (FAINT, "Connecting…"),
        "starting": (WARN, "Starting…"),
        "offline": (DANGER, "Offline"),
    }

    def __init__(self):
        super().__init__()
        self.setFixedHeight(26)
        self.state = "checking"
        self.extra = ""
        f = self.font()
        f.setPixelSize(12)
        f.setWeight(QtGui.QFont.Medium)
        self.setFont(f)
        self.setToolTip("The AI runs on this computer. Nothing you type, say or attach is uploaded.")
        self.set_state("checking")

    def set_state(self, state, extra=""):
        self.state = state
        self.extra = extra
        color, text = self.STATES[state]
        if extra and state == "ready":
            text = extra
        self.text = text
        self.color = color
        fm = QtGui.QFontMetrics(self.font())
        self.setFixedWidth(fm.horizontalAdvance(text) + 34)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 16), 1))
        p.setBrush(QtGui.QColor(255, 255, 255, 10))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        c = QtCore.QPointF(14, r.center().y())
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(self.color, 60))
        p.drawEllipse(c, 5, 5)
        p.setBrush(qcolor(self.color))
        p.drawEllipse(c, 3, 3)
        p.setPen(qcolor(MUTED if self.state != "ready" else "#cbd5e1"))
        p.setFont(self.font())
        p.drawText(r.adjusted(24, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        p.end()


class Header(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(56)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(12, 0, 14, 0)
        h.setSpacing(6)
        self.toggle = IconButton("sidebar", "Show or hide chats", size=34, icon_size=19, radius=10)
        h.addWidget(self.toggle)
        h.addSpacing(4)
        logo = QtWidgets.QLabel()
        logo.setPixmap(logo_pixmap(24, 0.32))
        logo.setFixedSize(24, 24)
        h.addWidget(logo)
        h.addSpacing(4)
        self.title = QtWidgets.QLabel("DevOS AI")
        self.title.setObjectName("title")
        h.addWidget(self.title)
        h.addSpacing(8)
        self.status = StatusPill()
        h.addWidget(self.status, 0, Qt.AlignVCenter)
        h.addStretch(1)
        self.new_btn = IconButton("new", "New chat (Ctrl+N)", size=34, icon_size=19, radius=10)
        h.addWidget(self.new_btn)


class ChatListDelegate(QtWidgets.QStyledItemDelegate):
    HEADER = Qt.UserRole + 1

    def sizeHint(self, option, index):
        if index.data(self.HEADER):
            return QtCore.QSize(0, 34 if index.row() else 26)
        return QtCore.QSize(0, 36)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(option.rect)
        text = index.data(Qt.DisplayRole) or ""
        f = QtGui.QFont(option.font)
        if index.data(self.HEADER):
            f.setPixelSize(12)
            f.setWeight(QtGui.QFont.DemiBold)
            p.setFont(f)
            p.setPen(qcolor(FAINT))
            p.drawText(r.adjusted(10, 0, -8, -6), Qt.AlignLeft | Qt.AlignBottom, text)
            p.restore()
            return
        sel = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver)
        if sel or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(qcolor(SURFACE_HI) if sel else QtGui.QColor(255, 255, 255, 9))
            p.drawRoundedRect(r.adjusted(0, 1, 0, -1), 8, 8)
        f.setPixelSize(14)
        p.setFont(f)
        p.setPen(qcolor(TEXT_STRONG if sel else "#c3cbd8"))
        fm = QtGui.QFontMetrics(f)
        p.drawText(r.adjusted(10, 0, -10, 0), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(text, Qt.ElideRight, int(r.width() - 20)))
        p.restore()

    def createEditor(self, parent, option, index):
        e = QtWidgets.QLineEdit(parent)
        e.setObjectName("renameEdit")
        return e

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(2, 3, -2, -3))


class SmartCard(QtWidgets.QFrame):
    """Sidebar footer: switch to (or away from) the bigger "Smarter DevOS AI" model."""
    clicked = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(6)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(10)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(30, 30)
        row.addWidget(self.icon)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(0)
        self.title = QtWidgets.QLabel(engine.SMART_LABEL)
        self.title.setObjectName("smartTitle")
        self.sub = QtWidgets.QLabel()
        self.sub.setObjectName("smartSub")
        col.addWidget(self.title)
        col.addWidget(self.sub)
        row.addLayout(col, 1)
        v.addLayout(row)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.hide()
        v.addWidget(self.bar)
        self.busy = False
        self.refresh()

    def refresh(self):
        self.model_info = engine.active_chat_model()
        model_id = self.model_info.get("id", "tiny")
        self.on = model_id != "tiny"
        if self.busy:
            return
        pm = QtGui.QPixmap(60, 60)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(2)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(accent_gradient(0, 0, 30, 30, 60 if not self.on else 255))
        p.drawRoundedRect(QtCore.QRectF(0, 0, 30, 30), 9, 9)
        draw_icon(p, "spark", QtCore.QRectF(7, 7, 16, 16), QtGui.QColor("#ffffff") if self.on else qcolor("#a5f3fc"))
        p.end()
        self.icon.setPixmap(pm)
        if model_id in ("large", "xl", "medium"):
            params = self.model_info.get("params", model_id.upper())
            name = self.model_info.get("name", "Active")
            self.title.setText(f"DevOS AI {params}")
            self.sub.setText(f"{name} model active")
            self.setToolTip(f"{name} ({params}) model is running on this PC. Click to manage models.")
        elif self.on:
            self.title.setText(f"{engine.SMART_LABEL} is on")
            self.sub.setText(f"Switch back (free {engine.SMART_SIZE})")
            self.setToolTip("Go back to the built-in DevOS AI and free the space")
        else:
            self.title.setText(engine.SMART_LABEL)
            self.sub.setText(f"Better answers · {engine.SMART_SIZE}")
            self.setToolTip(f"{engine.SMART_LABEL} ({engine.SMART_SIZE} download)")
        self.bar.hide()

    def set_progress(self, done_mb, total_mb, label=None):
        self.busy = True
        self.bar.show()
        self.bar.setValue(int(1000 * done_mb / total_mb) if total_mb else 0)
        self.sub.setText(label or (f"Downloading · {done_mb:,.0f} / {total_mb:,.0f} MB" if total_mb
                                   else "Starting…"))

    def done(self):
        self.busy = False
        self.refresh()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and not self.busy:
            self.clicked.emit()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 22 if self._hover else 13), 1))
        p.setBrush(QtGui.QColor(255, 255, 255, 12 if self._hover else 6))
        p.drawRoundedRect(r, 12, 12)
        p.end()


class Switch(QtWidgets.QAbstractButton):
    """A small on/off switch."""

    def __init__(self):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(38, 22)
        self._pos = 0.0
        self._anim = QtCore.QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.valueChanged.connect(self._moved)
        self.toggled.connect(self._animate)

    def _moved(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_quiet(self, on):
        self._anim.stop()
        self.blockSignals(True)
        self.setChecked(on)
        self.blockSignals(False)
        self._pos = 1.0 if on else 0.0
        self.update()

    dimmed = False

    def set_dimmed(self, on):
        self.dimmed = bool(on)
        self.setCursor(Qt.ArrowCursor if on else Qt.PointingHandCursor)
        self.update()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.dimmed:
            p.setOpacity(0.4)
        r = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(qcolor(BORDER_HI))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self._pos > 0:
            base = p.opacity()
            p.setOpacity(base * self._pos)
            p.setBrush(QtGui.QBrush(accent_gradient(r.left(), 0, r.right(), 0)))
            p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
            p.setOpacity(base)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._pos
        p.setBrush(QtGui.QColor("#ffffff"))
        p.drawEllipse(QtCore.QRectF(x, r.top() + 3, d, d))
        p.end()


class HandsFreeRow(QtWidgets.QWidget):
    """Sidebar footer: turn the "Hey DevOS" listener on or off."""
    toggled = QtCore.pyqtSignal(bool)

    HINT_MS = 4000

    def __init__(self):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 8)
        v.setSpacing(6)
        h = QtWidgets.QHBoxLayout()
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(30, 30)
        h.addWidget(self.icon)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(0)
        self.title = QtWidgets.QLabel("Hands-free")
        self.title.setObjectName("smartTitle")
        self.sub = QtWidgets.QLabel()
        self.sub.setObjectName("smartSub")
        col.addWidget(self.title)
        col.addWidget(self.sub)
        h.addLayout(col, 1)
        self.switch = Switch()
        self.switch.toggled.connect(self._changed)
        h.addWidget(self.switch)
        v.addLayout(h)
        # one small inline hint under the switch (never a chat message); hides itself
        self.hint = QtWidgets.QLabel()
        self.hint.setObjectName("smartSub")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet(f"color: {WARN};")
        self.hint.hide()
        v.addWidget(self.hint)
        self._hint_timer = QtCore.QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self.hint.hide)
        self.available = True
        self.unavailable_reason = ""
        self.setAccessibleName(listen.HANDS_FREE_LABEL)
        self._tip = (listen.HANDS_FREE_LABEL + ", then your command — DevOS AI does it without opening this "
                     "window. Listening happens on this PC only.\nAny time: press Meta+H and speak.")
        self.setToolTip(self._tip)
        self._label(False)

    def _changed(self, on):
        self._label(on)
        self.toggled.emit(on)

    def _label(self, on):
        self.sub.setText("On · “Hey DevOS”" if on else ("Say “Hey DevOS”" if self.available else "Not available"))
        pm = QtGui.QPixmap(60, 60)
        pm.fill(Qt.transparent)
        pm.setDevicePixelRatio(2)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        if not self.available:
            p.setOpacity(0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(accent_gradient(0, 0, 30, 30, 255 if on else 60))
        p.drawRoundedRect(QtCore.QRectF(0, 0, 30, 30), 9, 9)
        draw_icon(p, "mic", QtCore.QRectF(7, 7, 16, 16), QtGui.QColor("#ffffff") if on else qcolor("#a5f3fc"))
        p.end()
        self.icon.setPixmap(pm)

    def set_on(self, on):
        self.switch.set_quiet(on)
        self._label(on)

    def set_available(self, ok, reason=""):
        """Dimmed with a tooltip while voice can't work on this PC; the switch still takes clicks so it can
        explain why (show_hint)."""
        self.available = bool(ok)
        self.unavailable_reason = "" if ok else (reason or voice.VOICE_UNAVAILABLE_TEXT)
        self.switch.set_dimmed(not ok)
        for w in (self.title, self.sub):
            w.setEnabled(bool(ok))
        tip = self._tip if ok else self.unavailable_reason
        self.setToolTip(tip)
        self.switch.setToolTip(tip)
        if ok:
            self.hint.hide()
        self._label(self.switch.isChecked())

    def show_hint(self, text, ok=False):
        self.hint.setStyleSheet(f"color: {OK if ok else WARN};")
        self.hint.setText(text)
        self.hint.show()
        self._hint_timer.start(self.HINT_MS)


class Sidebar(QtWidgets.QWidget):
    chat_selected = QtCore.pyqtSignal(str)
    rename_requested = QtCore.pyqtSignal(str, str)
    delete_requested = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(12, 12, 13, 12)
        v.setSpacing(8)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(4)
        self.new_btn = QtWidgets.QPushButton("  New chat")
        self.new_btn.setObjectName("newChat")
        self.new_btn.setIcon(make_icon("new", TEXT_STRONG, 18))
        self.new_btn.setIconSize(QtCore.QSize(18, 18))
        self.new_btn.setFixedHeight(40)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        nl = QtWidgets.QHBoxLayout(self.new_btn)
        nl.setContentsMargins(0, 0, 12, 0)
        nl.addStretch(1)
        kbd = QtWidgets.QLabel("Ctrl N")
        kbd.setObjectName("kbd")
        kbd.setAttribute(Qt.WA_TransparentForMouseEvents)
        nl.addWidget(kbd)
        top.addWidget(self.new_btn, 1)
        self.close_btn = IconButton("sidebar", "Hide chats", size=40, icon_size=19, radius=12)
        top.addWidget(self.close_btn)
        v.addLayout(top)
        self.search = QtWidgets.QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Search chats")
        self.search.setFixedHeight(36)
        self.search.addAction(make_icon("search", FAINT, 16), QtWidgets.QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(False)
        pal = self.search.palette()
        pal.setColor(QtGui.QPalette.PlaceholderText, qcolor(FAINT))
        self.search.setPalette(pal)
        v.addWidget(self.search)
        v.addSpacing(4)
        self.list = QtWidgets.QListWidget()
        self.list.setObjectName("chatList")
        self.list.setItemDelegate(ChatListDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.list.viewport().setAutoFillBackground(False)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemDelegate().commitData.connect(self._commit)
        v.addWidget(self.list, 1)
        self.empty = QtWidgets.QLabel("No chats yet")
        self.empty.setObjectName("sideEmpty")
        self.empty.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty.hide()
        v.addWidget(self.empty, 1)
        self.smart = SmartCard()
        v.addWidget(self.smart)
        self.hands_free = HandsFreeRow()
        v.addWidget(self.hands_free)
        foot = QtWidgets.QHBoxLayout()
        foot.setContentsMargins(4, 2, 0, 0)
        foot.setSpacing(6)
        lock = QtWidgets.QLabel()
        lock.setPixmap(make_icon("lock", FAINT, 13).pixmap(13, 13))
        foot.addWidget(lock)
        fl = QtWidgets.QLabel("Private · runs on this PC")
        fl.setObjectName("hint")
        foot.addWidget(fl)
        foot.addStretch(1)
        v.addLayout(foot)
        self.current = None
        self._editing = None

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), qcolor(SIDEBAR_BG))
        p.fillRect(QtCore.QRect(self.width() - 1, 0, 1, self.height()), qcolor(DIVIDER))
        p.end()

    def populate(self, groups, current=None, query=""):
        self.current = current
        self.list.blockSignals(True)
        self.list.clear()
        sel = None
        for label, chats in groups:
            h = QtWidgets.QListWidgetItem(label)
            h.setData(ChatListDelegate.HEADER, True)
            h.setFlags(Qt.NoItemFlags)
            self.list.addItem(h)
            for c in chats:
                it = QtWidgets.QListWidgetItem(str(c.get("title") or "New chat"))
                it.setData(Qt.UserRole, c["id"])
                it.setToolTip(str(c.get("title") or ""))
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                self.list.addItem(it)
                if c["id"] == current:
                    sel = it
        if sel is not None:
            self.list.setCurrentItem(sel)
        else:
            self.list.clearSelection()
            self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        has = self.list.count() > 0
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        self.empty.setText("No matching chats" if query else "No chats yet")

    def _clicked(self, item):
        cid = item.data(Qt.UserRole)
        if cid:
            self.chat_selected.emit(cid)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        if item is None or not item.data(Qt.UserRole):
            return
        m = make_menu(self)
        a_ren = m.addAction(make_icon("edit", MUTED, 16), "Rename")
        a_del = m.addAction(make_icon("trash", DANGER, 16), "Delete")
        act = m.exec_(self.list.viewport().mapToGlobal(pos))
        if act is a_ren:
            self._editing = item.data(Qt.UserRole)
            self.list.editItem(item)
        elif act is a_del:
            self.delete_requested.emit(item.data(Qt.UserRole))

    def _commit(self, editor):
        item = self.list.currentItem()
        cid = self._editing or (item.data(Qt.UserRole) if item else None)
        self._editing = None
        if cid and isinstance(editor, QtWidgets.QLineEdit):
            self.rename_requested.emit(cid, editor.text())


class Scrim(QtWidgets.QWidget):
    clicked = QtCore.pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.alpha = 0.0

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, int(150 * self.alpha)))
        x = int(SIDEBAR_W * self.alpha)
        g = QtGui.QLinearGradient(x, 0, x + 28, 0)
        g.setColorAt(0.0, QtGui.QColor(0, 0, 0, int(110 * self.alpha)))
        g.setColorAt(1.0, QtGui.QColor(0, 0, 0, 0))
        p.fillRect(QtCore.QRect(x, 0, 28, self.height()), g)
        p.end()

    def mousePressEvent(self, e):
        self.clicked.emit()


class Toast(QtWidgets.QLabel):
    """A small transient note floating above a widget (e.g. the mic button); hides itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setWordWrap(True)
        self.setStyleSheet(f"QLabel#toast {{ background: {SURFACE_HI}; color: {TEXT}; border: 1px solid {BORDER_HI};"
                           f" border-radius: 10px; padding: 8px 12px; }}")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.anchor = self.above = None
        self.hide()

    def show_for(self, anchor, text, ms=4000, above=None):
        self.anchor = anchor
        self.above = above or anchor
        self.setText(text)
        self.place()
        self.show()
        self.raise_()
        self._timer.start(ms)

    def place(self):
        a, par = self.anchor, self.parentWidget()
        if a is None or par is None:
            return
        w = min(320, max(160, par.width() - 32))
        self.setFixedWidth(w)
        h = self.heightForWidth(w)
        self.setFixedHeight(h if h > 0 else self.sizeHint().height())
        top_right = a.mapTo(par, QtCore.QPoint(a.width(), 0))
        x = max(16, min(top_right.x() - w, par.width() - w - 16))
        y = max(8, self.above.mapTo(par, QtCore.QPoint(0, 0)).y() - self.height() - 8)
        self.move(x, y)


class DropOverlay(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(7, 9, 15, 215))
        r = QtCore.QRectF(self.rect()).adjusted(20, 20, -20, -20)
        p.setBrush(qcolor(ACCENT, 10))
        pen = QtGui.QPen(qcolor(ACCENT, 150), 1.6, Qt.DashLine)
        pen.setDashPattern([5, 4])
        p.setPen(pen)
        p.drawRoundedRect(r, 24, 24)
        c = r.center()
        tile = QtCore.QRectF(c.x() - 32, c.y() - 72, 64, 64)
        p.setPen(Qt.NoPen)
        p.setBrush(accent_gradient(tile.left(), tile.top(), tile.right(), tile.bottom()))
        p.drawRoundedRect(tile, 18, 18)
        draw_icon(p, "download", tile.adjusted(18, 18, -18, -18), QtGui.QColor("#ffffff"), 2.0)
        f = QtGui.QFont(self.font())
        f.setPixelSize(FS_LARGE + 3)
        f.setWeight(QtGui.QFont.DemiBold)
        p.setFont(f)
        p.setPen(qcolor(TEXT_STRONG))
        p.drawText(QtCore.QRectF(r.left(), c.y() + 6, r.width(), 30), Qt.AlignCenter, "Drop files to attach")
        f.setPixelSize(FS_SMALL + 1)
        f.setWeight(QtGui.QFont.Normal)
        p.setFont(f)
        p.setPen(qcolor(MUTED))
        p.drawText(QtCore.QRectF(r.left(), c.y() + 38, r.width(), 24), Qt.AlignCenter,
                   "Photos, PDF, Word and text files · up to 5 at a time")
        p.end()


class BottomFade(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        g = QtGui.QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, qcolor(BG, 0))
        g.setColorAt(1.0, qcolor(BG, 255))
        p.fillRect(self.rect(), g)
        p.end()


class ChatHost(QtWidgets.QWidget):
    """Content of the conversation scroll area; its height comes only from heightForWidth.

    A word-wrapped label's minimumSizeHint is measured at a guessed width, so it is taller than the label
    really is at the column width. QScrollArea (widgetResizable) makes its widget at least minimumSizeHint
    tall, so with a few wrapped messages the content got hundreds of pixels taller than the messages; the
    surplus went to the column's trailing stretch: blank space under the last message, and a scroll range
    that ended past it. Here the minimum height is 0, so the scroll area uses max(viewport, heightForWidth).
    """

    def minimumSizeHint(self):
        lay = self.layout()
        return QtCore.QSize(lay.minimumSize().width() if lay is not None else 0, 0)

    def sizeHint(self):
        lay = self.layout()
        if lay is None:
            return super().sizeHint()
        w = max(self.width(), lay.minimumSize().width())
        h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.sizeHint().height()
        return QtCore.QSize(lay.sizeHint().width(), h)


class MainArea(QtWidgets.QWidget):
    """Very dark background with a faint cyan / violet glow at the top."""

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), qcolor(BG))
        r = max(380.0, w * 0.55)
        for cx, color, a in ((w * 0.38, ACCENT, 17), (w * 0.66, ACCENT_2, 20)):
            g = QtGui.QRadialGradient(QtCore.QPointF(cx, -r * 0.30), r)
            g.setColorAt(0.0, qcolor(color, a))
            g.setColorAt(0.6, qcolor(color, a * 0.35))
            g.setColorAt(1.0, qcolor(color, 0))
            p.fillRect(QtCore.QRectF(0, 0, w, min(h, r * 0.8)), g)
        p.end()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class AssistantWindow(QtWidgets.QWidget):
    def __init__(self, assistant=None, history=None, store=None):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QtGui.QIcon(logo_pixmap(64)))
        self.resize(1180, 800)
        self.setMinimumSize(420, 540)
        self.setAcceptDrops(True)
        self.assistant = assistant or engine.Assistant()
        self.store = store if store is not None else engine.ChatStore().load()
        self.history = history if history is not None else self.store.new_history()
        self.attachments = []
        self.chips = {}
        self.workers = set()
        self.rows = []
        self.thinking = None
        self.recorder = None
        self.voice_worker = None
        self.busy = 0
        self._service_started = False
        self._sb_pos = 1.0
        self._sb_target = 1.0
        self._sidebar_pref = True
        self._narrow = None
        self._scroll_anim = None
        self._stick_bottom = True
        self._voice_ok = None           # None = not checked yet
        self._voice_reason = ""
        self._voice_checking = False
        self._hands_free_told = False   # "Hands-free is on" confirmation: once per session
        self._query = ""
        self._handle = None
        self._stream_row = None
        self._stream_text = ""
        self._stream_timer = QtCore.QTimer(self)
        self._stream_timer.setSingleShot(True)
        self._stream_timer.timeout.connect(self._flush_stream)
        self.setStyleSheet(STYLE)
        self._build()
        self._shortcuts()
        self._restore()
        self.refresh_sidebar()
        self.status_timer = QtCore.QTimer(self)
        self.status_timer.timeout.connect(self.check_status)
        self.status_timer.start(15000)
        QtCore.QTimer.singleShot(50, self.check_status)
        QtCore.QTimer.singleShot(0, self.check_voice)
        self.input.setFocus()

    # -- layout -------------------------------------------------------------

    def _build(self):
        self.sidebar = Sidebar()
        self.sidebar.setParent(self)
        self.sidebar.new_btn.clicked.connect(self.new_chat)
        self.sidebar.close_btn.clicked.connect(self.toggle_sidebar)
        self.sidebar.search.textChanged.connect(self._search_changed)
        self.sidebar.chat_selected.connect(self.open_chat)
        self.sidebar.rename_requested.connect(self.rename_chat)
        self.sidebar.delete_requested.connect(self.delete_chat)
        self.sidebar.smart.clicked.connect(self.smarter_ai)
        self.sidebar.hands_free.set_on(listen.hands_free_enabled())
        self.sidebar.hands_free.toggled.connect(self.set_hands_free)

        self.main = MainArea(self)
        root = QtWidgets.QVBoxLayout(self.main)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = Header()
        self.header.toggle.clicked.connect(self.toggle_sidebar)
        self.header.new_btn.clicked.connect(self.new_chat)
        self.status = self.header.status
        root.addWidget(self.header)

        self.pages = QtWidgets.QStackedWidget()
        self.pages.setStyleSheet("QStackedWidget { background: transparent; }")
        self.hero = EmptyState()
        self.hero.picked.connect(self.send)
        self.pages.addWidget(self.hero)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("chatScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.viewport().setAutoFillBackground(False)
        host = ChatHost()
        host.setObjectName("chatHost")
        host.setAutoFillBackground(False)
        self.host_l = QtWidgets.QHBoxLayout(host)
        self.host_l.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.host_l.setContentsMargins(24, 8, 24, 40)
        self.host_l.addStretch(1)
        self.column = QtWidgets.QWidget()
        self.column.setObjectName("column")
        self.column.setMaximumWidth(COLUMN_MAX)
        self.column.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.column.installEventFilter(self)
        self.col_l = QtWidgets.QVBoxLayout(self.column)
        self.col_l.setContentsMargins(0, 0, 0, 0)
        self.col_l.setSpacing(0)
        self.col_l.addStretch(1)
        self.host_l.addWidget(self.column, 100)
        self.host_l.addStretch(1)
        self.scroll.setWidget(host)
        sb = self.scroll.verticalScrollBar()
        sb.rangeChanged.connect(self._on_range)
        sb.valueChanged.connect(self._on_scroll)
        self.pages.addWidget(self.scroll)
        root.addWidget(self.pages, 1)
        self.pages.installEventFilter(self)

        bottom = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(bottom)
        self.bottom_l = bl
        bl.setContentsMargins(24, 0, 24, 12)
        bl.addStretch(1)
        wrap = QtWidgets.QWidget()
        wrap.setMaximumWidth(COLUMN_MAX + 8)
        wrap.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        wl = QtWidgets.QVBoxLayout(wrap)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(8)

        self.composer = QtWidgets.QFrame()
        self.composer.setObjectName("composer")
        shadow = QtWidgets.QGraphicsDropShadowEffect(self.composer)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 10)
        shadow.setColor(QtGui.QColor(0, 0, 0, 120))
        self.composer.setGraphicsEffect(shadow)
        cl = QtWidgets.QVBoxLayout(self.composer)
        cl.setContentsMargins(14, 12, 10, 10)
        cl.setSpacing(8)
        self.chips_w = QtWidgets.QWidget()
        self.chips_l = FlowLayout(self.chips_w, 8)
        self.chips_w.hide()
        cl.addWidget(self.chips_w)

        self.input = InputBox()
        self.input.submit.connect(self.send)
        self.input.focus_changed.connect(self._composer_focus)
        self.input.files_pasted.connect(self.add_files)
        self.input.textChanged.connect(self._update_send)
        cl.addWidget(self.input)
        self.rec_bar = RecordingBar()
        self.rec_bar.hide()
        cl.addWidget(self.rec_bar)
        # compatibility names
        self.listening = self.rec_bar.label
        self.meter = self.rec_bar.wave

        tb = QtWidgets.QHBoxLayout()
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)
        self.attach_btn = IconButton("plus", "Attach a photo, PDF or document", size=36, icon_size=20)
        self.attach_btn.clicked.connect(self._attach_menu)
        tb.addWidget(self.attach_btn)
        tb.addStretch(1)
        self.mic_btn = MicButton()
        self.mic_btn.pressed.connect(self._mic_pressed)
        self.mic_btn.released.connect(self._mic_released)
        tb.addWidget(self.mic_btn)
        tb.addSpacing(4)
        self.send_btn = SendButton()
        self.send_btn.clicked.connect(self._send_clicked)
        tb.addWidget(self.send_btn)
        cl.addLayout(tb)
        wl.addWidget(self.composer)
        hint = QtWidgets.QLabel("DevOS AI runs on this PC. Your chats, files and voice never leave it.")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self.hint = hint
        wl.addWidget(hint)
        bl.addWidget(wrap, 100)
        bl.addStretch(1)
        root.addWidget(bottom)

        self.fade = BottomFade(self.main)
        self.jump_btn = IconButton("arrow_down", "Jump to the latest message", size=34, icon_size=16,
                                   parent=self.main)
        self.jump_btn.setStyleSheet("")
        self.jump_btn.clicked.connect(lambda: self.scroll_to_bottom(True))
        self.jump_btn.hide()
        self.scrim = Scrim(self)
        self.scrim.hide()
        self.scrim.clicked.connect(lambda: self._animate_sidebar(0.0))
        self.drop = DropOverlay(self)
        self.toast = Toast(self.main)
        self._update_send()

    def _shortcuts(self):
        def sc(keys, fn):
            s = QtWidgets.QShortcut(QtGui.QKeySequence(keys), self)
            s.setContext(Qt.WindowShortcut)
            s.activated.connect(fn)
            return s
        sc("Ctrl+N", self.new_chat)
        sc("Ctrl+K", self.focus_search)
        sc("Ctrl+L", self.focus_input)
        sc("Ctrl+B", self.toggle_sidebar)
        sc("Esc", self.escape)

    def _place(self):
        w, h = self.width(), self.height()
        narrow = w < NARROW
        sw = int(SIDEBAR_W * self._sb_pos)
        if narrow:
            self.main.setGeometry(0, 0, w, h)
            self.sidebar.setGeometry(sw - SIDEBAR_W, 0, SIDEBAR_W, h)
            self.scrim.setGeometry(0, 0, w, h)
            self.scrim.alpha = self._sb_pos
            self.scrim.setVisible(self._sb_pos > 0.01)
            self.scrim.raise_()
            self.sidebar.raise_()
        else:
            self.scrim.hide()
            self.sidebar.setGeometry(sw - SIDEBAR_W, 0, SIDEBAR_W, h)
            self.main.setGeometry(sw, 0, w - sw, h)
        self.sidebar.setVisible(self._sb_pos > 0.01)
        self.scrim.update()
        self.drop.setGeometry(0, 0, w, h)
        self.drop.raise_()
        self._place_overlays()

    def _place_overlays(self):
        g = self.pages.geometry()
        self.fade.setGeometry(g.left(), g.bottom() - 28, g.width() - 10, 30)
        self.fade.raise_()
        self.jump_btn.move(g.left() + (g.width() - self.jump_btn.width()) // 2, g.bottom() - 46)
        self.jump_btn.raise_()
        if getattr(self, "toast", None) is not None and self.toast.isVisible():
            self.toast.place()

    def _animate_sidebar(self, target):
        self._sb_target = target
        anim = QtCore.QVariantAnimation(self)
        anim.setStartValue(self._sb_pos)
        anim.setEndValue(float(target))
        anim.setDuration(200)
        anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

        def step(v):
            self._sb_pos = float(v)
            self._place()
        anim.valueChanged.connect(step)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._sb_anim = anim

    def set_sidebar(self, show, animate=True):
        if self.width() >= NARROW:
            self._sidebar_pref = bool(show)
        target = 1.0 if show else 0.0
        if animate and self.isVisible():
            self._animate_sidebar(target)
        else:
            self._sb_target = self._sb_pos = target
            self._place()

    def toggle_sidebar(self):
        self.set_sidebar(self._sb_target < 0.5)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.width() < NARROW
        if narrow != self._narrow:
            self._narrow = narrow
            show = False if narrow else self._sidebar_pref
            self._sb_target = self._sb_pos = 1.0 if show else 0.0
        side = 16 if self.width() < 700 else 24
        self.host_l.setContentsMargins(side, 8, side, 40)
        self.bottom_l.setContentsMargins(side, 0, side, 12)
        self._place()

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "pages", None) and ev.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Move):
            self._place_overlays()
        if obj is self.column and ev.type() == QtCore.QEvent.Resize:
            w = self.column.width()
            for r in self.rows:
                r.set_column_width(w)
        return super().eventFilter(obj, ev)

    def showEvent(self, e):
        super().showEvent(e)
        QtCore.QTimer.singleShot(0, self._place_overlays)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QtCore.QEvent.ActivationChange and self.isActiveWindow():
            self.check_voice()          # cached for ~30 s in voice.VOICE_CHECK, so this stays cheap

    # -- voice readiness ----------------------------------------------------

    def check_voice(self, force=False):
        """Is voice usable (voice pack + a microphone)? Runs off the UI thread; updates the mic and switch."""
        if self._voice_checking:
            return
        self._voice_checking = True

        def job(_w):
            return voice.VOICE_CHECK.status(force)

        def done(res):
            self._voice_checking = False
            self._apply_voice(*res)

        def fail(_msg):
            self._voice_checking = False
        self._run(job, done, fail, track_busy=False)

    def _apply_voice(self, ok, reason=""):
        self._voice_ok = bool(ok)
        self._voice_reason = "" if ok else (reason or voice.VOICE_UNAVAILABLE_TEXT)
        self.mic_btn.set_unavailable(self._voice_reason)
        self.sidebar.hands_free.set_available(ok, self._voice_reason)

    def _voice_usable(self):
        if self._voice_ok is None:          # first click before the background check finished
            self._apply_voice(*voice.VOICE_CHECK.status())
        return self._voice_ok

    # -- helpers ------------------------------------------------------------

    def _set_status(self, state):
        extra = ""
        if state == "ready":
            model_info = engine.active_chat_model()
            model_id = model_info.get("id", "tiny")
            if model_id in ("large", "xl"):
                extra = f"{model_info.get('params', '7B')} · On this PC"
            elif model_id == "medium":
                extra = "3B · On this PC"
            elif model_id == "small":
                extra = "Smarter · On this PC"
        self.status.set_state(state, extra)

    def check_status(self):
        def job(_w):
            return self.assistant.model.health()

        def done(h):
            if h:
                self._set_status("ready")
            elif not self._service_started:
                self._service_started = engine.start_ai_service()
                self._set_status("starting" if self._service_started else "offline")
            else:
                self._set_status("starting")
        self._run(job, done, lambda _e: None, track_busy=False)

    def _composer_focus(self, on):
        self.composer.setProperty("focus", "true" if on else "false")
        self.composer.style().unpolish(self.composer)
        self.composer.style().polish(self.composer)

    def _update_send(self):
        if self.busy and self._handle is not None:
            self.send_btn.set_stop(True)
            self.send_btn.setEnabled(True)
            return
        self.send_btn.set_stop(False)
        has = bool(self.input.toPlainText().strip()) or bool(self.attachments)
        self.send_btn.setEnabled(has and self.busy == 0)

    def _send_clicked(self):
        if self.send_btn.stop_mode:
            self.stop_generation()
        else:
            self.send()

    def stop_generation(self):
        """Stop the answer being written: closes the connection to the AI service."""
        if self._handle is not None:
            self._handle.stop()

    # -- streaming ----------------------------------------------------------

    def _delta_for(self, hist):
        def on_delta(piece):
            if hist is not self.history:
                return
            self._stream_text += piece
            if self._stream_row is None:
                preview = engine.stream_preview(self._stream_text)
                if not preview:
                    return
                self.hide_thinking()
                self._stream_row = self._add_row(StreamingRow())
                self._stream_row.set_markdown(preview)
            if not self._stream_timer.isActive():
                self._stream_timer.start(33)        # at most ~30 repaints a second
        return on_delta

    def _flush_stream(self):
        if self._stream_row is not None:
            self._stream_row.set_markdown(engine.stream_preview(self._stream_text))

    def _end_stream(self):
        self._stream_timer.stop()
        row = self._stream_row
        self._stream_row = None
        self._stream_text = ""
        if row is not None:
            if row in self.rows:
                self.rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        return row is not None

    def _on_scroll(self, v):
        if self._scroll_anim is not None and self._scroll_anim.state() == QtCore.QAbstractAnimation.Running:
            return
        sb = self.scroll.verticalScrollBar()
        self._stick_bottom = v >= sb.maximum() - 24
        self.jump_btn.setVisible(not self._stick_bottom and self.pages.currentWidget() is self.scroll)

    def _on_range(self, _lo, hi):
        if self._stick_bottom:
            self.scroll_to_bottom(True)

    def scroll_to_bottom(self, animated=True):
        sb = self.scroll.verticalScrollBar()
        self._stick_bottom = True
        self.jump_btn.hide()
        if not animated or not self.isVisible():
            sb.setValue(sb.maximum())
            return
        if self._scroll_anim is not None and self._scroll_anim.state() == QtCore.QAbstractAnimation.Running:
            self._scroll_anim.setEndValue(sb.maximum())
            return
        if sb.value() == sb.maximum():
            return
        a = QtCore.QPropertyAnimation(sb, b"value", self)
        a.setDuration(260)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.setStartValue(sb.value())
        a.setEndValue(sb.maximum())
        a.finished.connect(self._scroll_anim_done)
        a.start()
        self._scroll_anim = a

    def _scroll_anim_done(self):
        # the range may have changed while animating: land exactly on the current end
        sb = self.scroll.verticalScrollBar()
        if self._stick_bottom:
            sb.setValue(sb.maximum())
        self._on_scroll(sb.value())

    def _show_chat_page(self):
        if self.pages.currentWidget() is not self.scroll:
            self.pages.setCurrentWidget(self.scroll)

    def _add_row(self, row, animate=True):
        self._show_chat_page()
        row.set_column_width(self.column.width())
        self.col_l.insertWidget(self.col_l.count() - 1, row)
        self.rows.append(row)
        if animate and self.isVisible():
            animate_in(row, row.lay, row.MARGINS)
        self._stick_bottom = True
        QtCore.QTimer.singleShot(0, lambda: self.scroll_to_bottom(animate))
        return row

    def _pin_latest(self):
        """Actions stay visible on the newest answer; Regenerate only there."""
        latest = None
        for r in self.rows:
            if isinstance(r, AssistantRow):
                latest = r
        for r in self.rows:
            if isinstance(r, AssistantRow):
                r.set_can_regenerate(r is latest and self._last_prompt() is not None)
                r.set_pinned(r is latest)

    def add_user(self, text, files=None, save=True):
        self._add_row(UserRow(text, files=files, ts=time.time()))
        if save:
            self.history.add("user", text, files=[os.path.basename(f) for f in (files or [])],
                             paths=list(files or []))
            self._save()

    def add_bot(self, text, ok=True, buttons=None, save=True, level=None, animate=True):
        row = AssistantRow(text, ok=ok, buttons=buttons, on_button=self.on_button, level=level,
                           on_regenerate=self.regenerate)
        self._add_row(row, animate=animate)
        if save:
            extra = {} if ok else {"ok": False}
            self.history.add("assistant", text, **extra)
            self._save()
        self._pin_latest()
        return row

    def show_thinking(self, text="Thinking"):
        self.hide_thinking()
        self.thinking = self._add_row(ThinkingRow(text))

    def hide_thinking(self):
        if self.thinking is not None:
            if self.thinking in self.rows:
                self.rows.remove(self.thinking)
            self.thinking.setParent(None)
            self.thinking.deleteLater()
            self.thinking = None

    def _run(self, job, on_done, on_fail=None, track_busy=True, on_progress=None, on_level=None, on_delta=None):
        w = Worker(job, self)
        self.workers.add(w)
        if track_busy:
            self.busy += 1
            self._update_send()

        def finish():
            self.workers.discard(w)
            if track_busy:
                self.busy -= 1
                self._update_send()
            w.deleteLater()

        w.done.connect(on_done)
        w.failed.connect(on_fail or self._worker_failed)
        if on_progress:
            w.progress.connect(on_progress)
        if on_level:
            w.level.connect(on_level)
        if on_delta:
            w.delta.connect(on_delta)
        w.finished.connect(finish)
        w.start()
        return w

    def _worker_failed(self, msg):
        self.hide_thinking()
        self._end_stream()
        self._handle = None
        self.add_bot(f"Something went wrong: {msg}", ok=False, level="error")

    # -- conversations ------------------------------------------------------

    def _save(self, history=None):
        h = history or self.history
        h.save()
        if self.store is not None:
            self.store.touch(h)
            self.refresh_sidebar()

    def _chat_id(self, h=None):
        h = h or self.history
        return getattr(h, "chat_id", None) or os.path.splitext(os.path.basename(h.path))[0]

    def refresh_sidebar(self):
        if self.store is None:
            return
        self.sidebar.populate(self.store.grouped(self._query), self._chat_id(), self._query)

    def _search_changed(self, text):
        self._query = text
        self.refresh_sidebar()

    def _clear_rows(self):
        self._end_stream()
        for r in list(self.rows):
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        self.thinking = None

    def _restore(self):
        msgs = self.history.messages[-60:]
        for m in msgs:
            if m["role"] == "user":
                paths = m.get("paths") or []
                files = [p for p in paths if os.path.isfile(p)] or (m.get("files") or [])
                self._add_row(UserRow(m["text"], files=files, ts=m.get("ts")), animate=False)
            else:
                self._add_row(AssistantRow(m["text"], ok=m.get("ok", True), ts=m.get("ts"),
                                           on_button=self.on_button, on_regenerate=self.regenerate),
                              animate=False)
        if msgs:
            self._pin_latest()
            QtCore.QTimer.singleShot(0, lambda: self.scroll_to_bottom(False))
        else:
            self.pages.setCurrentWidget(self.hero)

    def open_chat(self, cid):
        if self.store is None or cid == self._chat_id():
            self._close_drawer()
            return
        self.stop_listening()
        self._clear_rows()
        self.history = self.store.open(cid)
        self._restore()
        self.refresh_sidebar()
        self._close_drawer()
        self.input.setFocus()

    def _close_drawer(self):
        if self.width() < NARROW and self._sb_target > 0.5:
            self._animate_sidebar(0.0)

    def new_chat(self):
        if self.history.messages or self.rows:
            self._clear_rows()
            self.history = self.store.new_history() if self.store is not None else self.history
            if self.store is None:
                self.history.clear()
        self.pages.setCurrentWidget(self.hero)
        self.jump_btn.hide()
        self.refresh_sidebar()
        self._close_drawer()
        self.input.setFocus()

    def rename_chat(self, cid, title):
        if self.store is not None and self.store.rename(cid, title):
            self.refresh_sidebar()

    def delete_chat(self, cid):
        if self.store is None:
            return
        c = self.store.get(cid)
        title = (c or {}).get("title", "this chat")
        if not self.confirm(f"“{title}” will be deleted from this PC. This can't be undone.", "Delete chat?",
                            yes="Delete"):
            return
        self.store.delete(cid)
        if cid == self._chat_id():
            self._clear_rows()
            self.history = self.store.new_history()
            self.pages.setCurrentWidget(self.hero)
        self.refresh_sidebar()

    # -- attachments --------------------------------------------------------

    def _attach_menu(self):
        m = make_menu(self)
        a_img = m.addAction(make_icon("image", MUTED, 16), "Photo or screenshot…")
        a_doc = m.addAction(make_icon("file", MUTED, 16), "PDF or document…")
        pos = self.attach_btn.mapToGlobal(QtCore.QPoint(0, 0))
        size = m.sizeHint()
        act = m.exec_(QtCore.QPoint(pos.x(), pos.y() - size.height() - 6))
        if act is a_img:
            self.pick_files(IMAGE_FILTER)
        elif act is a_doc:
            self.pick_files(DOC_FILTER)

    def pick_files(self, filt=None):
        start = os.path.expanduser("~/Downloads")
        if not os.path.isdir(start):
            start = os.path.expanduser("~")
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Attach files", start, filt or ATTACH_FILTER)
        self.add_files(files)

    def add_files(self, files):
        for f in files:
            if not f or not os.path.isfile(f):
                continue
            if os.path.splitext(f)[1].lower() not in ATTACH_EXT:
                self.add_bot(f"I can't read **{os.path.basename(f)}**. Attach PNG, JPG or WebP photos, or PDF, "
                             "Word (.docx), text or Markdown files.", ok=False, save=False)
                continue
            if f in self.attachments or len(self.attachments) >= MAX_ATTACH:
                continue
            self.attachments.append(f)
            chip = Chip(f)
            chip.removed.connect(self.remove_file)
            self.chips[f] = chip
            self.chips_l.addWidget(chip)
        self._chips_changed()
        self.input.setFocus()

    def _chips_changed(self):
        self.chips_w.setVisible(bool(self.attachments))
        self.chips_l.invalidate()
        if self.attachments:
            self.chips_w.setFixedHeight(self.chips_l.heightForWidth(max(100, self.composer.width() - 24)))
        self._update_send()

    def remove_file(self, path):
        if path in self.attachments:
            self.attachments.remove(path)
        chip = self.chips.pop(path, None)
        if chip is not None:
            self.chips_l.removeWidget(chip)
            chip.setParent(None)
            chip.deleteLater()
        self._chips_changed()

    def clear_files(self):
        for p in list(self.attachments):
            self.remove_file(p)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop.setGeometry(self.rect())
            self.drop.show()
            self.drop.raise_()

    def dragLeaveEvent(self, e):
        self.drop.hide()

    def dropEvent(self, e):
        self.drop.hide()
        self.add_files([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # -- sending ------------------------------------------------------------

    def send(self, text=None):
        if self.busy:
            return
        if not isinstance(text, str):
            text = self.input.toPlainText()
        text = text.strip()
        files = list(self.attachments)
        if not text and not files:
            return
        self.input.clear()
        self.clear_files()
        self.add_user(text, files)
        self._dispatch(text, files)

    def _dispatch(self, text, files):
        hist = self.history
        on_replies = self._replies_for(hist)
        handle = engine.StreamHandle()
        on_delta = self._delta_for(hist)
        if files:
            label = "Reading " + (os.path.basename(files[0]) if len(files) == 1 else f"{len(files)} files")
            self.show_thinking(label)
            self._run(lambda _w: self.assistant.handle_attachments(text, files, hist), on_replies)
            return
        plan = self.assistant.plan(text, hist)
        if plan.actions:
            actions = []
            for a in plan.actions:
                if a.confirm and not self.confirm(a.confirm, a.label):
                    self.add_bot(f"Okay, I won't {a.label[:1].lower() + a.label[1:]}.")
                    continue
                actions.append(a)
            if not actions:
                return
            self._schedule_in_app_reminders(actions)
            if any(a.name == "type_text" for a in actions):
                # Typing goes to the window the user was in before: step out of the way first,
                # and never type into this window itself.
                for a in actions:
                    if a.name == "type_text":
                        a.args["avoid_window"] = str(int(self.winId()))
                self.showMinimized()
            self.show_thinking("Working on it")
            self._handle = handle
            self._run(lambda w: self.assistant.run_actions(actions, text, plan.leftover, hist,
                                                           on_delta=w.delta.emit, cancel=handle),
                      on_replies, on_delta=on_delta)
            return
        self.show_thinking()
        self._handle = handle
        self._run(lambda w: [self.assistant.chat(text, hist, on_delta=w.delta.emit, cancel=handle)], on_replies,
                  on_delta=on_delta)

    def _replies_for(self, hist):
        def done(replies):
            self._handle = None
            self._update_send()
            if hist is not self.history:      # the user switched chats meanwhile
                for r in replies or []:
                    hist.add("assistant", r.text, **({} if r.ok else {"ok": False}))
                self._save(hist)
                return
            self._replies(replies)
        return done

    def _replies(self, replies):
        self.hide_thinking()
        streamed = self._end_stream()
        replies = list(replies or [])
        for i, r in enumerate(replies):
            # the streamed answer is swapped for its final form in place, without a second fade-in
            still = streamed and i == len(replies) - 1 and getattr(r, "source", "") == "model"
            self.add_bot(r.text, ok=r.ok, buttons=r.buttons, animate=not still,
                         level="info" if r.text == "Stopped." else None)
        self.input.setFocus()

    def _last_prompt(self):
        for i in range(len(self.history.messages) - 1, -1, -1):
            m = self.history.messages[i]
            if m["role"] == "user":
                return i
        return None

    def regenerate(self):
        """Re-run the last prompt and replace the answers after it."""
        if self.busy:
            return
        idx = self._last_prompt()
        if idx is None:
            return
        m = self.history.messages[idx]
        text = m.get("text") or ""
        files = [p for p in (m.get("paths") or []) if os.path.isfile(p)]
        if not text and not files:
            return
        self.history.messages = self.history.messages[: idx + 1]
        self._save()
        last_user = max((i for i, r in enumerate(self.rows) if isinstance(r, UserRow)), default=-1)
        for r in self.rows[last_user + 1:]:
            r.setParent(None)
            r.deleteLater()
        self.rows = self.rows[: last_user + 1]
        self.thinking = None
        self._dispatch(text, files)

    def confirm(self, question, title="Confirm", yes="Yes, do it"):
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(APP_TITLE)
        box.setIcon(QtWidgets.QMessageBox.NoIcon)
        box.setIconPixmap(make_icon("warn", WARN, 32).pixmap(32, 32))
        box.setText(f"<span style='font-size:{FS_LARGE}px; font-weight:600; color:{TEXT_STRONG};'>{title}</span>")
        box.setInformativeText(question)
        yes_b = box.addButton(yes, QtWidgets.QMessageBox.AcceptRole)
        no = box.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.exec_()
        return box.clickedButton() is yes_b

    def on_button(self, payload, btn):
        if isinstance(payload, tools.Action):
            if payload.confirm and not self.confirm(payload.confirm, payload.label):
                return
            self._run(lambda _w: [engine.Reply(tools.execute(payload, self.assistant.ctx).text)],
                      lambda rs: None if not rs or rs[0].text.startswith("Opening") else self._replies(rs),
                      track_busy=False)
        elif payload == "download_vision":
            btn.setEnabled(False)
            self.download_vision(btn)
        elif payload == "smarter_ai":
            self.smarter_ai()

    # -- downloads ----------------------------------------------------------

    def _progress_dialog(self, title, total_label):
        dlg = QtWidgets.QProgressDialog(title, "Pause", 0, 1000, self)
        dlg.setWindowTitle(APP_TITLE)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumWidth(440)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        dlg.setLabelText(f"{title}\n0 MB of {total_label}")
        return dlg

    def download_vision(self, btn=None):
        ok, why = vision.runtime_supported()
        if not ok:
            self.add_bot(f"{vision.FEATURE} can't be set up on this PC: {why}", ok=False)
            return
        size = vision.download_size_label()
        ans = QtWidgets.QMessageBox.question(
            self, APP_TITLE,
            f"{vision.FEATURE} needs a one-time {size} download.\n\nAfter that, photos are understood "
            f"on this PC and never uploaded. Download now?")
        if ans != QtWidgets.QMessageBox.Yes:
            if btn:
                btn.setEnabled(True)
            return
        cancel = threading.Event()
        dlg = self._progress_dialog(f"Downloading {vision.FEATURE.lower()}", size)
        dlg.canceled.connect(cancel.set)

        def job(w):
            return vision.download_model(lambda d, t: w.progress.emit(int(d / 1e6), int(t / 1e6)), cancel=cancel)

        def prog(d, t):
            dlg.setMaximum(max(1, t))
            dlg.setValue(min(d, t))
            dlg.setLabelText(f"Downloading {vision.FEATURE.lower()}\n{d:,} MB of {t:,} MB")

        def done(res):
            dlg.close()
            ok2, msg = res
            if ok2:
                self.add_bot(msg + " Attach the photo again and ask about it.", ok=False, level="ok", save=False)
            else:
                self.add_bot(msg, ok=False)
            if btn and not ok2:
                try:
                    btn.setEnabled(True)
                except RuntimeError:
                    pass
        dlg.show()
        self._run(job, done, track_busy=False, on_progress=prog)

    def smarter_ai(self):
        """Install (or remove) the bigger chat model through the root helper, or open model manager."""
        card = self.sidebar.smart
        if card.busy:
            return
        model_info = getattr(card, "model_info", None) or engine.active_chat_model()
        model_id = model_info.get("id", "tiny")
        if model_id in ("large", "xl", "medium"):
            models_gui_py = os.path.join(tools.COMPONENTS, "ai-core", "models_gui.py")
            if os.path.isfile(models_gui_py):
                try:
                    subprocess.Popen([sys.executable or "python3", models_gui_py], start_new_session=True)
                    return
                except OSError:
                    pass
            if shutil.which("devos-ai-models"):
                subprocess.Popen(["devos-ai-models", "status"], start_new_session=True)
            return
        remove = engine.smart_model_installed()
        if remove:
            q = (f"Go back to the built-in DevOS AI and free {engine.SMART_SIZE}? Answers will be shorter and "
                 "simpler, but faster.")
            if not self.confirm(q, f"Switch back from {engine.SMART_LABEL}?", yes="Switch back"):
                return
        else:
            q = (f"{engine.SMART_LABEL} gives clearer, more accurate answers. It needs a one-time "
                 f"{engine.SMART_SIZE} download and about 2 GB of free space, and still runs only on this PC.")
            if not self.confirm(q, f"Get {engine.SMART_LABEL}?", yes="Download"):
                return
        card.set_progress(0, 0, "Removing…" if remove else "Waiting for the administrator password…")
        self._set_status("starting")

        def job(w):
            return engine.run_upgrade(remove, lambda d, t: w.progress.emit(int(d), int(t)))

        def prog(d, t):
            card.set_progress(d, t)

        def done(res):
            card.done()
            ok, msg = res
            self.add_bot(msg, ok=False, level="ok" if ok else "warn", save=False)
            self._service_started = True
            QtCore.QTimer.singleShot(1500, self.check_status)
            QtCore.QTimer.singleShot(6000, self.check_status)

        def fail(msg):
            card.done()
            self.add_bot(f"{engine.SMART_LABEL} couldn't be set up: {msg}", ok=False, save=False)
            self.check_status()
        self._run(job, done, fail, track_busy=False, on_progress=prog)

    # -- voice --------------------------------------------------------------

    def _mic_pressed(self):
        MicButton.pressed_at = time.monotonic()
        if self.recorder is not None:
            self.stop_listening()
            MicButton.pressed_at = 0.0
            return
        self.start_listening()

    def _mic_released(self):
        # held for a while -> push-to-talk: releasing stops
        if self.recorder is not None and MicButton.pressed_at and time.monotonic() - MicButton.pressed_at > 0.6:
            self.stop_listening()

    def _listening_ui_on(self):
        self.mic_btn.set_recording(True)
        self.input.hide()
        self.rec_bar.show()
        self.rec_bar.start()

    def start_listening(self):
        if not self._voice_usable():
            # a transient note by the mic, never a chat message (clicking again must not pile up cards)
            self.toast.show_for(self.mic_btn, self._voice_reason + " You can still type your request.",
                                above=self.composer)
            return
        rec = voice.Recorder()
        self.recorder = rec
        self._listening_ui_on()

        def job(w):
            rec.on_level = w.level.emit
            pcm, problem = rec.record()
            if problem or not pcm:
                return "", problem or "Nothing was recorded."
            w.level.emit(-1.0)
            return voice.fix_transcript(voice.Transcriber.transcribe(pcm)), ""

        def level(v):
            if v < 0:
                self.rec_bar.label.setText("Understanding…")
                self.rec_bar.set_level(0)
                self.mic_btn.set_level(0)
                return
            self.rec_bar.set_level(v)
            self.mic_btn.set_level(v)

        def done(res):
            self._listening_ui_off()
            text, problem = res
            if problem:
                self.add_bot(problem, ok=False, save=False)
                return
            if not text:
                self.add_bot("I didn't catch that. Try again, a little closer to the microphone.", ok=False,
                             save=False)
                return
            self.input.setPlainText(text)
            QtCore.QTimer.singleShot(350, self.send)

        def fail(msg):
            self._listening_ui_off()
            self.add_bot(f"Voice input stopped: {msg}", ok=False, save=False, level="error")

        self.voice_worker = self._run(job, done, fail, track_busy=False, on_level=level)

    def stop_listening(self):
        if self.recorder is not None:
            self.recorder.stop()

    def set_hands_free(self, on):
        """Sidebar switch: save the choice; the listener follows the setting file."""
        row = self.sidebar.hands_free
        if on and not self._voice_usable():
            # a short inline hint under the switch that hides itself; never a chat message
            row.set_on(False)
            row.show_hint(self._voice_reason)
            return
        if on and listen.live_session():
            row.set_on(False)
            row.show_hint("Hands-free works after DevOS is installed on this PC.")
            return
        listen.save_config(hands_free=bool(on), paused=False)
        if not on:
            row.hint.hide()
        if on:
            tools.popen_detached([tools.PYTHON, os.path.join(HERE, "listen.py"), "--daemon"])
            if not self._hands_free_told:   # explain once per session, not on every toggle
                self._hands_free_told = True
                self.add_bot("Hands-free is on. Say **“Hey DevOS”** and then your command, for example "
                             "“Hey DevOS, open Chrome”. A microphone icon in the panel shows it's listening; "
                             "turn it off here or from that icon.", ok=False, save=False, level="ok")
            else:
                row.show_hint("Hands-free is on.", ok=True)

    def _schedule_in_app_reminders(self, actions):
        """Reminders also pop up here while the window stays open (the desktop notification fires anyway)."""
        for a in actions:
            if a.name != "reminder":
                continue
            try:
                secs = int(a.args.get("seconds", 0))
            except (TypeError, ValueError):
                continue
            if not 0 < secs <= tools.MAX_REMINDER_S:
                continue
            if a.args.get("kind") == "timer":
                msg = f"⏰ Your **{tools.human_duration(secs)}** timer is done."
            else:
                what = str(a.args.get("message") or "").strip()
                msg = f"⏰ Reminder: **{what}**" if what else "⏰ This is your reminder."
            QtCore.QTimer.singleShot(secs * 1000, lambda m=msg: self.add_bot(m, ok=False, save=False, level="ok"))

    def _listening_ui_off(self):
        self.recorder = None
        self.mic_btn.set_recording(False)
        self.mic_btn.set_level(0)
        self.rec_bar.stop()
        self.rec_bar.hide()
        self.input.show()
        self.input.setFocus()

    # -- keyboard -----------------------------------------------------------

    def focus_input(self):
        self._close_drawer()
        self.input.setFocus()

    def focus_search(self):
        if self._sb_target < 0.5:
            self.set_sidebar(True)
        self.sidebar.search.setFocus()
        self.sidebar.search.selectAll()

    def escape(self):
        if self.recorder is not None:
            self.stop_listening()
        elif self._handle is not None and self.busy:
            self.stop_generation()
        elif self.drop.isVisible():
            self.drop.hide()
        elif self.width() < NARROW and self._sb_target > 0.5:
            self._animate_sidebar(0.0)
            self.input.setFocus()
        elif self.sidebar.search.hasFocus():
            self.sidebar.search.clear()
            self.input.setFocus()

    def closeEvent(self, e):
        self.stop_listening()
        if self.history.messages:
            self.history.save()
        super().closeEvent(e)


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    QtWidgets.QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    app.setDesktopFileName("devos-chat")
    apply_app_theme(app)
    win = AssistantWindow()
    win.show()
    # "Open in DevOS AI" from the voice overlay: devos-chat --ask "what was said"
    if "--ask" in argv:
        i = argv.index("--ask")
        ask = " ".join(argv[i + 1:i + 2]).strip()
        if ask:
            QtCore.QTimer.singleShot(400, lambda: win.send(ask))
    return app.exec_()


def apply_app_theme(app):
    font = QtGui.QFont()
    families = QtGui.QFontDatabase().families()
    for fam in ("Inter", "Noto Sans"):
        if fam in families:
            font = QtGui.QFont(fam)
            break
    font.setPixelSize(FS_BODY)
    font.setHintingPreference(QtGui.QFont.PreferNoHinting)
    app.setFont(font)
    app.setStyle("Fusion")
    pal = app.palette()
    for role, color in ((QtGui.QPalette.Window, BG), (QtGui.QPalette.Base, SURFACE),
                        (QtGui.QPalette.AlternateBase, SURFACE_HI),
                        (QtGui.QPalette.Text, TEXT), (QtGui.QPalette.WindowText, TEXT),
                        (QtGui.QPalette.Button, SURFACE), (QtGui.QPalette.ButtonText, TEXT),
                        (QtGui.QPalette.Highlight, SELECTION), (QtGui.QPalette.HighlightedText, "#ffffff"),
                        (QtGui.QPalette.PlaceholderText, FAINT), (QtGui.QPalette.ToolTipBase, SURFACE),
                        (QtGui.QPalette.ToolTipText, TEXT), (QtGui.QPalette.Link, LINK),
                        (QtGui.QPalette.Mid, BORDER), (QtGui.QPalette.Dark, BG), (QtGui.QPalette.Light, BORDER)):
        pal.setColor(role, QtGui.QColor(color))
    app.setPalette(pal)


if __name__ == "__main__":
    sys.exit(main())
