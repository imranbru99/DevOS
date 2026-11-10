#!/usr/bin/env python3
"""Recent Files and every DevOS UI must show clear app names, never raw IDs."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components"))

import app_friendly_names as names  # noqa: E402


def test_recent_files_screenshot_ids_are_clear():
    cases = {
        "/usr/bin/spectacle": "Snipping Tool",
        "spectacle": "Snipping Tool",
        "dolphin": "File Explorer",
        "gwenview": "Photos",
        "org.kde.krunner": "Search",
        "org.kde.libtaskmanager": "Taskbar",
        "org.kde.plasma.kicker": "Start Menu",
        "org.kde.systemsettings": "Settings",
    }
    for agent, want in cases.items():
        assert names.friendly_app_name(agent) == want, agent


def test_canonical_agent_strips_paths():
    assert names.canonical_agent("/usr/bin/spectacle") == "spectacle"
    assert names.canonical_agent("/usr/bin/dolphin") == "dolphin"
    assert names.canonical_agent("org.kde.spectacle.desktop") == "org.kde.spectacle"


def test_alias_desktop_has_clear_name():
    body = names.alias_desktop_body("dolphin")
    assert body is not None
    assert "Name=File Explorer\n" in body
    assert "NoDisplay=true" in body
    assert "X-DevOS-FriendlyAlias=true" in body


def test_looks_technical():
    assert names.looks_technical("/usr/bin/spectacle")
    assert names.looks_technical("org.kde.krunner")
    assert names.looks_technical("dolphin")
    assert not names.looks_technical("File Explorer")
    assert not names.looks_technical("Snipping Tool")


def test_debrand_writes_friendly_aliases():
    script = (ROOT / "build/includes.chroot/usr/local/sbin/devos-debrand-desktop").read_text(
        encoding="utf-8"
    )
    assert "write_friendly_aliases" in script
    assert "app_friendly_names" in script
    assert "Never shadow a real packaged" in script


def test_shipped_aliases_cover_recent_files_gaps():
    apps = ROOT / "build/includes.chroot/usr/local/share/applications"
    for name, label in (
        ("spectacle.desktop", "Snipping Tool"),
        ("dolphin.desktop", "File Explorer"),
        ("gwenview.desktop", "Photos"),
        ("krunner.desktop", "Search"),
        ("org.kde.libtaskmanager.desktop", "Taskbar"),
        ("org.kde.plasma.kicker.desktop", "Start Menu"),
    ):
        text = (apps / name).read_text(encoding="utf-8")
        assert f"Name={label}" in text
        assert "X-DevOS-FriendlyAlias=true" in text
    # Must not shadow real packaged launchers (Settings / KRunner).
    assert not (apps / "org.kde.systemsettings.desktop").exists()
    assert not (apps / "systemsettings.desktop").exists()
    assert not (apps / "org.kde.krunner.desktop").exists()


def test_normalize_recent_agents_script_exists():
    path = ROOT / "build/includes.chroot/usr/local/sbin/devos-normalize-recent-agents"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "canonical_agent" in text
    assert "initiatingAgent" in text
    apply = (ROOT / "build/includes.chroot/usr/local/sbin/devos-apply-branding").read_text(
        encoding="utf-8"
    )
    assert "devos-normalize-recent-agents" in apply
