"""Main DevOS windows must keep min/max/close and fit any screen."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app_identity import decorate_window, fit_to_screen, show_window  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    return app


def test_decorate_window_forces_close_minmax(qt_app):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QWidget

    win = QWidget()
    win.setWindowFlags(Qt.Window)
    decorate_window(win)
    flags = win.windowFlags()
    assert flags & Qt.WindowCloseButtonHint
    assert flags & Qt.WindowMinMaxButtonsHint
    assert flags & Qt.WindowTitleHint
    assert not (flags & Qt.FramelessWindowHint)
    win.deleteLater()


def test_decorate_window_clears_accidental_frameless(qt_app):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QMainWindow

    win = QMainWindow()
    win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    decorate_window(win)
    assert not (win.windowFlags() & Qt.FramelessWindowHint)
    assert win.windowFlags() & Qt.WindowCloseButtonHint
    win.deleteLater()


def test_fit_to_screen_clamps_oversized_geometry(qt_app):
    from PyQt5.QtWidgets import QWidget

    win = QWidget()
    win.setGeometry(-200, -100, 8000, 5000)
    fit_to_screen(win, margin=10, max_ratio=0.9, min_width=200, min_height=160)
    geo = win.geometry()
    assert geo.width() <= 8000
    assert geo.width() >= 200
    assert geo.height() >= 160
    assert geo.x() >= -10
    assert geo.y() >= -10
    win.deleteLater()


def test_show_window_applies_chrome(qt_app):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QWidget

    win = QWidget()
    win.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    show_window(win, fit=True)
    assert win.windowFlags() & Qt.WindowCloseButtonHint
    assert not (win.windowFlags() & Qt.FramelessWindowHint)
    win.close()
    win.deleteLater()


def test_show_window_shrinks_below_original_minimum(qt_app, monkeypatch):
    from PyQt5.QtCore import QRect
    from PyQt5.QtWidgets import QWidget

    work_area = QRect(0, 0, 1024, 560)
    monkeypatch.setattr("app_identity.available_screen_rect", lambda window: work_area)
    win = QWidget()
    win.setMinimumSize(1100, 760)
    show_window(win)
    assert work_area.contains(win.frameGeometry())
    win.close()
    win.deleteLater()


def test_kwinrc_keeps_titlebar_when_maximized():
    for relative in (
        "build/includes.chroot/etc/xdg/kwinrc",
        "build/includes.chroot/etc/skel/.config/kwinrc",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "BorderlessMaximizedWindows=false" in text
        assert "ButtonsOnRight=IAX" in text


def test_apply_desktop_reenforces_window_chrome():
    text = (ROOT / "build/includes.chroot/usr/local/bin/devos-apply-desktop").read_text(encoding="utf-8")
    assert "BorderlessMaximizedWindows" in text
    assert "ButtonsOnRight" in text
    assert "IAX" in text
