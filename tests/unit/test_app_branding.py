#!/usr/bin/env python3
"""DevOS app icons / desktop launchers must not look like raw python3."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPS = ROOT / "build/includes.chroot/usr/share/applications"
ICONS = ROOT / "build/includes.chroot/usr/share/icons/hicolor/scalable/apps"


def test_devos_desktops_use_branded_icons_and_wmclass():
    desks = list(APPS.glob("devos-*.desktop"))
    assert desks, "expected DevOS desktop files"
    for path in desks:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "NoDisplay=true" in text and "Hidden=true" in text:
            continue
        assert "Icon=devos-" in text or "Icon=/usr/" in text, path.name
        # Primary Exec must not be bare python3 for menu apps with a Name=
        for line in text.splitlines():
            if line.startswith("Exec=") and "python3" in line and "devos-run" not in line:
                # Allowed only if still transitioning; prefer failure for first Exec
                assert False, f"{path.name} still launches via bare python3: {line}"


def test_branded_icons_exist_for_desktop_references():
    needed = set()
    for path in APPS.glob("devos-*.desktop"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Icon=devos-"):
                needed.add(line.split("=", 1)[1].strip())
    missing = [n for n in sorted(needed) if not (ICONS / f"{n}.svg").is_file()]
    assert not missing, f"missing icons: {missing}"


def test_app_identity_prepare_rewrites_argv0(monkeypatch):
    import sys

    sys.path.insert(0, str(ROOT / "components"))
    import app_identity

    monkeypatch.setattr(sys, "argv", ["python3", "--flag"])
    app_identity.prepare("devos-clipboard")
    assert sys.argv[0] == "devos-clipboard"
