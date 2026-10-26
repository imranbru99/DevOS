#!/usr/bin/env python3
"""
DevOS Disk & Storage Controller
Inspects storage devices, partition tables (GPT vs MBR/DOS), filesystem sizes,
and provides Windows-like partition formatting, wipe, storage setup, and boot targets.
"""

import sys
import os
import re
import json
import shutil
import subprocess
import shlex

from storage_layout import plan_layout, layout_script, desktop_owner, ownership_script, volume_label, system_layout_script
from typing import Dict, Any, List, Tuple


def format_size(bytes_val: int) -> str:
    """Formats bytes into human readable MB, GB, or TB."""
    if bytes_val <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    val = float(bytes_val)
    unit_idx = 0
    while val >= 1024.0 and unit_idx < len(units) - 1:
        val /= 1024.0
        unit_idx += 1
    if unit_idx >= 3:
        return f"{val:.1f} {units[unit_idx]}"
    return f"{int(val)} {units[unit_idx]}"


LSBLK_COLUMNS = "NAME,SIZE,FSAVAIL,FSUSED,FSUSE%,TYPE,FSTYPE,MOUNTPOINTS,MODEL,TRAN,ROTA,PTTYPE,LABEL,PARTLABEL,PARTTYPE,RO,SERIAL"
# Older util-linux has no MOUNTPOINTS; same data with the single-mount column.
LSBLK_COLUMNS_OLD = LSBLK_COLUMNS.replace("MOUNTPOINTS", "MOUNTPOINT")
ESP_PARTTYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
BIOS_BOOT_PARTTYPE = "21686148-6449-6e6f-744e-656564454649"
LIVE_MEDIA_MOUNTS = ("/cdrom", "/run/live/medium", "/isodevice")


def is_live_system(cmdline_path: str = "/proc/cmdline", casper_dir: str = "/run/casper") -> bool:
    """True on the DevOS live USB (casper), False on an installed PC."""
    if casper_dir and os.path.isdir(casper_dir):
        return True
    try:
        with open(cmdline_path, "r", encoding="utf-8", errors="replace") as fh:
            return "boot=casper" in fh.read().split()
    except OSError:
        return False


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def _mounts_of(node: Dict[str, Any]) -> List[str]:
    """MOUNTPOINTS (list, newer lsblk) or MOUNTPOINT (string, older)."""
    raw = node.get("mountpoints")
    if raw is None:
        raw = [node.get("mountpoint")]
    return [m for m in raw if m]


def parse_findmnt_subvolumes(data: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    """findmnt -J -o TARGET,SOURCE,FSTYPE -> {"/dev/sda2": [{"target": "/", "subvol": "/@"}]}."""
    result: Dict[str, List[Dict[str, str]]] = {}

    def walk(nodes):
        for n in nodes or []:
            source = n.get("source") or ""
            if n.get("fstype") == "btrfs" and "[" in source and source.endswith("]"):
                dev, subvol = source[:-1].split("[", 1)
                result.setdefault(dev, []).append({"target": n.get("target") or "", "subvol": subvol})
            walk(n.get("children"))

    walk((data or {}).get("filesystems"))
    return result


def disk_description(dev: Dict[str, Any]) -> str:
    """Real model plus bus and media type, e.g. 'Samsung SSD 970 EVO - NVMe SSD'."""
    model = " ".join((dev.get("model") or "").split())
    tran = (dev.get("tran") or "").lower()
    name = dev.get("name") or ""
    if not tran:
        if name.startswith("nvme"):
            tran = "nvme"
        elif name.startswith("vd"):
            tran = "virtio"
        elif name.startswith("mmcblk"):
            tran = "mmc"
    media = "HDD" if _as_bool(dev.get("rota")) else "SSD"
    if tran == "usb":
        kind = "USB drive"
    elif tran == "virtio":
        kind = "Virtual disk"
    elif tran == "mmc":
        kind = "SD / eMMC"
    elif tran:
        kind = f"{tran.upper()} {media}"
    else:
        kind = media
    if not model:
        return kind
    return f"{model} · {kind}"


def parse_partition_parent(device_path: str) -> Tuple[str, str]:
    """
    Given a partition device like /dev/sda1 or /dev/nvme0n1p2,
    returns (parent_disk, partition_number), e.g. ('/dev/sda', '1') or ('/dev/nvme0n1', '2').
    """
    m = re.match(r"^(/dev/(?:nvme\d+n\d+|mmcblk\d+|[a-zA-Z]+))p?(\d+)$", device_path.strip())
    if m:
        return m.group(1), m.group(2)
    return "", ""


def parse_lsblk(data: Dict[str, Any], subvolumes: Dict[str, List[Dict[str, str]]] = None,
                is_uefi: bool = None, live: bool = None) -> List[Dict[str, Any]]:
    """Turns `lsblk -J -b` output into structured disk cards with Windows-like size info."""
    subvolumes = subvolumes or {}
    if is_uefi is None:
        is_uefi = DiskManager.is_uefi_system()
    if live is None:
        live = is_live_system()
    disks = []
    for dev in (data or {}).get("blockdevices", []):
        dev_name = dev.get("name", "")
        if dev.get("type") != "disk" or dev_name.startswith(("loop", "zram", "ram", "sr", "fd")):
            continue
        size_bytes = _as_int(dev.get("size"))
        if size_bytes <= 0:
            continue
        pttype = (dev.get("pttype") or "").lower()
        if pttype == "gpt":
            table_label = "GPT (GUID Partition Table - UEFI Standard)"
        elif pttype in ("dos", "mbr"):
            table_label = "MBR (Legacy BIOS / MSDOS)"
        elif pttype:
            table_label = pttype.upper()
        else:
            table_label = "Unpartitioned / Raw"

        disk_entry = {
            "device": f"/dev/{dev_name}",
            "model": disk_description(dev),
            "vendor_model": " ".join((dev.get("model") or "").split()),
            "transport": (dev.get("tran") or "").lower(),
            "rotational": _as_bool(dev.get("rota")),
            "read_only": _as_bool(dev.get("ro")),
            "serial": str(dev.get("serial") or ""),
            "size_bytes": size_bytes,
            "size_human": format_size(size_bytes),
            "partition_table": table_label,
            "raw_pttype": pttype or "unknown",
            "partitions": [],
            "unallocated_bytes": 0,
            "unallocated_human": "0 B",
            "is_system_disk": False,
            "is_live_media": False,
        }
        if dev.get("fstype") == "iso9660" or any(m in LIVE_MEDIA_MOUNTS for m in _mounts_of(dev)):
            disk_entry["is_live_media"] = True
        if dev.get("fstype") and not dev.get("children"):
            # Filesystem written straight onto the disk, without a partition table.
            disk_mounts = _mounts_of(dev)
            disk_entry["whole_disk_fs"] = dev["fstype"]
            fsavail = _as_int(dev.get("fsavail"))
            fsused = _as_int(dev.get("fsused"))
            fsuse_pct = str(dev.get("fsuse%") or "").strip()
            used_free_str = ""
            if fsused > 0 and fsavail > 0:
                used_free_str = f"{format_size(fsused)} used / {format_size(fsavail)} free"
                if fsuse_pct:
                    used_free_str += f" ({fsuse_pct})"
            elif fsused > 0:
                used_free_str = f"{format_size(fsused)} used"
            elif fsavail > 0:
                used_free_str = f"{format_size(fsavail)} free"

            disk_entry["partitions"].append({
                "device": disk_entry["device"],
                "size_bytes": size_bytes,
                "size_human": disk_entry["size_human"],
                "fs_avail_bytes": fsavail,
                "fs_avail_human": format_size(fsavail) if fsavail > 0 else "",
                "fs_used_bytes": fsused,
                "fs_used_human": format_size(fsused) if fsused > 0 else "",
                "fs_use_percent": fsuse_pct,
                "used_free_human": used_free_str,
                "fstype": dev["fstype"],
                "mountpoint": ", ".join(dict.fromkeys(disk_mounts)),
                "mounted": bool(disk_mounts),
                "label": dev.get("label") or "",
                "read_only": _as_bool(dev.get("ro")),
                "is_esp": False,
                "is_bios_boot": False,
            })
            if "/" in disk_mounts:
                disk_entry["is_system_disk"] = True

        for part in dev.get("children", []) or []:
            # Mounts can sit on a child of the partition (LUKS, LVM).
            mounts, stack, fstype = [], [part], part.get("fstype") or ""
            while stack:
                node = stack.pop()
                mounts.extend(_mounts_of(node))
                if not fstype and node.get("fstype"):
                    fstype = node["fstype"]
                stack.extend(node.get("children") or [])
            part_dev = f"/dev/{part.get('name', '')}"
            subs = subvolumes.get(part_dev, [])
            if subs:
                mount_text = ", ".join(f"{s['target']} ({s['subvol'].lstrip('/') or 'top'})" for s in subs)
            else:
                mount_text = ", ".join(dict.fromkeys(mounts))
            all_targets = set(mounts) | {s["target"] for s in subs}
            if "/" in all_targets:
                disk_entry["is_system_disk"] = True
            if fstype == "iso9660" or all_targets & set(LIVE_MEDIA_MOUNTS):
                disk_entry["is_live_media"] = True
            parttype = (part.get("parttype") or "").lower()
            part_size = _as_int(part.get("size"))
            fsavail = _as_int(part.get("fsavail"))
            fsused = _as_int(part.get("fsused"))
            fsuse_pct = str(part.get("fsuse%") or "").strip()

            used_free_str = ""
            if fsused > 0 and fsavail > 0:
                used_free_str = f"{format_size(fsused)} used / {format_size(fsavail)} free"
                if fsuse_pct:
                    used_free_str += f" ({fsuse_pct})"
            elif fsused > 0:
                used_free_str = f"{format_size(fsused)} used"
            elif fsavail > 0:
                used_free_str = f"{format_size(fsavail)} free"

            disk_entry["partitions"].append({
                "device": part_dev,
                "size_bytes": part_size,
                "size_human": format_size(part_size),
                "fs_avail_bytes": fsavail,
                "fs_avail_human": format_size(fsavail) if fsavail > 0 else "",
                "fs_used_bytes": fsused,
                "fs_used_human": format_size(fsused) if fsused > 0 else "",
                "fs_use_percent": fsuse_pct,
                "used_free_human": used_free_str,
                "fstype": fstype or "unknown",
                "mountpoint": mount_text,
                "mounted": bool(all_targets),
                "label": part.get("label") or part.get("partlabel") or "",
                "read_only": _as_bool(part.get("ro")),
                "is_esp": parttype == ESP_PARTTYPE,
                "is_bios_boot": parttype == BIOS_BOOT_PARTTYPE,
            })

        # Calculate unallocated free space across the disk
        total_part_size = sum(p["size_bytes"] for p in disk_entry["partitions"])
        unalloc = max(0, size_bytes - total_part_size)
        disk_entry["unallocated_bytes"] = unalloc
        disk_entry["unallocated_human"] = format_size(unalloc)

        disk_entry["issues"] = DiskManager.diagnose_disk(disk_entry, is_uefi=is_uefi, live=live)
        disks.append(disk_entry)
    return disks


class DiskManager:
    """Manager for disk inspection, MBR/GPT detection, and boot preparation."""

    last_error = ""

    @staticmethod
    def _run_json(cmd: List[str]) -> Dict[str, Any]:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             check=True, timeout=10)
        return json.loads(res.stdout or "{}")

    @classmethod
    def get_storage_info(cls) -> List[Dict[str, Any]]:
        """Real disks and partitions from lsblk. Empty list (never sample data) when lsblk fails."""
        cls.last_error = ""
        if not shutil.which("lsblk"):
            cls.last_error = "lsblk is not available on this system."
            return []
        data = None
        for cols in (LSBLK_COLUMNS, LSBLK_COLUMNS_OLD):
            try:
                data = cls._run_json(["lsblk", "-J", "-b", "-o", cols])
                break
            except Exception as exc:  # unknown column on old util-linux, or no /sys
                cls.last_error = f"lsblk failed: {exc}"
        if data is None:
            return []
        subvolumes = {}
        if shutil.which("findmnt"):
            try:
                subvolumes = parse_findmnt_subvolumes(
                    cls._run_json(["findmnt", "-J", "-o", "TARGET,SOURCE,FSTYPE"]))
            except Exception:
                subvolumes = {}
        cls.last_error = ""
        return parse_lsblk(data, subvolumes)

    @classmethod
    def storage_report(cls) -> Dict[str, Any]:
        devices = cls.get_storage_info()
        return {"devices": devices, "is_uefi": cls.is_uefi_system(), "live": is_live_system(),
                "error": cls.last_error}

    @staticmethod
    def is_uefi_system() -> bool:
        """Detects if host machine firmware is running in UEFI mode."""
        return os.path.isdir("/sys/firmware/efi")

    @classmethod
    def diagnose_disk(cls, disk: Dict[str, Any], is_uefi: bool = None, live: bool = None) -> List[Dict[str, Any]]:
        """Diagnoses partition table issues and generates one-click solutions."""
        issues = []
        if is_uefi is None:
            is_uefi = cls.is_uefi_system()
        if live is None:
            live = is_live_system()
        raw_pt = disk.get("raw_pttype", "").lower()
        partitions = disk.get("partitions", [])
        boot_mode = "UEFI" if is_uefi else "Legacy BIOS"

        if disk.get("is_live_media"):
            return [{
                "type": "live_media",
                "severity": "info",
                "title": "DevOS USB you started from",
                "description": "This is the installer drive. Protected from formatting.",
                "action_id": "",
                "action_label": "",
            }]
        if disk.get("is_system_disk") and not live:
            table = raw_pt.upper() if raw_pt not in ("", "unknown") else "no"
            return [{
                "type": "system_disk",
                "severity": "success",
                "title": "DevOS is installed on this disk",
                "description": f"Active system disk with a {table} partition table, booting in {boot_mode} mode.",
                "action_id": "",
                "action_label": "",
            }]

        if disk.get("whole_disk_fs") and (not raw_pt or raw_pt in ("unknown", "raw")):
            fs = disk["whole_disk_fs"]
            in_use = any(p.get("mounted") for p in partitions)
            return [{
                "type": "whole_disk_fs",
                "severity": "warning",
                "title": f"Whole disk formatted as {fs} without partition table",
                "description": ("In use. " if in_use else "") +
                               f"The disk has a {fs} filesystem but no partition table. "
                               "Initialize as GPT to use with modern operating systems.",
                "action_id": "format_storage",
                "action_label": "Format as GPT Storage Drive",
            }]

        # Check for unpartitioned drive
        if not raw_pt or raw_pt in ("unknown", "raw"):
            issues.append({
                "type": "unpartitioned",
                "severity": "warning",
                "title": "Unallocated / Unpartitioned Disk",
                "description": "Drive has no partition table. Initialize as GPT and format for DevOS or Storage.",
                "action_id": "format_storage",
                "action_label": "Format as Fast Storage Drive (GPT + Ext4)"
            })
            return issues

        # Check UEFI vs MBR mismatch
        if live and is_uefi and raw_pt in ("dos", "mbr"):
            issues.append({
                "type": "mbr_on_uefi",
                "severity": "warning",
                "title": "Legacy MBR Partition Table on UEFI Motherboard",
                "description": "Your computer booted in modern UEFI mode, but this drive uses legacy MBR (dos).",
                "action_id": "convert_gpt",
                "action_label": "Convert MBR to GPT…"
            })

        # Check BIOS vs GPT mismatch
        if live and not is_uefi and raw_pt == "gpt":
            has_bios_boot = any(p.get("is_bios_boot") or p.get("label") == "bios_grub"
                                or "bios" in p.get("label", "").lower() for p in partitions)
            if not has_bios_boot:
                issues.append({
                    "type": "gpt_on_bios",
                    "severity": "info",
                    "title": "GPT Disk on Legacy BIOS System",
                    "description": "Running in BIOS mode. You can convert to MBR or add a BIOS boot partition.",
                    "action_id": "convert_mbr",
                    "action_label": "Erase disk and create MBR"
                })

        # Check EFI partition existence for UEFI boot
        has_efi = any(
            p.get("is_esp") or
            "/boot/efi" in (p.get("mountpoint") or "") or
            p.get("label") in ("DEVOS_EFI", "EFI", "ESP") or
            "fat" in p.get("fstype", "").lower()
            for p in partitions
        )
        if live and is_uefi and raw_pt == "gpt" and not has_efi:
            issues.append({
                "type": "missing_efi",
                "severity": "warning",
                "title": "Missing 512 MB EFI System Partition (ESP)",
                "description": "UEFI requires a dedicated FAT32 EFI partition at /boot/efi to boot installed system.",
                "action_id": "format_devos",
                "action_label": "Setup DevOS Layout (512MB EFI + Ext4)"
            })

        # Check for unformatted data partitions on secondary / non-system disks
        if not disk.get("is_system_disk") and not disk.get("is_live_media"):
            for p in partitions:
                fstype = (p.get("fstype") or "").lower()
                if fstype in ("unknown", "", "none") and not p.get("is_esp") and p.get("size_bytes", 0) >= 1024 ** 3:
                    issues.append({
                        "type": "unformatted_partition",
                        "severity": "warning",
                        "title": f"Unformatted Storage Partition ({p['device']})",
                        "description": f"Partition {p['device']} ({p['size_human']}) has no filesystem. Format it to use as Storage.",
                        "action_id": f"format_partition:{p['device']}:ext4:Storage",
                        "action_label": f"Format {p['device']} (Ext4 Storage)"
                    })

        if not issues:
            if live:
                issues.append({
                    "type": "ready",
                    "severity": "success",
                    "title": "Disk Ready for DevOS Boot & Installation",
                    "description": f"Drive is configured with {raw_pt.upper()}. Calamares can install DevOS directly.",
                    "action_id": "launch_installer",
                    "action_label": "Open Installer"
                })
            else:
                issues.append({
                    "type": "healthy",
                    "severity": "success",
                    "title": "Data-drive layout recognised",
                    "description": f"{raw_pt.upper()} partition table detected. Data-only drives do not need an EFI boot partition. This is not a hardware-health test.",
                    "action_id": "",
                    "action_label": ""
                })

        return issues

    @classmethod
    def apply_solution(cls, device: str, action_id: str, fs_type: str = "ext4",
                       label: str = "", **kwargs) -> Dict[str, Any]:
        """
        Applies one-click resolution for storage/partition issues.
        Includes robust unmounting, swap deactivation, and signature wiping to prevent EBUSY.
        """
        if action_id == "reboot_system":
            try:
                subprocess.Popen(["systemctl", "reboot"])
                return {"success": True, "message": "Initiating reboot... Remove USB when screen turns dark."}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if action_id == "launch_installer":
            if not is_live_system():
                return {"success": False, "error": "DevOS is already installed on this PC."}
            cmd = ["/bin/bash", "/usr/local/bin/devos-install-gui"]
            if not os.path.exists(cmd[1]):
                return {"success": False, "error": "The installer is not available on this system."}
            try:
                subprocess.Popen(cmd)
            except Exception as e:
                return {"success": False, "error": str(e)}
            return {"success": True, "message": "Calamares Installer launched successfully."}

        # Parse compound action_ids (e.g. format_partition:/dev/sda2:ext4:Storage)
        if ":" in action_id:
            parts = action_id.split(":")
            base_action = parts[0]
            if len(parts) >= 2 and not device:
                device = parts[1]
            if len(parts) >= 3 and not fs_type:
                fs_type = parts[2]
            if len(parts) >= 4 and not label:
                label = parts[3]
            action_id = base_action

        if not device.startswith("/dev/") or not all(c.isalnum() or c in "/-_" for c in device):
            return {"success": False, "error": f"Invalid device '{device}'"}

        # Validate filesystem selection
        fs_type = (fs_type or "ext4").lower().strip()
        if fs_type not in ("ext4", "btrfs", "exfat", "vfat", "ntfs"):
            return {"success": False, "error": "Unsupported filesystem. Choose ext4, btrfs, exfat, ntfs or FAT32. Zstd is compression, not a filesystem."}

        needs_pkexec = (os.geteuid() != 0 and shutil.which("pkexec") is not None)

        def run_script(bash_script: str) -> Tuple[bool, str]:
            # Recheck after authorization: another process may have mounted it.
            guard = (f"set -e\n"
                     f"test -b {device} || {{ echo 'Target is not a block device' >&2; exit 1; }}\n"
                     f"test \"$(lsblk -dnro RO {device})\" = 0 || {{ echo 'Drive is read-only' >&2; exit 1; }}\n"
                     f"if lsblk -nro MOUNTPOINT {device} | grep -q '[^[:space:]]'; then "
                     f"echo 'Drive is mounted or in use; unmount it first' >&2; exit 1; fi\n")
            if device == target_disk["device"]:
                guard += f'test "$(lsblk -bdnro SIZE {device})" = {target_disk["size_bytes"]} || {{ echo "Drive size changed" >&2; exit 1; }}\n'
                serial = target_disk.get("serial", "")
                if serial:
                    guard += f'test "$(lsblk -dnro SERIAL {device})" = {shlex.quote(serial)} || {{ echo "Drive identity changed" >&2; exit 1; }}\n'
            bash_script = guard + bash_script
            runner = ["pkexec", "bash", "-c", bash_script] if needs_pkexec else ["bash", "-c", bash_script]
            proc = subprocess.run(runner, capture_output=True, text=True)
            if proc.returncode == 0:
                return True, proc.stdout.strip()
            return False, proc.stderr.strip() or f"Command failed with code {proc.returncode}"

        # ------------------ PROTECT ACTIVE SYSTEM & LIVE MEDIA ------------------
        disks = cls.get_storage_info()
        target_disk = next((d for d in disks if d["device"] == device), None)
        parent_disk, part_num = parse_partition_parent(device)

        if not target_disk and parent_disk:
            target_disk = next((d for d in disks if d["device"] == parent_disk), None)

        if target_disk is None:
            return {"success": False, "error": "Cannot identify the target drive. Refresh storage before trying again."}
        if target_disk:
            if target_disk.get("read_only"):
                return {"success": False, "error": "This drive is read-only. Diagnose its hardware or filesystem before changing it."}
            if target_disk.get("is_live_media"):
                return {"success": False, "error": f"{device} is the DevOS live installer USB. Protected from modifications."}
            if target_disk.get("is_system_disk") and not is_live_system():
                # Allow formatting only non-root partitions on system disk, but never whole disk
                if action_id in ("convert_gpt", "convert_mbr", "format_devos", "format_storage", "wipe_disk", "partition_storage"):
                    return {"success": False, "error": f"{device} is the running system disk. Cannot erase while running DevOS."}

        # Check if specific partition is root / boot
        if parent_disk:
            for d in disks:
                for p in d.get("partitions", []):
                    if p["device"] == device and any(m in ("/", "/boot", "/boot/efi") for m in p.get("mountpoint", "").split(", ")):
                        if not is_live_system():
                            return {"success": False, "error": f"Cannot modify partition {device}: mounted as active system root."}

        if target_disk.get("is_system_disk") and not is_live_system():
            return {"success": False, "error": f"Cannot modify {device}: mounted as active system root or on its running system disk."}

        # ------------------ MOUNT / UNMOUNT PARTITION ------------------
        if action_id in ("mount_partition", "mount"):
            try:
                res = subprocess.run(["udisksctl", "mount", "-b", device], capture_output=True, text=True)
                if res.returncode == 0:
                    return {"success": True, "message": f"Successfully mounted {device}."}
                return {"success": False, "error": res.stderr.strip() or "Failed to mount partition."}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        if action_id in ("unmount_partition", "unmount"):
            try:
                res = subprocess.run(["udisksctl", "unmount", "-b", device], capture_output=True, text=True)
                if res.returncode == 0:
                    return {"success": True, "message": f"Successfully unmounted {device}."}
                return {"success": False, "error": res.stderr.strip() or "Close files on this drive and try again."}
            except Exception as exc:
                return {"success": False, "error": str(exc)}

        expected = kwargs.get("expected_identity")
        if expected and any(expected.get(key) != target_disk.get(key) for key in ("size_bytes", "serial")):
            return {"success": False, "error": "Drive identity changed. Refresh storage and review the plan."}

        affected = target_disk.get("partitions", []) if device == target_disk["device"] else [
            p for p in target_disk.get("partitions", []) if p["device"] == device]
        if not affected and device != target_disk["device"]:
            return {"success": False, "error": "The selected partition is no longer present. Refresh storage."}
        if any(p.get("mounted") or p.get("read_only") for p in affected):
            return {"success": False, "error": "Unmount the selected volume(s) and deactivate swap before modifying them. Read-only volumes need diagnosis first."}
        try:
            owner = kwargs.get("owner") or desktop_owner()
            if label:
                label = volume_label(label, fs_type)
        except (ValueError, KeyError) as exc:
            return {"success": False, "error": str(exc)}

        required_tools = []
        mkfs_tool = "mkfs." + fs_type
        if action_id in ("format_partition", "format"):
            required_tools = [mkfs_tool, "wipefs", "udevadm"]
        elif action_id == "format_storage":
            required_tools = [mkfs_tool, "wipefs", "parted", "udevadm"]
        elif action_id == "format_devos":
            if fs_type not in ("ext4", "btrfs"):
                return {"success": False, "error": "DevOS system partitions require ext4 or btrfs."}
            required_tools = [mkfs_tool, "wipefs", "parted", "partprobe", "udevadm"]
            if cls.is_uefi_system():
                required_tools.append("mkfs.vfat")
        missing = sorted({tool for tool in required_tools if not shutil.which(tool)})
        if missing:
            return {"success": False, "error": "Install required storage tools first: " + ", ".join(missing)}

        # ------------------ ACTIONS IMPLEMENTATION ------------------
        try:
            if action_id == "partition_storage":
                if device != target_disk["device"]:
                    return {"success": False, "error": "Select a whole data disk for a new layout."}
                planned = plan_layout(target_disk["size_bytes"], kwargs.get("volumes"))
                needed = ["parted", "partprobe", "wipefs", "udevadm"] + [
                    "mkfs." + ("vfat" if p["filesystem"] == "vfat" else p["filesystem"]) for p in planned]
                missing = sorted({tool for tool in needed if not shutil.which(tool)})
                if missing:
                    return {"success": False, "error": "Install required storage tools first: " + ", ".join(missing)}
                ok, err = run_script(layout_script(device, planned, owner))
                return {"success": ok, "message": "Created data volumes: " + ", ".join(p["label"] for p in planned),
                        "error": "Partitioning stopped: " + err if not ok else ""}

            if action_id == "convert_gpt":
                if shutil.which("sgdisk"):
                    cmd = ["sgdisk", "-g", device]
                    if needs_pkexec:
                        cmd = ["pkexec"] + cmd
                    ok, err = run_script(shlex.join(["sgdisk", "-g", device]))
                    return {"success": ok, "message": f"Converted {device} from MBR to GPT.", "error": err if not ok else ""}
                return {"success": False, "error": "sgdisk tool not found."}

            elif action_id == "convert_mbr":
                if shutil.which("parted"):
                    cmd = ["parted", device, "--script", "mklabel", "msdos"]
                    if needs_pkexec:
                        cmd = ["pkexec"] + cmd
                    ok, err = run_script(shlex.join(["parted", device, "--script", "mklabel", "msdos"]))
                    return {"success": ok, "message": f"Initialized {device} as MBR (msdos).", "error": err if not ok else ""}
                return {"success": False, "error": "parted tool not found."}

            elif action_id == "wipe_disk":
                # Clean wipe of partition table and signatures with safe unmounting
                script = (
                    f"set -e\n"
                    f"wipefs -a {device}\n"
                    f"parted {device} --script mklabel gpt\n"
                    f"udevadm settle || sleep 1\n"
                )
                ok, err = run_script(script)
                if ok:
                    return {"success": True, "message": f"Successfully wiped and initialized {device} with clean GPT table."}
                return {"success": False, "error": f"Wiping failed: {err}"}

            elif action_id == "format_devos":
                uefi = cls.is_uefi_system()
                ok, err = run_script(system_layout_script(device, fs_type, label or "DevOS", uefi))
                boot = "EFI" if uefi else "BIOS boot"
                if ok:
                    return {"success": True, "message": f"Prepared {device} with GPT, {boot} space and an {fs_type} system partition. Install DevOS with the installer."}
                return {"success": False, "error": f"System layout preparation stopped: {err}"}

            elif action_id == "format_storage":
                # Single large GPT storage partition spanning 100% of the drive
                target_label = shlex.quote(label or "Storage")
                part1 = f"{device}1" if "nvme" not in device and "mmc" not in device else f"{device}p1"

                if fs_type == "btrfs":
                    mkfs_cmd = f"mkfs.btrfs -f -L {target_label} {part1}"
                elif fs_type == "exfat":
                    mkfs_cmd = f"mkfs.exfat -n {target_label} {part1}"
                elif fs_type == "ntfs":
                    mkfs_cmd = f"mkfs.ntfs -f -L {target_label} {part1}"
                elif fs_type == "vfat":
                    mkfs_cmd = f"mkfs.vfat -F32 -n {target_label} {part1}"
                else:
                    mkfs_cmd = f"mkfs.ext4 -F -L {target_label} {part1}"

                script = (
                    f"set -e\n"
                    f"wipefs -a {device}\n"
                    f"parted {device} --script mklabel gpt\n"
                    f"parted {device} --script mkpart {target_label} {({'exfat': 'ntfs', 'vfat': 'fat32'}.get(fs_type, fs_type))} 1MiB 100%\n"
                    f"udevadm settle || sleep 1\n"
                    f"{mkfs_cmd}\n"
                    + ownership_script(part1, fs_type, owner)
                    + f"udevadm settle || sleep 1\n"
                )
                ok, err = run_script(script)
                if ok:
                    return {"success": True, "message": f"Successfully formatted {device} as {fs_type.upper()} Storage ({target_label})!"}
                return {"success": False, "error": f"Storage formatting failed: {err}"}

            elif action_id in ("format_partition", "format"):
                target_label = shlex.quote(label or "Storage")

                if fs_type == "btrfs":
                    mkfs_cmd = f"mkfs.btrfs -f -L {target_label} {device}"
                elif fs_type == "exfat":
                    mkfs_cmd = f"mkfs.exfat -n {target_label} {device}"
                elif fs_type == "ntfs":
                    mkfs_cmd = f"mkfs.ntfs -f -L {target_label} {device}"
                elif fs_type == "vfat":
                    mkfs_cmd = f"mkfs.vfat -F32 -n {target_label} {device}"
                else:
                    mkfs_cmd = f"mkfs.ext4 -F -L {target_label} {device}"

                script = (
                    f"set -e\n"
                    f"wipefs -a {device}\n"
                    f"{mkfs_cmd}\n"
                    + ownership_script(device, fs_type, owner)
                    + f"udevadm settle || sleep 1\n"
                )
                ok, err = run_script(script)
                if ok:
                    return {"success": True, "message": f"Successfully formatted {device} as {fs_type.upper()} ({target_label})!"}
                return {"success": False, "error": f"Partition formatting failed: {err}"}

            elif action_id in ("delete_partition", "delete"):
                if not parent_disk or not part_num:
                    return {"success": False, "error": f"Cannot determine parent disk for partition '{device}'"}
                script = (
                    f"set -e\n"
                    f"wipefs -a {device}\n"
                    f"parted {parent_disk} --script rm {part_num}\n"
                    f"udevadm settle || sleep 1\n"
                )
                ok, err = run_script(script)
                if ok:
                    return {"success": True, "message": f"Successfully deleted partition {device}."}
                return {"success": False, "error": f"Failed to delete partition: {err}"}

            return {"success": False, "error": f"Unknown action '{action_id}'"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def print_storage_table(cls):
        """Prints a visual overview of all storage devices, partition schemes, and space usage."""
        disks = cls.get_storage_info()

        print("\n==========================================================================================")
        print("                               DevOS Storage & Disk Manager                               ")
        print("==========================================================================================")

        for disk in disks:
            print(f"\n[Disk Device]       {disk['device']}")
            print(f"  Model:            {disk['model']}")
            print(f"  Capacity:         {disk['size_human']} ({disk['size_bytes']:,} bytes)")
            print(f"  Partition Table:  {disk['partition_table']}")
            if disk.get("unallocated_bytes", 0) > 1024 * 1024:
                print(f"  Unallocated:      {disk['unallocated_human']}")

            if disk["partitions"]:
                print("  Partitions:")
                print("    " + f"{'PARTITION':<16} {'SIZE':<10} {'USED / FREE':<26} {'FSTYPE':<10} {'MOUNT / ROLE'}")
                print("    " + "-" * 78)
                for part in disk["partitions"]:
                    mount_info = part["mountpoint"] or (f"Label: {part['label']}" if part['label'] else "[unmounted]")
                    used_free = part.get("used_free_human") or "-"
                    print("    " + f"{part['device']:<16} {part['size_human']:<10} {used_free:<26} {part['fstype']:<10} {mount_info}")
            else:
                print("  Partitions:       (None - Disk is unallocated)")

        print("\n------------------------------------------------------------------------------------------")
        print("  Quick CLI Actions:")
        print("    * Format Partition:      devos disk format <partition> [--fs ext4|btrfs|exfat] [--label LABEL]")
        print("    * Format Entire Storage: devos disk format-storage <disk> [--fs ext4|btrfs|exfat] [--label LABEL]")
        print("    * Setup DevOS Boot Disk: devos disk setup-devos <disk> [--fs ext4|btrfs]")
        print("    * Wipe Disk Clean:       devos disk wipe <disk>")
        print("    * Open Visual GUI:       devos disk --gui (or devos-disk-gui)")
        print("==========================================================================================\n")

    @staticmethod
    def print_conversion_guide():
        """Prints guide for converting between MBR and GPT partition tables."""
        print("""
================================================================================
          DevOS Storage Conversion Guide: MBR <-> GPT & Formatting             
================================================================================

1. HOW TO DETECT PARTITION TABLE TYPE:
   Run:
     lsblk -o NAME,SIZE,PTTYPE,FSTYPE,MOUNTPOINT
   * 'pttype=gpt'  --> Modern UEFI system (Required for systems with UEFI/Secure Boot).
   * 'pttype=dos'  --> Legacy MBR partition table (Limited to 2TB and 4 primary partitions).

2. HOW TO CONVERT MBR TO GPT (NON-DESTRUCTIVELY):
   If you have an existing MBR disk and want to upgrade to GPT without losing data:
     sudo gdisk /dev/sdX
     # Press 'w' to write the GPT partition table, then press 'Y' to confirm.
   Alternatively via command line:
     sudo sgdisk -g /dev/sdX

3. HOW TO CONVERT GPT TO MBR / CLEAN FORMAT DISK:
   Warning: Creating a new partition table deletes existing partitions!
   * Convert to GPT:
     sudo parted /dev/sdX --script mklabel gpt
   * Convert to MBR (dos):
     sudo parted /dev/sdX --script mklabel msdos

4. IN THE DEVOS CALAMARES INSTALLER GUI:
   * To automatically format and apply GPT with DevOS Ext4:
     Select: [ Erase disk ] -> Choose your drive from the dropdown.
   * To manually adjust partition tables:
     Select: [ Manual partitioning ] -> Select Drive -> Click [ New Partition Table ]
     -> Select 'GPT' (Recommended) or 'MBR (msdos)'.

5. RESTARTING AFTER INSTALLATION:
   * When Calamares finishes, check 'Restart now' and click Done.
   * When the machine powers down and the screen goes dark, unplug the USB drive.
   * Your motherboard will immediately boot into your newly installed DevOS disk!
================================================================================
""")


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-t", "--table", "table", "status"):
        DiskManager.print_storage_table()
        return

    cmd = args[0]
    if cmd in ("-c", "--convert", "help-convert"):
        DiskManager.print_conversion_guide()
        return
    if cmd in ("-j", "--json", "json"):
        print(json.dumps(DiskManager.get_storage_info(), indent=2))
        return
    if cmd in ("-h", "--help", "help"):
        DiskManager.print_storage_table()
        DiskManager.print_conversion_guide()
        return

    # CLI Actions: format, format-storage, setup-devos, wipe, delete, mount, unmount
    if cmd in ("format", "format-partition", "format-storage", "setup-devos", "wipe", "delete", "mount", "unmount"):
        if len(args) < 2:
            print(f"Error: Missing device path for '{cmd}'. Example: devos disk {cmd} /dev/sda1")
            sys.exit(1)
        device = args[1]
        fs_type = "ext4"
        label = ""

        # parse flags
        i = 2
        while i < len(args):
            if args[i] in ("--fs", "-f") and i + 1 < len(args):
                fs_type = args[i + 1]
                i += 2
            elif args[i] in ("--label", "-l") and i + 1 < len(args):
                label = args[i + 1]
                i += 2
            else:
                i += 1

        action_map = {
            "format": "format_partition",
            "format-partition": "format_partition",
            "format-storage": "format_storage",
            "setup-devos": "format_devos",
            "wipe": "wipe_disk",
            "delete": "delete_partition",
            "mount": "mount_partition",
            "unmount": "unmount_partition"
        }
        action_id = action_map[cmd]
        res = DiskManager.apply_solution(device, action_id, fs_type=fs_type, label=label)
        if res.get("success"):
            print(f"✓ Success: {res.get('message')}")
        else:
            print(f"✗ Error: {res.get('error')}")
            sys.exit(1)
        return

    # Fallback default
    DiskManager.print_storage_table()


if __name__ == "__main__":
    main()
