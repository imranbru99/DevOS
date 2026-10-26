"""Route existing Windows App shortcuts through the reminder companion."""
import os
from pathlib import Path
import re
import tempfile


def integrate(directory):
    directory = Path(directory)
    if not directory.is_dir():
        return 0
    changed = 0
    for path in directory.glob('chrome-*-Default.desktop'):
        match = re.fullmatch(r'chrome-([a-p]{32})-Default\.desktop', path.name)
        if not match or path.is_symlink():
            continue
        try:
            info = path.stat()
            if info.st_uid != os.getuid() or info.st_size > 65536:
                continue
            text = path.read_text()
            lines = text.splitlines()
            start = lines.index('[Desktop Entry]') + 1
            end = next((i for i in range(start, len(lines)) if lines[i].startswith('[')), len(lines))
            values = dict(line.split('=', 1) for line in lines[start:end] if '=' in line and not line.startswith('#'))
            if values.get('Name', '').lower() != 'windows app':
                continue
            if values.get('X-DevOS-Cloud-Companion') == 'true':
                continue
            if '--app-id=' + match[1] not in values.get('Exec', ''):
                continue
            body = [line for line in lines[start:end] if not line.startswith(('Exec=', 'NoDisplay=', 'X-DevOS-Cloud-Companion='))]
            body += ['Exec=/usr/local/bin/devos-windows-app', 'NoDisplay=true', 'X-DevOS-Cloud-Companion=true']
            fd, temporary = tempfile.mkstemp(prefix='.devos-cloudpc-', dir=directory)
            try:
                with os.fdopen(fd, 'w') as handle:
                    handle.write('\n'.join(lines[:start] + body + lines[end:]) + '\n')
                os.chmod(temporary, info.st_mode & 0o777)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary): os.unlink(temporary)
            changed += 1
        except (OSError, UnicodeError, ValueError):
            continue
    return changed


def restore_companion(directory, system_entry=Path('/usr/local/share/applications/devos-web-winapp.desktop')):
    """Remove only our historical hidden stub when the companion is enabled."""
    path = Path(directory)/'devos-web-winapp.desktop'
    try:
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            return False
        if 'Exec=/usr/local/bin/devos-windows-app\n' not in Path(system_entry).read_text():
            return False
        if path.read_text().strip() != '[Desktop Entry]\nType=Application\nHidden=true\nX-DevOS-Hidden=true':
            return False
        path.unlink()
        return True
    except OSError:
        return False


if __name__ == '__main__':
    directory = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))/'applications'
    entry = Path('/usr/local/share/applications/devos-web-winapp.desktop')
    try:
        enabled = 'Exec=/usr/local/bin/devos-windows-app\n' in entry.read_text()
    except OSError:
        enabled = False
    if enabled:
        restore_companion(directory)
        integrate(directory)
