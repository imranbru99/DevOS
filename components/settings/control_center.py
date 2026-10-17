#!/usr/bin/env python3
"""
DevOS Control Center
Unified settings manager for Display, Network, AI Core, Universal Apps,
Developer Tools, and System Snapshots.
"""

import sys
import os
import json
import argparse
from typing import Dict, Any


class DevOSControlCenter:
    """Core settings and control coordinator for DevOS."""

    CONFIG_FILE = os.path.expanduser("~/.config/devos/settings.json")

    DEFAULT_SETTINGS = {
        "appearance": {
            "theme": "dark",
            "taskbar_align": "center",
            "accent_color": "#3b82f6",
            "scaling": 1.0,
            "font_family": "Inter",
        },
        "network": {
            "wifi_enabled": True,
            "firewall_ufw": True,
            "hostname": "devos",
        },
        "ai": {
            "enabled": True,
            "tier": "auto",
            "endpoint": "http://127.0.0.1:11434/v1",
            "auto_unload_timeout_sec": 300,
            "speech_whisper_enabled": False,
        },
        "developer": {
            "devserver_auto_start": True,
            "default_php_version": "8.3",
            "default_node_version": "20-lts",
            "container_runtime": "podman",
        },
        "compatibility": {
            "winlayer_wine_enabled": True,
            "androidlayer_waydroid_enabled": True,
            "flatpak_flathub_enabled": True,
        },
        "backup": {
            "btrfs_snapshots_enabled": True,
            "keep_last_snapshots": 10,
        }
    }

    def __init__(self):
        os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)
        self.settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    # Merge with defaults
                    merged = self.DEFAULT_SETTINGS.copy()
                    merged.update(data)
                    return merged
            except Exception:
                pass
        return self.DEFAULT_SETTINGS.copy()

    def save_settings(self):
        with open(self.CONFIG_FILE, "w") as f:
            json.dump(self.settings, f, indent=2)

    def set_value(self, section: str, key: str, value: Any) -> bool:
        if section in self.settings and key in self.settings[section]:
            self.settings[section][key] = value
            self.save_settings()
            return True
        return False

    def get_summary(self) -> Dict[str, Any]:
        return {
            "version": "DevOS 24.04 LTS",
            "desktop": "DevOS",
            "settings": self.settings,
        }


def main():
    parser = argparse.ArgumentParser(description="DevOS Control Center CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("get", help="Print all system settings")

    set_p = subparsers.add_parser("set", help="Update a setting")
    set_p.add_argument("section", help="Setting section (appearance, ai, developer, etc.)")
    set_p.add_argument("key", help="Setting key")
    set_p.add_argument("value", help="New value")

    args = parser.parse_args()
    cc = DevOSControlCenter()

    if args.command == "get" or not args.command:
        print(json.dumps(cc.get_summary(), indent=2))
    elif args.command == "set":
        # Parse boolean or float if needed
        val = args.value
        if val.lower() == "true": val = True
        elif val.lower() == "false": val = False
        elif val.replace(".", "", 1).isdigit(): val = float(val)

        success = cc.set_value(args.section, args.key, val)
        if success:
            print(f"Updated [{args.section}] {args.key} = {val}")
        else:
            print(f"Error: Could not find [{args.section}] {args.key}")


if __name__ == "__main__":
    main()
