"""Install and verify GRUB on the Calamares target before it is unmounted."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import libcalamares


def pretty_name():
    return "Install bootloader"


def pretty_status_message():
    return "Installing bootloader on the new disk…"


def _warn(root: Path, message: str) -> None:
    libcalamares.utils.warning("devosbootloader: " + message)
    try:
        path = root / "var/lib/DevOS/install-warnings"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("bootloader: " + message + "\n")
    except OSError:
        pass


def _parent_disk(device: str) -> str:
    if not device or not str(device).startswith("/dev/"):
        return ""
    device = str(device)
    m = re.match(r"^(/dev/(?:nvme\d+n\d+|mmcblk\d+|loop\d+))p\d+$", device)
    if m:
        return m.group(1)
    m = re.match(r"^(/dev/[a-z]+)\d+$", device)
    if m:
        return m.group(1)
    if re.match(r"^/dev/(?:nvme\d+n\d+|mmcblk\d+|[a-z]+)$", device):
        return device
    return device


def _install_disk() -> str:
    boot = libcalamares.globalstorage.value("bootLoader") or {}
    if isinstance(boot, dict):
        parent = _parent_disk(boot.get("installPath") or "")
        if parent:
            return parent
    for part in libcalamares.globalstorage.value("partitions") or []:
        if not isinstance(part, dict):
            continue
        if part.get("mountPoint") == "/":
            parent = _parent_disk(part.get("device") or "")
            if parent:
                return parent
    return ""


def _host_run(cmd, timeout=180) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()



def _target_run(root: Path, command: list[str], timeout: int = 120) -> tuple[int, str]:
    return _host_run(["chroot", str(root), *command], timeout=timeout)


def _run_checked(root: Path, command: list[str], timeout: int = 120) -> str:
    result, output = _target_run(root, command, timeout)
    if result:
        raise RuntimeError(f"{command[0]} failed ({result}): {output[-1500:]}")
    return output


def _grub_cfg_ok(root: Path, root_args: set[str]) -> bool:
    config = root / "boot/grub/grub.cfg"
    if not config.is_file() or not root_args:
        return False

    # Validate actual kernel/initrd pairs for the selected root. A comment
    # mentioning linux, or a submenu without a usable entry, is insufficient.
    version = ""
    for line in config.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if not fields:
            continue
        if fields[0] == "menuentry":
            version = ""
        elif fields[0] in ("linux", "linuxefi"):
            version = ""
            if len(fields) < 3 or not root_args.intersection(fields[2:]):
                continue
            kernel = Path(fields[1]).name
            if kernel.startswith("vmlinuz-") and (root / "boot" / kernel).is_file():
                version = kernel.removeprefix("vmlinuz-")
        elif version and fields[0] in ("initrd", "initrdefi"):
            image = f"initrd.img-{version}"
            if any(Path(field).name == image for field in fields[1:]):
                path = root / "boot" / image
                if path.is_file() and path.stat().st_size > 0:
                    return True
    return False


def run():
    target = libcalamares.globalstorage.value("rootMountPoint")
    if not target or not os.path.ismount(target):
        return "Bootloader failed", "The installed system is not mounted."

    root = Path(target).resolve()
    uefi = os.path.isdir("/sys/firmware/efi")
    try:
        root_uuid = _run_checked(root, ["grub-probe", "--target=fs_uuid", "/"], 20)
        if not root_uuid:
            raise RuntimeError("Could not identify the installed root filesystem.")
        root_args = {f"root=UUID={root_uuid}"}
        if uefi:
            esp = root / "boot/efi"
            rc, _ = _host_run(["findmnt", "-n", "--mountpoint", str(esp)], 15)
            if rc:
                raise RuntimeError("The selected EFI system partition is not mounted.")
            _run_checked(root, ["grub-install", "--target=x86_64-efi",
                                "--efi-directory=/boot/efi", "--bootloader-id=DevOS",
                                "--no-nvram", "--recheck", "--force"])
        else:
            disk = _install_disk()
            if not disk:
                raise RuntimeError("No disk was selected for BIOS GRUB installation.")
            _run_checked(root, ["grub-install", "--target=i386-pc", "--recheck", disk])

        _run_checked(root, ["grub-mkconfig", "-o", "/boot/grub/grub.cfg"], 180)
        _run_checked(root, ["grub-script-check", "/boot/grub/grub.cfg"], 20)
        # Ubuntu's generator can use a device or PARTUUID when udev has
        # not populated the UUID links, or when the root uses device mapper.
        for probe, prefix in (("device", ""), ("partuuid", "PARTUUID=")):
            rc, value = _target_run(root, ["grub-probe", f"--target={probe}", "/"], 20)
            if rc == 0 and len(value.split()) == 1:
                root_args.add(f"root={prefix}{value}")
        if not _grub_cfg_ok(root, root_args):
            raise RuntimeError("GRUB has no kernel and initramfs entry for the installed root.")

        if uefi:
            _run_checked(root, ["/bin/bash", "/usr/local/sbin/devos-install-efi-fallback"])
            rc, output = _host_run(
                ["/bin/bash", "/usr/local/sbin/devos-set-boot-order", str(esp)], 105
            )
            if rc:
                if not (esp / "EFI/BOOT/.devos-fallback").is_file():
                    raise RuntimeError("Could not register the selected EFI partition. "
                                       "The existing fallback loader was preserved. " + output[-1200:])
                _warn(root, "Could not verify UEFI NVRAM. Use the disk's EFI fallback "
                      "or Boot Override if needed. " + output[-1200:])

    except (OSError, RuntimeError) as exc:
        _warn(root, str(exc))
        return "Bootloader failed", str(exc)

    return None
