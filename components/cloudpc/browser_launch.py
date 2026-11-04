"""Run the official Windows App in a persistent, separate browser process."""
import os
from pathlib import Path
import shutil
import subprocess

URL = 'https://windows.cloud.microsoft/'


def browser_binary():
    # Prefer a separately installed Edge; never reuse the everyday Chrome profile.
    candidates = (
        ('edge', '/opt/microsoft/msedge/msedge'),
        ('edge', shutil.which('microsoft-edge-stable')),
        ('edge', shutil.which('microsoft-edge')),
        ('chrome', '/opt/google/chrome/chrome'),
        ('chrome', shutil.which('google-chrome-stable')),
        ('chrome', shutil.which('google-chrome')),
        ('chromium', shutil.which('chromium')),
    )
    for family, candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return family, str(candidate)
    raise OSError('Install Microsoft Edge or Google Chrome to open Windows App.')


def launch_command():
    family, binary = browser_binary()
    base = Path(os.environ.get('XDG_DATA_HOME', Path.home()/'.local/share'))
    profile = base/'devos/windows-app'/family
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)
    return [
        binary,
        f'--user-data-dir={profile}',
        '--profile-directory=Default',
        '--no-first-run',
        '--no-default-browser-check',
        '--class=chrome-windows.cloud.microsoft__-Default',
        '--enable-features=PointerLockOptions,KeyboardLock,OverlayScrollbar',
        '--enable-gpu-rasterization',
        '--enable-zero-copy',
        '--ozone-platform-hint=auto',
        f'--app={URL}',
    ]


def open_isolated():
    state = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'devos'
    state.mkdir(parents=True, exist_ok=True)
    fd = os.open(state/'windows-app-browser.log', os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'a') as log:
        return subprocess.Popen(launch_command(), stdin=subprocess.DEVNULL, stdout=log,
                                stderr=log, start_new_session=True)


if __name__ == '__main__':
    open_isolated()
