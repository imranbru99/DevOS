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
    """Set X11 resource identity before QApplication creates native resources."""
    import os
    from PyQt5.QtCore import QCoreApplication
    metadata = desktop_metadata(desktop_id)
    if metadata:
        os.environ['RESOURCE_NAME'] = metadata[2]
        QCoreApplication.setApplicationName(metadata[2])


def apply(app, desktop_id):
    from PyQt5.QtGui import QIcon
    metadata = desktop_metadata(desktop_id)
    if metadata is None:
        return
    name, icon_name, wm_class = metadata
    app.setApplicationName(wm_class)
    app.setApplicationDisplayName(name)
    app.setDesktopFileName(desktop_id)
    icon = QIcon.fromTheme(icon_name)
    if icon.isNull():
        for root in (SOURCE_ROOT, Path('/')):
            for relative in ('usr/share/icons/hicolor/256x256/apps/' + icon_name + '.png',
                             'usr/share/icons/hicolor/scalable/apps/' + icon_name + '.svg'):
                candidate = root / relative
                if candidate.is_file():
                    icon = QIcon(str(candidate))
                    break
            if not icon.isNull():
                break
    if not icon.isNull():
        app.setWindowIcon(icon)
