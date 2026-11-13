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


def open_browser():
    return subprocess.run(["xdg-open", browser_launch.URL]).returncode


def main():
    explicit = sys.argv[1:] == ["--install-client"]
    flatpak = shutil.which("flatpak")
    if platform.machine() != "x86_64" or not os.environ.get("WAYLAND_DISPLAY") or not flatpak:
        if explicit:
            print("This Windows App package requires x86-64, Flatpak, and a Wayland session.", file=sys.stderr)
            return 1
        return open_browser()
    installed = subprocess.run([flatpak, "info", "--user", APP_ID],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if installed.returncode != 0:
        if not explicit:
            dialog = shutil.which("kdialog")
            if not dialog or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
                return open_browser()
            result = subprocess.run([
                dialog, "--title", "Windows App", "--yesno",
                "Install the unofficial Windows App for Linux client from GitHub? "
                "The app and its Flatpak runtime will be installed for your account. "
                "This release uses a runtime that no longer receives security updates. "
                "Choose Open browser to use Microsoft's web client.",
                "--yes-label", "Install client", "--no-label", "Open browser",
            ])
            if result.returncode != 0:
                return open_browser()
        try:
            install(flatpak)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            print(f"Windows App client installation failed: {exc}", file=sys.stderr)
            if not explicit:
                browser_launch._notify(
                    "The Linux client could not be installed. Opening the browser instead.")
                return open_browser()
            return 1
    if explicit:
        return 0
    try:
        status = subprocess.run([flatpak, "run", "--user", APP_ID]).returncode
        if status == 0:
            return 0
        print(f"Windows App client exited with status {status}.", file=sys.stderr)
    except OSError as exc:
        print(f"Windows App client could not start: {exc}", file=sys.stderr)
    browser_launch._notify("The Linux client could not run. Opening the browser instead.")
    return open_browser()


if __name__ == "__main__":
    raise SystemExit(main())
