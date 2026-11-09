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

    warnings = []
    for disk in disks:
        libcalamares.utils.debug("Preparing install disk " + disk)
        # Three escalating attempts: automount / Fast Startup / udev races.
        rc, detail = 1, ""
        for attempt in range(1, 4):
            rc, detail = _run_prepare(disk)
            if rc == 0:
                break
            libcalamares.utils.warning(
                "prepare attempt %s failed for %s — auto retry" % (attempt, disk)
            )
            subprocess.run(["sleep", str(attempt)], check=False)
        if rc != 0:
            # Plan B: continue anyway. Partition may still succeed after a
            # partial wipe; aborting here forced "Installation Failed" with
            # a disk that was often already free enough for sfdisk.
            warnings.append("%s: %s" % (disk, detail or ("exit %s" % rc)))
            try:
                os.makedirs("/var/lib/DevOS", exist_ok=True)
                with open("/var/lib/DevOS/install-warnings", "a", encoding="utf-8") as fh:
                    fh.write("prepare-degraded: %s\n" % disk)
            except OSError:
                pass
            libcalamares.utils.warning(
                "Continuing install after prepare warnings on %s (auto fallback)" % disk
            )
        else:
            try:
                libcalamares.utils.debug(detail)
            except Exception:
                pass

    # Restart udisks so the desktop stays usable after install jobs.
    subprocess.run(["systemctl", "start", "udisks2.service"], check=False)

    if warnings:
        libcalamares.utils.warning(
            "Disk prepare used degraded fallback:\n" + "\n".join(warnings)
        )
    # Never hard-fail: partition is the next gate and will report real errors.
    return None
