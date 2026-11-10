"""Shared dark/light appearance for every DevOS Qt window and label.

Apps author a dark stylesheet as the source of truth. This module:
  * reads Plasma / DevOS theme mode
  * applies a matching QPalette (so unstyled text is never black-on-black
    or white-on-white)
  * rewrites stylesheets for light mode (and reverses light-authored sheets
    for dark mode)
  * watches kdeglobals + settings.json and live-refreshes open windows
"""
from __future__ import annotations

import colorsys
import json
import os
from pathlib import Path
import re

from PyQt5 import QtCore, QtGui, QtWidgets

# Prefer 8-digit hex before 6-digit so #RRGGBBAA is not truncated to #RRGGBB.
COLOR = re.compile(
    r"#[0-9a-fA-F]{8}\b|#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|\b(?:white|black)\b|"
    r"rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)",
    re.I,
)
# CSS authors write #RRGGBBAA; Qt stylesheets read 8-digit hex as #AARRGGBB.
HEX8 = re.compile(r"#([0-9a-fA-F]{8})\b")

# Canonical dark chrome. Light mode is derived; never ship light-only sheets
# as the only source or dark mode will stay washed out.
PREMIUM_CONTROLS_DARK = """
QToolTip { background: #172135; color: #f8fafc; border: 1px solid #425574;
    padding: 8px; border-radius: 6px; }
QPushButton { border-radius: 8px; padding: 7px 14px; color: #f8fafc; }
QPushButton:focus, QToolButton:focus { border: 2px solid #38bdf8; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    border-radius: 8px; padding: 7px; background: #0f1525; color: #f8fafc;
    selection-background-color: #2563eb; selection-color: #ffffff;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus,
QTextEdit:focus, QPlainTextEdit:focus { border: 2px solid #38bdf8; }
QLineEdit::placeholder, QTextEdit::placeholder, QPlainTextEdit::placeholder {
    color: #94a3b8;
}
QComboBox QAbstractItemView {
    background: #111827; color: #f8fafc;
    selection-background-color: #1e3a5f; selection-color: #ffffff;
}
QLabel { color: #e2e8f0; }
QCheckBox, QRadioButton { color: #e2e8f0; }
QTabBar::tab { padding: 10px 16px; margin-right: 3px; color: #94a3b8; }
QTabBar::tab:selected { border-bottom: 2px solid #38bdf8; color: #f8fafc; }
QHeaderView::section { padding: 9px; background: #111827; color: #e2e8f0; }
QMenu { padding: 6px; background: #111827; color: #f8fafc; }
QMenu::item { padding: 8px 24px; border-radius: 6px; }
QMenu::item:selected { background: #1e293b; }
QStatusBar { padding: 4px; color: #94a3b8; }
QScrollBar:vertical, QScrollBar:horizontal { background: transparent; }
"""

PALETTE_DARK = {
    "Window": "#0b101e",
    "WindowText": "#f1f5f9",
    "Base": "#0f1525",
    "AlternateBase": "#111827",
    "Text": "#f1f5f9",
    "Button": "#172135",
    "ButtonText": "#f1f5f9",
    "Highlight": "#2563eb",
    "HighlightedText": "#ffffff",
    "ToolTipBase": "#172135",
    "ToolTipText": "#f8fafc",
    "PlaceholderText": "#94a3b8",
    "Link": "#38bdf8",
    "BrightText": "#ffffff",
    "Light": "#334155",
    "Mid": "#1f2937",
    "Dark": "#0b0f19",
    "Shadow": "#000000",
}

PALETTE_LIGHT = {
    "Window": "#f4f7fb",
    "WindowText": "#0f172a",
    "Base": "#ffffff",
    "AlternateBase": "#f8fafc",
    "Text": "#0f172a",
    "Button": "#ffffff",
    "ButtonText": "#0f172a",
    "Highlight": "#2563eb",
    "HighlightedText": "#ffffff",
    # Match Plasma DevOS-Light frosted menus/tooltips over wallpapers.
    "ToolTipBase": "#0f172a",
    "ToolTipText": "#f1f5f9",
    "PlaceholderText": "#64748b",
    "Link": "#1d4ed8",
    "BrightText": "#0f172a",
    "Light": "#e2e8f0",
    "Mid": "#cbd5e1",
    "Dark": "#64748b",
    "Shadow": "#94a3b8",
}


def _role(name: str):
    return getattr(QtGui.QPalette, name)


def build_palette(mode: str) -> QtGui.QPalette:
    colors = PALETTE_LIGHT if mode in ("light", "mac-light") else PALETTE_DARK
    pal = QtGui.QPalette()
    for name, value in colors.items():
        pal.setColor(_role(name), QtGui.QColor(value))
    disabled = QtGui.QColor("#94a3b8") if mode in ("light", "mac-light") else QtGui.QColor("#64748b")
    for role_name in ("Text", "WindowText", "ButtonText", "PlaceholderText"):
        pal.setColor(QtGui.QPalette.Disabled, _role(role_name), disabled)
    return pal


def apply_palette(app: QtWidgets.QApplication, mode: str) -> None:
    app.setPalette(build_palette(mode))
    # Fusion paints palettes reliably across Plasma/Kvantum mixes.
    try:
        if not app.style() or app.style().objectName().lower() in ("", "kvantum", "kvantum-dark"):
            app.setStyle("Fusion")
    except Exception:
        try:
            app.setStyle("Fusion")
        except Exception:
            pass


def _parse_color(token: str) -> QtGui.QColor:
    raw = token.strip()
    # CSS #RRGGBBAA (authors) before Qt's #AARRGGBB read of 8-digit hex.
    m8 = re.fullmatch(r"#([0-9a-fA-F]{8})", raw)
    if m8:
        h = m8.group(1)
        c = QtGui.QColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
        c.setAlpha(int(h[6:8], 16))
        return c
    c = QtGui.QColor(raw)
    if c.isValid():
        return c
    # Qt may reject some rgba forms; normalize manually.
    m = re.fullmatch(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)",
        raw,
        re.I,
    )
    if not m:
        return QtGui.QColor()
    c = QtGui.QColor(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m.group(4) is not None:
        c.setAlphaF(float(m.group(4)))
    return c


def _fmt_color(c: QtGui.QColor, prefer_rgba: bool = False) -> str:
    if prefer_rgba or c.alpha() < 255:
        return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alphaF():.3g})"
    return c.name()


def normalize_stylesheet_colors(sheet: str) -> str:
    """Rewrite CSS #RRGGBBAA to rgba() so Qt does not paint #AARRGGBB."""

    def repl(match):
        h = match.group(1)
        r, g, b, a = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(h[6:8], 16))
        return f"rgba({r}, {g}, {b}, {a / 255:.3g})"

    return HEX8.sub(repl, sheet or "")


def _is_strong_fill(c: QtGui.QColor) -> bool:
    """True only for solid mid-tone accent fills that need white labels.

    Pastel cyan (#38bdf8) and translucent washes must keep authored dark ink.
    """
    if not c.isValid() or c.alphaF() < 0.55:
        return False
    sat, val = c.hsvSaturationF(), c.valueF()
    return sat > 0.55 and 0.4 < val < 0.88


def light_stylesheet(sheet: str) -> str:
    """Translate explicit chrome colors by role, preserving colored action buttons."""
    sheet = normalize_stylesheet_colors(sheet)

    def block(match):
        body = match.group(1)
        background = re.search(
            r"(?:^|;)\s*background(?:-color)?\s*:\s*"
            r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|white|black)",
            body,
            re.I,
        )
        strong = False
        if background:
            strong = _is_strong_fill(_parse_color(background.group(1)))

        def declaration(m):
            prop, value = m.group(1), m.group(2)

            def color(cm):
                token = cm.group()
                c = _parse_color(token)
                if not c.isValid():
                    return token
                h, sat, val, _ = c.getHsvF()
                keep_alpha = c.alpha() < 255
                if prop.startswith("background") or prop == "selection-background-color":
                    # White glass on dark chrome → slate glass on light chrome.
                    if keep_alpha and sat < 0.12 and val > 0.85:
                        out = QtGui.QColor("#0f172a")
                        out.setAlpha(c.alpha())
                        return _fmt_color(out, True)
                    if sat > 0.55 and val > 0.4:
                        return token
                    if val < 0.13:
                        out = QtGui.QColor("#ffffff")
                    elif val < 0.25:
                        out = QtGui.QColor("#f8fafc")
                    elif val < 0.5:
                        out = QtGui.QColor("#e2e8f0")
                    else:
                        return token
                    if keep_alpha:
                        out.setAlpha(c.alpha())
                    return _fmt_color(out, keep_alpha)
                if prop in ("color", "selection-color"):
                    if strong:
                        return "#ffffff"
                    if sat > 0.5 and val > 0.55:
                        r, g, b = colorsys.hsv_to_rgb(max(0, h), max(0.6, sat), 0.55)
                        return QtGui.QColor.fromRgbF(r, g, b).name()
                    # Near-white text on a light surface → near-black.
                    if val > 0.75:
                        return "#0f172a"
                    if val > 0.35:
                        return "#334155"
                    return "#0f172a"
                if prop.startswith("border"):
                    if keep_alpha and sat < 0.12 and val > 0.85:
                        out = QtGui.QColor("#0f172a")
                        out.setAlpha(max(c.alpha(), 40))
                        return _fmt_color(out, True)
                    return "#2563eb" if sat > 0.55 and val > 0.55 else "#cbd5e1"
                return token

            return prop + ": " + COLOR.sub(color, value) + ";"

        return "{" + re.sub(r"([\w-]+)\s*:\s*([^;{}]+);?", declaration, body) + "}"

    if "{" not in sheet:
        return light_stylesheet("QWidget {" + sheet + "}").split("{", 1)[1].rsplit("}", 1)[0]
    return re.sub(r"\{([^{}]*)\}", block, sheet)


def dark_stylesheet(sheet: str) -> str:
    """Convert a light-authored sheet back to dark chrome (for apps that shipped light CSS)."""
    sheet = normalize_stylesheet_colors(sheet)

    def block(match):
        body = match.group(1)
        background = re.search(
            r"(?:^|;)\s*background(?:-color)?\s*:\s*"
            r"(#[0-9a-fA-F]{3,8}|rgba?\([^)]+\)|white|black)",
            body,
            re.I,
        )
        strong = False
        if background:
            strong = _is_strong_fill(_parse_color(background.group(1)))

        def declaration(m):
            prop, value = m.group(1), m.group(2)

            def color(cm):
                token = cm.group()
                c = _parse_color(token)
                if not c.isValid():
                    return token
                h, sat, val, _ = c.getHsvF()
                keep_alpha = c.alpha() < 255
                if prop.startswith("background") or prop == "selection-background-color":
                    if sat > 0.55 and val > 0.4:
                        return token
                    if val > 0.92:
                        out = QtGui.QColor("#0b101e")
                    elif val > 0.85:
                        out = QtGui.QColor("#111827")
                    elif val > 0.7:
                        out = QtGui.QColor("#172135")
                    else:
                        return token
                    if keep_alpha:
                        out.setAlpha(c.alpha())
                    return _fmt_color(out, keep_alpha)
                if prop in ("color", "selection-color"):
                    if strong:
                        return "#ffffff"
                    if val < 0.2:
                        return "#f1f5f9"
                    if sat > 0.5 and val < 0.55:
                        r, g, b = colorsys.hsv_to_rgb(max(0, h), max(0.45, sat), 0.78)
                        return QtGui.QColor.fromRgbF(r, g, b).name()
                    if val < 0.35:
                        return "#f1f5f9"
                    if val < 0.55:
                        return "#cbd5e1"
                    return "#e2e8f0"
                if prop.startswith("border"):
                    return "#38bdf8" if sat > 0.55 and val > 0.45 else "#334155"
                return token

            return prop + ": " + COLOR.sub(color, value) + ";"

        return "{" + re.sub(r"([\w-]+)\s*:\s*([^;{}]+);?", declaration, body) + "}"

    if "{" not in sheet:
        return dark_stylesheet("QWidget {" + sheet + "}").split("{", 1)[1].rsplit("}", 1)[0]
    return re.sub(r"\{([^{}]*)\}", block, sheet)


def sheet_looks_light(sheet: str) -> bool:
    """True when most explicit backgrounds are light (light-authored CSS)."""
    bgs = re.findall(
        r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,6}|rgba?\([^)]+\))",
        sheet or "",
        re.I,
    )
    if not bgs:
        return False
    light = 0
    for token in bgs:
        c = _parse_color(token)
        if not c.isValid() or c.hsvSaturationF() > 0.55:
            continue
        if c.valueF() > 0.75:
            light += 1
    return light >= max(1, len(bgs) // 2)


def adapt_stylesheet(sheet: str, mode: str) -> str:
    if not sheet:
        return sheet
    # Always normalize CSS #RRGGBBAA so Qt never paints 8-digit hex as AARRGGBB.
    sheet = normalize_stylesheet_colors(sheet)
    light_mode = mode in ("light", "mac-light")
    if light_mode:
        return light_stylesheet(sheet) if not sheet_looks_light(sheet) else sheet
    # Dark mode: keep dark sources; invert light-authored sources.
    return dark_stylesheet(sheet) if sheet_looks_light(sheet) else sheet


def current_mode() -> str:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    # Plasma ColorScheme wins over a stale settings.json.
    try:
        text = (base / "kdeglobals").read_text(encoding="utf-8", errors="replace").lower()
        match = re.search(r"^colorscheme\s*=\s*(.+)$", text, re.M)
        if match:
            scheme = match.group(1).strip()
            if "light" in scheme or scheme in ("breeze", "breezelight"):
                return "light"
            if "dark" in scheme or scheme in ("devos", "breezedark"):
                return "dark"
            if "whitesur" in scheme and "light" in scheme:
                return "mac-light"
            if "whitesur" in scheme:
                return "mac"
    except OSError:
        pass
    try:
        mode = json.loads((base / "devos/settings.json").read_text(encoding="utf-8")).get(
            "appearance", {}
        ).get("theme")
        if mode in ("dark", "light", "mac", "mac-light"):
            return mode
    except (OSError, ValueError, TypeError):
        pass
    # Match DevOS default desktop (DevOS-Light).
    return "light"


class Appearance(QtCore.QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.busy = False
        self.mode = current_mode()
        self.app_source = None
        self.app_rendered = None
        self.watcher = QtCore.QFileSystemWatcher(self)
        self.debounce = QtCore.QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(120)
        self.debounce.timeout.connect(self.refresh)
        self.watcher.fileChanged.connect(lambda _: self.debounce.start())
        self.watcher.directoryChanged.connect(lambda _: self.debounce.start())
        apply_palette(self.app, self.mode)
        self.watch()
        self.sync_app()

    def watch(self):
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        for p in (base, base / "devos", base / "devos/settings.json", base / "kdeglobals"):
            if p.exists() and str(p) not in self.watcher.files() + self.watcher.directories():
                self.watcher.addPath(str(p))

    def style(self, widget: QtWidgets.QWidget) -> None:
        current = widget.styleSheet()
        rendered = widget.property("_devosRenderedStyle")
        source = widget.property("_devosSourceStyle")
        if source is None or current != rendered:
            source = current
        result = adapt_stylesheet(source, self.mode) if source else source
        widget.setProperty("_devosSourceStyle", source)
        widget.setProperty("_devosRenderedStyle", result)
        if current != result:
            widget.setStyleSheet(result)

    def sync_app(self) -> None:
        current = self.app.styleSheet()
        if self.app_source is None or current != self.app_rendered:
            # Strip previously injected premium controls before re-wrapping.
            raw = current or ""
            if PREMIUM_CONTROLS_DARK.strip() and PREMIUM_CONTROLS_DARK in raw:
                raw = raw.replace(PREMIUM_CONTROLS_DARK, "")
            self.app_source = raw
        source = PREMIUM_CONTROLS_DARK + (self.app_source or "")
        result = adapt_stylesheet(source, self.mode)
        self.app_rendered = result
        if current != result:
            self.app.setStyleSheet(result)

    def refresh(self) -> None:
        self.watch()
        mode = current_mode()
        # Always restyle: settings.json may be touched after Global Theme Apply
        # even when the mode string is unchanged, and dark STYLE sheets need a
        # fresh light_stylesheet() pass.
        self.mode = mode
        self.busy = True
        try:
            apply_palette(self.app, mode)
            self.sync_app()
            for widget in self.app.allWidgets():
                self.style(widget)
        finally:
            self.busy = False

    def eventFilter(self, widget, event):
        if self.busy:
            return False
        if not isinstance(widget, QtWidgets.QWidget):
            return False
        et = event.type()
        if et == QtCore.QEvent.Show or (
            et == QtCore.QEvent.StyleChange and widget.isVisible()
        ):
            self.busy = True
            try:
                # Keep mode fresh when a window opens after a theme switch.
                mode = current_mode()
                if mode != self.mode:
                    self.mode = mode
                    apply_palette(self.app, mode)
                self.sync_app()
                self.style(widget)
            finally:
                self.busy = False
        return False


def install(app: QtWidgets.QApplication) -> Appearance:
    """Install once per QApplication — safe to call from every DevOS entrypoint."""
    if not hasattr(app, "_devos_appearance"):
        app._devos_appearance = Appearance(app)
        app.installEventFilter(app._devos_appearance)
    else:
        # Re-sync when a late caller installs after setting its own stylesheet.
        app._devos_appearance.refresh()
        app._devos_appearance.sync_app()
    return app._devos_appearance
