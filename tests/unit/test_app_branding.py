#!/usr/bin/env python3
"""DevOS app icons / desktop launchers must not look like raw python3."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "build/includes.chroot/usr/share/applications"
ICONS = ROOT / "build/includes.chroot/usr/share/icons/hicolor/scalable/apps"
SKEL_DESKTOP = ROOT / "build/includes.chroot/etc/skel/Desktop"
APPLETS = ROOT / "build/includes.chroot/etc/skel/.config/plasma-org.kde.plasma.desktop-appletsrc"

# Taskbar pins — blank if .desktop is invalid or Icon asset is missing.
PINNED = (
    "devos-search.desktop",
    "devos-taskman.desktop",
    "devos-windows.desktop",
    "devos-thispc.desktop",
    "devos-chat.desktop",
    "devos-code.desktop",
)


# Theme icons used by Windows-like wrappers (Calculator, Photos, …) — not blank.
_THEME_ICONS = {
    "accessories-calculator",
    "accessories-text-editor",
    "application-pdf",
    "gwenview",
    "spectacle",
    "utilities-file-archiver",
    "utilities-terminal",
    "preferences-desktop-user",
    "google-chrome",
    "antigravity-kde",
}


def test_devos_desktops_use_branded_icons_and_wmclass():
    desks = list(APPS.glob("devos-*.desktop"))
    assert desks, "expected DevOS desktop files"
    for path in desks:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "NoDisplay=true" in text and "Hidden=true" in text:
            continue
        icon = next(
            (line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith("Icon=")),
            "",
        )
        assert icon.startswith("devos-") or icon.startswith("/usr/") or icon in _THEME_ICONS, (
            f"{path.name} Icon={icon}"
        )
        # WMClass must never be a python script basename (causes blank / python3 tiles).
        wm = next(
            (line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith("StartupWMClass=")),
            "",
        )
        if wm:
            assert not wm.endswith(".py"), f"{path.name} StartupWMClass={wm}"
            assert " " not in wm, f"{path.name} StartupWMClass has spaces: {wm}"
            assert wm.lower() != "python3", f"{path.name} StartupWMClass=python3"
        # Primary Exec must not be bare python3 for menu apps with a Name=
        for line in text.splitlines():
            if line.startswith("Exec=") and "python3" in line and "devos-run" not in line:
                assert False, f"{path.name} still launches via bare python3: {line}"


def test_taskbar_keeps_pin_under_icon_like_windows():
    text = APPLETS.read_text(encoding="utf-8", errors="replace")
    assert "hideActivatedLaunchers=false" in text
    assert "launchInPlace=true" in text
    assert "groupingStrategy=1" in text


def test_skel_shortcuts_not_python3_wmclass():
    for path in SKEL_DESKTOP.glob("*.desktop"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.startswith("StartupWMClass="):
                wm = line.split("=", 1)[1].strip()
                assert not wm.endswith(".py"), path.name
                assert wm.lower() != "python3", path.name
            if line.startswith("Exec=") and "python3" in line and "devos-run" not in line:
                assert False, f"{path.name} Exec still uses bare python3: {line}"


def test_desktop_type_is_not_glued_to_startupwmclass():
    """Plasma rejects Type=ApplicationStartupWMClass=… → blank taskbar icons."""
    bad = []
    for path in APPS.glob("devos-*.desktop"):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "Type=ApplicationStartupWMClass=" in text:
            bad.append(path.name)
            continue
        if re.search(r"(?m)^Type=Application$", text) is None:
            bad.append(f"{path.name}: missing Type=Application")
    assert not bad, f"invalid desktop Type lines: {bad}"


def test_branded_icons_exist_for_desktop_references():
    needed = set()
    for path in APPS.glob("devos-*.desktop"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Icon=devos-"):
                needed.add(line.split("=", 1)[1].strip())
    missing = [n for n in sorted(needed) if not (ICONS / f"{n}.svg").is_file()]
    assert not missing, f"missing icons: {missing}"


def test_no_letter_placeholder_icons():
    bad = []
    for path in ICONS.glob("devos-*.svg"):
        if "<text" in path.read_text(encoding="utf-8", errors="replace").lower():
            bad.append(path.name)
    assert not bad, f"letter-placeholder SVGs: {bad}"


def test_maximized_windows_keep_titlebar_buttons():
    for relative in (
        "build/includes.chroot/etc/xdg/kwinrc",
        "build/includes.chroot/etc/skel/.config/kwinrc",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        assert "BorderlessMaximizedWindows=false" in text, relative


def test_pinned_taskbar_desktops_are_valid():
    applets = APPLETS.read_text(encoding="utf-8", errors="replace")
    for name in PINNED:
        assert f"applications:{name}" in applets, name
        path = APPS / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8", errors="replace")
        assert re.search(r"(?m)^Type=Application$", text), name
        assert "Type=ApplicationStartupWMClass=" not in text, name
        icon = next(
            (line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith("Icon=")),
            "",
        )
        assert icon.startswith("devos-"), f"{name} Icon={icon}"
        assert (ICONS / f"{icon}.svg").is_file(), f"{name} missing {icon}.svg"
        # Placeholder letter tiles often fail to paint in Qt SVG.
        svg = (ICONS / f"{icon}.svg").read_text(encoding="utf-8", errors="replace")
        assert "<text" not in svg.lower(), f"{name} icon still uses <text> placeholder"


def test_skel_desktop_icons_match_branded_names():
    """Desktop shortcuts must not point at theme-only / wrong Icon= names."""
    expected = {
        "chat.desktop": "devos-chat",
        "devos-code.desktop": "devos-code",
        "devos-apps.desktop": "devos-apps",
        "devos-dashboard.desktop": "devos-dashboard",
        "devos-disk.desktop": "devos-disk",
        "notepad.desktop": "devos-notepad",
        "thispc.desktop": "devos-thispc",
    }
    for name, icon in expected.items():
        path = SKEL_DESKTOP / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8", errors="replace")
        assert f"Icon={icon}" in text, f"{name} expected Icon={icon}"


def test_app_identity_prepare_rewrites_argv0(monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT / "components"))
    import app_identity

    monkeypatch.setattr(sys, "argv", ["python3", "--flag"])
    app_identity.prepare("devos-clipboard")
    assert sys.argv[0] == "devos-clipboard"


def test_everyday_tools_use_search_friendly_names():
    """Menus must say Calculator / Photos / PDF Viewer — never KCalc / Gwenview."""
    expected = {
        "devos-calculator.desktop": "Calculator",
        "devos-pdf.desktop": "PDF Viewer",
        "devos-photos.desktop": "Photos",
        "devos-zip.desktop": "Zip Folders",
        "devos-snip.desktop": "Snipping Tool",
        "devos-thispc.desktop": "File Explorer",
        "devos-notepad.desktop": "Notepad",
        "devos-terminal.desktop": "Terminal",
        "devos-editor.desktop": "Text Editor",
        "devos-antigravity-studio.desktop": "Antigravity IDE",
        "devos-paint.desktop": "Paint",
        "devos-scanner.desktop": "Scanner",
        "devos-charmap.desktop": "Character Map",
        "devos-magnifier.desktop": "Magnifier",
        "devos-passwords.desktop": "Password Manager",
        "devos-notes.desktop": "Notes",
        "devos-resources.desktop": "Resource Monitor",
        "devos-broadband.desktop": "Internet Dial-up",
        "devos-ai-pipeline.desktop": "AI Pipeline",
        "devos-optimizer.desktop": "PC Optimizer",
        "devos-apps.desktop": "Apps",
        "devos-security.desktop": "Security",
        "devos-features.desktop": "Features",
        "devos-dashboard.desktop": "Dashboard",
        "devos-ai-models.desktop": "AI Models",
    }
    banned = re.compile(
        r"(?i)^Name=(KCalc|Dolphin|Kate|KWrite|Konsole|Spectacle|Okular|Gwenview|Ark|"
        r"Discover|Elisa|Klipper|KolourPaint|Skanlite|KCharSelect|KMag|Kvantum|btop\+\+|btop)\b"
    )
    for desk, name in expected.items():
        path = APPS / desk
        assert path.is_file(), desk
        text = path.read_text(encoding="utf-8", errors="replace")
        assert f"Name={name}" in text, desk
        assert banned.search(text) is None, desk
        assert "Keywords=" in text, desk


def test_debrand_keeps_friendly_name_when_hiding_upstream():
    """Regression: hide-only rewrite used to restore upstream Name=KCalc."""
    script = (
        ROOT / "build/includes.chroot/usr/local/sbin/devos-debrand-desktop"
    ).read_text(encoding="utf-8", errors="replace")
    assert "hide=app_id in HIDE" in script
    assert '"org.kde.kcalc"' in script
    assert "Calculator" in script
    assert r"\bKCalc\b" in script
    assert r"\bDolphin\b" in script
    assert r"\bKate\b" in script
    assert "devos-editor.desktop" in script
    assert "Text Editor" in script
    assert "devos-antigravity-studio.desktop" in script
    assert "devos-paint.desktop" in script
    assert "devos-scanner.desktop" in script
    assert "Password Manager" in script
    assert "kvantummanager" in script
    assert '"kolourpaint"' in script or '"org.kde.kolourpaint"' in script
    assert "Resource Monitor" in script
    assert "Storage Sense" in script
    assert "File Transfer" in script
    assert '"btop"' in script
    assert '"htop"' in script
    assert '"calamares"' in script
    assert "Phone Link" in script
    assert "devos-resources.desktop" in script


def test_installer_feature_catalog_uses_friendly_names():
    catalog = (
        ROOT / "build/includes.chroot/usr/local/share/devos/components/features/feature_catalog.py"
    ).read_text(encoding="utf-8", errors="replace")
    for needle in (
        '"Storage Sense"',
        '"Resource Monitor"',
        '"File Transfer"',
        '"PDF Viewer"',
        '"Password Manager"',
        '"PC Optimizer"',
        'builtin={"desktop": ["devos-photos.desktop"]}',
        'builtin={"desktop": ["devos-pdf.desktop"]}',
        'builtin={"desktop": ["devos-terminal.desktop"]}',
        'builtin={"desktop": ["devos-resources.desktop"]}',
    ):
        assert needle in catalog, needle
    assert "See what fills your disk (Filelight)" not in catalog
    assert 'builtin={"desktop": ["org.kde.gwenview.desktop"]}' not in catalog


def test_notes_and_notepad_icons_are_distinct():
    notes = (ICONS / "devos-notes.svg").read_text(encoding="utf-8", errors="replace")
    notepad = (ICONS / "devos-notepad.svg").read_text(encoding="utf-8", errors="replace")
    assert notes != notepad
    # Notes = amber sticky; Notepad = blue document
    assert "#f59e0b" in notes or "f59e0b" in notes
    assert "#3b82f6" in notepad or "3b82f6" in notepad
    assert "Icon=devos-notes" in (APPS / "devos-notes.desktop").read_text(encoding="utf-8")
    assert "Icon=devos-notepad" in (APPS / "devos-notepad.desktop").read_text(encoding="utf-8")
