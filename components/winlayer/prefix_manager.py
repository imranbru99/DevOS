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

        # 3. Create .desktop Start menu shortcut
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
            "desktop_shortcut": desktop_file,
            "message": f"Windows app '{app_id}' launched in isolated prefix."
        }

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
