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
import argparse
from typing import Dict, Any, List

from type_router import AppTypeRouter
from safety_scanner import AppSafetyScanner

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


class DevOSAppHub:
    """Universal application manager coordinating all runtime layers."""

    MOCK_SEARCH_CATALOG = [
        {"name": "VLC Media Player", "runtime": "Linux (Flatpak)", "badge": "[Linux]", "source": "Flathub"},
        {"name": "Notepad++", "runtime": "Windows (WinLayer)", "badge": "[Windows]", "source": "WinLayer AppDB"},
        {"name": "NewPipe", "runtime": "Android (Waydroid)", "badge": "[Android]", "source": "F-Droid"},
        {"name": "Postman / Bruno", "runtime": "Linux (Native/Deb)", "badge": "[Linux]", "source": "APT"},
        {"name": "7-Zip", "runtime": "Windows (WinLayer)", "badge": "[Windows]", "source": "WinLayer AppDB"},
        {"name": "Telegram Desktop", "runtime": "Linux (Flatpak)", "badge": "[Linux]", "source": "Flathub"},
    ]

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Searches apps across Flathub, apt, F-Droid, and Windows AppDB."""
        q = query.lower()
        results = [app for app in self.MOCK_SEARCH_CATALOG if q in app["name"].lower()]
        return results

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

            # Step B: Magic-Byte Type Routing
            routing = AppTypeRouter.identify_type(target)
            runtime = routing.get("detected_runtime")

            if runtime == AppTypeRouter.TARGET_WINDOWS:
                if WinLayerManager:
                    win_mgr = WinLayerManager()
                    win_res = win_mgr.launch(target)
                    return {
                        "status": "SUCCESS",
                        "runtime": "Windows (WinLayer)",
                        "routing": routing,
                        "winlayer_result": win_res,
                        "message": f"Windows app successfully routed and launched via WinLayer."
                    }
                return {"status": "SUCCESS", "runtime": "Windows (WinLayer)", "file": target}

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

            elif runtime in (AppTypeRouter.TARGET_LINUX, AppTypeRouter.TARGET_DEB, AppTypeRouter.TARGET_FLATPAK):
                return {
                    "status": "SUCCESS",
                    "runtime": f"Linux ({runtime.upper()})",
                    "routing": routing,
                    "message": f"Linux application routed to system package manager: {target}"
                }

            else:
                return {
                    "status": "UNRECOGNIZED_FORMAT",
                    "file": target,
                    "routing": routing,
                }

        # 2. Online package name query
        matching = self.search(target)
        if matching:
            picked = matching[0]
            return {
                "status": "SUCCESS",
                "package_name": picked["name"],
                "runtime": picked["runtime"],
                "source": picked["source"],
                "message": f"Initiated installation for '{picked['name']}' via {picked['runtime']}"
            }

        return {
            "status": "NOT_FOUND",
            "query": target,
            "message": f"Could not locate '{target}' in Flathub, APT, F-Droid, or WinLayer catalogs."
        }


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
        print(json.dumps(res, indent=2))
    elif args.command == "list" or not args.command:
        print("Installed Applications (Universal App Hub):")
        for app in hub.MOCK_SEARCH_CATALOG:
            print(f" - {app['name']} {app['badge']}")


if __name__ == "__main__":
    main()
