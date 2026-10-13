#!/usr/bin/env python3
"""
DevOS WinLayer Prefix Manager
Orchestrates isolated per-app Wine/Proton prefixes, reflink deduplication,
runtime DLL installations, and Windows-like desktop menu integration.
"""

import sys
import os
import re
import json
import shutil
import argparse
import subprocess
from typing import Dict, Any, List
from doctor import WinLayerDoctor


PREFIXES_ROOT = os.path.expanduser("~/.local/share/winlayer/prefixes")
DESKTOP_DIR = os.path.expanduser("~/.local/share/applications")
# Ready-made Windows environment copied for each new app (see prepare_prefix).
BASE_PREFIX = os.path.expanduser("~/.local/share/winlayer/base")


class WinLayerManager:
    """Manages isolated per-application Windows prefixes."""

    def __init__(self):
        os.makedirs(PREFIXES_ROOT, exist_ok=True)
        os.makedirs(DESKTOP_DIR, exist_ok=True)

    @staticmethod
    def sanitize_name(name: str) -> str:
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", name).lower()

    def get_prefix_dir(self, app_name: str) -> str:
        return os.path.join(PREFIXES_ROOT, self.sanitize_name(app_name))

    def launch(self, executable_path: str, app_name: str = None) -> Dict[str, Any]:
        """Runs a Windows executable inside its dedicated prefix with desktop integration."""
        abs_exe = os.path.abspath(os.path.expanduser(executable_path))
        if not os.path.exists(abs_exe):
            return {"status": "ERROR", "error": f"Executable '{abs_exe}' not found."}

        # 1. Analyze PE compatibility
        analysis = WinLayerDoctor.analyze_pe(abs_exe)
        if not analysis.get("is_pe", False):
            return {"status": "ERROR", "error": f"File '{abs_exe}' is not a valid Windows PE binary."}

        # 2. Derive App Name
        base_name = os.path.basename(abs_exe)
        app_id = app_name or os.path.splitext(base_name)[0]
        prefix_dir = self.get_prefix_dir(app_id)
        os.makedirs(prefix_dir, exist_ok=True)

        # 3. Start it under Wine. Earlier versions only wrote the menu entry
        # below and reported LAUNCHED, so no .exe ever ran.
        started = self.run_in_wine(abs_exe, prefix_dir, app_id)
        if started.get("status") != "STARTED":
            return started

        # 4. Create .desktop Start menu shortcut
        desktop_file = os.path.join(DESKTOP_DIR, f"winlayer-{self.sanitize_name(app_id)}.desktop")
        desktop_content = f"""[Desktop Entry]
Name={app_id} (Windows)
Exec=python3 "{os.path.abspath(__file__)}" launch "{abs_exe}"
Type=Application
Icon=application-x-msdownload
Categories=Utility;DevOS-Windows;
StartupNotify=true
Comment=Windows Application running via DevOS WinLayer
"""
        with open(desktop_file, "w") as f:
            f.write(desktop_content)

        return {
            "status": "LAUNCHED",
            "app_name": app_id,
            "prefix": prefix_dir,
            "executable": abs_exe,
            "compatibility": analysis.get("compatibility_rating"),
            "architecture": analysis.get("architecture"),
            "pid": started.get("pid"),
            "log": started.get("log"),
            "desktop_shortcut": desktop_file,
            "message": f"Windows app '{app_id}' launched in isolated prefix."
        }

    @staticmethod
    def wine_command(abs_exe: str) -> List[str]:
        """Command that opens the file the way Windows would."""
        ext = os.path.splitext(abs_exe)[1].lower()
        if ext == ".msi":
            return ["wine", "msiexec", "/i", abs_exe]
        if ext in (".bat", ".cmd"):
            return ["wine", "cmd", "/c", abs_exe]
        return ["wine", abs_exe]

    @staticmethod
    def wine_env(prefix_dir: str) -> Dict[str, str]:
        env = os.environ.copy()
        env["WINEPREFIX"] = prefix_dir
        # One 64-bit prefix runs both 32-bit (most installers, e.g. AnyDesk)
        # and 64-bit programs when wine32:i386 is installed.
        env["WINEARCH"] = "win64"
        env.setdefault("WINEDEBUG", "-all")
        # No Mono/Gecko download prompts on first start.
        env.setdefault("WINEDLLOVERRIDES", "mscoree,mshtml=")
        return env

    @staticmethod
    def is_prepared(prefix_dir: str) -> bool:
        return os.path.isfile(os.path.join(prefix_dir, "system.reg"))

    def prepare_prefix(self, prefix_dir: str) -> Dict[str, Any]:
        """Give a new app a ready Windows environment without any Wine window.

        Building one takes 20-60 s and Wine shows its own "configuration is
        being updated" box with its name and the folder path. DevOS builds a
        base once with no display (so no box appears) and copies it for each
        app; on btrfs the copy is a reflink and costs no space.
        """
        if self.is_prepared(prefix_dir):
            return {"status": "READY"}
        base = BASE_PREFIX
        if not self.is_prepared(base):
            os.makedirs(base, exist_ok=True)
            env = self.wine_env(base)
            env.pop("DISPLAY", None)
            env.pop("WAYLAND_DISPLAY", None)
            try:
                subprocess.run(["wineboot", "-u"], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=600)
                subprocess.run(["wineserver", "-w"], env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=120)
            except (OSError, subprocess.SubprocessError) as exc:
                return {"status": "ERROR", "error": f"Windows support could not be prepared: {exc}"}
            if not self.is_prepared(base):
                return {"status": "ERROR", "error": "Windows support could not be prepared."}
        if os.path.isdir(prefix_dir) and not os.listdir(prefix_dir):
            os.rmdir(prefix_dir)
        copy = subprocess.run(["cp", "-a", "--reflink=auto", base, prefix_dir],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if copy.returncode != 0:
            return {"status": "ERROR", "error": f"Windows support could not be prepared: {copy.stderr.strip()}"}
        return {"status": "READY"}

    def run_in_wine(self, abs_exe: str, prefix_dir: str, app_id: str) -> Dict[str, Any]:
        """Start the program detached so it keeps running after this CLI exits."""
        if shutil.which("wine") is None:
            return {
                "status": "ERROR",
                "error": "Windows support (Wine) is not installed on this system.",
            }
        prepared = self.prepare_prefix(prefix_dir)
        if prepared["status"] != "READY":
            return prepared
        log_dir = os.path.expanduser("~/.local/share/winlayer/logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{self.sanitize_name(app_id)}.log")
        env = self.wine_env(prefix_dir)
        try:
            with open(log_path, "ab") as log:
                proc = subprocess.Popen(
                    self.wine_command(abs_exe),
                    cwd=os.path.dirname(abs_exe),
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as exc:
            return {"status": "ERROR", "error": f"Could not start Wine: {exc}"}
        return {"status": "STARTED", "pid": proc.pid, "log": log_path}

    def list_prefixes(self) -> List[Dict[str, Any]]:
        """Lists all existing Windows app prefixes."""
        res = []
        if os.path.exists(PREFIXES_ROOT):
            for d in os.listdir(PREFIXES_ROOT):
                p = os.path.join(PREFIXES_ROOT, d)
                if os.path.isdir(p):
                    res.append({"name": d, "path": p})
        return res


def main():
    parser = argparse.ArgumentParser(description="DevOS WinLayer Manager")
    subparsers = parser.add_subparsers(dest="command")

    launch_p = subparsers.add_parser("launch", help="Launch a Windows binary")
    launch_p.add_argument("binary", help="Path to .exe / .msi")
    launch_p.add_argument("--name", help="Custom application name")

    subparsers.add_parser("list", help="List all installed Windows prefixes")

    doc_p = subparsers.add_parser("doctor", help="Inspect binary compatibility")
    doc_p.add_argument("binary", help="Path to .exe / .msi")

    args = parser.parse_args()
    mgr = WinLayerManager()

    if args.command == "launch":
        res = mgr.launch(args.binary, args.name)
        print(json.dumps(res, indent=2))
    elif args.command == "list":
        print(json.dumps(mgr.list_prefixes(), indent=2))
    elif args.command == "doctor":
        doc = WinLayerDoctor.analyze_pe(args.binary)
        print(json.dumps(doc, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
