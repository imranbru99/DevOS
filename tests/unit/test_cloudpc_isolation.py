from pathlib import Path
import json
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'components/cloudpc'))
from browser_launch import (
    discover_app_id,
    launch_command,
    launch_via_default_pwa,
    PWA_NAV,
)
from launchers import integrate


def test_isolated_fallback_keeps_pwa_navigation_capturing(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    monkeypatch.setenv('DEVOS_WINDOWS_APP_ISOLATED','1')
    with patch('browser_launch.browser_binary',return_value=('chrome','/browser')):
        cmd=launch_command()
    assert '--user-data-dir='+str(tmp_path/'devos/windows-app/chrome') in cmd
    assert '--profile-directory=Default' in cmd
    assert ('--app=https://windows.cloud.microsoft/' in cmd) or any(a.startswith('--app-id=') for a in cmd)
    assert '--class=chrome-windows.cloud.microsoft__-Default' in cmd
    assert any(PWA_NAV in arg for arg in cmd)
    assert not any('force-dark' in arg or 'no-sandbox' in arg for arg in cmd)
    assert (tmp_path/'devos/windows-app/chrome').stat().st_mode & 0o777 == 0o700


def test_installed_pwa_uses_app_id_not_plain_app_url(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    app_id='a'*32
    apps=tmp_path/'applications'
    apps.mkdir(parents=True)
    (apps / f"chrome-{app_id}-Default.desktop").write_text(
        f"[Desktop Entry]\nName=Windows App\nExec=chrome --app-id={app_id}\n"
    )
    with patch('browser_launch.browser_binary',return_value=('chrome','/browser')):
        cmd=launch_command()
    assert f'--app-id={app_id}' in cmd
    assert not any(a.startswith('--app=https://') for a in cmd)
    assert any(PWA_NAV in arg for arg in cmd)
    assert not any(a.startswith('--user-data-dir=') for a in cmd)


def test_discover_app_id_from_chrome_preferences(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'share'))
    chrome = tmp_path / '.config/google-chrome/Default'
    chrome.mkdir(parents=True)
    app_id = 'c' * 32
    (chrome / 'Preferences').write_text(
        json.dumps({"web_apps": {"app_id": app_id, "url": "https://windows.cloud.microsoft/"}}),
        encoding='utf-8',
    )
    assert discover_app_id(None) == app_id


def test_default_pwa_launch_command_shape():
    with patch('browser_launch.browser_binary',return_value=('chrome','/browser')):
        cmd=launch_via_default_pwa('b'*32)
    assert cmd[0]=='/browser'
    assert '--app-id='+('b'*32) in cmd
    assert any(PWA_NAV in arg for arg in cmd)
    assert '--class=chrome-windows.cloud.microsoft__-Default' in cmd


def test_profile_shortcut_uses_same_isolated_launcher(tmp_path):
    p=tmp_path/('chrome-'+'a'*32+'-Profile_2.desktop')
    p.write_text('[Desktop Entry]\nName=Windows App\nExec=chrome --app-id='+'a'*32+'\n')
    assert integrate(tmp_path,'/local/launcher')==1
    assert 'Exec=/local/launcher\n' in p.read_text()
    assert integrate(tmp_path,'/local/launcher')==0
