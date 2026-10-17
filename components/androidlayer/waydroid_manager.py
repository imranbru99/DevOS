#!/usr/bin/env python3
"""
DevOS Android Layer (Waydroid Manager)
Manages Waydroid container lifecycle, multi-window Wayland integration,
APK installations, shared folders (~/Android), and adb developer debugging.
"""

import sys
import os
import shutil
import json
import argparse
import subprocess
import time
from typing import Dict, Any, List


SHARED_FOLDER = os.path.expanduser("~/Android")
# Written by "waydroid init" once the Android system image is downloaded.
WAYDROID_IMAGES = "/var/lib/waydroid/images/system.img"
WAYDROID_CONFIG = "/var/lib/waydroid/waydroid.cfg"
# Wayland socket of the Weston window that hosts Android on the X11 desktop.
WESTON_SOCKET = "devos-android"


def rename_android_window(title: str = "DevOS Android") -> bool:
    """The hosting window is titled "Weston Compositor - screen0"; show DevOS instead."""
    if not shutil.which("xdotool"):
        return False
    for _ in range(25):
        found = subprocess.run(["xdotool", "search", "--name", "^Weston Compositor"],
                               capture_output=True, text=True).stdout.split()
        if found:
            for window in found:
                subprocess.run(["xdotool", "set_window", "--name", title,
                                "--classname", "devos-android", window], capture_output=True)
            return True
        time.sleep(0.2)
    return False


def parse_status(text: str) -> Dict[str, str]:
    """Session and container state from `waydroid status` output."""
    state = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in ("session", "container"):
            state[key] = value.strip().upper()
    return state


def parse_download_progress(line: str):
    """(done_mb, total_mb) from a waydroid download line, e.g.
    "[Downloading]   312.45 MB/795.32 MB    4.61 MB/s    00:01:44 ETA"."""
    import re
    match = re.search(r"([\d.]+)\s*MB\s*/\s*([\d.]+)\s*MB", line)
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError:
        return None


class WaydroidManager:
    """Controls the local Android LXC container and desktop bridging."""

    def __init__(self):
        os.makedirs(SHARED_FOLDER, exist_ok=True)

    def get_status(self) -> Dict[str, Any]:
        """Returns container and Waydroid session state."""
        has_waydroid = shutil.which("waydroid") is not None
        has_adb = shutil.which("adb") is not None

        return {
            "waydroid_installed": has_waydroid,
            "session_mode": "Wayland window (Weston when the desktop is X11)",
            "shared_folder": SHARED_FOLDER,
            "adb_debugging": "enabled" if has_adb else "adb available in dev profile",
            "stores_included": [],
            "fdroid": "devos android fdroid",
            "play_services": "devos android setup-play (only before the first Android download)",
            "google_play_bundled": False,
            "status": "READY" if has_waydroid else "CONTAINER_ENGINE_CONFIGURED",
            "message": "Android runs in a window after the system image is downloaded."
        }

    @staticmethod
    def is_initialized() -> bool:
        """True once the Android system image has been downloaded."""
        return os.path.exists(WAYDROID_IMAGES) or os.path.exists(WAYDROID_CONFIG)

    @staticmethod
    def init_images(progress=None, argv=None) -> Dict[str, Any]:
        """One-time download of the Android system (~800 MB). Asks for the admin password.

        progress(percent, text) is called while waydroid prints its download
        lines, so the window can show a real percentage instead of a spinner.
        """
        waydroid = shutil.which("waydroid")
        if not waydroid:
            return {"status": "NEEDS_ENGINE", "message": "Android support is not installed on this system."}
        # The Android system needs ~850 MB plus room to unpack. On the live USB
        # the writable space is RAM and the download failed at 99%.
        free = shutil.disk_usage("/var/lib" if os.path.isdir("/var/lib") else "/").free
        if free < 2.5 * 1024 ** 3:
            live = "boot=casper" in open("/proc/cmdline").read() if os.path.exists("/proc/cmdline") else False
            return {
                "status": "ERROR",
                "error": ("Android apps work after DevOS is installed on the disk."
                          if live else
                          f"Android needs about 2.5 GB of free space; only {free / 1024 ** 3:.1f} GB is free. "
                          "Use DevOS Optimizer to clean up and try again."),
            }
        # One password prompt: download, graphics mode and service start (the
        # helper switches to software rendering where the GPU cannot be used,
        # otherwise the Android window stayed black).
        helper = "/usr/local/sbin/devos-android-init"
        if argv:
            cmd = list(argv)
        elif os.path.isfile(helper):
            cmd = [helper]
        else:
            cmd = [waydroid, "init"]
        euid = os.geteuid() if hasattr(os, "geteuid") else 0
        if euid != 0 and cmd[0] != "pkexec":
            cmd = ["pkexec"] + cmd
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = bytearray()
        line = bytearray()
        part = 0
        last_total = None
        while True:
            chunk = proc.stdout.read(1)
            if not chunk:
                break
            output += chunk
            if chunk not in (b"\r", b"\n"):
                line += chunk
                continue
            parsed = parse_download_progress(line.decode("utf-8", "replace"))
            line.clear()
            if parsed and progress:
                done, total = parsed
                # waydroid downloads the system image, then the vendor image.
                if last_total is not None and abs(total - last_total) > 1:
                    part += 1
                last_total = total
                label = "Android system" if part == 0 else "Android drivers"
                progress(int(done * 100 / total) if total else 0,
                         f"Downloading {label}: {done:.0f} of {total:.0f} MB")
        proc.wait()
        if proc.returncode != 0 or not WaydroidManager.is_initialized():
            tail = output.decode("utf-8", "replace").replace("\r", "\n").strip().splitlines()[-3:]
            return {
                "status": "ERROR",
                "error": "Android download did not finish. Check the internet connection and try again.",
                "details": tail,
            }
        return {"status": "READY", "message": "Android is ready."}

    @staticmethod
    def wayland_env() -> Dict[str, str]:
        """Environment with a Wayland display for Waydroid.

        Plasma Wayland already has one. On the X11 desktop Waydroid needs a
        Wayland compositor, so DevOS opens Android inside a Weston window.
        """
        env = os.environ.copy()
        if env.get("WAYLAND_DISPLAY"):
            return env
        runtime = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        socket_path = os.path.join(runtime, WESTON_SOCKET)
        if not os.path.exists(socket_path) and shutil.which("weston"):
            subprocess.Popen(
                ["weston", "--backend=x11-backend.so", f"--socket={WESTON_SOCKET}",
                 "--width=1280", "--height=800", "--shell=kiosk-shell.so"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            for _ in range(50):
                if os.path.exists(socket_path):
                    break
                time.sleep(0.2)
            rename_android_window()
        env["WAYLAND_DISPLAY"] = WESTON_SOCKET
        env["XDG_SESSION_TYPE"] = "wayland"
        return env

    def ensure_session(self, timeout: int = 240) -> Dict[str, Any]:
        """Start Android and wait until it has fully booted.

        "Session: RUNNING" alone is not enough: with the container stopped
        (e.g. after the service restarted) app installs "succeeded" while no
        Android was running and the window stayed black. Ready means both
        are RUNNING and the package list answers (boot completed).
        """
        waydroid = shutil.which("waydroid")
        env = self.wayland_env()
        state = self.status()
        if state.get("session") == "RUNNING" and state.get("container") != "RUNNING":
            subprocess.run([waydroid, "session", "stop"], env=env, capture_output=True, timeout=60)
            state = {}
        if state.get("session") != "RUNNING":
            subprocess.Popen([waydroid, "session", "start"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.session_running() and self.installed_packages(env):
                return {"status": "RUNNING", "env": env}
            time.sleep(3)
        return {"status": "ERROR", "error": "Android did not start in time. Try again in a moment."}

    @staticmethod
    def status() -> Dict[str, str]:
        """{"session": "RUNNING"|"STOPPED", "container": ...} from `waydroid status`."""
        try:
            out = subprocess.run(["waydroid", "status"], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        return parse_status(out)

    @classmethod
    def session_running(cls) -> bool:
        state = cls.status()
        return state.get("session") == "RUNNING" and state.get("container") == "RUNNING"

    @staticmethod
    def installed_packages(env: Dict[str, str] = None) -> List[str]:
        try:
            out = subprocess.run(["waydroid", "app", "list"], capture_output=True, text=True,
                                 timeout=30, env=env).stdout
        except (OSError, subprocess.SubprocessError):
            return []
        return [line.split(":", 1)[1].strip() for line in out.splitlines()
                if line.strip().lower().startswith("packagename:")]

    def install_apk(self, apk_path: str, launch: bool = True) -> Dict[str, Any]:
        """Installs an APK into the Android session and opens it."""
        abs_apk = os.path.abspath(os.path.expanduser(apk_path))
        if not os.path.exists(abs_apk):
            return {"status": "ERROR", "error": f"APK '{abs_apk}' not found."}

        waydroid = shutil.which("waydroid")
        if not waydroid:
            return {
                "status": "NEEDS_ENGINE",
                "apk": abs_apk,
                "message": "Android support is not installed on this system.",
            }
        if not self.is_initialized():
            return {
                "status": "NEEDS_INIT",
                "apk": abs_apk,
                "message": "Android needs a one-time download (about 800 MB) before apps can be installed.",
            }

        session = self.ensure_session()
        if session["status"] != "RUNNING":
            return {"status": "ERROR", "apk": abs_apk, "error": session["error"]}
        env = session["env"]

        before = set(self.installed_packages(env))
        proc = subprocess.run([waydroid, "app", "install", abs_apk], env=env,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return {
                "status": "ERROR",
                "apk": abs_apk,
                "error": "Android could not install this app. It may need a newer Android or Google Play services.",
                "details": (proc.stdout + proc.stderr).strip().splitlines()[-3:],
            }
        new = [p for p in self.installed_packages(env) if p not in before]
        package = new[0] if new else None
        if launch:
            target = [waydroid, "app", "launch", package] if package else [waydroid, "show-full-ui"]
            subprocess.Popen(target, env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)

        return {
            "status": "SUCCESS",
            "apk": abs_apk,
            "package": package,
            "integration": "Multi-window desktop entry added to the application menu",
            "shared_storage": SHARED_FOLDER,
            "message": f"Installed Android app '{os.path.basename(abs_apk)}' into DevOS Android.",
        }

    def setup(self) -> Dict[str, Any]:
        """Download the Android system once (Waydroid ships in the image)."""
        if not shutil.which("waydroid"):
            return {
                "status": "NEEDS_ENGINE",
                "message": "Android support is not installed on this system.",
            }
        if self.is_initialized():
            return {"status": "READY", "message": "Android is ready. Open any .apk file to install it."}
        return self.init_images()

    def setup_play(self) -> Dict[str, Any]:
        """Download the Android image that includes Google Play. Only before first setup."""
        if self.is_initialized():
            return {
                "status": "ALREADY_SET_UP",
                "message": "Android is already downloaded without Play Services. "
                           "Remove Android in DevOS Features and run devos android setup-play before opening an APK.",
            }
        helper = "/usr/local/sbin/devos-android-init"
        if not os.path.isfile(helper):
            return {"status": "NEEDS_ENGINE", "message": "Android setup is not installed on this system."}
        return self.init_images(argv=[helper, "gapps"])

    def install_fdroid(self) -> Dict[str, Any]:
        """Download the official F-Droid client and install it into Android."""
        if not self.is_initialized():
            return {"status": "NEEDS_SETUP", "message": "Download Android first, then install F-Droid."}
        dest = os.path.join(os.path.expanduser("~/.local/share/devos"), "F-Droid.apk")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        try:
            proc = subprocess.run(
                ["curl", "-fL", "--retry", "3", "-o", dest, "https://f-droid.org/F-Droid.apk"],
                capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAILED", "error": str(exc)}
        if proc.returncode != 0 or not os.path.isfile(dest) or os.path.getsize(dest) < 100000:
            return {"status": "FAILED", "error": (proc.stderr or "F-Droid download did not finish.").strip()[-400:]}
        return self.install_apk(dest, launch=True)


def main():
    parser = argparse.ArgumentParser(description="DevOS Waydroid Android Manager")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Get Waydroid status")
    subparsers.add_parser("setup", help="Check the Android engine and print the next step")
    subparsers.add_parser("setup-play", help="Download Android with Google Play (before the first setup)")
    subparsers.add_parser("fdroid", help="Install the F-Droid app store")
    inst_p = subparsers.add_parser("install", help="Install an APK")
    inst_p.add_argument("apk", help="Path to .apk file")

    args = parser.parse_args()
    mgr = WaydroidManager()

    if args.command == "install":
        res = mgr.install_apk(args.apk)
        print(json.dumps(res, indent=2))
    elif args.command == "setup":
        print(json.dumps(mgr.setup(), indent=2))
    elif args.command == "setup-play":
        print(json.dumps(mgr.setup_play(), indent=2))
    elif args.command == "fdroid":
        print(json.dumps(mgr.install_fdroid(), indent=2))
    elif args.command == "status" or not args.command:
        print(json.dumps(mgr.get_status(), indent=2))


if __name__ == "__main__":
    main()
