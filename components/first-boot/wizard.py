#!/usr/bin/env python3
"""
DevOS First-Boot Wizard
Interactive setup wizard executed on initial user login.
Detects hardware, sets up language/keyboard, privacy, AI tier, and feature toggles.
"""

import sys
import os
import json
import argparse
from typing import Dict, Any

SYS_PATH_AI = os.path.abspath(os.path.join(os.path.dirname(__file__), "../ai-core"))
sys.path.insert(0, SYS_PATH_AI)

try:
    from hardware_detector import HardwareDetector
except ImportError:
    HardwareDetector = None


class FirstBootWizard:
    """Manages the initial setup state and feature toggles."""

    STATE_FILE = os.path.expanduser("~/.config/devos/first_boot_completed.json")

    def __init__(self):
        os.makedirs(os.path.dirname(self.STATE_FILE), exist_ok=True)

    def is_completed(self) -> bool:
        return os.path.exists(self.STATE_FILE)

    def run_setup(self, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """Executes setup choices and records completion."""
        tier = HardwareDetector.evaluate_tier() if HardwareDetector else {"tier": "Standard"}

        default_choices = {
            "locale": "en_US.UTF-8",
            "available_locales": ["en_US.UTF-8", "bn_BD.UTF-8"],
            "keyboard": "us",
            "telemetry": False,  # Strict privacy constraint
            "theme": "dark",
            "available_themes": ["dark", "light"],
            "ai_tier": tier["tier"],
            "enable_winlayer": True,
            "enable_waydroid": True,
            "enable_dev_workstation": True,
            "hidpi_auto": True,
            "windows_app_tip": True,
            "backup_tip": True,
            "tips": [
                "Display: run `devos-display auto` (or Display Settings) for Wayland HiDPI 125–200%.",
                "Windows App: open once, install as PWA if prompted — later launches stay in one focused window.",
                "Backup: prefer Btrfs + Snapper at install time; on ext4 use Timeshift or rsync before big upgrades.",
                "Smooth under load: `devos smooth apply` then optional `tools/hang-soak.sh --minutes 60`.",
            ],
            "completed_at": "2026-10-10T12:00:00Z"
        }

        if options:
            default_choices.update(options)

        # Apply chosen theme
        selected_theme = default_choices.get("theme", "dark")
        try:
            settings_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../settings"))
            if settings_dir not in sys.path:
                sys.path.insert(0, settings_dir)
            from theme_switcher import ThemeSwitcher
            ThemeSwitcher.apply_theme(selected_theme)
        except Exception:
            pass

        # Best-effort HiDPI auto-fit on first login (never blocks setup).
        if default_choices.get("hidpi_auto", True):
            display = "/usr/local/bin/devos-display"
            if os.access(display, os.X_OK):
                try:
                    import subprocess
                    subprocess.run([display, "auto"], timeout=20, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass

        # Soft responsiveness policy (CPU/I/O weights) so AI + browser stay snappy.
        try:
            import subprocess
            smooth = "/usr/local/bin/devos"
            if os.access(smooth, os.X_OK):
                subprocess.run(
                    [smooth, "smooth", "apply", "--priority-only"],
                    timeout=25,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

        with open(self.STATE_FILE, "w") as f:
            json.dump(default_choices, f, indent=2)

        tips_path = os.path.expanduser("~/.config/devos/first_boot_tips.txt")
        try:
            with open(tips_path, "w", encoding="utf-8") as tipf:
                tipf.write("\n".join(default_choices.get("tips", [])) + "\n")
        except OSError:
            pass

        return default_choices


def main():
    parser = argparse.ArgumentParser(description="DevOS First-Boot Setup Wizard")
    parser.add_argument("--auto", action="store_true", help="Run automated default setup")
    parser.add_argument("--theme", choices=["dark", "light"], default=None, help="Initial appearance theme (dark or light)")
    args = parser.parse_args()

    wizard = FirstBootWizard()
    opts = {}
    if args.theme:
        opts["theme"] = args.theme
    res = wizard.run_setup(options=opts if opts else None)
    print("DevOS First Boot Setup Complete:")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
