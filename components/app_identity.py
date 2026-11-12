"""Connect first-party Qt windows to their installed desktop name and icon.

Also guarantees system title-bar min / max / close and a size that fits the
current screen (laptops, 1080p, 4K, small panels).
"""
import configparser
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parent.parent / 'build/includes.chroot'


def desktop_metadata(desktop_id):
    if not desktop_id or '/' in desktop_id or '..' in desktop_id:
        return None
    for root in (SOURCE_ROOT, Path('/')):
        path = root / 'usr/share/applications' / (desktop_id.removesuffix('.desktop') + '.desktop')
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding='utf-8')
            entry = parser['Desktop Entry']
            return entry.get('Name', desktop_id), entry.get('Icon', 'devos-logo'), entry.get('StartupWMClass', desktop_id)
        except (OSError, KeyError, configparser.Error):
            continue
    return None


def prepare(desktop_id):
    """Set X11/Wayland resource identity before QApplication creates native resources."""
    import os
    import sys
    from PyQt5.QtCore import QCoreApplication

    desktop_id = (desktop_id or "").removesuffix(".desktop")
    # Allow wrappers to pass identity when the script forgot to call prepare().
    if not desktop_id:
        desktop_id = (os.environ.get("DEVOS_DESKTOP_FILE") or "").removesuffix(".desktop")
    metadata = desktop_metadata(desktop_id)
    wm_class = (metadata[2] if metadata else desktop_id) or desktop_id
    display_name = (metadata[0] if metadata else desktop_id) or desktop_id
    # Task managers match on argv0 / WM_CLASS — never leave this as "python3".
    if desktop_id:
        if sys.argv:
            sys.argv[0] = desktop_id
        else:
            sys.argv = [desktop_id]
        os.environ["RESOURCE_NAME"] = wm_class
        os.environ["DEVOS_DESKTOP_FILE"] = desktop_id
        # Wayland app id → desktop file match (Plasma 6).
        os.environ.setdefault("QT_WAYLAND_FORCE_DPI", os.environ.get("QT_WAYLAND_FORCE_DPI", ""))
        os.environ["QT_WAYLAND_APP_ID"] = desktop_id
        try:
            QCoreApplication.setApplicationName(wm_class)
            QCoreApplication.setOrganizationName("DevOS")
            QCoreApplication.setOrganizationDomain("devos")
            QCoreApplication.setApplicationVersion("1")
        except Exception:
            pass
        # Hint for scripts that read display name before QApplication.
        os.environ.setdefault("DEVOS_APP_NAME", display_name)


def resolve_icon(icon_name):
    """Load a theme or hicolor icon by name; never return a null QIcon if a file exists."""
    from PyQt5.QtGui import QIcon

    icon = QIcon.fromTheme(icon_name)
    if not icon.isNull():
        return icon
    for root in (SOURCE_ROOT, Path("/"), Path("/usr/local/share/devos")):
        for relative in (
            "usr/share/icons/hicolor/256x256/apps/" + icon_name + ".png",
            "usr/share/icons/hicolor/128x128/apps/" + icon_name + ".png",
            "usr/share/icons/hicolor/48x48/apps/" + icon_name + ".png",
            "usr/share/icons/hicolor/scalable/apps/" + icon_name + ".svg",
            "icons/hicolor/scalable/apps/" + icon_name + ".svg",
            "usr/share/pixmaps/" + icon_name + ".png",
        ):
            candidate = root / relative
            if candidate.is_file():
                return QIcon(str(candidate))
    return icon


def _qt():
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication, QDesktopWidget
        return Qt, QApplication, QDesktopWidget
    except ImportError:  # pragma: no cover
        from PyQt6.QtCore import Qt  # type: ignore
        from PyQt6.QtWidgets import QApplication, QDesktopWidget  # type: ignore
        return Qt, QApplication, QDesktopWidget


def available_screen_rect(window=None):
    """Usable desktop area (excludes panels) for the screen that owns window."""
    Qt, QApplication, QDesktopWidget = _qt()
    app = QApplication.instance()
    if app is None:
        return None
    # Qt5 screen API
    try:
        from PyQt5.QtGui import QGuiApplication
        screen = None
        if window is not None:
            handle = window.windowHandle() if hasattr(window, "windowHandle") else None
            if handle is not None and handle.screen() is not None:
                screen = handle.screen()
            elif hasattr(window, "frameGeometry"):
                center = window.frameGeometry().center()
                screen = QGuiApplication.screenAt(center)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            return screen.availableGeometry()
    except Exception:
        pass
    try:
        desk = QDesktopWidget()
        i = desk.screenNumber(window) if window is not None else desk.primaryScreen()
        return desk.availableGeometry(i)
    except Exception:
        return None


def decorate_window(window, *, allow_frameless=False):
    """Force system title-bar min / max / close on top-level DevOS windows.

    Plain QWidget windows sometimes omit button hints; maximized windows also
    lost buttons when KWin BorderlessMaximizedWindows was enabled.
    """
    Qt, _QApplication, _Desk = _qt()
    current = window.windowFlags()
    # Intentional overlays (clipboard popups, voice HUD, etc.) stay frameless.
    if allow_frameless or (
        current & (Qt.Tool | Qt.ToolTip | Qt.Popup | Qt.SplashScreen)
        and not (current & Qt.Window)
    ):
        return
    # Main app windows: never keep Frameless — that removes close/min/max.
    flags = (
        Qt.Window
        | Qt.WindowTitleHint
        | Qt.WindowSystemMenuHint
        | Qt.WindowMinMaxButtonsHint
        | Qt.WindowCloseButtonHint
    )
    if current != flags:
        window.setWindowFlags(flags)


def fit_to_screen(window, *, margin=24, max_ratio=0.92, min_width=480, min_height=320):
    """Clamp and place the window so it fits any laptop / monitor / HiDPI screen.

    Uses availableGeometry (screen minus panels). Restored maximized geometries
    that spilled under panels or hid the title bar are pulled back into view.
    """
    Qt, QApplication, _Desk = _qt()
    rect = available_screen_rect(window)
    if rect is None or not rect.isValid():
        return

    # Prefer a normal (decorated) window over borderless-maximized chrome loss.
    if window.isFullScreen():
        window.showNormal()
    if window.isMaximized():
        # Keep maximize if the user wants it, but ensure decorations stay
        # (KWin BorderlessMaximizedWindows must be false — apply-desktop enforces).
        frame = window.frameGeometry() if hasattr(window, "frameGeometry") else window.geometry()
        if frame.width() > rect.width() + 8 or frame.height() > rect.height() + 8:
            window.showNormal()

    geo = window.geometry()
    max_w = max(min_width, int(rect.width() * max_ratio))
    max_h = max(min_height, int(rect.height() * max_ratio))
    w = min(max(geo.width(), min_width), max_w, rect.width() - margin * 2)
    h = min(max(geo.height(), min_height), max_h, rect.height() - margin * 2)
    if w < min_width:
        w = min(min_width, rect.width() - margin * 2)
    if h < min_height:
        h = min(min_height, rect.height() - margin * 2)

    x = geo.x()
    y = geo.y()
    # Center when off-screen or wildly oversized restore.
    if x < rect.x() or y < rect.y() or x + w > rect.right() or y + h > rect.bottom():
        x = rect.x() + max(margin, (rect.width() - w) // 2)
        y = rect.y() + max(margin, (rect.height() - h) // 2)
    x = min(max(x, rect.x() + margin), rect.right() - w - margin)
    y = min(max(y, rect.y() + margin), rect.bottom() - h - margin)
    # QWidget rejects a resize below its current minimum. Lower the minimum
    # first so a window designed for a tall display can actually shrink.
    window.setMinimumSize(min(min_width, w), min(min_height, h))
    window.setGeometry(x, y, w, h)


def apply(app, desktop_id):
    desktop_id = (desktop_id or "").removesuffix(".desktop")
    # Every DevOS app gets live dark/light palette + stylesheet adaptation.
    try:
        from devos_appearance import install as install_appearance
        install_appearance(app)
    except Exception:
        pass
    metadata = desktop_metadata(desktop_id)
    if metadata is None:
        # Still bind the desktop file id so Plasma can find the .desktop entry.
        if desktop_id:
            app.setApplicationName(desktop_id)
            app.setDesktopFileName(desktop_id)
        return
    name, icon_name, wm_class = metadata
    app.setApplicationName(wm_class)
    app.setApplicationDisplayName(name)
    app.setDesktopFileName(desktop_id if desktop_id.endswith(".desktop") else desktop_id + ".desktop")
    # Also accept bare id (Qt6 prefers without .desktop on some builds).
    try:
        app.setDesktopFileName(desktop_id)
    except Exception:
        pass
    icon = resolve_icon(icon_name)
    if not icon.isNull():
        app.setWindowIcon(icon)


def show_window(window, desktop_id=None, *, fit=True, allow_frameless=False):
    """Apply chrome + branded icon + screen fit, then show.

    Use instead of bare window.show() for every main DevOS window so close /
    minimize / maximize always appear and the window fits the device screen.
    """
    decorate_window(window, allow_frameless=allow_frameless)
    if desktop_id:
        metadata = desktop_metadata(desktop_id)
        if metadata:
            _name, icon_name, _wm = metadata
            icon = resolve_icon(icon_name)
            if not icon.isNull():
                window.setWindowIcon(icon)
            if not window.windowTitle():
                window.setWindowTitle(_name)
    # setWindowFlags can hide a previously shown window — always show after.
    window.show()
    if fit and not allow_frameless:
        fit_to_screen(window)
        # Re-show after geometry clamp so WMs apply decorations on the new size.
        window.show()
    window.raise_()
    window.activateWindow()
