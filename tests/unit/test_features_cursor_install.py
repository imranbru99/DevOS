"""Cursor Features install must use official .deb, not missing Flatpak."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "features"))

import feature_catalog as catalog  # noqa: E402


def _by_id(fid: str) -> dict:
    return next(f for f in catalog.FEATURES if f["id"] == fid)


def test_cursor_uses_official_deb_script_not_flatpak():
    cursor = _by_id("cursor")
    assert cursor["script"] == "/usr/local/sbin/devos-install-cursor"
    assert cursor["flatpak"] == []
    assert "/usr/bin/cursor" in cursor["detect"]
    assert "cursor" in cursor["remove"]
    script = ROOT / "build/includes.chroot/usr/local/sbin/devos-install-cursor"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "api2.cursor.sh" in text
    assert "com.cursor.Cursor" not in text


def test_keepassxc_still_apt_backed():
    passwords = _by_id("passwords")
    assert "keepassxc" in passwords["apt"]
