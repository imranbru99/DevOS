"""
Unit tests for DevOS Disk & Storage Controller (disk_manager.py).
Tests Windows-like size formatting, partition parent parsing, lsblk parsing,
diagnostics, and solution dispatching.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

SYS_PATH_SETTINGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/settings"))
if SYS_PATH_SETTINGS not in sys.path:
    sys.path.insert(0, SYS_PATH_SETTINGS)

from disk_manager import (
    format_size,
    parse_partition_parent,
    parse_lsblk,
    DiskManager
)


class TestDiskManager(unittest.TestCase):

    def test_format_size(self):
        self.assertEqual(format_size(0), "0 B")
        self.assertEqual(format_size(-50), "0 B")
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(1024), "1 KB")
        self.assertEqual(format_size(536870912), "512 MB")
        self.assertEqual(format_size(500107862016), "465.8 GB")
        self.assertEqual(format_size(1000204886016), "931.5 GB")

    def test_parse_partition_parent(self):
        self.assertEqual(parse_partition_parent("/dev/sda1"), ("/dev/sda", "1"))
        self.assertEqual(parse_partition_parent("/dev/sda2"), ("/dev/sda", "2"))
        self.assertEqual(parse_partition_parent("/dev/nvme0n1p1"), ("/dev/nvme0n1", "1"))
        self.assertEqual(parse_partition_parent("/dev/nvme0n1p2"), ("/dev/nvme0n1", "2"))
        self.assertEqual(parse_partition_parent("/dev/mmcblk0p1"), ("/dev/mmcblk0", "1"))
        self.assertEqual(parse_partition_parent("/dev/vda3"), ("/dev/vda", "3"))
        self.assertEqual(parse_partition_parent("/dev/sda"), ("", ""))

    def test_parse_lsblk_structure(self):
        sample_data = {
            "blockdevices": [
                {
                    "name": "sda",
                    "type": "disk",
                    "size": 1000204886016,
                    "model": "WDC WD10EZEX",
                    "tran": "sata",
                    "rota": True,
                    "pttype": "gpt",
                    "children": [
                        {
                            "name": "sda1",
                            "size": 536870912,
                            "fsavail": 500000000,
                            "fsused": 36870912,
                            "fsuse%": "7%",
                            "fstype": "vfat",
                            "mountpoints": ["/boot/efi"],
                            "label": "DEVOS_EFI",
                            "parttype": "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
                        },
                        {
                            "name": "sda2",
                            "size": 999666221056,
                            "fsavail": 800000000000,
                            "fsused": 199666221056,
                            "fsuse%": "20%",
                            "fstype": "ext4",
                            "mountpoints": ["/"],
                            "label": "DevOS",
                            "parttype": "0fc63daf-8483-4772-8e79-3d69d8477de4"
                        }
                    ]
                }
            ]
        }
        disks = parse_lsblk(sample_data, subvolumes={}, is_uefi=True, live=False)
        self.assertEqual(len(disks), 1)
        disk = disks[0]
        self.assertEqual(disk["device"], "/dev/sda")
        self.assertEqual(disk["size_human"], "931.5 GB")
        self.assertEqual(disk["partition_table"], "GPT (GUID Partition Table - UEFI Standard)")
        self.assertTrue(disk["is_system_disk"])
        self.assertEqual(len(disk["partitions"]), 2)

        part1 = disk["partitions"][0]
        self.assertEqual(part1["device"], "/dev/sda1")
        self.assertEqual(part1["size_human"], "512 MB")
        self.assertTrue(part1["is_esp"])
        self.assertIn("used", part1["used_free_human"])

    def test_diagnose_disk_protection(self):
        # Live media protection
        usb_disk = {
            "device": "/dev/sdb",
            "is_live_media": True,
            "is_system_disk": False,
            "raw_pttype": "gpt",
            "partitions": []
        }
        issues = DiskManager.diagnose_disk(usb_disk, is_uefi=True, live=True)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "live_media")
        self.assertEqual(issues[0]["action_id"], "")

        # System disk protection
        sys_disk = {
            "device": "/dev/nvme0n1",
            "is_live_media": False,
            "is_system_disk": True,
            "raw_pttype": "gpt",
            "partitions": []
        }
        issues = DiskManager.diagnose_disk(sys_disk, is_uefi=True, live=False)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "system_disk")
        self.assertEqual(issues[0]["action_id"], "")

    def test_diagnose_disk_unpartitioned_and_mbr(self):
        # Unpartitioned disk
        unpart_disk = {
            "device": "/dev/sda",
            "is_live_media": False,
            "is_system_disk": False,
            "raw_pttype": "",
            "partitions": []
        }
        issues = DiskManager.diagnose_disk(unpart_disk, is_uefi=True, live=False)
        self.assertEqual(issues[0]["type"], "unpartitioned")
        self.assertEqual(issues[0]["action_id"], "format_storage")

        # MBR disk on UEFI
        mbr_disk = {
            "device": "/dev/sda",
            "is_live_media": False,
            "is_system_disk": False,
            "raw_pttype": "dos",
            "partitions": []
        }
        # MBR is valid for a data drive on a UEFI desktop; it is only an
        # installation compatibility warning while preparing a boot disk.
        issues = DiskManager.diagnose_disk(mbr_disk, is_uefi=True, live=False)
        self.assertFalse(any(i["type"] == "mbr_on_uefi" for i in issues))
        issues = DiskManager.diagnose_disk(mbr_disk, is_uefi=True, live=True)
        self.assertTrue(any(i["type"] == "mbr_on_uefi" for i in issues))

    def test_apply_solution_safety_guards(self):
        # Test invalid device name
        res = DiskManager.apply_solution("sda; rm -rf /", "wipe_disk")
        self.assertFalse(res["success"])
        self.assertIn("Invalid device", res["error"])

        # Test system disk protection
        with patch.object(DiskManager, "get_storage_info") as mock_info:
            mock_info.return_value = [{
                "device": "/dev/nvme0n1",
                "is_system_disk": True,
                "is_live_media": False,
                "partitions": [{"device": "/dev/nvme0n1p2", "mountpoint": "/"}]
            }]
            with patch("disk_manager.is_live_system", return_value=False):
                res = DiskManager.apply_solution("/dev/nvme0n1", "wipe_disk")
                self.assertFalse(res["success"])
                self.assertIn("running system disk", res["error"])

                res2 = DiskManager.apply_solution("/dev/nvme0n1p2", "format_partition")
                self.assertFalse(res2["success"])
                self.assertIn("mounted as active system root", res2["error"])


if __name__ == "__main__":
    unittest.main()
