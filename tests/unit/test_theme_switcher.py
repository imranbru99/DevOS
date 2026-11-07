#!/usr/bin/env python3
"""
Unit tests for DevOS Theme Switcher
Tests Dark and Light mode detection, toggling, and configuration updating.
"""

import sys
import os
import tempfile
import json
import pytest

SYS_PATH_SETTINGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/settings"))
if SYS_PATH_SETTINGS not in sys.path:
    sys.path.insert(0, SYS_PATH_SETTINGS)

from theme_switcher import ThemeSwitcher


def test_theme_switcher_get_default_theme():
    """Verify ThemeSwitcher returns valid theme (dark or light)."""
    theme = ThemeSwitcher.get_current_theme()
    assert theme in ("dark", "light")


def test_theme_switcher_specs_defined():
    """Verify all dark, light, and mac specs have all required desktop keys."""
    for mode in ("dark", "light", "mac", "mac-light"):
        assert mode in ThemeSwitcher.THEMES
        spec = ThemeSwitcher.THEMES[mode]
        assert "kdeglobals_scheme" in spec
        assert "plasma_desktoptheme" in spec
        assert "gtk_theme" in spec
        assert "gtk_icon_theme" in spec
        assert "gtk_prefer_dark" in spec
        assert "code_theme" in spec
        assert "buttons_left" in spec
        assert "buttons_right" in spec


def test_theme_switcher_apply_mac(monkeypatch):
    """Verify applying mac theme sets Cupertino settings and buttons on left."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = os.path.join(tmpdir, "devos", "settings.json")
        gtk3_path = os.path.join(tmpdir, "gtk-3.0", "settings.ini")
        kdeglobals_path = os.path.join(tmpdir, "kdeglobals")
        kwinrc_path = os.path.join(tmpdir, "kwinrc")

        monkeypatch.setattr("theme_switcher.SETTINGS_FILE", settings_path)
        monkeypatch.setattr("theme_switcher.GTK3_FILE", gtk3_path)
        monkeypatch.setattr("theme_switcher.KDEGLOBALS_FILE", kdeglobals_path)
        monkeypatch.setattr("theme_switcher.KWINRC_FILE", kwinrc_path)

        ok = ThemeSwitcher.apply_theme("mac")
        assert ok is True
        assert ThemeSwitcher.get_current_theme() == "mac"

        with open(settings_path, "r") as f:
            data = json.load(f)
            assert data["appearance"]["theme"] == "mac"


def test_theme_switcher_apply_and_toggle(monkeypatch):
    """Verify applying light mode and toggling updates correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        settings_path = os.path.join(tmpdir, "devos", "settings.json")
        gtk3_path = os.path.join(tmpdir, "gtk-3.0", "settings.ini")
        kdeglobals_path = os.path.join(tmpdir, "kdeglobals")

        monkeypatch.setattr("theme_switcher.SETTINGS_FILE", settings_path)
        monkeypatch.setattr("theme_switcher.GTK3_FILE", gtk3_path)
        monkeypatch.setattr("theme_switcher.KDEGLOBALS_FILE", kdeglobals_path)

        # Apply light theme
        ok = ThemeSwitcher.apply_theme("light")
        assert ok is True
        assert ThemeSwitcher.get_current_theme() == "light"

        with open(settings_path, "r") as f:
            data = json.load(f)
            assert data["appearance"]["theme"] == "light"

        # Toggle to dark
        new_mode = ThemeSwitcher.toggle()
        assert new_mode == "dark"
        assert ThemeSwitcher.get_current_theme() == "dark"

        with open(settings_path, "r") as f:
            data = json.load(f)
            assert data["appearance"]["theme"] == "dark"

@pytest.fixture(autouse=True)
def isolate_desktop_configuration(monkeypatch, tmp_path):
    """Theme tests must never write the developer's live desktop settings."""
    import theme_switcher as module
    for key in ('SETTINGS_FILE','KDEGLOBALS_FILE','PLASMARC_FILE','GTK3_FILE','GTK4_FILE','KVANTUM_FILE','KWINRC_FILE','CODE_SETTINGS','VSCODIUM_SETTINGS'):
        monkeypatch.setattr(module,key,str(tmp_path/key/'settings'))
    monkeypatch.setattr(module,'KATE_FILES',[])
    monkeypatch.setattr(module,'ANTIGRAVITY_SETTINGS',[str(tmp_path/'antigravity_kde'/'User'/'settings.json')])
    monkeypatch.setattr(module,'_run_cmd',lambda _cmd: True)
    monkeypatch.setattr(module.shutil,'which',lambda _name: None)


def test_theme_switcher_updates_antigravity_ide(monkeypatch, tmp_path):
    """Verify switching to light mode sets Default Light Modern on Antigravity IDE."""
    import theme_switcher as module
    ag_settings = tmp_path / "antigravity" / "User" / "settings.json"
    ag_settings.parent.mkdir(parents=True)
    monkeypatch.setattr(module, 'ANTIGRAVITY_SETTINGS', [str(ag_settings)])

    assert ThemeSwitcher.apply_theme("light") is True
    assert ag_settings.exists()
    with open(ag_settings, "r") as f:
        data = json.load(f)
        assert data["workbench.colorTheme"] == "Default Light Modern"
        assert data["window.autoDetectColorScheme"] is True


def test_premium_light_wallpaper_preferred(monkeypatch):
    import theme_switcher as module
    scripts = []
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/qdbus6')
    monkeypatch.setattr(module.os.path, 'isfile', lambda p: p.startswith('/usr/share/wallpapers/'))
    monkeypatch.setattr(module, '_run_cmd', lambda args: scripts.append(args[-1]) or True)
    assert ThemeSwitcher.apply_wallpaper('light')
    assert 'file:///usr/share/wallpapers/DevOS-Premium-01-PearlFold/contents/images/wallpaper.png' in scripts[0]
    assert 'var light = true;' in scripts[0]


def test_legacy_wallpaper_fallback(monkeypatch):
    import theme_switcher as module
    scripts = []
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/qdbus6')
    monkeypatch.setattr(module.os.path, 'isfile', lambda p: p == '/usr/share/wallpapers/DevOS-Daylight/contents/images/daylight.svg')
    monkeypatch.setattr(module, '_run_cmd', lambda args: scripts.append(args[-1]) or True)
    assert ThemeSwitcher.apply_wallpaper('light')
    assert 'file:///usr/share/wallpapers/DevOS-Daylight/contents/images/daylight.svg' in scripts[0]


def test_theme_apply_does_not_broadcast_palette_reload(monkeypatch):
    """Palette notify / GtkConfig.setGtkTheme segfault Chromium; must stay unused."""
    import theme_switcher as module
    calls = []
    monkeypatch.setattr(module, '_run_cmd', lambda cmd: calls.append(list(cmd)) or True)
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/usr/bin/' + name if name in (
        'plasma-apply-colorscheme','plasma-apply-desktoptheme','kvantummanager','qdbus6','gsettings','kwriteconfig6','killall'
    ) else None)
    assert module.ThemeSwitcher.apply_theme('light') is True
    flat = [' '.join(c) for c in calls]
    assert not any('notifyChange' in s for s in flat)
    assert not any('setGtkTheme' in s for s in flat)
    assert any('plasma-apply-colorscheme' in s for s in flat)
    assert any(c == ['killall', 'dolphin'] for c in calls)
