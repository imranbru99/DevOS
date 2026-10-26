"""Plan data volumes before any disk writes; shared by the storage UI/backend."""
from decimal import Decimal, InvalidOperation
import os
import pwd
import re
import shlex

MIB = 1024 ** 2
GIB = 1024 ** 3
FILESYSTEMS = {"ext4", "btrfs", "ntfs", "exfat", "vfat"}


def volume_label(label, filesystem):
    label = str(label).strip()
    limits = {"ext4": 16, "btrfs": 64, "ntfs": 32, "exfat": 15, "vfat": 11}
    if filesystem not in FILESYSTEMS:
        raise ValueError("Choose a supported filesystem.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]*", label) or len(label) > limits[filesystem]:
        raise ValueError(f"Use 1–{limits[filesystem]} letters, digits, spaces, dots, underscores or dashes for the volume label.")
    return label


def plan_layout(disk_bytes, volumes):
    """Return aligned extents, preserving 1 MiB at either end for GPT metadata.

    Only the final volume may request size_gib=0 to consume remaining space.
    This is a whole-disk replacement plan, never an in-place resize.
    """
    if not isinstance(volumes, list) or not 1 <= len(volumes) <= 8:
        raise ValueError("Choose between 1 and 8 data volumes.")
    end_limit = int(disk_bytes) // MIB - 1
    start = 1
    planned = []
    names = set()
    for index, spec in enumerate(volumes):
        fs = str(spec.get("filesystem", "ext4"))
        label = volume_label(spec.get("label", ""), fs)
        if label.casefold() in names:
            raise ValueError("Each volume needs a different label.")
        names.add(label.casefold())
        try:
            amount = Decimal(str(spec.get("size_gib", 0)))
            if not amount.is_finite() or amount < 0:
                raise ValueError("Partition sizes must be finite, positive numbers.")
            if amount == 0 and index != len(volumes) - 1:
                raise ValueError("Only the last volume can use remaining space.")
            end = end_limit if amount == 0 else start + int(amount * 1024)
        except (InvalidOperation, TypeError, OverflowError) as exc:
            raise ValueError("Enter valid partition sizes in GiB.") from exc
        if end - start < 64:
            raise ValueError("Every partition needs at least 64 MiB.")
        if end > end_limit:
            raise ValueError("The requested partitions do not fit on this disk.")
        planned.append({"label": label, "filesystem": fs, "start_mib": start,
                        "end_mib": end, "size_bytes": (end - start) * MIB})
        start = end
    return planned


def partition_device(device, number):
    return f"{device}{'p' if device[-1].isdigit() else ''}{number}"


def desktop_owner():
    """Return the invoking desktop account, including a sudo/pkexec invocation."""
    uid = os.getuid()
    if uid == 0:
        uid = int(os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID") or 0)
    account = pwd.getpwuid(uid)
    return account.pw_uid, account.pw_gid


def ownership_script(device, filesystem, owner):
    """Give only a freshly formatted Linux volume's top directory to its owner.

    Never recurse into existing files; Windows-compatible filesystems use the
    per-user udisks mount options instead of Unix on-disk ownership.
    """
    uid, gid = owner
    if filesystem not in ("ext4", "btrfs") or uid == 0:
        return ""
    dev = shlex.quote(device)
    return ("volume_mount=$(mktemp -d /run/devos-volume.XXXXXXXX)\n"
            'trap \'umount "$volume_mount" 2>/dev/null || true; rmdir "$volume_mount" 2>/dev/null || true\' EXIT\n'
            f'mount -o nodev,nosuid {dev} "$volume_mount"\n'
            f'chown {int(uid)}:{int(gid)} "$volume_mount"\n'
            'chmod 0750 "$volume_mount"\n'
            'umount "$volume_mount"\nrmdir "$volume_mount"\ntrap - EXIT\n')


def mkfs_command(device, filesystem, label):
    label = volume_label(label, filesystem)
    tool, flags = {
        "ext4": ("mkfs.ext4", ["-F", "-L"]),
        "btrfs": ("mkfs.btrfs", ["-f", "-L"]),
        "ntfs": ("mkfs.ntfs", ["-f", "-L"]),
        "exfat": ("mkfs.exfat", ["-n"]),
        "vfat": ("mkfs.vfat", ["-F32", "-n"]),
    }[filesystem]
    return shlex.join([tool, *flags, label, device])


def layout_script(device, planned, owner):
    """Build a validated whole-disk data layout; caller supplies safety checks."""
    dev = shlex.quote(device)
    commands = ["set -e", f"wipefs -a {dev}", f"parted {dev} --script mklabel gpt"]
    for number, part in enumerate(planned, 1):
        fs = part["filesystem"]
        parted_fs = {"exfat": "ntfs", "vfat": "fat32"}.get(fs, fs)
        commands.append(shlex.join(["parted", device, "--script", "mkpart", part["label"], parted_fs,
                                    f"{part['start_mib']}MiB", f"{part['end_mib']}MiB"]))
    commands += [f"partprobe {dev}", "udevadm settle"]
    for number, part in enumerate(planned, 1):
        target = partition_device(device, number)
        commands += [mkfs_command(target, part["filesystem"], part["label"]),
                     ownership_script(target, part["filesystem"], owner)]
    return "\n".join(commands) + "\n"


def system_layout_script(device, filesystem, label, uefi):
    """Prepare firmware-appropriate boot space and an unowned system filesystem."""
    if filesystem not in ('ext4', 'btrfs'):
        raise ValueError('DevOS system partitions require ext4 or btrfs.')
    label = volume_label(label, filesystem)
    commands = ['set -e', shlex.join(['wipefs','-a',device]), shlex.join(['parted',device,'--script','mklabel','gpt'])]
    if uefi:
        commands += [shlex.join(['parted',device,'--script','mkpart','DEVOS_EFI','fat32','1MiB','513MiB']),
                     shlex.join(['parted',device,'--script','set','1','esp','on'])]
        root_start = '513MiB'
    else:
        commands += [shlex.join(['parted',device,'--script','mkpart','BIOS_BOOT','1MiB','3MiB']),
                     shlex.join(['parted',device,'--script','set','1','bios_grub','on'])]
        root_start = '3MiB'
    commands += [shlex.join(['parted',device,'--script','mkpart',label,filesystem,root_start,'100%']),
                 shlex.join(['partprobe',device]), 'udevadm settle']
    if uefi:
        commands.append(mkfs_command(partition_device(device,1),'vfat','DEVOS_EFI'))
    commands += [mkfs_command(partition_device(device,2),filesystem,label),'udevadm settle']
    return '\n'.join(commands)+'\n'
