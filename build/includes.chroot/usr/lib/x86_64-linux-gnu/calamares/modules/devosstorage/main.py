"""Apply reviewed data-disk choices after Calamares has mounted its own layout."""
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


def run():
    try:
        installer_storage.apply(selection(), libcalamares.globalstorage.value('rootMountPoint'),
                                libcalamares.globalstorage.value('partitions'))
    except Exception as exc:
        return ('Additional storage setup stopped', str(exc))
    return None
