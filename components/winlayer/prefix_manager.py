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

    def launch(self, executable_path: str, app_name: str = None, force: bool = False) -> Dict[str, Any]:
        """Runs a Windows executable inside its dedicated prefix with desktop integration."""
        abs_exe = os.path.abspath(os.path.expanduser(executable_path))
        if not os.path.exists(abs_exe):
            return {"status": "ERROR", "error": f"Executable '{abs_exe}' not found."}

        # 1. Analyze PE compatibility
        analysis = WinLayerDoctor.analyze_pe(abs_exe)
        if not analysis.get("is_pe", False):
            return {"status": "ERROR", "error": f"File '{abs_exe}' is not a valid Windows PE binary."}
        if analysis.get("anti_cheat_flagged") and not force:
            return {
                "status": "USE_VM",
                "compatibility": analysis.get("compatibility_rating"),
                "recommendation": analysis.get("recommendation"),
                "native_alternative": analysis.get("native_alternative"),
                "message": analysis.get("recommendation"),
            }

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
        overrides = ["mscoree,mshtml="]
        marker = os.path.join(prefix_dir, "devos-graphics.json")
        if os.path.isfile(marker):
            try:
                with open(marker, encoding="utf-8") as handle:
                    graphics = json.load(handle)
            except (OSError, ValueError):
                graphics = {}
            if graphics.get("dxvk"):
                overrides.append("d3d9,d3d10core,d3d11,dxgi=n")
            if graphics.get("vkd3d"):
                overrides.append("d3d12=n")
        env["WINEDLLOVERRIDES"] = ";".join(overrides)
        return env

    @staticmethod
    def dxvk_dirs():
        pairs = (
            ("/usr/lib/dxvk/x64", "/usr/lib/dxvk/x32"),
            ("/usr/share/dxvk/x64", "/usr/share/dxvk/x32"),
            ("/usr/lib/dxvk", "/usr/lib/dxvk"),
        )
        for x64, x32 in pairs:
            if os.path.isdir(x64):
                return x64, x32 if os.path.isdir(x32) else ""
        return "", ""

    def install_graphics(self, prefix_dir: str) -> Dict[str, Any]:
        """Copy DXVK DLLs into a prefix when the distro package is installed."""
        system32 = os.path.join(prefix_dir, "drive_c", "windows", "system32")
        syswow = os.path.join(prefix_dir, "drive_c", "windows", "syswow64")
        x64, x32 = self.dxvk_dirs()
        copied = []
        for source, dest in ((x64, system32), (x32, syswow)):
            if not source or not os.path.isdir(dest):
                continue
            for name in ("d3d11.dll", "d3d10core.dll", "d3d9.dll", "dxgi.dll"):
                src = os.path.join(source, name)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(dest, name))
                    copied.append(name)
        marker = {
            "dxvk": bool(copied),
            "vkd3d": False,
            "dlls": sorted(set(copied)),
        }
        try:
            with open(os.path.join(prefix_dir, "devos-graphics.json"), "w", encoding="utf-8") as handle:
                json.dump(marker, handle)
        except OSError:
            pass
        return marker

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
            self.install_graphics(prefix_dir)
            return {"status": "READY"}
        base = BASE_PREFIX
        if self.is_prepared(base) and not os.path.isfile(os.path.join(base, "devos-graphics.json")):
            self.install_graphics(base)
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
            self.install_graphics(base)
        if os.path.isdir(prefix_dir) and not os.listdir(prefix_dir):
            os.rmdir(prefix_dir)
        copy = subprocess.run(["cp", "-a", "--reflink=auto", base, prefix_dir],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if copy.returncode != 0:
            return {"status": "ERROR", "error": f"Windows support could not be prepared: {copy.stderr.strip()}"}
        if not os.path.isfile(os.path.join(prefix_dir, "devos-graphics.json")):
            self.install_graphics(prefix_dir)
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

    def apply_tweaks(self, executable_path: str, kind: str = "dotnet") -> Dict[str, Any]:
        """Install a Windows runtime into this app's prefix. Needs network for winetricks."""
        if kind != "dotnet":
            return {"status": "ERROR", "error": "Only the dotnet tweak is available."}
        if shutil.which("winetricks") is None:
            return {"status": "NEEDS_PACKAGE", "message": "winetricks is not installed."}
        abs_exe = os.path.abspath(os.path.expanduser(executable_path))
        app_id = os.path.splitext(os.path.basename(abs_exe))[0]
        prefix_dir = self.get_prefix_dir(app_id)
        prepared = self.prepare_prefix(prefix_dir)
        if prepared.get("status") != "READY":
            return prepared
        env = self.wine_env(prefix_dir)
        try:
            proc = subprocess.run(["winetricks", "-q", "dotnet48"], env=env, capture_output=True,
                                  text=True, timeout=1800)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"status": "FAILED", "error": str(exc)}
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "winetricks failed").strip()[-400:]
            return {"status": "FAILED", "error": tail}
        return {"status": "READY", "prefix": prefix_dir,
                "message": ".NET Framework 4.8 was added to this app's Windows prefix."}

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
    launch_p.add_argument("--force", action="store_true",
                          help="Start anyway when kernel anti-cheat was detected")

    subparsers.add_parser("list", help="List all installed Windows prefixes")

    vm_p = subparsers.add_parser("vm", help="Windows virtual PC (bring your own ISO)")
    vm_p.add_argument("vm_command", nargs="?", default="status", choices=["status", "create", "start"])
    vm_p.add_argument("--iso", default="")
    vm_p.add_argument("--disk-gb", type=int, default=64)
    vm_p.add_argument("--memory", type=int, default=4096)
    vm_p.add_argument("--no-start", action="store_true")

    tweak_p = subparsers.add_parser("tweaks", help="Add a Windows runtime inside a prefix")
    tweak_p.add_argument("kind", choices=["dotnet"])
    tweak_p.add_argument("binary", help="The .exe whose prefix should be updated")

    doc_p = subparsers.add_parser("doctor", help="Inspect binary compatibility")
    doc_p.add_argument("binary", help="Path to .exe / .msi")

    args = parser.parse_args()
    mgr = WinLayerManager()

    if args.command == "launch":
        res = mgr.launch(args.binary, args.name, force=args.force)
        print(json.dumps(res, indent=2))
    elif args.command == "list":
        print(json.dumps(mgr.list_prefixes(), indent=2))
    elif args.command == "doctor":
        doc = WinLayerDoctor.analyze_pe(args.binary)
        print(json.dumps(doc, indent=2))
    elif args.command == "tweaks":
        res = mgr.apply_tweaks(args.binary, args.kind)
        print(json.dumps(res, indent=2))
    elif args.command == "vm":
        from vm_fallback import WindowsVM, status as vm_status
        vm = WindowsVM()
        if args.vm_command == "create":
            res = vm.create(args.iso, args.disk_gb, args.memory, start=not args.no_start)
        elif args.vm_command == "start":
            res = vm.start(args.iso, args.memory)
        else:
            res = vm_status()
        print(json.dumps(res, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
