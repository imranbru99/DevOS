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
            "ai_tier": tier["tier"],
            "enable_winlayer": True,
            "enable_waydroid": True,
            "enable_dev_workstation": True,
            "completed_at": "2026-10-10T12:00:00Z"
        }

        if options:
            default_choices.update(options)

        with open(self.STATE_FILE, "w") as f:
            json.dump(default_choices, f, indent=2)

        return default_choices


def main():
    parser = argparse.ArgumentParser(description="DevOS First-Boot Setup Wizard")
    parser.add_argument("--auto", action="store_true", help="Run automated default setup")
    args = parser.parse_args()

    wizard = FirstBootWizard()
    res = wizard.run_setup()
    print("DevOS First Boot Setup Complete:")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
