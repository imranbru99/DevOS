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
KWINRC_FILE = os.path.expanduser("~/.config/kwinrc")
CODE_SETTINGS = os.path.expanduser("~/.config/Code/User/settings.json")
KATE_FILES = [os.path.expanduser("~/.config/" + name) for name in ("katerc", "kwriterc", "katepartrc")]
VSCODIUM_SETTINGS = os.path.expanduser("~/.config/VSCodium/User/settings.json")
ANTIGRAVITY_SETTINGS = [
    os.path.expanduser("~/.config/Antigravity-KDE/User/settings.json"),
    os.path.expanduser("~/.config/Antigravity/User/settings.json"),
    os.path.expanduser("~/.config/antigravity/User/settings.json"),
]


def _run_cmd(cmd: list) -> bool:
    """Run a shell command silently if the executable exists."""
    if not shutil.which(cmd[0]):
        return False
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5
        )
        return result.returncode == 0
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
            "buttons_left": "M",
            "buttons_right": "IAX",
            "kdecoration_theme": "Breeze",
        },
        "light": {
            "name": "DevOS Light",
            "kdeglobals_scheme": "DevOS-Light",
            "fallback_scheme": "BreezeLight",
            # Keep the DevOS look-and-feel package so light mode does not wipe the
            # DevOS panel/branding (org.kde.breeze.desktop was resetting the desktop).
            "plasma_desktoptheme": "breeze-light",
            "lookandfeel": "org.devos.desktop",
            "fallback_lookandfeel": "org.kde.breeze.desktop",
            "gtk_theme": "Breeze",
            "gtk_icon_theme": "Papirus",
            "gtk_prefer_dark": "0",
            "gsettings_color_scheme": "prefer-light",
            "kvantum_theme": "KvSimplicity",
            "code_theme": "Default Light Modern",
            "buttons_left": "M",
            "buttons_right": "IAX",
            "kdecoration_theme": "Breeze",
        },
        "mac": {
            "name": "DevOS Cupertino (macOS WhiteSur Dark)",
            "kdeglobals_scheme": "WhiteSurDark",
            "fallback_scheme": "DevOS",
            "plasma_desktoptheme": "WhiteSur-dark",
            "lookandfeel": "com.github.vinceliuice.WhiteSur-dark",
            "fallback_lookandfeel": "org.devos.desktop",
            "gtk_theme": "WhiteSur-Dark",
            "gtk_icon_theme": "WhiteSur-dark",
            "gtk_prefer_dark": "1",
            "gsettings_color_scheme": "prefer-dark",
            "kvantum_theme": "WhiteSurDark",
            "code_theme": "Default Dark Modern",
            "buttons_left": "XAI",
            "buttons_right": "",
            "kdecoration_theme": "WhiteSur-dark",
        },
        "mac-light": {
            "name": "DevOS Cupertino Light (macOS WhiteSur Light)",
            "kdeglobals_scheme": "WhiteSurLight",
            "fallback_scheme": "DevOS-Light",
            "plasma_desktoptheme": "WhiteSur-light",
            "lookandfeel": "com.github.vinceliuice.WhiteSur",
            "fallback_lookandfeel": "org.kde.breeze.desktop",
            "gtk_theme": "WhiteSur-Light",
            "gtk_icon_theme": "WhiteSur",
            "gtk_prefer_dark": "0",
            "gsettings_color_scheme": "prefer-light",
            "kvantum_theme": "WhiteSur",
            "code_theme": "Default Light Modern",
            "buttons_left": "XAI",
            "buttons_right": "",
            "kdecoration_theme": "WhiteSur-light",
        }
    }

    @classmethod
    def is_whitesur_installed(cls) -> bool:
        """Checks if WhiteSur GTK / KDE assets are present on the system."""
        indicators = [
            "/usr/share/themes/WhiteSur-Dark",
            "/usr/share/plasma/desktoptheme/WhiteSur-dark",
            "/usr/share/icons/WhiteSur-dark",
            os.path.expanduser("~/.local/share/themes/WhiteSur-Dark"),
            os.path.expanduser("~/.local/share/icons/WhiteSur-dark"),
        ]
        return any(os.path.exists(p) for p in indicators)

    @classmethod
    def get_current_theme(cls) -> str:
        """Determines if the system is currently using dark, light, or mac theme."""
        # 1. Check DevOS settings
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    data = json.load(f)
                    theme = data.get("appearance", {}).get("theme", "").lower()
                    if theme in cls.THEMES:
                        return theme
            except Exception:
                pass

        # 2. Check kdeglobals
        if os.path.exists(KDEGLOBALS_FILE):
            try:
                cp = configparser.ConfigParser()
                cp.read(KDEGLOBALS_FILE)
                scheme = cp.get("General", "ColorScheme", fallback="").lower()
                if "whitesurlight" in scheme:
                    return "mac-light"
                if "whitesur" in scheme:
                    return "mac"
                if "light" in scheme or scheme in ("breeze", "breezelight"):
                    return "light"
            except Exception:
                pass

        # 3. Check GTK settings
        if os.path.exists(GTK3_FILE):
            try:
                cp = configparser.ConfigParser()
                cp.read(GTK3_FILE)
                theme_name = cp.get("Settings", "gtk-theme-name", fallback="").lower()
                if "whitesur-light" in theme_name:
                    return "mac-light"
                if "whitesur" in theme_name:
                    return "mac"
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
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        if os.path.exists(path):
            try:
                cp.read(path)
            except Exception:
                pass
        if not cp.has_section(section):
            cp.add_section(section)
        # Purge problematic GTK modules that trigger SIGSEGV crashes in Chromium/Electron
        for doomed in ("gtk-modules", "gtk-module"):
            if cp.has_option(section, doomed):
                cp.remove_option(section, doomed)
        for k, v in values.items():
            cp.set(section, k, v)
        try:
            with open(path, "w") as f:
                cp.write(f)
        except Exception:
            pass

    @classmethod
    def _strip_crashy_gtk_modules(cls) -> None:
        """Remove colorreload/window-decorations GTK modules that SIGSEGV Chromium/Electron.

        Plasma's gtkconfig often re-injects `colorreload-gtk-module` when the palette
        changes. That module reloads GTK chrome inside Chrome/Edge/Antigravity and
        kills the process. We strip it from settings and never broadcast a GTK reload.
        """
        for path in (GTK3_FILE, GTK4_FILE):
            if not os.path.exists(path):
                continue
            try:
                text = open(path, encoding="utf-8", errors="replace").read()
                lines = [
                    ln for ln in text.splitlines(True)
                    if not ln.lower().startswith("gtk-modules=")
                    and not ln.lower().startswith("gtk-module=")
                ]
                open(path, "w", encoding="utf-8").writelines(lines)
            except OSError:
                pass

    @classmethod
    def _write_gtk_settings(cls, spec: Dict[str, str]) -> None:
        """Write GTK 3/4 settings without asking GtkConfig to hot-reload (crashes Chrome)."""
        prefer = spec["gtk_prefer_dark"]
        gtk_vals = {
            "gtk-theme-name": spec["gtk_theme"],
            "gtk-icon-theme-name": spec["gtk_icon_theme"],
            "gtk-application-prefer-dark-theme": prefer,
        }
        cls._update_ini_file(GTK3_FILE, "Settings", gtk_vals)
        cls._update_ini_file(GTK4_FILE, "Settings", gtk_vals)
        cls._strip_crashy_gtk_modules()
        # Do NOT call org.kde.GtkConfig.setGtkTheme — it reloads GTK in every
        # running Chromium/Electron process and commonly segfaults them.

    @classmethod
    def _reload_desktop(cls, spec: Dict[str, str]) -> None:
        """Push live Plasma / KWin / Kvantum refresh without resetting the shell layout."""
        if shutil.which("plasma-apply-colorscheme"):
            # If already on the target scheme, briefly flip to fallback so Plasma
            # does not no-op and leave a stale palette in memory.
            try:
                current = ""
                if os.path.exists(KDEGLOBALS_FILE):
                    cp = configparser.ConfigParser()
                    cp.read(KDEGLOBALS_FILE)
                    current = cp.get("General", "ColorScheme", fallback="")
                if current == spec["kdeglobals_scheme"] and spec.get("fallback_scheme"):
                    _run_cmd(["plasma-apply-colorscheme", spec["fallback_scheme"]])
                    cls._strip_crashy_gtk_modules()
            except Exception:
                pass
            if not _run_cmd(["plasma-apply-colorscheme", spec["kdeglobals_scheme"]]):
                _run_cmd(["plasma-apply-colorscheme", spec["fallback_scheme"]])
            cls._strip_crashy_gtk_modules()
        if shutil.which("plasma-apply-desktoptheme"):
            _run_cmd(["plasma-apply-desktoptheme", spec["plasma_desktoptheme"]])
        if shutil.which("kvantummanager"):
            _run_cmd(["kvantummanager", "--set", spec["kvantum_theme"]])
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if qdbus:
            _run_cmd([qdbus, "org.kde.KWin", "/KWin", "reconfigure"])
            # Intentionally skip KGlobalSettings.notifyChange(Palette): that signal
            # triggers colorreload-gtk-module inside Chrome / Edge / Antigravity and
            # they exit with Segmentation fault. Plasma still picks up kdeglobals.
        # Stock KDE apps (Dolphin, etc.) cache the old palette when we skip the
        # global notify — restart them so they match DevOS dark/light.
        cls._refresh_stock_kde_apps()
        # gtkconfig may rewrite settings.ini a moment after colorscheme apply.
        cls._strip_crashy_gtk_modules()
        try:
            import threading

            for delay in (0.8, 2.0):
                threading.Timer(delay, cls._strip_crashy_gtk_modules).start()
        except Exception:
            pass

    @classmethod
    def _refresh_stock_kde_apps(cls) -> None:
        """Restart palette-caching KDE apps without a global palette notify.

        DevOS Files paints its own stylesheet from settings.json, so it tracks
        dark/light on its own. Dolphin uses the Plasma ColorScheme and keeps a
        stale light/dark paint until restarted when notifyChange is skipped.
        """
        # Close Dolphin windows + daemon; next open (or --daemon) gets new colors.
        if shutil.which("killall"):
            _run_cmd(["killall", "dolphin"])
        # Prefer the DevOS file manager for folders; leave mimeapps alone here.

    @classmethod
    def _update_code_settings(cls, path: str, theme_name: str):
        """Helper to update VS Code / VSCodium / Antigravity color theme."""
        parent_dir = os.path.dirname(path)
        base_dir = os.path.dirname(parent_dir)
        if not os.path.exists(parent_dir) and not os.path.exists(base_dir):
            return
        os.makedirs(parent_dir, exist_ok=True)
        try:
            data = {}
            if os.path.exists(path):
                with open(path, "r") as f:
                    data = json.load(f)
            data["workbench.colorTheme"] = theme_name
            data["workbench.preferredLightColorTheme"] = "Default Light Modern"
            data["workbench.preferredDarkColorTheme"] = "Default Dark Modern"
            data["window.autoDetectColorScheme"] = True
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

        # lookandfeeltool resets panel layout and can fight color apply. Only use it
        # for macOS WhiteSur packs; dark/light stay on org.devos.desktop.
        if mode in ("mac", "mac-light") and shutil.which("lookandfeeltool"):
            if not _run_cmd(["lookandfeeltool", "-a", spec["lookandfeel"]]):
                _run_cmd(["lookandfeeltool", "-a", spec["fallback_lookandfeel"]])

        # 2. Update GTK 3 & GTK 4 (after any LNF so we win the final write)
        cls._write_gtk_settings(spec)

        # 3. Update XDG / GNOME desktop interface portal via gsettings
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", spec["gsettings_color_scheme"]])
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", spec["gtk_theme"]])
        _run_cmd(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", spec["gtk_icon_theme"]])

        # 4. Update Kvantum configuration
        cls._update_ini_file(KVANTUM_FILE, "General", {"theme": spec["kvantum_theme"]})

        # 5. Update VS Code / VSCodium / Antigravity IDE
        cls._update_code_settings(CODE_SETTINGS, spec["code_theme"])
        cls._update_code_settings(VSCODIUM_SETTINGS, spec["code_theme"])
        for ag_path in ANTIGRAVITY_SETTINGS:
            cls._update_code_settings(ag_path, spec["code_theme"])

        # Kate/KWrite have a separate syntax-editor color scheme.
        for path in KATE_FILES:
            if os.path.exists(path):
                cls._update_ini_file(path, "KTextEditor Renderer", {
                    "Auto Color Theme Selection": "true",
                    "Color Theme": "Breeze Light" if mode in ("light", "mac-light") else "Breeze Dark",
                })

        # 6. Update KDE Plasma Configuration Files
        kwrite_bin = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
        if kwrite_bin:
            # Do not pre-write ColorScheme when plasma-apply-colorscheme exists —
            # pre-writing can make the apply tool no-op with a stale palette.
            if not shutil.which("plasma-apply-colorscheme"):
                _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "General", "--key", "ColorScheme", spec["kdeglobals_scheme"]])
            _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "Icons", "--key", "Theme", spec["gtk_icon_theme"]])
            _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "KDE", "--key", "widgetStyle", "kvantum"])
            # Keep DevOS look-and-feel for dark/light so branding/panel stay put.
            if mode in ("dark", "light"):
                _run_cmd([kwrite_bin, "--file", "kdeglobals", "--group", "KDE", "--key", "LookAndFeelPackage", "org.devos.desktop"])
            _run_cmd([kwrite_bin, "--file", "plasmarc", "--group", "Theme", "--key", "name", spec["plasma_desktoptheme"]])
            _run_cmd([kwrite_bin, "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "ButtonsOnLeft", spec.get("buttons_left", "M")])
            _run_cmd([kwrite_bin, "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "ButtonsOnRight", spec.get("buttons_right", "IAX")])
            if "kdecoration_theme" in spec:
                _run_cmd([kwrite_bin, "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "theme", spec["kdecoration_theme"]])
        else:
            cls._update_ini_file(KDEGLOBALS_FILE, "General", {"ColorScheme": spec["kdeglobals_scheme"]})
            cls._update_ini_file(KDEGLOBALS_FILE, "Icons", {"Theme": spec["gtk_icon_theme"]})
            cls._update_ini_file(PLASMARC_FILE, "Theme", {"name": spec["plasma_desktoptheme"]})
            kwin_vals = {
                "ButtonsOnLeft": spec.get("buttons_left", "M"),
                "ButtonsOnRight": spec.get("buttons_right", "IAX"),
            }
            if "kdecoration_theme" in spec:
                kwin_vals["theme"] = spec["kdecoration_theme"]
            cls._update_ini_file(KWINRC_FILE, "org.kde.kdecoration2", kwin_vals)

        # 7. Live refresh (colors, plasma theme, kvantum, kwin) — no full LNF reset.
        cls._reload_desktop(spec)
        # GTK last again so portal/LNF helpers cannot leave crashy gtk-modules behind.
        cls._write_gtk_settings(spec)

        cls.apply_wallpaper(mode)
        return True

    @classmethod
    def apply_wallpaper(cls, mode):
        """Pair DevOS-owned wallpapers; keep a user's custom wallpaper unchanged."""
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        candidates = [os.path.expanduser("~/.local/share/wallpapers/DevOS-Premium-01-PearlFold/contents/images/wallpaper.png"),
                      "/usr/share/wallpapers/DevOS-Premium-01-PearlFold/contents/images/wallpaper.png",
                      os.path.expanduser("~/.local/share/wallpapers/DevOS-Daylight/contents/images/daylight.svg"),
                      "/usr/share/wallpapers/DevOS-Daylight/contents/images/daylight.svg"]
        image = next((p for p in candidates if os.path.isfile(p)), None)
        if not qdbus or not image:
            return False
        script = """
var light = LIGHT_MODE;
var target = LIGHT_IMAGE;
var screens = desktops();
for (var i=0; i<screens.length; i++) {
    var d=screens[i];
    var plugin=d.wallpaperPlugin;
    d.currentConfigGroup=["Wallpaper",plugin,"General"];
    var current=d.readConfig("Image", "");
    var paths=d.readConfig("SlidePaths", []);
    var premium=String(current).indexOf("/DevOS-Premium-")>=0;
    var paired=String(current).indexOf("/DevOS-Premium-02-SapphireBloom/")>=0;
    var owned=(!premium || paired) && (String(current).indexOf("/DevOS-")>=0 || String(current).indexOf("/DevOS/")>=0 || String(paths).indexOf("/DevOS-")>=0);
    if(light && owned && current!==target) {
        d.currentConfigGroup=["DevOSAppearance"];
        d.writeConfig("PreviousWallpaperPlugin",plugin);
        d.writeConfig("PreviousWallpaperImage",current);
        d.wallpaperPlugin="org.kde.image";
        d.currentConfigGroup=["Wallpaper","org.kde.image","General"];
        d.writeConfig("Image",target);
    } else if(!light && current===target) {
        d.currentConfigGroup=["DevOSAppearance"];
        var oldPlugin=d.readConfig("PreviousWallpaperPlugin","org.kde.image");
        var oldImage=d.readConfig("PreviousWallpaperImage","");
        if(oldImage) {
            d.wallpaperPlugin=oldPlugin;
            d.currentConfigGroup=["Wallpaper",oldPlugin,"General"];
            d.writeConfig("Image",oldImage);
        }
    }
}
""".replace("LIGHT_MODE", "true" if mode in ("light", "mac-light") else "false").replace("LIGHT_IMAGE", json.dumps("file://" + image))
        return _run_cmd([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script])

    @classmethod
    def toggle(cls) -> str:
        """Toggles current theme between dark and light, returning the new theme."""
        current = cls.get_current_theme()
        new_theme = "light" if current in ("dark", "mac") else "dark"
        cls.apply_theme(new_theme)
        return new_theme


def main():
    if len(sys.argv) < 2:
        current = ThemeSwitcher.get_current_theme()
        whitesur_status = "Installed" if ThemeSwitcher.is_whitesur_installed() else "Not Installed (Run 'devos theme install-mac')"
        print(f"\nDevOS Theme & Appearance Manager")
        print(f"Current Theme: {current.upper()} MODE")
        print(f"macOS Theme Suite: {whitesur_status}\n")
        print("Available options:")
        print("  devos theme dark        - Switch to DevOS Dark theme (ergonomic graphite & cyan)")
        print("  devos theme light       - Switch to DevOS Light theme (clean daylight & crisp blue)")
        print("  devos theme mac         - Switch to Cupertino macOS Dark theme (WhiteSur traffic lights)")
        print("  devos theme mac-light   - Switch to Cupertino macOS Light theme")
        print("  devos theme toggle      - Toggle between Dark and Light mode")
        print("  devos theme status      - Print active theme mode")
        print("  devos theme install-mac - Download & install WhiteSur macOS Theme Suite\n")
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
    elif arg in ("mac", "macos", "whitesur"):
        if not ThemeSwitcher.is_whitesur_installed():
            print("Notice: WhiteSur macOS assets are not yet installed.")
            print("Tip: Run 'devos theme install-mac' or 'sudo devos-install-whitesur' to install full assets.")
        ThemeSwitcher.apply_theme("mac")
        print("✓ Switched system appearance to macOS CUPERTINO DARK (WhiteSur, Traffic Lights, Kvantum).")
    elif arg in ("mac-light", "macos-light"):
        if not ThemeSwitcher.is_whitesur_installed():
            print("Notice: WhiteSur macOS assets are not yet installed.")
            print("Tip: Run 'devos theme install-mac' or 'sudo devos-install-whitesur' to install full assets.")
        ThemeSwitcher.apply_theme("mac-light")
        print("✓ Switched system appearance to macOS CUPERTINO LIGHT (WhiteSur Light).")
    elif arg in ("install-mac", "install-whitesur"):
        candidates = [
            shutil.which("devos-install-whitesur"),
            os.path.expanduser("~/.local/bin/devos-install-whitesur"),
            "/usr/local/sbin/devos-install-whitesur",
            os.path.join(os.path.dirname(__file__), "../../build/includes.chroot/usr/local/sbin/devos-install-whitesur"),
        ]
        installer = next((c for c in candidates if c and os.path.exists(c)), None)
        if installer:
            subprocess.run(["bash", installer])
        else:
            print("Installer script not found. Please ensure devos-install-whitesur is in PATH.")
    elif arg in ("toggle", "t"):
        new_mode = ThemeSwitcher.toggle()
        print(f"✓ Toggled system appearance to {new_mode.upper()} MODE.")
    else:
        print(f"Unknown theme option: {arg}")
        print("Usage: devos theme [dark|light|mac|mac-light|toggle|status|install-mac]")
        sys.exit(1)


if __name__ == "__main__":
    main()
