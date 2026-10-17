#!/usr/bin/env python3
"""
DevOS app window: shows one of DevOS's own local web tools (Dashboard, chat, ...)
in a native window instead of a browser tab.

    devos-webapp --app-id dashboard --title "DevOS Dashboard" \
        --icon preferences-system --url http://127.0.0.1:7070/#storage \
        [--width 1280 --height 820] [--start-cmd "python3 .../dashboard_server.py --no-browser"]

* Own title, icon and WM_CLASS ("DevOS-<app-id>"), so the taskbar shows the DevOS app.
* Dark background from the first frame, no white flash.
* Persistent profile per app in ~/.local/share/DevOS/webapps/<app-id>.
* One window per app-id: a second launch raises it (and opens the new URL).
* Links that leave 127.0.0.1/localhost open in the default browser.
* Downloads ask where to save, starting in ~/Downloads.
* Ctrl+R / F5 reload, Ctrl+W / Esc close. Inspect only with --debug.
* If the page does not answer, a DevOS "not running" page with Retry; Retry also
  (re)starts the backing server when --start-cmd is given.
* Without QtWebEngine (python3-pyqt5.qtwebengine) it falls back to a Chrome app window.

The helpers above the Qt section have no Qt dependency and are unit tested.
"""

import argparse
import html
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
from typing import List, Optional
from urllib.parse import urlparse

APP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
BACKGROUND = "#0b0f1a"
RETRY_TITLE = "devos-webapp:retry"  # the offline page sets this title to ask for a retry
CHROME_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")


# ---------------------------------------------------------------------------
# Pure helpers (tested without Qt)
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="devos-webapp", description="Open a DevOS web tool in its own window.")
    p.add_argument("--app-id", required=True, help="Short id, e.g. dashboard (a-z, 0-9, - and _)")
    p.add_argument("--url", required=True, help="Local page to show, e.g. http://127.0.0.1:7070/")
    p.add_argument("--title", default="", help="Window title")
    p.add_argument("--icon", default="", help="Icon theme name or path to an image")
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=820)
    p.add_argument("--start-cmd", default="", help="Command that starts the page's server (used by Retry)")
    p.add_argument("--desktop-file", default="", help="Desktop entry id (default devos-<app-id>)")
    p.add_argument("--debug", action="store_true", help="Enable Inspect in the right-click menu")
    args = p.parse_args(argv)
    if not APP_ID_RE.match(args.app_id):
        p.error("--app-id must be lowercase letters, digits, - or _")
    if url_policy(args.url) != "internal":
        p.error("--url must be a page on this computer (127.0.0.1 or localhost)")
    args.width = max(480, min(args.width, 7680))
    args.height = max(360, min(args.height, 4320))
    if not args.title:
        args.title = "DevOS " + args.app_id.replace("-", " ").replace("_", " ").title()
    if not args.desktop_file:
        args.desktop_file = f"devos-{args.app_id}"
    return args


def url_policy(url: str) -> str:
    """'internal' (show in the window), 'external' (default browser) or 'block'."""
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return "block"
    scheme = (parsed.scheme or "").lower()
    if scheme in ("about", "data", "blob"):
        return "internal"
    if scheme in ("http", "https", "ws", "wss"):
        try:
            host = (parsed.hostname or "").lower()
        except ValueError:
            return "block"
        if host in LOCAL_HOSTS:
            return "internal"
        return "external" if scheme in ("http", "https") and host else "block"
    if scheme in ("mailto", "tel"):
        return "external"
    # file:, javascript:, chrome:, unknown schemes: never navigate there.
    return "block"


def wm_class(app_id: str) -> str:
    return f"DevOS-{app_id}"


def instance_name(app_id: str, uid: Optional[int] = None) -> str:
    """QLocalServer name; per user so two accounts never talk to each other's window."""
    if uid is None:
        uid = os.getuid() if hasattr(os, "getuid") else 0
    return f"devos-webapp-{uid}-{app_id}"


def profile_dir(app_id: str, home: Optional[str] = None) -> str:
    home = home or os.path.expanduser("~")
    return os.path.join(home, ".local", "share", "DevOS", "webapps", app_id)


def downloads_dir(home: Optional[str] = None) -> str:
    home = home or os.path.expanduser("~")
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2)
        path = out.stdout.strip()
        if out.returncode == 0 and path and path != home and os.path.isdir(path):
            return path
    except Exception:
        pass
    return os.path.join(home, "Downloads")


def fallback_command(url: str, app_id: str, home: Optional[str] = None, which=shutil.which) -> List[str]:
    """Chrome app window used when QtWebEngine is not installed."""
    browser = next((c for c in CHROME_CANDIDATES if which(c)), None)
    if browser is None:
        return ["xdg-open", url]
    data_dir = profile_dir(app_id, home) + "-chrome"
    return [browser, f"--app={url}", f"--class={wm_class(app_id)}", f"--user-data-dir={data_dir}",
            "--no-first-run", "--no-default-browser-check"]


def host_port(url: str):
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname or "127.0.0.1", port


def port_open(url: str, timeout: float = 0.3) -> bool:
    host, port = host_port(url)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def start_backend(start_cmd: str) -> bool:
    """Starts the page's server in the background, detached from this window."""
    if not start_cmd:
        return False
    try:
        argv = shlex.split(start_cmd)
        log = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "devos-webapp-backend.log")
        with open(log, "ab") as fh:
            subprocess.Popen(argv, stdout=fh, stderr=fh, stdin=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


def offline_html(title: str, url: str, starting: bool = False) -> str:
    t = html.escape(title)
    u = html.escape(url)
    if starting:
        head, text, button = "Starting…", f"{t} is starting. This takes a moment.", ""
    else:
        head = f"{t} is not running"
        text = "Nothing is answering at this address yet. Press Retry to start it again."
        button = f'<button id="retry" onclick="document.title=\'{RETRY_TITLE}\'">Retry</button>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>{t}</title><style>
html,body{{margin:0;height:100%;background:{BACKGROUND};color:#e2e8f0;
font-family:Inter,"Noto Sans","Liberation Sans",sans-serif}}
.wrap{{height:100%;display:flex;align-items:center;justify-content:center}}
.card{{max-width:460px;padding:36px 40px;border-radius:20px;text-align:center;
background:linear-gradient(160deg,rgba(30,41,59,.72),rgba(15,23,42,.72));
border:1px solid rgba(148,163,184,.16);box-shadow:0 24px 60px rgba(0,0,0,.45)}}
.mark{{width:56px;height:56px;margin:0 auto 18px;border-radius:16px;
background:linear-gradient(135deg,#00f2fe,#4facfe);display:flex;align-items:center;justify-content:center;
font-weight:800;color:#041018;font-size:22px}}
h1{{font-size:20px;margin:0 0 10px}} p{{color:#94a3b8;line-height:1.5;margin:0 0 6px}}
code{{color:#7dd3fc;font-size:12px}}
button{{margin-top:22px;border:0;border-radius:12px;padding:12px 30px;font:inherit;font-weight:700;
color:#041018;background:linear-gradient(135deg,#00f2fe,#4facfe);cursor:pointer}}
button:hover{{filter:brightness(1.08)}}
</style></head><body><div class="wrap"><div class="card"><div class="mark">D</div>
<h1>{head}</h1><p>{text}</p><p><code>{u}</code></p>{button}</div></div></body></html>"""


def launch_fallback(args) -> int:
    if not port_open(args.url):
        start_backend(args.start_cmd)
    cmd = fallback_command(args.url, args.app_id)
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        print(f"devos-webapp: cannot open {args.url}: {exc}", file=sys.stderr)
        return 1
    return 0


# ---------------------------------------------------------------------------
# Qt window
# ---------------------------------------------------------------------------

def run_qt(args) -> int:
    wmc = wm_class(args.app_id)
    # WM_CLASS = (res_name, res_class). Qt takes res_name from RESOURCE_NAME and
    # res_class from the application name; both are DevOS-<app-id>.
    os.environ["RESOURCE_NAME"] = wmc

    from PyQt5.QtCore import Qt, QUrl, QSettings, QTimer, QCoreApplication, QByteArray
    from PyQt5.QtGui import QIcon, QColor, QPalette, QKeySequence, QDesktopServices
    from PyQt5.QtWidgets import QApplication, QMainWindow, QMenu, QShortcut, QFileDialog
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket
    from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage, QWebEngineProfile

    QCoreApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    QCoreApplication.setApplicationName(wmc)
    QCoreApplication.setOrganizationName("DevOS")
    app = QApplication([sys.argv[0]])
    app.setApplicationDisplayName(args.title)
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName(args.desktop_file)

    # ---- single instance -------------------------------------------------
    name = instance_name(args.app_id)
    sock = QLocalSocket()
    sock.connectToServer(name)
    if sock.waitForConnected(400):
        sock.write(json.dumps({"url": args.url}).encode("utf-8") + b"\n")
        sock.flush()
        sock.waitForBytesWritten(800)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    server.listen(name)

    # ---- profile -----------------------------------------------------------
    pdir = profile_dir(args.app_id)
    os.makedirs(pdir, exist_ok=True)
    profile = QWebEngineProfile(args.app_id, app)
    profile.setPersistentStoragePath(os.path.join(pdir, "storage"))
    profile.setCachePath(os.path.join(pdir, "cache"))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
    profile.setHttpUserAgent(profile.httpUserAgent() + " DevOS-WebApp/1.0")

    if args.icon and os.path.exists(args.icon):
        icon = QIcon(args.icon)
    else:
        icon = QIcon.fromTheme(args.icon or "applications-internet")
    app.setWindowIcon(icon)

    def open_external(qurl):
        try:
            subprocess.Popen(["xdg-open", qurl.toString()], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            QDesktopServices.openUrl(qurl)

    class Page(QWebEnginePage):
        def __init__(self, prof, window):
            super().__init__(prof, window)
            self.window_ref = window

        def acceptNavigationRequest(self, qurl, nav_type, is_main_frame):
            target = qurl.toString()
            policy = url_policy(target)
            if policy == "internal":
                return True
            if policy == "external" and nav_type != QWebEnginePage.NavigationTypeRedirect:
                open_external(qurl)
            return False

        def createWindow(self, _type):
            # target=_blank / window.open: route through a throwaway page.
            tmp = QWebEnginePage(self.profile(), self)

            def route(qurl):
                if url_policy(qurl.toString()) == "internal":
                    self.window_ref.view.setUrl(qurl)
                elif url_policy(qurl.toString()) == "external":
                    open_external(qurl)
                tmp.deleteLater()
            tmp.urlChanged.connect(route)
            return tmp

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle(args.title)
            self.setWindowIcon(icon)
            pal = self.palette()
            pal.setColor(QPalette.Window, QColor(BACKGROUND))
            self.setPalette(pal)
            self.setAutoFillBackground(True)
            self.setStyleSheet(f"QMainWindow{{background:{BACKGROUND};}}")

            self.url = args.url
            self.offline = False
            self.auto_started = False
            self.poll_left = 0
            self.devtools = None

            self.view = QWebEngineView(self)
            self.view.setStyleSheet(f"background:{BACKGROUND};")
            self.page = Page(profile, self)
            self.page.setBackgroundColor(QColor(BACKGROUND))
            self.view.setPage(self.page)
            self.view.setContextMenuPolicy(Qt.CustomContextMenu)
            self.view.customContextMenuRequested.connect(self.context_menu)
            self.page.loadFinished.connect(self.load_finished)
            self.page.titleChanged.connect(self.title_changed)
            self.setCentralWidget(self.view)

            for seq in ("Ctrl+R", "F5"):
                QShortcut(QKeySequence(seq), self, activated=self.reload)
            for seq in ("Ctrl+W", "Esc"):
                QShortcut(QKeySequence(seq), self, activated=self.close)
            if args.debug:
                QShortcut(QKeySequence("F12"), self, activated=self.inspect)

            self.settings = QSettings(os.path.join(pdir, "window.ini"), QSettings.IniFormat)
            geo = self.settings.value("geometry")
            if isinstance(geo, QByteArray) and not geo.isEmpty():
                self.restoreGeometry(geo)
            else:
                self.resize(args.width, args.height)

            self.poll = QTimer(self)
            self.poll.setInterval(300)
            self.poll.timeout.connect(self.poll_backend)
            self.view.setUrl(QUrl(self.url))

        def title_changed(self, title):
            if title == RETRY_TITLE and self.offline:
                QTimer.singleShot(0, self.retry)

        # -- loading / offline ---------------------------------------------
        def load_finished(self, ok):
            if ok or self.offline:
                return
            if port_open(self.url):
                return  # aborted navigation, server is fine
            if args.start_cmd and not self.auto_started:
                self.auto_started = True
                self.retry()
                return
            self.show_offline()

        def show_offline(self, starting=False):
            self.offline = True
            self.page.setHtml(offline_html(args.title, self.url, starting), QUrl("about:blank"))

        def retry(self):
            if port_open(self.url):
                self.load(self.url)
                return
            if args.start_cmd:
                start_backend(args.start_cmd)
                self.show_offline(starting=True)
                self.poll_left = 34  # ~10 s
                self.poll.start()
            else:
                self.show_offline()

        def poll_backend(self):
            self.poll_left -= 1
            if port_open(self.url):
                self.poll.stop()
                self.load(self.url)
            elif self.poll_left <= 0:
                self.poll.stop()
                self.show_offline()

        def load(self, url):
            self.offline = False
            self.url = url
            self.view.setUrl(QUrl(url))

        def reload(self):
            if self.offline:
                self.retry()
            else:
                self.view.reload()

        # -- menu ----------------------------------------------------------
        def context_menu(self, pos):
            menu = QMenu(self)
            data = self.page.contextMenuData() if hasattr(self.page, "contextMenuData") else None
            editable = bool(data and data.isContentEditable())
            if editable:
                menu.addAction(self.page.action(QWebEnginePage.Cut))
            if self.page.hasSelection() or editable:
                menu.addAction(self.page.action(QWebEnginePage.Copy))
            if editable:
                menu.addAction(self.page.action(QWebEnginePage.Paste))
            if menu.actions():
                menu.addSeparator()
            menu.addAction("Reload", self.reload)
            if args.debug:
                menu.addAction("Inspect", self.inspect)
            menu.exec_(self.view.mapToGlobal(pos))

        def inspect(self):
            if self.devtools is None:
                self.devtools = QWebEngineView()
                self.devtools.setWindowTitle(f"{args.title} — Inspect")
                self.page.setDevToolsPage(self.devtools.page())
                self.devtools.resize(1000, 700)
            self.devtools.show()
            self.devtools.raise_()

        # -- single instance -------------------------------------------------
        def raise_window(self, url=None):
            if url and url_policy(url) == "internal" and url != self.url:
                self.load(url)
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()

        def closeEvent(self, event):
            self.settings.setValue("geometry", self.saveGeometry())
            self.settings.sync()
            if self.devtools is not None:
                self.devtools.close()
            super().closeEvent(event)

    win = Window()

    def on_connection():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            raw = bytes(conn.readAll()).decode("utf-8", "replace").strip()
            url = None
            try:
                url = json.loads(raw.splitlines()[0]).get("url") if raw else None
            except Exception:
                url = None
            win.raise_window(url)
            conn.disconnectFromServer()
        conn.readyRead.connect(read)
        if conn.bytesAvailable():
            read()
    server.newConnection.connect(on_connection)

    def on_download(item):
        suggested = os.path.basename(item.path()) if hasattr(item, "path") else "download"
        if hasattr(item, "downloadFileName"):
            suggested = item.downloadFileName() or suggested
        ddir = downloads_dir()
        os.makedirs(ddir, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(win, "Save download", os.path.join(ddir, suggested))
        if not path:
            item.cancel()
            return
        if hasattr(item, "setDownloadDirectory"):
            item.setDownloadDirectory(os.path.dirname(path))
            item.setDownloadFileName(os.path.basename(path))
        else:
            item.setPath(path)
        item.accept()
    profile.downloadRequested.connect(on_download)

    win.show()
    rc = app.exec_()
    server.close()
    return rc


def webengine_available() -> bool:
    try:
        import PyQt5.QtWebEngineWidgets  # noqa: F401
        return True
    except Exception:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if os.environ.get("DEVOS_WEBAPP_FORCE_FALLBACK") == "1" or not webengine_available():
        return launch_fallback(args)
    return run_qt(args)


if __name__ == "__main__":
    sys.exit(main())
