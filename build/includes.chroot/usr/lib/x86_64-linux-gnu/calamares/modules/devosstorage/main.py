"""Apply reviewed data-disk choices after Calamares has mounted its own layout.

Optional extra drives only. Failures here must never abort the install:
GRUB/bootloader already ran earlier in settings.conf, and DevOS on the system
disk must stay bootable even if mkfs.ext4 segfaults on a spare HDD/SSD.
"""
import json
import sys
from pathlib import Path
import libcalamares
sys.path.insert(0, '/usr/local/share/devos/components/settings')
import installer_storage


def selection():
    choice = libcalamares.globalstorage.value('packagechooser_storage') or ''
    if not choice or choice == 'Preserve all additional drives':
        return '{}'
    snapshot = json.loads(Path('/etc/calamares/branding/devos/storage-devices.json').read_text())
    return installer_storage.parse_choice(choice, snapshot)


def pretty_name():
    try:
        chosen = json.loads(selection())
        if chosen.get('confirmed'):
            return 'Apply selected data-drive plan (OS/manual disks excluded): ' + ', '.join(d['device'] for d in chosen.get('drives', []))
    except (OSError, ValueError, TypeError, KeyError):
        pass
    return 'Preserve additional data disks'


def pretty_status_message():
    return pretty_name()


def _warn(detail):
    try:
        libcalamares.utils.warning('Additional storage setup stopped (OS install continues): ' + detail)
    except Exception:
        pass
    try:
        Path('/tmp/devos-storage-warning.txt').write_text(
            'Extra data-drive formatting did not finish.\n'
            + detail
            + '\n\nDevOS itself already has the bootloader installed and continues. '
              'Format the extra disk later in Storage & Boot Doctor if needed.\n',
            encoding='utf-8',
        )
    except OSError:
        pass


def run():
    """Format optional extra data disks. Always return success to Calamares.

    Returning a (message, detail) tuple would show "Installation Failed" and
    stop the job queue. We never do that for optional storage — mkfs races on
    slow disks (segfault) must not block a bootable DevOS.
    """
    try:
        failures = installer_storage.apply(
            selection(),
            libcalamares.globalstorage.value('rootMountPoint'),
            libcalamares.globalstorage.value('partitions'),
        ) or []
        if failures:
            _warn('; '.join(failures))
    except Exception as exc:
        _warn(str(exc))
    # Always None = success. Optional data disks can be fixed after first boot.
    return None
