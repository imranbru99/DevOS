from pathlib import Path
import json
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'components/cloudpc'))
from browser_launch import (
    discover_app_id,
    focus_existing_window,
    launch_command,
    launch_via_default_pwa,
    open_via_devos_pwa,
    restore_menu_entry,
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


def test_rewritten_shortcut_still_launches_app_id(tmp_path, monkeypatch):
    """An update replaces Exec with devos-windows-app and drops --app-id."""
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    app_id = 'e' * 32
    apps = tmp_path / 'applications'
    apps.mkdir()
    (apps / f'chrome-{app_id}-Default.desktop').write_text(
        "[Desktop Entry]\nName=Windows App\n"
        "Exec=/usr/local/bin/devos-windows-app\nNoDisplay=true\n"
    )
    with patch('browser_launch.browser_binary', return_value=('chrome', '/browser')):
        cmd = launch_command()
    assert f'--app-id={app_id}' in cmd
    assert not any(a.startswith('--app=') for a in cmd)
    assert not any(a.startswith('--user-data-dir=') for a in cmd)


def test_focus_existing_ignores_a_process_that_is_not_a_window(monkeypatch):
    monkeypatch.setattr('browser_launch.shutil.which', lambda cmd: None)

    def boom(*_args, **_kwargs):
        raise AssertionError('must not scan the process list')

    monkeypatch.setattr('browser_launch.subprocess.check_output', boom)
    assert focus_existing_window() is False


def test_focus_existing_raises_mapped_window(monkeypatch):
    calls = []
    monkeypatch.setattr(
        'browser_launch.shutil.which',
        lambda cmd: '/usr/bin/wmctrl' if cmd == 'wmctrl' else None,
    )

    def check_output(cmd, **_kwargs):
        assert cmd == ['wmctrl', '-lx']
        return (
            '0x0420000a 0 host chrome-windows.cloud.microsoft__-Default.Windows_App '
            'Windows App\n'
        )

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return type('R', (), {'returncode': 0})()

    monkeypatch.setattr('browser_launch.subprocess.check_output', check_output)
    monkeypatch.setattr('browser_launch.subprocess.run', run)
    assert focus_existing_window() is True
    assert calls == [['wmctrl', '-ia', '0x0420000a']]


def test_restore_menu_entry_drops_hidden_user_override(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.setattr('browser_launch.shutil.which', lambda _cmd: None)
    apps = tmp_path / 'applications'
    apps.mkdir()
    stub = apps / 'devos-web-winapp.desktop'
    stub.write_text('[Desktop Entry]\nType=Application\nHidden=true\nX-DevOS-Hidden=true\n')
    restore_menu_entry()
    assert not stub.exists()

    full = apps / 'devos-web-winapp.desktop'
    full.write_text(
        '[Desktop Entry]\nType=Application\nName=Windows App\n'
        'Exec=/usr/local/bin/devos-windows-app\nHidden=true\nNoDisplay=true\n'
    )
    restore_menu_entry()
    text = full.read_text()
    assert 'Exec=/usr/local/bin/devos-windows-app' in text
    assert 'Hidden=true' not in text
    assert 'NoDisplay=true' not in text


def test_pwa_helper_does_not_reenter(monkeypatch):
    monkeypatch.setenv('DEVOS_WINDOWS_APP_IN_PWA', '1')
    assert open_via_devos_pwa() is False


def test_profile_shortcut_uses_same_isolated_launcher(tmp_path):
    p=tmp_path/('chrome-'+'a'*32+'-Profile_2.desktop')
    p.write_text('[Desktop Entry]\nName=Windows App\nExec=chrome --app-id='+'a'*32+'\n')
    assert integrate(tmp_path,'/local/launcher')==1
    assert 'Exec=/local/launcher\n' in p.read_text()
    assert integrate(tmp_path,'/local/launcher')==0
