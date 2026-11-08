"""Free the install disk before Calamares runs sfdisk --wipe=always.

A second install (or a Windows Fast Startup / hibernated NTFS volume) often
leaves mounts or signatures that make sfdisk fail with a vague error. This
job force-unmounts, wipefs, and sgdisk --zap-all on the target disk only.
"""
import os
import re
import subprocess
import libcalamares


PREPARE = "/usr/local/sbin/devos-prepare-install-disk"


def pretty_name():
    return "Prepare install disk (unmount & clear signatures)"


def pretty_status_message():
    return pretty_name()


def _parent_disk(device):
    if not device or not str(device).startswith("/dev/"):
        return ""
    device = str(device)
    # /dev/nvme0n1p3 → /dev/nvme0n1 ; /dev/sda2 → /dev/sda ; /dev/mmcblk0p1 → /dev/mmcblk0
    m = re.match(r"^(/dev/(?:nvme\d+n\d+|mmcblk\d+|loop\d+))p\d+$", device)
    if m:
        return m.group(1)
    m = re.match(r"^(/dev/[a-z]+)\d+$", device)
    if m:
        return m.group(1)
    if re.match(r"^/dev/(?:nvme\d+n\d+|mmcblk\d+|[a-z]+)$", device):
        return device
    return device


def _target_disks():
    disks = set()
    boot = libcalamares.globalstorage.value("bootLoader") or {}
    if isinstance(boot, dict):
        path = boot.get("installPath") or ""
        parent = _parent_disk(path)
        if parent:
            disks.add(parent)
    for part in libcalamares.globalstorage.value("partitions") or []:
        if not isinstance(part, dict):
            continue
        device = part.get("device") or ""
        parent = _parent_disk(device)
        if not parent:
            continue
        # Erase / replace layouts always touch the parent disk.
        if part.get("mountPoint") in ("/", "/boot", "/boot/efi"):
            disks.add(parent)
        if part.get("claimed") or part.get("format") or part.get("wipe"):
            disks.add(parent)
    return sorted(disks)


def _run_prepare(disk):
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    try:
        proc = subprocess.run(
            ["bash", PREPARE, disk],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def run():
    if not os.path.isfile(PREPARE):
        libcalamares.utils.warning("devos-prepare-install-disk missing; skipping pre-wipe")
        return None

    disks = _target_disks()
    if not disks:
        # Still clear swap so a previous attempt cannot hold the next disk.
        subprocess.run(["swapoff", "-a"], check=False)
        return None

    errors = []
    for disk in disks:
        libcalamares.utils.debug("Preparing install disk " + disk)
        # Two attempts: automount can race the first pass.
        rc, detail = _run_prepare(disk)
        if rc != 0:
            rc, detail = _run_prepare(disk)
        if rc != 0:
            errors.append("%s: %s" % (disk, detail or ("exit %s" % rc)))
        else:
            try:
                libcalamares.utils.debug(detail)
            except Exception:
                pass

    # Restart udisks so the desktop stays usable after install jobs.
    subprocess.run(["systemctl", "start", "udisks2.service"], check=False)

    if errors:
        return (
            "Could not free the install disk for partitioning",
            "DevOS could not unmount or clear:\n"
            + "\n".join(errors)
            + "\n\nClose any open files on that SSD, disable Windows Fast Startup "
              "if you dual-boot, then try Install again. "
              "Or reboot from the USB and choose Erase disk once more.",
        )
    return None
