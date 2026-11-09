#!/usr/bin/env python3
"""Inspect desktop resource policy or run a heavy job in its own bounded scope."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

POLICIES = {
    'session.slice': {'CPUWeight': '400', 'IOWeight': '200', 'MemoryAccounting': 'yes',
                      'MemoryLow': '8%'},
    'app.slice': {'CPUWeight': '100', 'IOWeight': '100', 'MemoryAccounting': 'yes',
                  'MemoryHigh': '92%', 'ManagedOOMMemoryPressure': 'auto',
                  'ManagedOOMMemoryPressureLimit': '80%', 'ManagedOOMSwap': 'kill'},
    'background.slice': {'CPUWeight': '10', 'IOWeight': '10', 'CPUQuota': '35%',
                         'MemoryAccounting': 'yes', 'MemoryHigh': '18%', 'MemoryMax': '25%',
                         'ManagedOOMMemoryPressure': 'kill',
                         'ManagedOOMMemoryPressureLimit': '35%', 'ManagedOOMSwap': 'kill'},
}


def memory_info(path=Path('/proc/meminfo')):
    fields = {}
    for line in path.read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree'):
            fields[key] = int(value.split()[0]) * 1024
    return fields


def heavy_budget(total, available):
    """Budget against both installed and currently available RAM, leaving headroom."""
    if total <= 0 or available < 512 * 1024**2:
        raise ValueError('Less than 512 MiB is available. Close an unused app before starting a heavy job.')
    high = int(min(total * .5, available * .6))
    maximum = int(min(total * .7, available * .8))
    return high, maximum


def scope_command(command, memory):
    if not command:
        raise ValueError('Supply a command after run --, for example: run -- make -j4')
    high, maximum = heavy_budget(memory['MemTotal'], memory['MemAvailable'])
    return ['systemd-run', '--user', '--scope', '--collect', '--quiet',
            '--unit=devos-heavy-' + uuid.uuid4().hex,
            '--slice=background.slice', '--property=CPUWeight=25', '--property=IOWeight=25',
            f'--property=MemoryHigh={high}', f'--property=MemoryMax={maximum}',
            '--property=OOMPolicy=kill', '--property=TasksMax=2048', '--', *command]


def read_status():
    result = {'memory_bytes': memory_info(), 'pressure': {}, 'slices': {}}
    for resource in ('cpu', 'memory', 'io'):
        try:
            result['pressure'][resource] = (Path('/proc/pressure') / resource).read_text().strip()
        except OSError:
            result['pressure'][resource] = None
    for unit in POLICIES:
        try:
            proc = subprocess.run(['systemctl', '--user', 'show', unit,
                                   '-p', 'CPUWeight', '-p', 'IOWeight', '-p', 'MemoryHigh',
                                   '-p', 'ManagedOOMMemoryPressure', '-p', 'ManagedOOMSwap',
                                   '-p', 'ControlGroup'], capture_output=True, text=True, timeout=5)
            if proc.returncode:
                result['slices'][unit] = {'error': proc.stderr.strip()}
                continue
            values = dict(line.split('=', 1) for line in proc.stdout.splitlines() if '=' in line)
            group = Path('/sys/fs/cgroup') / values.get('ControlGroup', '').lstrip('/')
            for name in ('cpu.weight', 'memory.high', 'io.weight'):
                try:
                    values[name] = (group / name).read_text().strip()
                except OSError:
                    values[name] = 'unavailable'
            result['slices'][unit] = values
        except (OSError, subprocess.TimeoutExpired) as error:
            result['slices'][unit] = {'error': str(error)}
    try:
        proc = subprocess.run(['systemctl', 'is-active', 'systemd-oomd'], capture_output=True, text=True, timeout=5)
        result['oomd'] = proc.stdout.strip() or 'unavailable'
    except (OSError, subprocess.TimeoutExpired):
        result['oomd'] = 'unavailable'
    return result


def install_user_policy(priority_only=False):
    # Check the bus before writing; never report a policy active on connection failure.
    subprocess.run(['systemctl', '--user', 'show-environment'], check=True, stdout=subprocess.DEVNULL)
    policies = {unit: {key: value for key, value in settings.items() if not priority_only or key in ('CPUWeight', 'IOWeight')}
                for unit, settings in POLICIES.items()}
    base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'systemd/user'
    for unit, settings in policies.items():
        directory = base / (unit + '.d')
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / ('90-devos-priority.conf' if priority_only else '90-devos-responsiveness.conf')
        backup = target.with_suffix('.conf.before-devos')
        if target.exists() and not backup.exists():
            shutil.copy2(target, backup)
        target.write_text('[Slice]\n' + ''.join(f'{key}={value}\n' for key, value in settings.items()))
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    for unit, settings in policies.items():
        subprocess.run(['systemctl', '--user', 'set-property', '--runtime', unit,
                        *[f'{key}={value}' for key, value in settings.items()]], check=True)
    print(json.dumps(read_status(), indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('status', help='Read live pressure, available RAM and effective slice policy')
    apply = sub.add_parser('apply', help='Install and activate desktop resource policy for the current user')
    apply.add_argument('--priority-only', action='store_true', help='Only CPU/I/O scheduling weights; no memory limits or OOM policy changes')
    run = sub.add_parser('run', help='Run a heavy job with lower priority and a memory budget; exceeding the hard budget can terminate this job')
    run.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == 'apply':
            install_user_policy(priority_only=args.priority_only)
        elif args.action == 'run':
            command = args.command[1:] if args.command[:1] == ['--'] else args.command
            invocation = scope_command(command, memory_info())
            if not shutil.which('systemd-run'):
                raise ValueError('systemd-run is unavailable; the job was not started without limits.')
            return subprocess.call(invocation)
        else:
            print(json.dumps(read_status(), indent=2))
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'DevOS responsiveness: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
