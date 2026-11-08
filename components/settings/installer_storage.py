"""Explicit additional-disk plans for the installer; default is to preserve disks."""
import json
import re
from pathlib import Path
import shutil
from disk_manager import DiskManager, parse_partition_parent
from storage_layout import plan_layout


def parse_choice(choice, snapshot):
    """Decode the human-readable installer summary against its root-owned scan."""
    if not choice or choice == 'Preserve all additional drives':
        return '{}'
    prefix = 'Erase selected additional drives (ext4):<br/>'
    suffix = '<br/>OS and manually configured disks are excluded.'
    if not choice.startswith(prefix) or not choice.endswith(suffix):
        raise ValueError('Storage selection is not a reviewed drive plan.')
    expected = {d['device']: d for d in snapshot}
    drives = []
    for line in choice[len(prefix):-len(suffix)].split('<br/>'):
        device, sep, volumes_text = line.partition(' → ')
        if not sep or device not in expected:
            raise ValueError('A selected disk is absent from the reviewed hardware scan.')
        volumes = []
        for description in volumes_text.split(' · '):
            match = re.fullmatch(r'([A-Za-z0-9][A-Za-z0-9 _.-]{0,15}) (remaining|[0-9]+(?:\.[0-9]+)? GiB)', description)
            if not match:
                raise ValueError('Invalid volume description in storage review.')
            label, size = match.groups()
            volumes.append({'label': label, 'filesystem': 'ext4',
                            'size_gib': 0 if size == 'remaining' else float(size[:-4])})
        original = expected[device]
        drives.append(dict(device=device, model=original['model'], serial=original.get('serial', ''),
                           size_bytes=original['size_bytes'], volumes=volumes))
    return json.dumps({'confirmed': True, 'drives': drives})


def protected_devices(partitions):
    """Disks already claimed or mounted by Calamares belong to its partition job."""
    protected = set()
    for part in partitions or []:
        if part.get('claimed') or part.get('mountPoint'):
            device = part.get('device', '')
            parent, _ = parse_partition_parent(device)
            protected.add(parent or device)
    return protected


def inventory():
    return [{'device': d['device'], 'model': d['model'], 'size_bytes': d['size_bytes'],
             'size_human': d['size_human'], 'serial': d.get('serial', ''),
             'read_only': d.get('read_only', False), 'is_live_media': d.get('is_live_media', False),
             'in_use': any(p.get('mounted') for p in d.get('partitions', []))}
            for d in DiskManager.get_storage_info()]


def prepare(raw, disks, partitions):
    """Validate the entire selection before any additional drive is erased."""
    plan = json.loads(raw or '{}')
    if not isinstance(plan, dict):
        raise ValueError('Invalid storage selection.')
    if plan.get('confirmed') is not True:
        return []
    selected = plan.get('drives', [])
    if not isinstance(selected, list) or len(selected) > 32:
        raise ValueError('Invalid drive selection.')
    if selected and (not isinstance(partitions, list) or not partitions):
        raise ValueError('The installer partition map is unavailable. Additional drives were left unchanged.')
    protected = protected_devices(partitions)
    current = {d['device']: d for d in disks}
    seen, ready = set(), []
    for selected_disk in selected:
        device = selected_disk['device']
        if device in seen:
            raise ValueError('A disk is selected more than once.')
        seen.add(device)
        disk = current.get(device)
        if disk is None:
            raise ValueError(f'{device} is no longer available. No additional drives were formatted.')
        if device in protected:
            continue  # The installation disk/manual layouts are handled by Calamares.
        if disk.get('is_live_media') or disk.get('is_system_disk') or disk.get('read_only'):
            raise ValueError(f'{device} is protected or read-only.')
        if any(p.get('mounted') or p.get('read_only') for p in disk.get('partitions', [])):
            raise ValueError(f'{device} is in use. Unmount it and review your plan.')
        if int(selected_disk['size_bytes']) != disk['size_bytes'] or selected_disk.get('serial', '') != disk.get('serial', '') or selected_disk.get('model') != disk.get('model'):
            raise ValueError(f'The identity or size of {device} changed. Review storage again.')
        volumes = selected_disk['volumes']
        if any(p.get('filesystem', 'ext4') != 'ext4' for p in volumes):
            raise ValueError('Automatic additional-drive formatting uses ext4.')
        plan_layout(disk['size_bytes'], volumes)
        ready.append((device, volumes, disk))
    if ready:
        missing = [p for p in ['parted', 'partprobe', 'wipefs', 'udevadm', 'mkfs.ext4'] if not shutil.which(p)]
        if missing:
            raise ValueError('Required storage tools are missing: ' + ', '.join(missing))
    return ready


def installed_owner(root_mount):
    for line in (Path(root_mount) / 'etc/passwd').read_text().splitlines():
        fields = line.split(':')
        if len(fields) >= 7 and fields[2].isdigit() and 1000 <= int(fields[2]) < 65534:
            return int(fields[2]), int(fields[3])
    raise ValueError('The installed desktop account is not available; data drives were left unchanged.')


def apply(raw, root_mount, partitions):
    """Format optional extra data disks.

    Returns a list of per-disk error strings. An empty list means every chosen
    disk succeeded (or nothing was selected). Callers must treat a non-empty
    list as a warning only — never as a reason to abort OS install / bootloader.
    """
    ready = prepare(raw, DiskManager.get_storage_info(), partitions)
    if not ready:
        return []
    owner = installed_owner(root_mount)
    failures = []
    for device, volumes, identity in ready:
        try:
            result = DiskManager.apply_solution(
                device, 'partition_storage', volumes=volumes, owner=owner, expected_identity=identity)
        except Exception as exc:
            failures.append(f'{device}: {exc}. Earlier completed disk changes are not rolled back.')
            continue
        if not result.get('success'):
            failures.append(
                f"{device}: {result.get('error', 'storage operation failed')}. "
                'Earlier completed disk changes are not rolled back.')
    return failures
