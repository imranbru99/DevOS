"""Install and open the pinned Windows App for Linux release for this user."""

import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

import browser_launch


RELEASE = "0.1.0"
URL = ("https://github.com/mariuszkopowski/windows-app-for-linux/releases/download/"
       f"v{RELEASE}/Windows.App-{RELEASE}-x86_64.flatpak")
SHA256 = "19a2e3151558b368eeb35eac0fd0ed0e6469adf94f47d1461a7d1204f323af5f"
APP_ID = "io.github.mariuszkopowski.WindowsAppForLinux"
FLATHUB = "https://dl.flathub.org/repo/flathub.flatpakrepo"


def verified(path):
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == SHA256
    except OSError:
        return False


def install(flatpak):
    with tempfile.TemporaryDirectory(prefix="devos-windows-app-") as scratch:
        download = Path(scratch) / "windows-app.flatpak"
        subprocess.run([
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--proto", "=https", "--proto-redir", "=https", "--max-time", "300",
            "--max-filesize", "125829120", "--output", str(download), URL,
        ], check=True)
        if not verified(download):
            raise ValueError("The Windows App download failed its SHA-256 check.")
        subprocess.run([flatpak, "remote-add", "--user", "--if-not-exists", "flathub", FLATHUB],
                       check=True)
        subprocess.run([flatpak, "install", "--user", "--noninteractive", "--assumeyes",
                        "--bundle", str(download)], check=True)


def open_microsoft_windows_app():
    """Open Microsoft's Windows App (Cloud PC) as an app window, not a Chrome tab."""
    try:
        browser_launch.open_isolated()
        return 0
    except OSError as exc:
        print(f"Windows App could not start: {exc}", file=sys.stderr)
        browser_launch._notify(str(exc))
        # Last resort only — Cloud PC may open in a normal tab.
        return subprocess.run(["xdg-open", browser_launch.URL]).returncode


def main():
    explicit = sys.argv[1:] in (["--install-client"], ["--native-client"])
    flatpak = shutil.which("flatpak")
    # Official path for the Start-menu "Windows App" entry is always the
    # Microsoft web client (PWA). Flatpak is opt-in via --install-client.
    if not explicit:
        return open_microsoft_windows_app()
    if platform.machine() != "x86_64" or not os.environ.get("WAYLAND_DISPLAY") or not flatpak:
        print("This Windows App package requires x86-64, Flatpak, and a Wayland session.", file=sys.stderr)
        return 1
    installed = subprocess.run([flatpak, "info", "--user", APP_ID],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if installed.returncode != 0:
        try:
            install(flatpak)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Windows App client installation failed: {exc}", file=sys.stderr)
            return 1
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
