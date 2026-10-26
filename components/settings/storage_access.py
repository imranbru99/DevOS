"""Check user write access without changing ownership or filesystem mount flags."""
import argparse
import errno
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

CAUSES = {
    errno.EACCES: 'permission_denied', errno.EPERM: 'permission_denied',
    errno.EROFS: 'read_only_filesystem', errno.ENOSPC: 'disk_or_inodes_full',
    errno.EDQUOT: 'quota_exceeded', errno.EIO: 'disk_io_error',
}


def check_directory(path):
    filename = None
    try:
        # The probe uses the same effective account as the desktop application.
        fd, filename = tempfile.mkstemp(prefix='.devos-write-probe-', dir=path)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(b'DevOS storage access check\n')
            stream.flush()
            os.fsync(stream.fileno())
        return {'path': str(path), 'writable': True}
    except OSError as exc:
        return {'path': str(path), 'writable': False,
                'cause': CAUSES.get(exc.errno, 'write_error'), 'error': str(exc)}
    finally:
        if filename:
            try:
                os.unlink(filename)
            except OSError:
                pass


def check_home(home=None):
    home = Path(home or Path.home())
    paths = [home]
    for relative in ('.config', '.cache', '.local', '.local/share'):
        path = home / relative
        if path.exists():
            paths.append(path)
    results = [check_directory(p) for p in paths]
    return {'success': all(r['writable'] for r in results), 'checks': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        print('Run as the desktop account; a root write test does not validate user permissions.')
        return 1
    report = check_home()
    print(json.dumps(report, indent=2))
    if not report['success'] and args.notify and shutil.which('notify-send'):
        failed = [r for r in report['checks'] if not r['writable']]
        detail = '; '.join(r['path'] + ': ' + r['cause'].replace('_', ' ') for r in failed)
        try:
            subprocess.run(['notify-send', '--urgency=critical', 'DevOS storage needs attention', detail], timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            pass
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
