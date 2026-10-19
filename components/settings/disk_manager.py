#!/usr/bin/env python3
"""
DevOS Disk & Storage Controller
Inspects storage devices, partition tables (GPT vs MBR/DOS), filesystem sizes,
and provides guidance for partition scheme conversion and boot targets.
"""

import sys
import os
import json
import shutil
import subprocess
from typing import Dict, Any, List


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


LSBLK_COLUMNS = "NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS,MODEL,TRAN,ROTA,PTTYPE,LABEL,PARTLABEL,PARTTYPE"
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


def parse_lsblk(data: Dict[str, Any], subvolumes: Dict[str, List[Dict[str, str]]] = None,
                is_uefi: bool = None, live: bool = None) -> List[Dict[str, Any]]:
    """Turns `lsblk -J -b` output into the dashboard's disk cards. Pure, so it is testable."""
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
            "size_bytes": size_bytes,
            "size_human": format_size(size_bytes),
            "partition_table": table_label,
            "raw_pttype": pttype or "unknown",
            "partitions": [],
            "is_system_disk": False,
            "is_live_media": False,
        }
        if dev.get("fstype") == "iso9660" or any(m in LIVE_MEDIA_MOUNTS for m in _mounts_of(dev)):
            disk_entry["is_live_media"] = True
        if dev.get("fstype") and not dev.get("children"):
            # Filesystem written straight onto the disk, without a partition table.
            disk_mounts = _mounts_of(dev)
            disk_entry["whole_disk_fs"] = dev["fstype"]
            disk_entry["partitions"].append({
                "device": disk_entry["device"],
                "size_bytes": size_bytes,
                "size_human": disk_entry["size_human"],
                "fstype": dev["fstype"],
                "mountpoint": ", ".join(dict.fromkeys(disk_mounts)),
                "mounted": bool(disk_mounts),
                "label": dev.get("label") or "",
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
            disk_entry["partitions"].append({
                "device": part_dev,
                "size_bytes": part_size,
                "size_human": format_size(part_size),
                "fstype": fstype or "unknown",
                "mountpoint": mount_text,
                "mounted": bool(all_targets),
                "label": part.get("label") or part.get("partlabel") or "",
                "is_esp": parttype == ESP_PARTTYPE,
                "is_bios_boot": parttype == BIOS_BOOT_PARTTYPE,
            })

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
                "description": "This is the installer drive. Do not install onto it.",
                "action_id": "",
                "action_label": "",
            }]
        if disk.get("is_system_disk") and not live:
            table = raw_pt.upper() if raw_pt not in ("", "unknown") else "no"
            return [{
                "type": "system_disk",
                "severity": "success",
                "title": "DevOS is installed on this disk",
                "description": f"System disk with a {table} partition table, booting in {boot_mode} mode.",
                "action_id": "",
                "action_label": "",
            }]

        if disk.get("whole_disk_fs") and (not raw_pt or raw_pt in ("unknown", "raw")):
            fs = disk["whole_disk_fs"]
            in_use = any(p.get("mounted") for p in partitions)
            return [{
                "type": "whole_disk_fs",
                "severity": "info",
                "title": f"Whole disk formatted as {fs}",
                "description": ("In use. " if in_use else "") +
                               f"The disk has a {fs} filesystem but no partition table. "
                               "Back up its files before reformatting it for DevOS.",
                "action_id": "",
                "action_label": "",
            }]

        # Check for unpartitioned drive
        if not raw_pt or raw_pt in ("unknown", "raw"):
            issues.append({
                "type": "unpartitioned",
                "severity": "warning",
                "title": "Unallocated / Unpartitioned Disk",
                "description": "Drive has no partition table. Needs GPT table and filesystem formatting.",
                "action_id": "format_devos",
                "action_label": "Initialize as GPT & Format for DevOS"
            })
            return issues

        # Check UEFI vs MBR mismatch
        if is_uefi and raw_pt in ("dos", "mbr"):
            issues.append({
                "type": "mbr_on_uefi",
                "severity": "warning",
                "title": "Legacy MBR Partition Table on UEFI Motherboard",
                "description": "Your computer booted in modern UEFI mode, but this drive uses legacy MBR (dos).",
                "action_id": "convert_gpt",
                "action_label": "Convert MBR to GPT (Safe One-Click)"
            })

        # Check BIOS vs GPT mismatch
        if not is_uefi and raw_pt == "gpt":
            has_bios_boot = any(p.get("is_bios_boot") or p.get("label") == "bios_grub"
                                or "bios" in p.get("label", "").lower() for p in partitions)
            if not has_bios_boot:
                issues.append({
                    "type": "gpt_on_bios",
                    "severity": "info",
                    "title": "GPT Disk on Legacy BIOS System",
                    "description": "Running in BIOS mode. You can convert to MBR or add a BIOS boot partition.",
                    "action_id": "convert_mbr",
                    "action_label": "Convert to MBR (Legacy BIOS)"
                })

        # Check EFI partition existence for UEFI boot
        has_efi = any(
            p.get("is_esp") or
            "/boot/efi" in (p.get("mountpoint") or "") or
            p.get("label") in ("DEVOS_EFI", "EFI", "ESP") or
            "fat" in p.get("fstype", "").lower()
            for p in partitions
        )
        if is_uefi and raw_pt == "gpt" and not has_efi:
            issues.append({
                "type": "missing_efi",
                "severity": "warning",
                "title": "Missing 512 MB EFI System Partition (ESP)",
                "description": "UEFI requires a dedicated FAT32 EFI partition at /boot/efi to boot installed system.",
                "action_id": "format_devos",
                "action_label": "Format with DevOS Standard Layout (EFI + BTRFS)"
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
                    "title": "Partition table looks healthy",
                    "description": f"{raw_pt.upper()} partition table matches this PC's {boot_mode} boot mode.",
                    "action_id": "",
                    "action_label": ""
                })

        return issues

    @classmethod
    def apply_solution(cls, device: str, action_id: str) -> Dict[str, Any]:
        """Applies one-click resolution for storage/partition issues."""
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
        if not device.startswith("/dev/") or not all(c.isalnum() or c in "/-_" for c in device):
            return {"success": False, "error": f"Invalid device '{device}'"}
        if action_id in ("convert_gpt", "convert_mbr", "format_devos"):
            # Never rewrite a disk that is in use (the running system, the live USB, mounted data).
            disk = next((d for d in cls.get_storage_info() if d["device"] == device), None)
            if disk is None:
                return {"success": False, "error": f"{device} is not a disk on this PC."}
            if (disk.get("is_system_disk") or disk.get("is_live_media")
                    or any(p.get("mounted") for p in disk.get("partitions", []))):
                return {"success": False, "error": f"{device} is in use (mounted). Unmount it first."}

        try:
            needs_pkexec = (os.geteuid() != 0 and shutil.which("pkexec") is not None)

            if action_id == "convert_gpt":
                # Use sgdisk to convert MBR to GPT non-destructively
                if shutil.which("sgdisk"):
                    cmd = ["sgdisk", "-g", device]
                    if needs_pkexec:
                        cmd = ["pkexec"] + cmd
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode == 0:
                        return {"success": True, "message": f"Successfully converted {device} from MBR to GPT!"}
                    return {"success": False, "error": proc.stderr.strip() or f"sgdisk exited with code {proc.returncode}"}
                return {"success": False, "error": "sgdisk tool not found in live system."}

            elif action_id == "convert_mbr":
                if shutil.which("parted"):
                    cmd = ["parted", device, "--script", "mklabel", "msdos"]
                    if needs_pkexec:
                        cmd = ["pkexec"] + cmd
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode == 0:
                        return {"success": True, "message": f"Successfully initialized {device} as MBR (msdos)."}
                    return {"success": False, "error": proc.stderr.strip() or f"parted exited with code {proc.returncode}"}
                return {"success": False, "error": "parted tool not found."}

            elif action_id == "format_devos":
                # Standard DevOS layout: GPT + 512MB EFI (vfat) + remainder BTRFS
                if shutil.which("parted") and shutil.which("mkfs.vfat") and shutil.which("mkfs.btrfs"):
                    part1 = f"{device}1" if "nvme" not in device else f"{device}p1"
                    part2 = f"{device}2" if "nvme" not in device else f"{device}p2"

                    script = (
                        f"set -e\n"
                        f"parted {device} --script mklabel gpt\n"
                        f"parted {device} --script mkpart DEVOS_EFI fat32 1MiB 513MiB\n"
                        f"parted {device} --script set 1 esp on\n"
                        f"parted {device} --script mkpart DEVOS_ROOT btrfs 513MiB 100%\n"
                        f"udevadm settle || sleep 1\n"
                        f"mkfs.vfat -F32 -n DEVOS_EFI {part1}\n"
                        f"mkfs.btrfs -f -L DEVOS_ROOT {part2}\n"
                    )

                    runner = ["pkexec", "bash", "-c", script] if needs_pkexec else ["bash", "-c", script]
                    proc = subprocess.run(runner, capture_output=True, text=True)
                    if proc.returncode == 0:
                        return {"success": True, "message": f"Successfully formatted {device} with DevOS standard EFI + BTRFS layout!"}
                    return {"success": False, "error": proc.stderr.strip() or f"Formatting failed with exit code {proc.returncode}"}
                return {"success": False, "error": "parted, mkfs.vfat and mkfs.btrfs are needed to format a disk."}

            return {"success": False, "error": f"Unknown action '{action_id}'"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def print_storage_table(cls):
        """Prints a visual overview of all storage devices and partition schemes."""
        disks = cls.get_storage_info()

        print("\n================================================================================")
        print("                        DevOS Storage & Disk Manager                            ")
        print("================================================================================")

        for disk in disks:
            print(f"\n[Disk Device]       {disk['device']}")
            print(f"  Model:            {disk['model']}")
            print(f"  Capacity:         {disk['size_human']} ({disk['size_bytes']:,} bytes)")
            print(f"  Partition Table:  {disk['partition_table']}")

            if disk["partitions"]:
                print("  Partitions:")
                print("    " + f"{'PARTITION':<16} {'SIZE':<12} {'FILESYSTEM':<18} {'MOUNTPOINT / ROLE'}")
                print("    " + "-" * 68)
                for part in disk["partitions"]:
                    mount_info = part["mountpoint"] or (f"Label: {part['label']}" if part['label'] else "[unmounted]")
                    print("    " + f"{part['device']:<16} {part['size_human']:<12} {part['fstype']:<18} {mount_info}")
            else:
                print("  Partitions:       (None - Disk is unallocated)")

        print("\n--------------------------------------------------------------------------------")
        print("  Bootloader Target Recommendations:")
        print("    * UEFI Systems: Select the GPT disk (e.g., /dev/sda). EFI partition: 512MB FAT32.")
        print("    * BIOS Systems: Select the MBR/DOS disk (e.g., /dev/sda).")
        print("================================================================================\n")

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
   * To automatically format and apply GPT with DevOS BTRFS + zstd compression:
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
    if len(sys.argv) > 1 and sys.argv[1] in ("-c", "--convert", "help-convert"):
        DiskManager.print_conversion_guide()
    elif len(sys.argv) > 1 and sys.argv[1] in ("-j", "--json", "json"):
        print(json.dumps(DiskManager.get_storage_info(), indent=2))
    else:
        DiskManager.print_storage_table()
        if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
            DiskManager.print_conversion_guide()


if __name__ == "__main__":
    main()
