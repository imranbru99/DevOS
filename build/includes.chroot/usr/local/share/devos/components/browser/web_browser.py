#!/usr/bin/env python3
"""DevOS Browser — premium Qt WebEngine browser with modern chrome and New Tab."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QStandardPaths, Qt, QUrl, QSize, QTimer
from PyQt5.QtGui import QDesktopServices, QFont, QKeySequence
from PyQt5.QtWebEngineWidgets import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView
from PyQt5.QtWidgets import (
    QAction, QApplication, QFrame, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QShortcut,
    QSizePolicy, QStatusBar, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app_identity import apply, prepare, show_window


# ---------------------------------------------------------------------------
# New Tab (premium landing)
# ---------------------------------------------------------------------------

_NTP_CSS_SHARED = """
  * { box-sizing: border-box; }
  html, body { height: 100%; }
  body {
    margin: 0; min-height: 100vh;
    font-family: "Outfit", "Noto Sans", "Segoe UI", sans-serif;
    display: grid; place-items: center;
    padding: 40px 22px 56px;
    overflow-x: hidden;
  }
  main {
    width: min(720px, 100%);
    text-align: center;
    position: relative;
    z-index: 1;
  }
  .glow {
    position: fixed; inset: auto; pointer-events: none; border-radius: 50%;
    filter: blur(60px); z-index: 0;
  }
  .glow.a { width: 42vw; height: 42vw; top: -12%; left: -8%; }
  .glow.b { width: 36vw; height: 36vw; bottom: -10%; right: -6%; }
  .brand {
    display: inline-flex; align-items: center; gap: 14px;
    margin: 0 auto 8px;
  }
  .mark {
    width: 64px; height: 64px; border-radius: 20px;
    display: grid; place-items: center;
    position: relative;
  }
  .mark::after {
    content: ""; position: absolute; inset: -1px; border-radius: 21px;
    padding: 1px; background: linear-gradient(135deg, rgba(255,255,255,.55), transparent 55%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor; mask-composite: exclude;
  }
  .mark span {
    font-family: "Fraunces", "Noto Serif", Georgia, serif;
    font-size: 30px; font-weight: 700; letter-spacing: -.04em;
  }
  h1 {
    margin: 0; font-family: "Fraunces", "Noto Serif", Georgia, serif;
    font-size: clamp(36px, 5vw, 48px); font-weight: 700;
    letter-spacing: -.035em; line-height: 1.05;
  }
  .tag {
    margin: 12px 0 0; font-size: 15px; font-weight: 500; letter-spacing: .01em;
  }
  form.omni {
    margin-top: 34px; display: flex; align-items: stretch; gap: 0;
    border-radius: 22px; overflow: hidden;
    backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
    transition: transform .25s ease, box-shadow .25s ease;
  }
  form.omni:focus-within { transform: translateY(-2px); }
  form.omni .lens {
    width: 52px; display: grid; place-items: center; flex: 0 0 auto;
    opacity: .55; font-size: 18px;
  }
  form.omni input {
    flex: 1; min-width: 0; border: 0; background: transparent;
    font: inherit; font-size: 16px; font-weight: 500; padding: 18px 4px 18px 0;
    outline: none;
  }
  form.omni button {
    border: 0; margin: 8px; border-radius: 14px;
    font: inherit; font-weight: 700; font-size: 14px;
    padding: 0 22px; cursor: pointer;
    transition: filter .15s ease, transform .15s ease;
  }
  form.omni button:hover { filter: brightness(1.06); transform: translateY(-1px); }
  .rail {
    margin-top: 36px;
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 12px;
  }
  @media (max-width: 560px) {
    .rail { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  }
  .tile {
    text-decoration: none; border-radius: 18px; padding: 16px 12px 14px;
    display: flex; flex-direction: column; align-items: center; gap: 10px;
    transition: transform .2s ease, background .2s ease, border-color .2s ease;
  }
  .tile:hover { transform: translateY(-3px); }
  .tile .icon {
    width: 44px; height: 44px; border-radius: 14px;
    display: grid; place-items: center;
    font-weight: 800; font-size: 15px; letter-spacing: -.03em;
  }
  .tile .name { font-size: 13px; font-weight: 600; }
  .foot {
    margin-top: 28px; font-size: 12px; font-weight: 500; letter-spacing: .04em;
    text-transform: uppercase; opacity: .55;
  }
"""

HOME_HTML_DARK = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New tab</title>
<style>
  :root {{ color-scheme: dark; }}
  {_NTP_CSS_SHARED}
  body {{
    color: #eef4fb;
    background:
      radial-gradient(1200px 520px at 18% -10%, rgba(34, 211, 238, .16), transparent 55%),
      radial-gradient(900px 480px at 92% 8%, rgba(14, 165, 233, .14), transparent 50%),
      linear-gradient(165deg, #070b14 0%, #0c1524 48%, #0a101c 100%);
  }}
  .glow.a {{ background: rgba(34, 211, 238, .22); }}
  .glow.b {{ background: rgba(56, 189, 248, .14); }}
  .mark {{
    background: linear-gradient(145deg, #22d3ee 0%, #0284c7 100%);
    box-shadow: 0 18px 50px rgba(14, 165, 233, .32), inset 0 1px 0 rgba(255,255,255,.35);
  }}
  .mark span {{ color: #041018; }}
  .tag {{ color: #93a7c0; }}
  form.omni {{
    background: rgba(14, 22, 38, .78);
    border: 1px solid rgba(255,255,255,.10);
    box-shadow: 0 24px 60px rgba(0,0,0,.35), inset 0 1px 0 rgba(255,255,255,.06);
  }}
  form.omni:focus-within {{
    border-color: rgba(34, 211, 238, .45);
    box-shadow: 0 28px 70px rgba(0,0,0,.4), 0 0 0 4px rgba(34, 211, 238, .12);
  }}
  form.omni input {{ color: #eef4fb; }}
  form.omni input::placeholder {{ color: #7f93ad; }}
  form.omni button {{ background: linear-gradient(135deg, #22d3ee, #0ea5e9); color: #041018; }}
  .tile {{
    background: rgba(255,255,255,.035);
    border: 1px solid rgba(255,255,255,.08);
    color: #d7e3f4;
  }}
  .tile:hover {{
    background: rgba(34, 211, 238, .08);
    border-color: rgba(34, 211, 238, .28);
    color: #fff;
  }}
  .tile .icon {{
    background: linear-gradient(145deg, rgba(34,211,238,.25), rgba(14,165,233,.12));
    color: #a5f3fc;
  }}
</style></head>
<body>
  <div class="glow a" aria-hidden="true"></div>
  <div class="glow b" aria-hidden="true"></div>
  <main>
    <div class="brand">
      <div class="mark" aria-hidden="true"><span>D</span></div>
    </div>
    <h1>DevOS Browser</h1>
    <p class="tag">Fast, private search on this PC — type a site or ask the web.</p>
    <form class="omni" action="https://duckduckgo.com/" method="get" role="search">
      <div class="lens" aria-hidden="true">⌕</div>
      <input name="q" placeholder="Search the web" autocomplete="off" spellcheck="false">
      <button type="submit">Go</button>
    </form>
    <div class="rail" aria-label="Quick links">
      <a class="tile" href="https://duckduckgo.com/"><span class="icon">Dd</span><span class="name">DuckDuckGo</span></a>
      <a class="tile" href="https://www.wikipedia.org/"><span class="icon">W</span><span class="name">Wikipedia</span></a>
      <a class="tile" href="https://news.google.com/"><span class="icon">N</span><span class="name">News</span></a>
      <a class="tile" href="https://maps.google.com/"><span class="icon">M</span><span class="name">Maps</span></a>
    </div>
    <p class="foot">Private browsing · Local bookmarks · Always on DevOS</p>
  </main>
</body></html>
"""

HOME_HTML_LIGHT = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New tab</title>
<style>
  :root {{ color-scheme: light; }}
  {_NTP_CSS_SHARED}
  body {{
    color: #0b1220;
    background:
      radial-gradient(1100px 480px at 14% -12%, rgba(14, 165, 233, .22), transparent 55%),
      radial-gradient(900px 460px at 90% 0%, rgba(125, 211, 252, .28), transparent 52%),
      linear-gradient(168deg, #f4f8fc 0%, #e8f1f8 42%, #e2ebf4 100%);
  }}
  .glow.a {{ background: rgba(56, 189, 248, .28); }}
  .glow.b {{ background: rgba(14, 165, 233, .16); }}
  .mark {{
    background: linear-gradient(145deg, #38bdf8 0%, #0369a1 100%);
    box-shadow: 0 18px 48px rgba(14, 165, 233, .28), inset 0 1px 0 rgba(255,255,255,.45);
  }}
  .mark span {{ color: #041018; }}
  .tag {{ color: #51657d; }}
  form.omni {{
    background: rgba(255,255,255,.82);
    border: 1px solid rgba(15, 23, 42, .08);
    box-shadow: 0 22px 55px rgba(15, 23, 42, .10), inset 0 1px 0 #fff;
  }}
  form.omni:focus-within {{
    border-color: rgba(2, 132, 199, .45);
    box-shadow: 0 28px 64px rgba(15, 23, 42, .12), 0 0 0 4px rgba(14, 165, 233, .14);
  }}
  form.omni input {{ color: #0b1220; }}
  form.omni input::placeholder {{ color: #7b8ea5; }}
  form.omni button {{ background: linear-gradient(135deg, #0ea5e9, #0369a1); color: #fff; }}
  .tile {{
    background: rgba(255,255,255,.55);
    border: 1px solid rgba(15, 23, 42, .08);
    color: #1e293b;
    box-shadow: 0 8px 24px rgba(15, 23, 42, .04);
  }}
  .tile:hover {{
    background: #fff;
    border-color: rgba(14, 165, 233, .35);
    color: #0b1220;
  }}
  .tile .icon {{
    background: linear-gradient(145deg, #e0f2fe, #bae6fd);
    color: #0369a1;
  }}
</style></head>
<body>
  <div class="glow a" aria-hidden="true"></div>
  <div class="glow b" aria-hidden="true"></div>
  <main>
    <div class="brand">
      <div class="mark" aria-hidden="true"><span>D</span></div>
    </div>
    <h1>DevOS Browser</h1>
    <p class="tag">Fast, private search on this PC — type a site or ask the web.</p>
    <form class="omni" action="https://duckduckgo.com/" method="get" role="search">
      <div class="lens" aria-hidden="true">⌕</div>
      <input name="q" placeholder="Search the web" autocomplete="off" spellcheck="false">
      <button type="submit">Go</button>
    </form>
    <div class="rail" aria-label="Quick links">
      <a class="tile" href="https://duckduckgo.com/"><span class="icon">Dd</span><span class="name">DuckDuckGo</span></a>
      <a class="tile" href="https://www.wikipedia.org/"><span class="icon">W</span><span class="name">Wikipedia</span></a>
      <a class="tile" href="https://news.google.com/"><span class="icon">N</span><span class="name">News</span></a>
      <a class="tile" href="https://maps.google.com/"><span class="icon">M</span><span class="name">Maps</span></a>
    </div>
    <p class="foot">Private browsing · Local bookmarks · Always on DevOS</p>
  </main>
</body></html>
"""


def is_light_mode() -> bool:
    try:
        from devos_appearance import current_mode
        return current_mode() in ("light", "mac-light")
    except Exception:
        return False


def home_html() -> str:
    return HOME_HTML_LIGHT if is_light_mode() else HOME_HTML_DARK


HOME_HTML = HOME_HTML_DARK  # legacy alias for imports/tests


def chrome_style(light: bool) -> str:
    if light:
        return """
QMainWindow { background: #e8eef5; }
QToolBar#nav {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #f7fafc, stop:1 #eef3f8);
  border: 0; border-bottom: 1px solid rgba(15,23,42,0.08);
  padding: 8px 10px; spacing: 5px;
}
QToolBar#bookmarks {
  background: #f3f7fb; border: 0; border-bottom: 1px solid rgba(15,23,42,0.06);
  padding: 4px 10px; spacing: 4px;
}
QToolBar QToolButton {
  color: #1e293b; background: transparent; border: 0; border-radius: 11px;
  padding: 7px 11px; font-weight: 600; min-width: 34px;
}
QToolBar QToolButton:hover { background: rgba(14,165,233,0.12); }
QToolBar QToolButton:pressed { background: rgba(14,165,233,0.20); }
QToolBar QToolButton:disabled { color: #94a3b8; }
QToolBar QToolButton#menuBtn {
  background: rgba(15,23,42,0.05); border-radius: 12px; padding: 7px 12px;
}
QToolBar QToolButton#newTabBtn {
  color: #075985; background: #e0f2fe; border: 1px solid #bae6fd;
  border-radius: 10px; padding: 6px 11px; min-width: 76px;
}
QToolBar QToolButton#newTabBtn:hover { background: #bae6fd; }
QFrame#omnibox {
  background: #ffffff; border: 1px solid rgba(15,23,42,0.10);
  border-radius: 16px;
}
QFrame#omnibox[focused="true"] {
  border-color: #0ea5e9;
}
QLabel#secureIcon { color: #059669; font-size: 12px; font-weight: 700; padding-left: 10px; }
QLabel#secureIcon[insecure="true"] { color: #64748b; }
QLineEdit#address {
  background: transparent; color: #0f172a; border: 0;
  padding: 9px 12px 9px 4px; selection-background-color: #bae6fd;
  font-size: 13px; font-weight: 500;
}
QTabWidget::pane { border: 0; background: #e8eef5; top: -1px; }
QTabBar { qproperty-drawBase: 0; background: #e8eef5; }
QTabBar::tab {
  background: transparent; color: #64748b; border: 0;
  border-top-left-radius: 12px; border-top-right-radius: 12px;
  padding: 8px 12px; margin: 4px 2px 0; min-width: 72px; max-width: 180px;
  font-weight: 600;
}
QTabBar::tab:selected {
  background: #ffffff; color: #0f172a;
  border: 1px solid rgba(15,23,42,0.08); border-top: 2px solid #0284c7; border-bottom: 0;
}
QTabBar::tab:hover:!selected { background: rgba(255,255,255,0.55); color: #334155; }
QTabBar::close-button { margin: 2px; }
QStatusBar { background: #eef3f8; color: #64748b; border-top: 1px solid rgba(15,23,42,0.06); }
QLabel#privateBadge {
  background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa;
  border-radius: 9px; padding: 3px 9px; font-size: 11px; font-weight: 700;
}
QProgressBar#loadBar {
  border: 0; background: transparent; max-height: 2px; min-height: 2px;
}
QProgressBar#loadBar::chunk { background: #0ea5e9; border-radius: 1px; }
QFrame#findBar {
  background: #ffffff; border-top: 1px solid rgba(15,23,42,0.08); padding: 8px 12px;
}
QLineEdit#findInput {
  background: #f1f5f9; border: 1px solid #cbd5e1; border-radius: 10px;
  padding: 7px 12px; color: #0f172a;
}
"""
    return """
QMainWindow { background: #070b14; }
QToolBar#nav {
  background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #121a2b, stop:1 #0e1624);
  border: 0; border-bottom: 1px solid rgba(255,255,255,0.07);
  padding: 8px 10px; spacing: 5px;
}
QToolBar#bookmarks {
  background: #0c1422; border: 0; border-bottom: 1px solid rgba(255,255,255,0.05);
  padding: 4px 10px; spacing: 4px;
}
QToolBar QToolButton {
  color: #e8eef8; background: transparent; border: 0; border-radius: 11px;
  padding: 7px 11px; font-weight: 600; min-width: 34px;
}
QToolBar QToolButton:hover { background: rgba(34,211,238,0.12); }
QToolBar QToolButton:pressed { background: rgba(34,211,238,0.20); }
QToolBar QToolButton:disabled { color: #5b6b82; }
QToolBar QToolButton#menuBtn {
  background: rgba(255,255,255,0.05); border-radius: 12px; padding: 7px 12px;
}
QToolBar QToolButton#newTabBtn {
  color: #a5f3fc; background: #153244; border: 1px solid #245469;
  border-radius: 10px; padding: 6px 11px; min-width: 76px;
}
QToolBar QToolButton#newTabBtn:hover { background: #20485e; }
QFrame#omnibox {
  background: #0a1220; border: 1px solid rgba(255,255,255,0.10);
  border-radius: 16px;
}
QFrame#omnibox[focused="true"] {
  border-color: #22d3ee;
}
QLabel#secureIcon { color: #34d399; font-size: 12px; font-weight: 700; padding-left: 10px; }
QLabel#secureIcon[insecure="true"] { color: #7f91a8; }
QLineEdit#address {
  background: transparent; color: #e8eef8; border: 0;
  padding: 9px 12px 9px 4px; selection-background-color: #0284c7;
  font-size: 13px; font-weight: 500;
}
QTabWidget::pane { border: 0; background: #070b14; top: -1px; }
QTabBar { qproperty-drawBase: 0; background: #0c1422; }
QTabBar::tab {
  background: transparent; color: #7f91a8; border: 0;
  border-top-left-radius: 12px; border-top-right-radius: 12px;
  padding: 8px 12px; margin: 4px 2px 0; min-width: 72px; max-width: 180px;
  font-weight: 600;
}
QTabBar::tab:selected {
  background: #121a2b; color: #eef4fb;
  border: 1px solid rgba(255,255,255,0.09); border-top: 2px solid #22d3ee; border-bottom: 0;
}
QTabBar::tab:hover:!selected { background: rgba(255,255,255,0.04); color: #c9d7ea; }
QStatusBar { background: #070b14; color: #7f91a8; border-top: 1px solid rgba(255,255,255,0.06); }
QLabel#privateBadge {
  background: #422006; color: #fbbf24; border-radius: 9px; padding: 3px 9px;
  font-size: 11px; font-weight: 700;
}
QProgressBar#loadBar {
  border: 0; background: transparent; max-height: 2px; min-height: 2px;
}
QProgressBar#loadBar::chunk { background: #22d3ee; border-radius: 1px; }
QFrame#findBar {
  background: #121a2b; border-top: 1px solid rgba(255,255,255,0.08); padding: 8px 12px;
}
QLineEdit#findInput {
  background: #0a1220; border: 1px solid rgba(255,255,255,0.12); border-radius: 10px;
  padding: 7px 12px; color: #e8eef8;
}
"""


STYLE = chrome_style(False)  # legacy default


def address_url(text):
    text = text.strip()
    if not text:
        return QUrl("about:blank")
    candidate = QUrl.fromUserInput(text)
    if candidate.isLocalFile() or (
        candidate.scheme() in ("http", "https") and candidate.host()
        and ("://" in text or "." in candidate.host() or candidate.host() == "localhost")
    ):
        return candidate
    return QUrl("https://duckduckgo.com/?" + urlencode({"q": text}))


def data_dir() -> Path:
    base = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "browser"
    base.mkdir(parents=True, exist_ok=True)
    return base


def bookmarks_path():
    return data_dir() / "bookmarks.json"


def recent_path():
    return data_dir() / "recent.json"


DEFAULT_BOOKMARKS = [
    {"title": "DuckDuckGo", "url": "https://duckduckgo.com/"},
    {"title": "Wikipedia", "url": "https://www.wikipedia.org/"},
    {"title": "News", "url": "https://news.google.com/"},
]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


class Omnibox(QFrame):
    """Address field with security indicator — modern omnibox look."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("omnibox")
        self.setProperty("focused", False)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(0)
        self.secure = QLabel("·")
        self.secure.setObjectName("secureIcon")
        self.secure.setProperty("insecure", True)
        self.secure.setToolTip("Connection status")
        lay.addWidget(self.secure)
        self.edit = QLineEdit(self)
        self.edit.setObjectName("address")
        self.edit.setPlaceholderText("Search or enter a web address")
        self.edit.setClearButtonEnabled(True)
        self.edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.edit.installEventFilter(self)
        lay.addWidget(self.edit, 1)

    def eventFilter(self, obj, event):
        if obj is self.edit:
            if event.type() == QEvent.FocusIn:
                self.setProperty("focused", True)
                self.style().unpolish(self)
                self.style().polish(self)
            elif event.type() == QEvent.FocusOut:
                self.setProperty("focused", False)
                self.style().unpolish(self)
                self.style().polish(self)
        return super().eventFilter(obj, event)

    def set_secure(self, secure: bool, tip: str = ""):
        self.secure.setProperty("insecure", not secure)
        self.secure.setText("Sec" if secure else "·")
        self.secure.setToolTip(tip or ("Secure connection" if secure else "Not secure"))
        self.secure.style().unpolish(self.secure)
        self.secure.style().polish(self.secure)


class BrowserView(QWebEngineView):
    def __init__(self, window):
        super().__init__()
        self.window = window
        page = QWebEnginePage(window.profile, self)
        self.setPage(page)
        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.PluginsEnabled, False)
        settings.setAttribute(QWebEngineSettings.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.LocalStorageEnabled, True)
        settings.setAttribute(QWebEngineSettings.ScrollAnimatorEnabled, True)
        settings.setAttribute(QWebEngineSettings.FullScreenSupportEnabled, True)
        settings.setAttribute(QWebEngineSettings.FocusOnNavigationEnabled, True)
        try:
            settings.setAttribute(QWebEngineSettings.DnsPrefetchEnabled, True)
        except Exception:
            pass

    def createWindow(self, _window_type):
        return self.window.new_tab(load_home=False)


class BrowserWindow(QMainWindow):
    def __init__(self, private):
        super().__init__()
        self.private = bool(private)
        self.light = is_light_mode()
        self._closed_tabs = []  # stack of QUrl strings
        self._zoom = 1.0
        self.resize(1240, 820)
        self.setMinimumSize(760, 480)
        self.setWindowTitle("DevOS Browser" + (" — Private" if self.private else ""))
        self.setStyleSheet(chrome_style(self.light))
        app = QApplication.instance()
        if self.private:
            self.profile = QWebEngineProfile(app)
        else:
            self.profile = QWebEngineProfile("DevOSBrowser", app)
            data = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
            cache = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
            self.profile.setPersistentStoragePath(data + "/browser")
            self.profile.setCachePath(cache + "/browser")
            self.profile.setPersistentCookiesPolicy(QWebEngineProfile.AllowPersistentCookies)
        self.profile.downloadRequested.connect(self.download)
        self.profile.setHttpUserAgent(self.profile.httpUserAgent() + " DevOSBrowser/2.0")

        shell = QWidget(self)
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)

        self.tabs = QTabWidget(shell)
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.update_chrome)

        self.load_bar = QProgressBar(shell)
        self.load_bar.setObjectName("loadBar")
        self.load_bar.setTextVisible(False)
        self.load_bar.setRange(0, 100)
        self.load_bar.setValue(0)
        self.load_bar.setFixedHeight(2)
        self.load_bar.hide()

        self.find_bar = QFrame(shell)
        self.find_bar.setObjectName("findBar")
        self.find_bar.hide()
        find_row = QHBoxLayout(self.find_bar)
        find_row.setContentsMargins(12, 6, 12, 6)
        find_row.addWidget(QLabel("Find"))
        self.find_input = QLineEdit(self.find_bar)
        self.find_input.setObjectName("findInput")
        self.find_input.setPlaceholderText("Find in page")
        self.find_input.textChanged.connect(self._find_text)
        self.find_input.returnPressed.connect(lambda: self._find_text(self.find_input.text(), True))
        find_row.addWidget(self.find_input, 1)
        prev_btn = QPushButton("Prev", self.find_bar)
        prev_btn.clicked.connect(lambda: self._find_text(self.find_input.text(), False))
        next_btn = QPushButton("Next", self.find_bar)
        next_btn.clicked.connect(lambda: self._find_text(self.find_input.text(), True))
        close_find = QPushButton("Done", self.find_bar)
        close_find.clicked.connect(self.hide_find)
        find_row.addWidget(prev_btn)
        find_row.addWidget(next_btn)
        find_row.addWidget(close_find)

        shell_lay.addWidget(self.tabs, 1)
        shell_lay.addWidget(self.load_bar)
        shell_lay.addWidget(self.find_bar)
        self.setCentralWidget(shell)

        self._build_nav()
        self._build_bookmarks()
        self._build_shortcuts()
        self._build_status()

    def _build_nav(self):
        nav = QToolBar("Navigation", self)
        nav.setObjectName("nav")
        nav.setMovable(False)
        nav.setIconSize(QSize(18, 18))
        self.addToolBar(nav)

        self.act_back = nav.addAction("←", lambda: self.current_view() and self.current_view().back())
        self.act_back.setToolTip("Back (Alt+Left)")
        self.act_back.setShortcut(QKeySequence(Qt.ALT | Qt.Key_Left))
        self.act_fwd = nav.addAction("→", lambda: self.current_view() and self.current_view().forward())
        self.act_fwd.setToolTip("Forward (Alt+Right)")
        self.act_fwd.setShortcut(QKeySequence(Qt.ALT | Qt.Key_Right))
        self.act_reload = nav.addAction("↻", self.reload_or_stop)
        self.act_reload.setToolTip("Reload (Ctrl+R)")
        self.act_reload.setShortcut(QKeySequence.Refresh)
        self.act_home = nav.addAction("⌂", self.go_home)
        self.act_home.setToolTip("New tab page")

        self.new_tab_action = QAction("New tab", self)
        self.new_tab_action.setShortcut(QKeySequence.AddTab)
        self.new_tab_action.triggered.connect(self.open_new_tab)
        self.addAction(self.new_tab_action)
        self.new_tab_button = QToolButton(nav)
        self.new_tab_button.setObjectName("newTabBtn")
        self.new_tab_button.setDefaultAction(self.new_tab_action)
        self.new_tab_button.setText("+ New tab")
        self.new_tab_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.new_tab_button.setToolTip("New tab (Ctrl+T)")
        nav.addWidget(self.new_tab_button)

        self.omnibox = Omnibox(nav)
        self.address = self.omnibox.edit
        self.address.returnPressed.connect(self.navigate)
        nav.addWidget(self.omnibox)

        focus = QAction("Address bar", self)
        focus.setShortcut("Ctrl+L")
        focus.triggered.connect(self.focus_address)
        self.addAction(focus)

        self.act_bookmark = nav.addAction("★", self.bookmark_current)
        self.act_bookmark.setToolTip("Bookmark this page (Ctrl+D)")
        self.act_bookmark.setShortcut("Ctrl+D")

        self.tab_picker = QToolButton(nav)
        self.tab_picker.setToolTip("Show open tabs")
        self.tab_picker.setAccessibleName("Show open tabs")
        self.tab_picker.setPopupMode(QToolButton.InstantPopup)
        tab_menu = QMenu(self.tab_picker)
        tab_menu.aboutToShow.connect(self._fill_tab_menu)
        self.tab_picker.setMenu(tab_menu)
        nav.addWidget(self.tab_picker)
        self._update_tab_count()

        menu_btn = QToolButton(nav)
        menu_btn.setObjectName("menuBtn")
        menu_btn.setText("☰")
        menu_btn.setToolTip("Menu")
        menu_btn.setPopupMode(QToolButton.InstantPopup)
        menu_btn.setMenu(self._build_menu())
        nav.addWidget(menu_btn)

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        def command(label, callback, shortcut):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback)
            self.addAction(action)
            menu.addAction(action)

        menu.addAction(self.new_tab_action)
        menu.addAction("New window", self.open_window)
        command("New private window", self.open_private, "Ctrl+Shift+N")
        menu.addSeparator()
        command("Find in page…", self.show_find, "Ctrl+F")
        command("Zoom in", lambda: self.adjust_zoom(0.1), "Ctrl+=")
        command("Zoom out", lambda: self.adjust_zoom(-0.1), "Ctrl+-")
        command("Reset zoom", lambda: self.set_zoom(1.0), "Ctrl+0")
        menu.addSeparator()
        hist = menu.addMenu("Recent")
        hist.aboutToShow.connect(lambda: self._fill_recent_menu(hist))
        command("Reopen closed tab", self.reopen_closed_tab, "Ctrl+Shift+T")
        menu.addAction("Duplicate tab", self.duplicate_tab)
        menu.addSeparator()
        menu.addAction("Copy page link", self.copy_url)
        command("Print…", self.print_page, "Ctrl+P")
        menu.addAction("Downloads folder", self.open_downloads)
        if not self.private:
            menu.addAction("Clear recent history…", self.clear_recent)
        menu.addSeparator()
        menu.addAction("Private window" if not self.private else "Private window active", self.open_private)
        return menu

    def _build_bookmarks(self):
        self.bookmark_bar = QToolBar("Bookmarks", self)
        self.bookmark_bar.setObjectName("bookmarks")
        self.bookmark_bar.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(self.bookmark_bar)
        self.reload_bookmarks()

    def _build_shortcuts(self):
        QShortcut(QKeySequence("Escape"), self, activated=self.hide_find)
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self.adjust_zoom(0.1))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self._cycle_tab(1))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self, activated=lambda: self._cycle_tab(-1))
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        close_tab = QAction("Close tab", self)
        close_tab.setShortcut("Ctrl+W")
        close_tab.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        self.addAction(close_tab)

    def _build_status(self):
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_url = QLabel("")
        status.addWidget(self.status_url, 1)
        self.zoom_label = QLabel("100%")
        status.addPermanentWidget(self.zoom_label)
        if self.private:
            badge = QLabel("PRIVATE")
            badge.setObjectName("privateBadge")
            status.addPermanentWidget(badge)

    # -- persistence --------------------------------------------------------

    def bookmarks(self):
        path = bookmarks_path()
        if not path.is_file():
            return list(DEFAULT_BOOKMARKS)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
        except (OSError, ValueError, TypeError):
            pass
        return list(DEFAULT_BOOKMARKS)

    def save_bookmarks(self, items):
        try:
            bookmarks_path().write_text(json.dumps(items, indent=2), encoding="utf-8")
        except OSError:
            pass

    def recent(self):
        if self.private:
            return []
        path = recent_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return []

    def remember_visit(self, url: QUrl, title: str = ""):
        if self.private or url.scheme() not in ("http", "https") or not url.host():
            return
        href = url.toString()
        items = [i for i in self.recent() if str(i.get("url")) != href]
        items.insert(0, {"title": (title or url.host())[:80], "url": href, "at": int(time.time())})
        try:
            recent_path().write_text(json.dumps(items[:40], indent=2), encoding="utf-8")
        except OSError:
            pass

    def reload_bookmarks(self):
        self.bookmark_bar.clear()
        for item in self.bookmarks()[:14]:
            title = str(item.get("title") or item.get("url") or "Link")[:28]
            url = str(item.get("url") or "")
            if not url:
                continue
            act = self.bookmark_bar.addAction(title, lambda _=False, u=url: self.open_url(u))
            act.setToolTip(url)

    # -- tabs ---------------------------------------------------------------

    def current_view(self):
        return self.tabs.currentWidget()

    def open_new_tab(self):
        self.new_tab()
        self.focus_address()

    def _cycle_tab(self, step):
        count = self.tabs.count()
        if count:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + step) % count)

    def _update_tab_count(self):
        self.tab_picker.setText(f"Tabs {self.tabs.count()}")

    def _fill_tab_menu(self):
        menu = self.tab_picker.menu()
        menu.clear()
        for index in range(self.tabs.count()):
            action = menu.addAction(self.tabs.tabIcon(index), self.tabs.tabText(index))
            action.setCheckable(True)
            action.setChecked(index == self.tabs.currentIndex())
            action.triggered.connect(lambda _checked, i=index: self.tabs.setCurrentIndex(i))

    def new_tab(self, url=None, load_home=True):
        view = BrowserView(self)
        view.urlChanged.connect(lambda _u, v=view: self._on_url(v))
        view.loadStarted.connect(lambda v=view: self._on_load(v, True))
        view.loadProgress.connect(lambda p, v=view: self._on_progress(v, p))
        view.loadFinished.connect(lambda _ok, v=view: self._on_load(v, False))
        view.titleChanged.connect(lambda title, v=view: self._set_tab_title(v, title))
        view.iconChanged.connect(lambda icon, v=view: self._set_tab_icon(v, icon))
        view.page().linkHovered.connect(self._link_hover)
        view.page().fullScreenRequested.connect(self._fullscreen_request)
        idx = self.tabs.addTab(view, "New tab")
        self.tabs.setCurrentIndex(idx)
        self._update_tab_count()
        if url:
            view.setUrl(address_url(url) if isinstance(url, str) else url)
        elif load_home:
            view.setHtml(home_html(), QUrl("https://newtab.local/"))
        view.setZoomFactor(self._zoom)
        return view

    def _set_tab_title(self, view, title):
        i = self.tabs.indexOf(view)
        if i >= 0:
            self.tabs.setTabText(i, (title or "New tab").replace("&", "&&"))
            self.tabs.setTabToolTip(i, title or "New tab")
        if view is self.current_view():
            self.remember_visit(view.url(), title)

    def _set_tab_icon(self, view, icon):
        index = self.tabs.indexOf(view)
        if index >= 0:
            self.tabs.setTabIcon(index, icon)

    def _on_url(self, view):
        if view is self.current_view():
            self.update_chrome()

    def _on_load(self, view, loading):
        if view is not self.current_view():
            return
        self.act_reload.setText("✕" if loading else "↻")
        self.act_reload.setToolTip("Stop" if loading else "Reload (Ctrl+R)")
        if loading:
            self.load_bar.show()
            self.load_bar.setValue(8)
        else:
            self.load_bar.setValue(100)
            QTimer.singleShot(220, self.load_bar.hide)
            self.update_chrome()
            self.remember_visit(view.url(), view.title())

    def _on_progress(self, view, value):
        if view is self.current_view():
            self.load_bar.show()
            self.load_bar.setValue(max(5, int(value)))

    def _link_hover(self, url):
        self.status_url.setText(url or "")

    def _fullscreen_request(self, request):
        request.accept()
        if request.toggleOn():
            self.showFullScreen()
        else:
            self.showNormal()

    def close_tab(self, index):
        view = self.tabs.widget(index)
        if view is None:
            return
        url = view.url()
        if url.scheme() in ("http", "https") and url.host():
            self._closed_tabs.append(url.toString())
            self._closed_tabs = self._closed_tabs[-20:]
        if self.tabs.count() == 1:
            self.close()
            return
        self.tabs.removeTab(index)
        self._update_tab_count()
        view.deleteLater()

    def reopen_closed_tab(self):
        if not self._closed_tabs:
            return
        self.new_tab(self._closed_tabs.pop())

    def duplicate_tab(self):
        view = self.current_view()
        if not view:
            return
        url = view.url()
        if url.scheme() in ("http", "https") and url.host():
            self.new_tab(url.toString())
        else:
            self.new_tab()

    def update_chrome(self, _index=None):
        view = self.current_view()
        if not view:
            return
        url = view.url()
        if url.scheme() in ("about", "data") or not url.host() or url.host() == "newtab.local":
            self.address.setText("")
            self.omnibox.set_secure(False, "New tab")
        else:
            self.address.setText(url.toDisplayString())
            secure = url.scheme() == "https"
            host = url.host()
            self.omnibox.set_secure(secure, f"Connection is secure — {host}" if secure else f"Not secure — {host}")
        hist = view.history()
        self.act_back.setEnabled(hist.canGoBack())
        self.act_fwd.setEnabled(hist.canGoForward())
        view.setZoomFactor(self._zoom)

    def focus_address(self):
        self.address.setFocus()
        self.address.selectAll()

    def navigate(self):
        text = self.address.text().strip()
        if not text:
            return
        view = self.current_view()
        if view:
            view.setUrl(address_url(text))

    def open_url(self, url):
        view = self.current_view()
        if view:
            view.setUrl(QUrl(url))
        else:
            self.new_tab(url)

    def go_home(self):
        view = self.current_view()
        if view:
            view.setHtml(home_html(), QUrl("https://newtab.local/"))
            self.address.clear()
            self.omnibox.set_secure(False, "New tab")

    def reload_or_stop(self):
        view = self.current_view()
        if not view:
            return
        if self.act_reload.text() == "✕":
            view.stop()
        else:
            view.reload()

    # -- find / zoom / extras -----------------------------------------------

    def show_find(self):
        self.find_bar.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def hide_find(self):
        view = self.current_view()
        if view:
            view.findText("")
        self.find_bar.hide()

    def _find_text(self, text=None, forward=True):
        view = self.current_view()
        if not view:
            return
        text = self.find_input.text() if text is None else text
        flags = QWebEnginePage.FindFlags(0)
        if not forward:
            flags |= QWebEnginePage.FindBackward
        view.findText(text, flags)

    def adjust_zoom(self, delta: float):
        self.set_zoom(self._zoom + delta)

    def set_zoom(self, value: float):
        self._zoom = max(0.5, min(2.5, float(value)))
        view = self.current_view()
        if view:
            view.setZoomFactor(self._zoom)
        self.zoom_label.setText("%d%%" % int(round(self._zoom * 100)))

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def print_page(self):
        view = self.current_view()
        if not view:
            return
        try:
            from PyQt5.QtPrintSupport import QPrintDialog, QPrinter
            printer = QPrinter(QPrinter.HighResolution)
            dlg = QPrintDialog(printer, self)
            if dlg.exec_() == QPrintDialog.Accepted:
                view.page().print(printer, lambda _ok: None)
        except Exception:
            QMessageBox.information(self, "Print", "Printing is not available on this PC.")

    def copy_url(self):
        view = self.current_view()
        if not view:
            return
        QApplication.clipboard().setText(view.url().toDisplayString())
        self.statusBar().showMessage("Link copied", 1800)

    def open_downloads(self):
        folder = QStandardPaths.writableLocation(QStandardPaths.DownloadLocation)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def clear_recent(self):
        if QMessageBox.question(self, "Clear recent", "Clear recent history on this PC?") != QMessageBox.Yes:
            return
        try:
            if recent_path().is_file():
                recent_path().unlink()
        except OSError:
            pass

    def _fill_recent_menu(self, menu: QMenu):
        menu.clear()
        items = self.recent()[:12]
        if not items:
            act = menu.addAction("No recent pages")
            act.setEnabled(False)
            return
        for item in items:
            title = str(item.get("title") or item.get("url") or "Page")[:40]
            url = str(item.get("url") or "")
            menu.addAction(title, lambda _=False, u=url: self.open_url(u))

    def bookmark_current(self):
        view = self.current_view()
        if not view:
            return
        url = view.url()
        if url.scheme() not in ("http", "https") or not url.host():
            QMessageBox.information(self, "Bookmark", "Open a website first, then bookmark it.")
            return
        items = self.bookmarks()
        href = url.toString()
        if any(str(i.get("url")) == href for i in items):
            QMessageBox.information(self, "Bookmark", "This page is already bookmarked.")
            return
        items.insert(0, {"title": view.title() or url.host(), "url": href})
        self.save_bookmarks(items[:40])
        self.reload_bookmarks()
        self.statusBar().showMessage("Bookmarked", 1600)

    def open_private(self):
        import subprocess
        script = Path(__file__).resolve()
        subprocess.Popen([sys.executable, str(script), "--private"], start_new_session=True)

    def open_window(self):
        import subprocess
        script = Path(__file__).resolve()
        subprocess.Popen([sys.executable, str(script)], start_new_session=True)

    def download(self, item):
        path, _ = QFileDialog.getSaveFileName(self, "Save download", item.path())
        if path:
            item.setPath(path)
            item.accept()
            self.statusBar().showMessage("Downloading…", 2500)
        else:
            item.cancel()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", action="store_true")
    parser.add_argument("urls", nargs="*")
    args = parser.parse_args()
    prepare("devos-browser")
    app = QApplication([sys.argv[0]])
    apply(app, "devos-browser")
    font = QFont("Noto Sans")
    if not font.exactMatch():
        font = QFont("Segoe UI")
    font.setPixelSize(13)
    app.setFont(font)
    window = BrowserWindow(args.private)
    for url in args.urls or [None]:
        window.new_tab(url)
    show_window(window, "devos-browser")
    result = app.exec_()
    if not sip.isdeleted(window):
        sip.delete(window)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
