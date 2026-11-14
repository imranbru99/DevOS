"""Antigravity IDE must not share the main Google Antigravity binary identity."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_kde_launcher_prefers_dedicated_ide_binary():
    text = (ROOT / "build/includes.chroot/usr/local/bin/antigravity-kde").read_text(encoding="utf-8")
    assert "/usr/local/lib/antigravity-ide/antigravity-ide" in text
    assert "CHROME_DESKTOP" in text
    assert "--user-data-dir=" in text
    assert "Antigravity-KDE" in text
    assert "GEMINI_APP_DATA_DIR=\"antigravity-kde\"" in text
    # Must not prefer the old recursive stub path before a real binary.
    assert "share/devos/antigravity-ide/bin/antigravity-ide" not in text


def test_install_script_builds_dedicated_tree_and_patches_product():
    text = (ROOT / "build/includes.chroot/usr/local/sbin/devos-install-antigravity-kde").read_text(
        encoding="utf-8"
    )
    assert 'IDE_ROOT=/usr/local/lib/antigravity-ide' in text
    assert "applicationName" in text
    assert "antigravity-ide" in text
    assert "cp -al" in text
    # Must not recreate the recursive wrapper that execs antigravity-kde again.
    assert "exec /usr/local/bin/antigravity-kde" not in text


def test_live_fix_helper_runs_install():
    text = (ROOT / "build/includes.chroot/usr/local/bin/devos-fix-antigravity-split").read_text(
        encoding="utf-8"
    )
    assert "devos-install-antigravity-kde" in text
    assert "Antigravity IDE" in text
