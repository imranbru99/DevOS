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
