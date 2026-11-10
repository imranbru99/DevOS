#!/usr/bin/env python3
"""Installer selection must not force optional toys like emoji as always installed."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "features"))
import feature_catalog as catalog  # noqa: E402


def test_emoji_not_forced_base_feature():
    assert "emoji" not in catalog.BASE_FEATURE_IDS
    emoji = catalog.feature("emoji")
    assert emoji is not None
    assert emoji.get("builtin")


def test_remmina_is_not_labeled_windows_app():
    remmina = catalog.feature("remmina")
    assert remmina is not None
    assert remmina.get("windows") == "Remote Desktop"
    assert "Windows App" not in (remmina.get("windows") or "")
    winapp = catalog.feature("winapp")
    assert winapp is not None
    assert winapp.get("windows") == "Windows App"


def test_webcam_is_base_os_feature_not_installer_card():
    assert "webcam" in catalog.BASE_FEATURE_IDS
    cam = catalog.feature("webcam")
    assert cam is not None
    assert cam.get("preinstalled") is True
    js = (ROOT / "build/includes.chroot/etc/calamares/branding/devos/features-catalog.js").read_text(
        encoding="utf-8"
    )
    assert '"id": "webcam"' not in js and '"id":"webcam"' not in js
    assert "kamoso" in (ROOT / "build/package-lists/10-hardware.list.chroot").read_text(encoding="utf-8")
    assert "v4l-utils" in (ROOT / "build/package-lists/10-hardware.list.chroot").read_text(encoding="utf-8")
    users = (ROOT / "build/includes.chroot/etc/calamares/modules/usersq.conf").read_text(encoding="utf-8")
    for group in ("audio", "video", "input"):
        assert group in users


def test_essential_preset_does_not_tag_minimal():
    assert "minimal" not in catalog.ESSENTIAL
    libre = catalog.feature("libreoffice")
    assert libre is not None
    assert "minimal" not in libre.get("presets", [])


def test_featuresq_minimal_picks_nothing():
    qml = (ROOT / "build/includes.chroot/etc/calamares/branding/devos/featuresq.qml").read_text(
        encoding="utf-8"
    )
    assert 'p === "minimal"' in qml
    assert "picked = [];" in qml
    # Old bug: selecting every feature tagged "minimal".
    assert "presets.indexOf(\"minimal\")" not in qml


def test_emoji_desktop_hidden_by_default():
    desk = (ROOT / "build/includes.chroot/usr/share/applications/devos-emoji.desktop").read_text(
        encoding="utf-8"
    )
    assert "Hidden=true" in desk
    assert "X-DevOS-Hidden=true" in desk


def test_plasma_emojier_hidden_in_debrand():
    script = (ROOT / "build/includes.chroot/usr/local/sbin/devos-debrand-desktop").read_text(
        encoding="utf-8"
    )
    assert '"org.kde.plasma.emojier"' in script
    # Must be in the upstream HIDE set, not promoted as a Start-menu rename.
    hide_chunk = script.split("\nHIDE = {", 1)[1].split("}", 1)[0]
    assert "org.kde.plasma.emojier" in hide_chunk
    assert "libreoffice-calc" not in hide_chunk  # optional apps use OPTIONAL_APPS_HIDDEN


def test_wrapper_icons_are_unique_devos_branded():
    apps = ROOT / "build/includes.chroot/usr/share/applications"
    icons_dir = ROOT / "build/includes.chroot/usr/share/icons/hicolor/scalable/apps"
    wrappers = [
        "devos-calculator.desktop",
        "devos-photos.desktop",
        "devos-snip.desktop",
        "devos-zip.desktop",
        "devos-editor.desktop",
        "devos-paint.desktop",
        "devos-thispc.desktop",
    ]
    seen = {}
    for name in wrappers:
        text = (apps / name).read_text(encoding="utf-8")
        icon = next(line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith("Icon="))
        assert icon.startswith("devos-"), f"{name} should use a DevOS icon, got {icon}"
        assert (icons_dir / f"{icon}.svg").is_file(), f"missing icon asset for {icon}"
        seen.setdefault(icon, []).append(name)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, f"shared icons across different apps: {dupes}"


def test_features_catalog_js_lists_emoji_after_regen():
    js = (ROOT / "build/includes.chroot/etc/calamares/branding/devos/features-catalog.js").read_text(
        encoding="utf-8"
    )
    assert '"id": "emoji"' in js or '"id":"emoji"' in js
