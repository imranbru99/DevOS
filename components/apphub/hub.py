#!/usr/bin/env python3
"""
DevOS Universal App Hub (apphub)
Single unified CLI & backend for Windows, Linux, and Android applications.
Commands:
  devos app search <query>
  devos app install <name | file | url>
  devos app list
  devos app info <target>
"""

import sys
import os
import json
import shutil
import argparse
import subprocess
from typing import Any, Callable, Dict, List, Optional

from type_router import AppTypeRouter
from safety_scanner import AppSafetyScanner

FEATURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../features"))
LINUX_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../linuxlayer"))
if FEATURES_DIR not in sys.path:
    sys.path.insert(0, FEATURES_DIR)
if LINUX_DIR not in sys.path:
    sys.path.insert(0, LINUX_DIR)
try:
    from feature_catalog import FEATURES, feature as feature_by_id
except ImportError:
    FEATURES = []
    feature_by_id = lambda _fid: None
try:
    from runner import launch as launch_linux
except ImportError:
    launch_linux = None

# Path to winlayer
SYS_PATH_WIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "../winlayer"))
sys.path.insert(0, SYS_PATH_WIN)
try:
    from prefix_manager import WinLayerManager
except ImportError:
    WinLayerManager = None

SYS_PATH_ANDROID = os.path.abspath(os.path.join(os.path.dirname(__file__), "../androidlayer"))
sys.path.insert(0, SYS_PATH_ANDROID)
try:
    from waydroid_manager import WaydroidManager
except ImportError:
    WaydroidManager = None


def parse_apt_search(text: str) -> List[Dict[str, Any]]:
    """`apt-cache search` lines: `name - description`."""
    results = []
    for line in (text or "").splitlines():
        if " - " not in line:
            continue
        name, desc = line.split(" - ", 1)
        name = name.strip()
        if not name or " " in name:
            continue
        results.append({
            "name": name,
            "description": desc.strip(),
            "runtime": "Linux (apt)",
            "badge": "[Linux]",
            "source": "APT",
            "install": name,
            "kind": "apt",
        })
    return results


def parse_flatpak_search(text: str) -> List[Dict[str, Any]]:
    """`flatpak search --columns=name,application` tab-separated rows."""
    results = []
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name, appid = parts[0].strip(), parts[1].strip()
        if not appid or "." not in appid or " " in appid:
            continue
        results.append({
            "name": name or appid,
            "description": appid,
            "runtime": "Linux (Flatpak)",
            "badge": "[Linux]",
            "source": "Flathub",
            "install": appid,
            "kind": "flatpak",
        })
    return results


def search_features(query: str) -> List[Dict[str, Any]]:
    needle = (query or "").strip().lower()
    if not needle:
        return []
    hits = []
    for item in FEATURES:
        blob = " ".join([
            item.get("id") or "", item.get("name") or "", item.get("about") or "",
            item.get("windows") or "",
        ]).lower()
        if needle in blob:
            hits.append({
                "name": item["name"],
                "description": item.get("about") or "",
                "runtime": "DevOS Features",
                "badge": "[DevOS]",
                "source": "Features",
                "install": item["id"],
                "kind": "feature",
            })
    return hits


class DevOSAppHub:
    """Universal application manager coordinating all runtime layers."""

    def __init__(self, runner: Optional[Callable] = None, euid: Optional[int] = None):
        self.runner = runner or self._default_run
        fn = getattr(os, "geteuid", None)
        self._euid = (fn() if fn else 0) if euid is None else euid

    @staticmethod
    def _default_run(argv: List[str], timeout: int = 1800):
        if not argv or (argv[0] != sys.executable and shutil.which(argv[0]) is None):
            return 127, "", "not installed"
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except (OSError, subprocess.SubprocessError) as exc:
            return 127, "", str(exc)

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Search DevOS Features, apt and Flathub. No built-in fake catalog."""
        results = search_features(query)
        code, out, _err = self.runner(["apt-cache", "search", "--names-only", query])
        if code == 0:
            results.extend(parse_apt_search(out))
        code, out, _err = self.runner(
            ["flatpak", "search", "--columns=name,application", query])
        if code == 0:
            results.extend(parse_flatpak_search(out))
        return results

    def _install_feature(self, item: Dict[str, Any]) -> Dict[str, Any]:
        cli = os.path.join(FEATURES_DIR, "features_cli.py")
        if item.get("apt") and self._euid != 0:
            return {
                "status": "NEEDS_ROOT",
                "package_name": item["name"],
                "runtime": "DevOS Features",
                "command": ["pkexec", sys.executable, cli, "set", "--add", item["id"]],
                "message": f"Installing {item['name']} needs an administrator password.",
            }
        code, out, err = self.runner([sys.executable, cli, "set", "--add", item["id"]])
        if code != 0:
            return {"status": "FAILED", "package_name": item["name"],
                    "error": (err or out or "DevOS Features could not install it.").strip()}
        return {"status": "SUCCESS", "package_name": item["name"], "runtime": "DevOS Features",
                "source": "Features", "message": f"Installed {item['name']}."}

    def _install_named(self, target: str) -> Dict[str, Any]:
        query = target.strip()
        chosen = feature_by_id(query)
        if chosen is None:
            for item in FEATURES:
                if item["name"].lower() == query.lower():
                    chosen = item
                    break
        if chosen is not None:
            return self._install_feature(chosen)
        matches = self.search(query)
        exact = [hit for hit in matches
                  if hit.get("install", "").lower() == query.lower() or hit["name"].lower() == query.lower()]
        if len(exact) == 1:
            pick = exact[0]
        elif len(matches) == 1:
            pick = matches[0]
        elif matches:
            return {
                "status": "AMBIGUOUS",
                "matches": [{"name": h["name"], "source": h["source"], "install": h.get("install")}
                            for h in matches[:15]],
                "message": "Several apps match. Install one by its exact package name or feature id.",
            }
        else:
            return {
                "status": "NOT_FOUND",
                "query": query,
                "message": f"Could not find '{query}' in DevOS Features, apt or Flathub. "
                           "Microsoft Store and UWP apps do not run on DevOS.",
            }
        if pick.get("kind") == "feature":
            item = feature_by_id(pick["install"])
            if item:
                return self._install_feature(item)
        if pick.get("kind") == "flatpak":
            code, out, err = self.runner(
                ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", pick["install"]])
            if code != 0:
                return {"status": "FAILED", "error": (err or out or "Flatpak install failed.").strip(),
                        "package_name": pick["name"]}
            return {"status": "SUCCESS", "package_name": pick["name"], "runtime": pick["runtime"],
                    "source": "Flathub", "message": f"Installed {pick['name']}."}
        if self._euid != 0:
            return {
                "status": "NEEDS_ROOT",
                "package_name": pick["name"],
                "command": ["pkexec", "apt-get", "install", "-y", "--no-install-recommends", pick["install"]],
                "message": f"Installing {pick['name']} needs an administrator password.",
            }
        code, out, err = self.runner(
            ["apt-get", "install", "-y", "--no-install-recommends", pick["install"]])
        if code != 0:
            return {"status": "FAILED", "error": (err or out or "apt install failed.").strip(),
                    "package_name": pick["name"]}
        return {"status": "SUCCESS", "package_name": pick["name"], "runtime": "Linux (apt)",
                "source": "APT", "message": f"Installed {pick['name']}."}

    def install(self, target: str, skip_safety: bool = False) -> Dict[str, Any]:
        """Installs or routes an application based on type and safety."""
        # 1. Check if target is a local file
        if os.path.exists(target):
            # Step A: Pre-execution Safety Scan
            scan = AppSafetyScanner.scan_file(target)
            if not scan.get("safe_to_run", True) and not skip_safety:
                return {
                    "status": "BLOCKED_BY_SAFETY_SCAN",
                    "file": target,
                    "reason": scan.get("ai_summary"),
                    "details": scan,
                }
            if scan.get("blocked"):
                # Found by ClamAV (and quarantined) or inside the quarantine:
                # --skip-safety does not override this.
                return {
                    "status": "BLOCKED_BY_SAFETY_SCAN",
                    "file": target,
                    "reason": scan.get("ai_summary"),
                    "details": scan,
                }
            if scan.get("needs_confirmation") and not skip_safety:
                # The antivirus could not check this Windows/Android app: the
                # caller asks the person, then calls again with --skip-safety.
                return {
                    "status": "NEEDS_CONFIRMATION",
                    "file": target,
                    "reason": scan.get("ai_summary"),
                    "details": scan,
                }

            # Step B: Magic-Byte Type Routing
            routing = AppTypeRouter.identify_type(target)
            runtime = routing.get("detected_runtime")

            if runtime == AppTypeRouter.TARGET_WINDOWS:
                if not WinLayerManager:
                    return {"status": "NEEDS_ENGINE", "runtime": "Windows (WinLayer)", "file": target,
                            "message": "Windows support is not available on this system."}
                win_res = WinLayerManager().launch(target)
                win_res["runtime"] = "Windows (WinLayer)"
                win_res["routing"] = routing
                if win_res.get("status") != "LAUNCHED":
                    return win_res
                win_res["message"] = "Windows app launched."
                return win_res

            elif runtime == AppTypeRouter.TARGET_ANDROID:
                if WaydroidManager:
                    result = WaydroidManager().install_apk(target)
                    result["runtime"] = "Android (Waydroid)"
                    result["routing"] = routing
                    return result
                return {
                    "status": "NEEDS_ENGINE",
                    "runtime": "Android (Waydroid)",
                    "routing": routing,
                    "message": "Android routing is present, but the Waydroid engine is not available.",
                }

            elif runtime == AppTypeRouter.TARGET_DEB:
                if self._euid != 0:
                    return {
                        "status": "NEEDS_ROOT",
                        "runtime": "Linux (apt)",
                        "routing": routing,
                        "command": ["pkexec", "apt-get", "install", "-y", target],
                        "message": "Installing a .deb package needs an administrator password.",
                    }
                code, out, err = self.runner(["apt-get", "install", "-y", target])
                if code != 0:
                    return {"status": "FAILED", "error": (err or out or "apt could not install the package.").strip(),
                            "routing": routing}
                return {"status": "SUCCESS", "runtime": "Linux (apt)", "routing": routing,
                        "message": "Package installed."}

            elif runtime == AppTypeRouter.TARGET_FLATPAK:
                code, out, err = self.runner(
                    ["flatpak", "install", "--user", "-y", "--noninteractive", target])
                if code != 0:
                    return {"status": "FAILED", "error": (err or out or "Flatpak could not install the file.").strip(),
                            "routing": routing}
                return {"status": "SUCCESS", "runtime": "Linux (Flatpak)", "routing": routing,
                        "message": "Flatpak installed."}

            elif runtime == AppTypeRouter.TARGET_LINUX:
                if not launch_linux:
                    return {"status": "NEEDS_ENGINE", "routing": routing,
                            "message": "Linux program launch is not available."}
                started = launch_linux(target)
                started["routing"] = routing
                return started

            else:
                return {
                    "status": "UNRECOGNIZED_FORMAT",
                    "file": target,
                    "routing": routing,
                }

        return self._install_named(target)

    def list_installed(self) -> List[Dict[str, Any]]:
        code, out, _err = self.runner(["flatpak", "list", "--app", "--columns=name,application"])
        if code != 0:
            return []
        return parse_flatpak_search(out)


def main():
    parser = argparse.ArgumentParser(description="DevOS Universal App Hub")
    subparsers = parser.add_subparsers(dest="command")

    search_p = subparsers.add_parser("search", help="Search across all app ecosystems")
    search_p.add_argument("query", help="App name or keyword")

    install_p = subparsers.add_parser("install", help="Install a package, file, or URL")
    install_p.add_argument("target", help="File (.exe, .apk, .deb, etc.) or app name")
    install_p.add_argument("--skip-safety", action="store_true", help="Bypass safety scan (caution)")

    subparsers.add_parser("list", help="List installed universal apps")

    args = parser.parse_args()
    hub = DevOSAppHub()

    if args.command == "search":
        res = hub.search(args.query)
        print(f"{'APPLICATION':<25} {'RUNTIME BADGE':<15} {'SOURCE':<15}")
        print("-" * 55)
        for r in res:
            print(f"{r['name']:<25} {r['badge']:<15} {r['source']:<15}")
    elif args.command == "install":
        res = hub.install(args.target, skip_safety=args.skip_safety)
        if res.get("status") == "NEEDS_ROOT" and res.get("command") and shutil.which("pkexec") \
                and os.environ.get("DEVOS_NO_PKEXEC") != "1":
            os.execvp("pkexec", res["command"])
        print(json.dumps(res, indent=2))
    elif args.command == "list" or not args.command:
        installed = hub.list_installed()
        if not installed:
            print("No Flatpak apps installed yet. Search with: devos app search <name>")
        for app in installed:
            print(f" - {app['name']}  {app.get('install', '')}")


if __name__ == "__main__":
    main()
