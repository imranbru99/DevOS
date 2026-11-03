import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'components'))
from devos_appearance import light_stylesheet,Appearance
from PyQt5 import QtWidgets


def test_light_surfaces_text_and_action_contrast():
    result=light_stylesheet('QWidget {background:#0b1220;color:#f8fafc;border:1px solid #283344;} QPushButton {background:#0078d4;color:#ffffff;}')
    assert 'background: #ffffff' in result
    assert 'color: #172438' in result
    assert '#cbd5e1' in result
    assert 'background: #0078d4' in result
    assert 'color: #ffffff' in result


def test_style_roundtrip_and_new_dynamic_style():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    manager=Appearance(app);manager.mode='light'
    widget=QtWidgets.QWidget();original='background:#101828;color:#edf3fc;'
    widget.setStyleSheet(original);manager.style(widget)
    assert widget.styleSheet()!=original
    manager.mode='dark';manager.style(widget)
    assert widget.styleSheet()==original
    widget.setStyleSheet('color:#94a3b8;');manager.mode='light';manager.style(widget)
    assert '#475569' in widget.styleSheet() or '#172438' in widget.styleSheet()
    widget.deleteLater()


def test_native_kde_change_overrides_old_saved_mode(monkeypatch,tmp_path):
    from devos_appearance import current_mode
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path))
    (tmp_path/'devos').mkdir()
    (tmp_path/'devos/settings.json').write_text('{"appearance":{"theme":"dark"}}')
    (tmp_path/'kdeglobals').write_text('[General]\nColorScheme=DevOS-Light\n')
    assert current_mode()=='light'
