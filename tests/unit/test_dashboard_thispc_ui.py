#!/usr/bin/env python3
"""Dashboard contrast tokens + This PC drive card layout sanity."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS = ROOT / "components/dashboard/static/style.css"
CSS_CHROOT = (
    ROOT / "build/includes.chroot/usr/local/share/devos/components/dashboard/static/style.css"
)
FILES = ROOT / "build/includes.chroot/usr/local/bin/devos-files"


def test_dashboard_controls_use_text_tokens_not_hardcoded_white():
    for path in (CSS, CSS_CHROOT):
        text = path.read_text(encoding="utf-8")
        # Critical light-mode offenders must use theme tokens.
        assert ".key-btn" in text
        assert "color: var(--text-main)" in text
        assert ".disk-name" in text
        assert ".part-dev" in text
        assert ".part-mount" in text
        assert "var(--accent-emerald)" in text
        # Unscoped dark-only white on inputs should be gone.
        assert "color: #fff;" not in text.split(".key-btn")[1].split("}")[0]
        assert "#command-dialog" in text and "var(--bg-card)" in text
        assert ".loading-state" in text
        # Alert / offline titles follow theme accents (readable in light mode).
        assert "alert-warning .issue-title" in text
        assert "var(--accent-amber)" in text
        assert "var(--accent-emerald)" in text
        assert "html[data-theme=\"light\"] .btn-secondary" in text


def test_help_center_contact_styles_avoid_hex8():
    about = (ROOT / "components/about/about.py").read_text(encoding="utf-8")
    assert "QPushButton#contactBtn" in about
    assert "rgba(14, 165, 233" in about
    # CSS-style 8-digit hex washes break Qt (read as AARRGGBB).
    assert "#0ea5e922" not in about
    assert "#0ea5e914" not in about
    assert "#0ea5e955" not in about


def test_thispc_drive_cards_capped_and_styles_persist():
    src = FILES.read_text(encoding="utf-8")
    assert "setMaximumWidth(420)" in src
    assert "QSizePolicy.Preferred" in src
    assert "(self.drives_grid, 280, 3)" in src
    # Drive/folder card rules must live in _apply_appearance (not wiped).
    apply = src.split("def _apply_appearance", 1)[1]
    assert "#driveCard" in apply
    assert "QLabel#driveTitle" in apply
    assert "QProgressBar#driveBar" in apply
    assert "background: #202020" not in src
