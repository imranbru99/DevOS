#!/usr/bin/env python3
"""
DevOS Theme Switcher & Appearance Manager
Coordinates live switching between Dark and Light themes across KDE Plasma,
GTK 3/4, Kvantum, XDG portals, Code/VSCodium, and DevOS design tokens.
"""

import sys
import os
import json
import shutil
import subprocess
import configparser
from typing import Dict, Any, Optional

SETTINGS_FILE = os.path.expanduser("~/.config/devos/settings.json")
KDEGLOBALS_FILE = os.path.expanduser("~/.config/kdeglobals")
PLASMARC_FILE = os.path.expanduser("~/.config/plasmarc")
GTK3_FILE = os.path.expanduser("~/.config/gtk-3.0/settings.ini")
GTK4_FILE = os.path.expanduser("~/.config/gtk-4.0/settings.ini")
KVANTUM_FILE = os.path.expanduser("~/.config/Kvantum/kvantum.kvconfig")
CODE_SETTINGS = os.path.expanduser("~/.config/Code/User/settings.json")
VSCODIUM_SETTINGS = os.path.expanduser("~/.config/VSCodium/User/settings.json")


def _run_cmd(cmd: list) -> bool:
    """Run a shell command silently if the executable exists."""
    if not shutil.which(cmd[0]):
        return False
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5
        )
        return True
    except Exception:
        return False


class ThemeSwitcher:
    """Unified appearance manager for Dark and Light themes in DevOS."""

    THEMES = {
        "dark": {
            "name": "DevOS Dark",
            "kdeglobals_scheme": "DevOS",
            "fallback_scheme": "BreezeDark",
            "plasma_desktoptheme": "breeze-dark",
            "lookandfeel": "org.devos.desktop",
            "fallback_lookandfeel": "org.kde.breezedark.desktop",
            "gtk_theme": "Breeze-Dark",
            "gtk_icon_theme": "Papirus-Dark",
            "gtk_prefer_dark": "1",
            "gsettings_color_scheme": "prefer-dark",
            "kvantum_theme": "KvSimplicityDark",
            "code_theme": "Default Dark Modern",
        },
        "light": {
            "name": "DevOS Light",
            "kdeglobals_scheme": "DevOS-Light",
            "fallback_scheme": "BreezeLight",
            "plasma_desktoptheme": "breeze-light",
            "lookandfeel": "org.kde.breeze.desktop",
            "fallback_lookandfeel": "org.kde.breeze.desktop",
            "gtk_theme": "Breeze",
            "gtk_icon_theme": "Papirus",
            "gtk_prefer_dark": "0",
            "gsettings_color_scheme": "prefer-light",
            "kvantum_theme": "KvSimplicity",
            "code_theme": "Default Light Modern",
        }
    }

    @classmethod
    def get_current_theme(cls) -> str:
        """Determines if the system is currently using dark or light theme."""
        # 1. Check DevOS settings
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    theme = data.get("appearance", {}).get("theme", "").lower()
                    if theme in ("dark", "light"):
                        return theme
            except Exception:
                pass

        # 2. Check kdeglobals
        if os.path.exists(KDEGLOBALS_FILE):
            try:
                cp = configparser.ConfigParser()
                cp.read(KDEGLOBALS_FILE)
                scheme = cp.get("General", "ColorScheme", fallback="").lower()
                if "light" in scheme or scheme in ("breeze", "breezelight"):
                    return "light"
            except Exception:
                pass

        # 3. Check GTK settings
        if os.path.exists(GTK3_FILE):
            try:
                cp = configparser.ConfigParser()
                cp.read(GTK3_FILE)
                prefer_dark = cp.get("Settings", "gtk-application-prefer-dark-theme", fallback="1")
                if prefer_dark == "0":
                    return "light"
            except Exception:
                pass

        return "dark"

    @classmethod
    def _update_ini_file(cls, path: str, section: str, values: Dict[str, str]):
        """Helper to safely read and update INI config files."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cp = configparser.ConfigParser()
        if os.path.exists(path):
            try:
                cp.read(path)
            except Exception:
                pass
        if not cp.has_section(section):
            cp.add_section(section)
        for k, v in values.items():
            cp.set(section, k, v)
        try:
            with open(path, "w") as f:
                cp.write(f)
        except Exception:
            pass

    @classmethod
    def _update_code_settings(cls, path: str, theme_name: str):
        """Helper to update VS Code / VSCodium color theme."""
        if not os.path.exists(os.path.dirname(path)):
            return
        try:
            data = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
            data["workbench.colorTheme"] = theme_name
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    @classmethod
    def apply_theme(cls, mode: str) -> bool:
        """Applies dark or light theme across all desktop subsystems."""
        mode = mode.lower().strip()
        if mode not in cls.THEMES:
            return False

        spec = cls.THEMES[mode]

        # 1. Update DevOS settings.json
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        settings = {}
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
            except Exception:
                pass
        if "appearance" not in settings:
            settings["appearance"] = {}
        settings["appearance"]["theme"] = mode
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass

        # 2. Update GTK 3 & GTK 4
        gtk_vals = {
            "gtk-theme-name": spec["gtk_theme"],
            "gtk-icon-theme-name": spec["gtk_icon_theme"],
            "gtk-application-prefer-dark-theme": spec["gtk_prefer_dark"],
        }
        cls._update_ini_file(GTK3_FILE, "Settings", gtk_vals)
        cls._update_ini_file(GTK4_FILE, "Settings", gtk_vals)

        # 3. Update XDG / GNOME desktop interface portal via gsettings
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", spec["gsettings_color_scheme"]])
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", spec["gtk_theme"]])
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", spec["gtk_icon_theme"]])

        # 4. Update Kvantum configuration
        cls._update_ini_file(KVANTUM_FILE, "General", {"theme": spec["kvantum_theme"]})

        # 5. Update VS Code / VSCodium
        cls._update_code_settings(CODE_SETTINGS, spec["code_theme"])
        cls._update_code_settings(VSCODIUM_SETTINGS, spec["code_theme"])

        # 6. Update KDE Plasma Configuration Files
        kwrite_bin = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if kwrite_bin:
            _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "General", "--key", "ColorScheme", spec["kdeglobals_scheme"]])
            _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "Icons", "--key", "Theme", spec["gtk_icon_theme"]])
            _run_cmd([kwrite_bin, "--file", "plasmarc", "--group", "Theme", "--key", "name", spec["plasma_desktoptheme"]])
        else:
            cls._update_ini_file(KDEGLOBALS_FILE, "General", {"ColorScheme": spec["kdeglobals_scheme"]})
            cls._update_ini_file(KDEGLOBALS_FILE, "Icons", {"Theme": spec["gtk_icon_theme"]})
            cls._update_ini_file(PLASMARC_FILE, "Theme", {"name": spec["plasma_desktoptheme"]})

        # 7. Apply live Plasma 6 runtime hooks if active session exists
        if shutil.which("plasma-apply-colorscheme"):
            if not _run_cmd(["plasma-apply-colorscheme", spec["kdeglobals_scheme"]]):
                _run_cmd(["plasma-apply-colorscheme", spec["fallback_scheme"]])

        if shutil.which("plasma-apply-desktoptheme"):
            _run_cmd(["plasma-apply-desktoptheme", spec["plasma_desktoptheme"]])

        if shutil.which("lookandfeeltool"):
            if not _run_cmd(["lookandfeeltool", "-a", spec["lookandfeel"]]):
                _run_cmd(["lookandfeeltool", "-a", spec["fallback_lookandfeel"]])

        return True

    @classmethod
    def toggle(cls) -> str:
        """Toggles current theme between dark and light, returning the new theme."""
        current = cls.get_current_theme()
        new_theme = "light" if current == "dark" else "dark"
        cls.apply_theme(new_theme)
        return new_theme


def main():
    if len(sys.argv) < 2:
        current = ThemeSwitcher.get_current_theme()
        print(f"\nDevOS Theme Manager")
        print(f"Current Theme: {current.upper()} MODE\n")
        print("Available options:")
        print("  devos theme dark    - Switch to DevOS Dark theme (ergonomic graphite & cyan)")
        print("  devos theme light   - Switch to DevOS Light theme (clean daylight & crisp blue)")
        print("  devos theme toggle  - Toggle between Dark and Light mode")
        print("  devos theme status  - Print active theme ('dark' or 'light')\n")
        sys.exit(0)

    arg = sys.argv[1].lower().strip()

    if arg in ("status", "current", "get"):
        print(ThemeSwitcher.get_current_theme())
    elif arg in ("dark", "d"):
        ThemeSwitcher.apply_theme("dark")
        print("✓ Switched system appearance to DARK MODE (Plasma, GTK, Kvantum, Code).")
    elif arg in ("light", "l"):
        ThemeSwitcher.apply_theme("light")
        print("✓ Switched system appearance to LIGHT MODE (Plasma, GTK, Kvantum, Code).")
    elif arg in ("toggle", "t"):
        new_mode = ThemeSwitcher.toggle()
        print(f"✓ Toggled system appearance to {new_mode.upper()} MODE.")
    else:
        print(f"Unknown theme option: {arg}")
        print("Usage: devos theme [dark|light|toggle|status]")
        sys.exit(1)


if __name__ == "__main__":
    main()
