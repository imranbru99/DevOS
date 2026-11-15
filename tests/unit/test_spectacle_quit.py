#!/usr/bin/env python3
"""Spectacle should quit/hide after Copy or Save (no leftover editor window)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "build/includes.chroot/etc/xdg/spectaclerc"
SKEL = ROOT / "build/includes.chroot/etc/skel/.config/spectaclerc"


def test_quit_after_save_copy_enabled():
    for path in (SYSTEM, SKEL):
        text = path.read_text(encoding="utf-8")
        assert "quitAfterSaveCopyExport=true" in text
        assert "quitAfterSaveCopyExport=false" not in text
