from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'components/cloudpc'))
from browser_launch import launch_command
from launchers import integrate


def test_persistent_separate_profile_and_no_forced_theme(tmp_path,monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME',str(tmp_path))
    with patch('browser_launch.browser_binary',return_value=('chrome','/browser')):
        cmd=launch_command()
    assert '--user-data-dir='+str(tmp_path/'devos/windows-app/chrome') in cmd
    assert '--profile-directory=Default' in cmd
    assert ('--app=https://windows.cloud.microsoft/' in cmd) or any(a.startswith('--app-id=') for a in cmd)
    assert '--class=chrome-windows.cloud.microsoft__-Default' in cmd
    assert not any('force-dark' in arg or 'no-sandbox' in arg for arg in cmd)
    assert (tmp_path/'devos/windows-app/chrome').stat().st_mode & 0o777 == 0o700


def test_profile_shortcut_uses_same_isolated_launcher(tmp_path):
    p=tmp_path/('chrome-'+'a'*32+'-Profile_2.desktop')
    p.write_text('[Desktop Entry]\nName=Windows App\nExec=chrome --app-id='+'a'*32+'\n')
    assert integrate(tmp_path,'/local/launcher')==1
    assert 'Exec=/local/launcher\n' in p.read_text()
    assert integrate(tmp_path,'/local/launcher')==0
