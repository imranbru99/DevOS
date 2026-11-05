import importlib.util
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('responsiveness', ROOT / 'components/optimizer/responsiveness.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
GiB = 1024**3


@pytest.mark.parametrize('total,available', [(2*GiB, GiB), (32*GiB, 25*GiB), (64*GiB, 2*GiB)])
def test_budget_leaves_available_headroom(total, available):
    high, maximum = r.heavy_budget(total, available)
    assert 0 < high < maximum <= available * .8
    assert maximum <= total * .7


def test_refuses_heavy_job_when_memory_is_already_low():
    with pytest.raises(ValueError):
        r.heavy_budget(8*GiB, 256*1024**2)


def test_scope_preserves_literal_arguments_and_isolates_whole_job():
    args = ['printf', '%s', '$(touch /tmp/not-executed)', '--property=CPUWeight=10000']
    command = r.scope_command(args, {'MemTotal': 8*GiB, 'MemAvailable': 4*GiB})
    assert command[command.index('--')+1:] == args
    assert '--property=OOMPolicy=kill' in command
    assert '--slice=background.slice' in command
    assert not any(arg.startswith('--property=CPUQuota') for arg in command)


def test_no_policy_written_when_session_bus_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])
    monkeypatch.setattr(r.subprocess, 'run', fail)
    assert r.main(['apply']) == 1
    assert not (tmp_path/'systemd').exists()


def test_live_apply_and_image_defaults_have_same_policy():
    import configparser
    for unit, settings in r.POLICIES.items():
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(ROOT / 'build/includes.chroot/etc/systemd/user' / (unit+'.d') / '20-devos-responsiveness.conf')
        assert dict(cfg['Slice']) == {k.lower(): v for k, v in settings.items()}


def test_missing_launcher_does_not_run_job_unbounded(monkeypatch):
    monkeypatch.setattr(r, 'memory_info', lambda: {'MemTotal': 8*GiB, 'MemAvailable': 4*GiB})
    monkeypatch.setattr(r.shutil, 'which', lambda _: None)
    monkeypatch.setattr(r.subprocess, 'call', lambda _: pytest.fail('Unbounded command executed'))
    assert r.main(['run', '--', 'true']) == 1


def test_priority_only_never_changes_memory_or_oom_policy(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    calls = []
    monkeypatch.setattr(r.subprocess, 'run', lambda args, **kwargs: calls.append(args))
    monkeypatch.setattr(r, 'read_status', lambda: {})
    r.install_user_policy(priority_only=True)
    for call in calls:
        assert not any('Memory' in arg or 'OOM' in arg for arg in call)
    files = list(tmp_path.rglob('*.conf'))
    assert len(files) == 3
    assert all('Memory' not in p.read_text() and 'OOM' not in p.read_text() for p in files)


def test_memory_reader_returns_byte_counts_only(tmp_path):
    meminfo = tmp_path/'meminfo'
    meminfo.write_text('MemTotal: 8388608 kB\nMemAvailable: 4194304 kB\nSwapTotal: 2097152 kB\nSwapFree: 2097152 kB\nHugePages_Total: 7\n')
    values = r.memory_info(meminfo)
    assert values == {'MemTotal': 8*GiB, 'MemAvailable': 4*GiB, 'SwapTotal': 2*GiB, 'SwapFree': 2*GiB}
