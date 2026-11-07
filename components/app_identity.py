"""Connect first-party Qt windows to their installed desktop name and icon."""
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
    metadata = desktop_metadata(desktop_id)
    # Task managers match on argv0 / WM_CLASS — never leave this as "python3".
    if desktop_id:
        sys.argv[0] = desktop_id
        os.environ["RESOURCE_NAME"] = (metadata[2] if metadata else desktop_id)
        try:
            QCoreApplication.setApplicationName(metadata[2] if metadata else desktop_id)
        except Exception:
            pass


def apply(app, desktop_id):
    from PyQt5.QtGui import QIcon

    desktop_id = (desktop_id or "").removesuffix(".desktop")
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
    icon = QIcon.fromTheme(icon_name)
    if icon.isNull():
        for root in (SOURCE_ROOT, Path("/"), Path("/usr/local/share/devos")):
            for relative in (
                "usr/share/icons/hicolor/256x256/apps/" + icon_name + ".png",
                "usr/share/icons/hicolor/scalable/apps/" + icon_name + ".svg",
                "icons/hicolor/scalable/apps/" + icon_name + ".svg",
            ):
                candidate = root / relative
                if candidate.is_file():
                    icon = QIcon(str(candidate))
                    break
            if not icon.isNull():
                break
    if not icon.isNull():
        app.setWindowIcon(icon)
