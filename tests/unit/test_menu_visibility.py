"""Unticked Features must not leave Calc / Fingerprint / etc. in All Applications."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "features"))

import feature_catalog as catalog  # noqa: E402


def test_libreoffice_owns_calc_menu_entry():
    lo = catalog.feature("libreoffice")
    desks = catalog.feature_desktops(lo)
    assert "libreoffice-calc.desktop" in desks
    assert "libreoffice-writer.desktop" in desks
    assert "libreoffice-impress.desktop" in desks


def test_fingerprint_menu_hidden_until_chosen():
    fp = catalog.feature("fingerprint")
    assert "devos-fingerprint.desktop" in catalog.feature_desktops(fp)
    assert "ESSENTIAL" not in str(fp["presets"]) or "windows" in fp["presets"]
    assert fp["preinstalled"] is False or not fp.get("preinstalled")
    # Not forced onto every Normal PC via ESSENTIAL anymore.
    assert "normal" not in fp["presets"] or "windows" in fp["presets"]
    text = (
        ROOT / "build/includes.chroot/usr/share/applications/devos-fingerprint.desktop"
    ).read_text(encoding="utf-8")
    assert "X-DevOS-Hidden=true" in text
    assert "TryExec=/usr/bin/fprintd" in text


def test_debrand_feature_hides_libreoffice():
    script = (
        ROOT / "build/includes.chroot/usr/local/sbin/devos-debrand-desktop"
    ).read_text(encoding="utf-8")
    assert "OPTIONAL_APPS_HIDDEN" in script
    assert "libreoffice-calc" in script
    assert "X-DevOS-Hidden=true" in script


def test_ai_models_wrapper_opens_gui():
    wrapper = (
        ROOT / "build/includes.chroot/usr/local/bin/devos-ai-models"
    ).read_text(encoding="utf-8")
    assert "models_gui.py" in wrapper
    assert '""|--gui)' in wrapper or "\"\"|--gui)" in wrapper


def test_apphub_has_gui_launcher():
    desk = (
        ROOT / "build/includes.chroot/usr/share/applications/devos-apphub.desktop"
    ).read_text(encoding="utf-8")
    assert "devos-apphub" in desk
    assert (
        ROOT / "build/includes.chroot/usr/local/share/devos/components/apphub/apphub_gui.py"
    ).is_file()
    assert (ROOT / "build/includes.chroot/usr/local/bin/devos-apphub").is_file()


def test_fprintd_not_forced_in_hardware_list():
    hw = (ROOT / "build/package-lists/10-hardware.list.chroot").read_text(encoding="utf-8")
    assert not any(
        line.strip() == "fprintd" or line.strip() == "libpam-fprintd"
        for line in hw.splitlines()
    )
