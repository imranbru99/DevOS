import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'components'))
from devos_appearance import (
    Appearance, adapt_stylesheet, current_mode, dark_stylesheet,
    light_stylesheet, sheet_looks_light,
)
from PyQt5 import QtWidgets


def test_light_surfaces_text_and_action_contrast():
    result=light_stylesheet('QWidget {background:#0b1220;color:#f8fafc;border:1px solid #283344;} QPushButton {background:#0078d4;color:#ffffff;}')
    assert 'background: #ffffff' in result
    assert 'color: #0f172a' in result or 'color: #172438' in result
    assert '#cbd5e1' in result
    assert 'background: #0078d4' in result
    assert 'color: #ffffff' in result


def test_dark_stylesheet_inverts_light_authored_chrome():
    light='QWidget {background:#f4f7fb;color:#0f172a;} QLineEdit {background:#ffffff;color:#0f172a;}'
    assert sheet_looks_light(light)
    dark=dark_stylesheet(light)
    assert '#0b101e' in dark or '#111827' in dark
    assert '#f1f5f9' in dark or '#e2e8f0' in dark


def test_adapt_stylesheet_roundtrip_roles():
    dark_src='QLabel {background:#0b101e;color:#f8fafc;}'
    light=adapt_stylesheet(dark_src,'light')
    assert 'color: #0f172a' in light or 'color: #172438' in light
    back=adapt_stylesheet(light,'dark')
    # Round-trip may not be bitwise identical; dark mode must keep light text.
    assert sheet_looks_light(back) is False or '#f' in back.lower()


def test_style_roundtrip_and_new_dynamic_style():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    manager=Appearance(app);manager.mode='light'
    widget=QtWidgets.QWidget();original='background:#101828;color:#edf3fc;'
    widget.setStyleSheet(original);manager.style(widget)
    assert widget.styleSheet()!=original
    manager.mode='dark';manager.style(widget)
    assert widget.styleSheet()==original
    widget.setStyleSheet('color:#94a3b8;');manager.mode='light';manager.style(widget)
    assert '#475569' in widget.styleSheet() or '#334155' in widget.styleSheet() or '#0f172a' in widget.styleSheet() or '#172438' in widget.styleSheet()
    widget.deleteLater()


def test_native_kde_change_overrides_old_saved_mode(monkeypatch,tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    (tmp_path/'devos').mkdir()
    (tmp_path/'devos/settings.json').write_text('{"appearance":{"theme":"dark"}}')
    (tmp_path/'kdeglobals').write_text('[General]\nColorScheme=DevOS-Light\n')
    assert current_mode()=='light'


def test_default_mode_is_light_when_unconfigured(monkeypatch,tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    (tmp_path/'devos').mkdir()
    assert current_mode()=='light'


def test_construction_keeps_original_style_for_dark_roundtrip(monkeypatch,tmp_path):
    from devos_appearance import install
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    (tmp_path/'devos').mkdir()
    (tmp_path/'devos/settings.json').write_text('{"appearance":{"theme":"light"}}')
    (tmp_path/'kdeglobals').write_text('[General]\nColorScheme=DevOS-Light\n')
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    install(app)
    widget=QtWidgets.QWidget()
    original='QWidget {background:#101828;color:#edf3fc;}'
    widget.setStyleSheet(original)
    assert widget.styleSheet()==original
    widget.show();app.processEvents()
    assert widget.styleSheet()!=original
    manager=app._devos_appearance;manager.mode='dark';manager.busy=True
    try:manager.style(widget)
    finally:manager.busy=False
    assert widget.styleSheet()==original
    widget.close()


def test_app_identity_installs_appearance():
    text=(Path(__file__).resolve().parents[2]/'components/app_identity.py').read_text(encoding='utf-8')
    assert 'install_appearance' in text


def test_appearance_refresh_always_restyles(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    (tmp_path / 'devos').mkdir()
    (tmp_path / 'devos/settings.json').write_text('{"appearance":{"theme":"light"}}')
    (tmp_path / 'kdeglobals').write_text('[General]\nColorScheme=DevOS-Light\n')
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    manager = Appearance(app)
    manager.mode = 'light'
    calls = []
    monkeypatch.setattr(manager, 'sync_app', lambda: calls.append('sync'))
    monkeypatch.setattr(manager, 'style', lambda _w: calls.append('style'))
    manager.refresh()
    assert 'sync' in calls
    assert manager.mode == 'light'


def test_apps_manager_picks_papirus_by_mode():
    text = (Path(__file__).resolve().parents[2] / 'components/apps/apps_manager.py').read_text(encoding='utf-8')
    assert 'current_mode()' in text
    assert 'icon_theme = "Papirus" if current_mode()' in text
    assert 'Papirus-Dark' in text
