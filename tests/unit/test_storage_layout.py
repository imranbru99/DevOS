import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'components/settings'))
from storage_layout import plan_layout, partition_device, layout_script, ownership_script, volume_label, GIB, system_layout_script
from disk_manager import DiskManager


def disk(**changes):
    result = {'device': '/dev/sdb', 'size_bytes': 500 * GIB, 'partitions': [],
              'is_live_media': False, 'is_system_disk': False, 'read_only': False}
    result.update(changes)
    return result


class StorageLayoutTests(unittest.TestCase):
    def test_abc_sizes_are_aligned_with_remaining_space(self):
        plan = plan_layout(500 * GIB, [{'label': 'A', 'size_gib': 100}, {'label': 'B', 'size_gib': 150}, {'label': 'C'}])
        self.assertEqual([p['label'] for p in plan], ['A', 'B', 'C'])
        self.assertEqual(plan[0]['size_bytes'], 100 * GIB)
        self.assertEqual(plan[1]['end_mib'], plan[2]['start_mib'])
        self.assertEqual(sum(p['size_bytes'] for p in plan), 500 * GIB - 2 * 1024 ** 2)

    def test_invalid_or_overcommitted_sizes_are_rejected(self):
        for sizes in ([600, 0], [0, 20], [-1, 0], ['nan', 0], ['Infinity', 0], [0.001, 0]):
            with self.subTest(sizes=sizes), self.assertRaises(ValueError):
                plan_layout(500 * GIB, [{'label': chr(65+i), 'size_gib': s} for i, s in enumerate(sizes)])

    def test_duplicate_and_shell_labels_are_rejected(self):
        for label in [';touch /tmp/injected', '$(id)', '../C', 'A\nB']:
            with self.assertRaises(ValueError): volume_label(label, 'ext4')
        with self.assertRaises(ValueError):
            plan_layout(500 * GIB, [{'label': 'A', 'size_gib': 10}, {'label': 'a'}])

    def test_nvme_mmc_sata_partition_names(self):
        for source, expected in [('/dev/sdb','/dev/sdb3'),('/dev/nvme0n1','/dev/nvme0n1p3'),('/dev/mmcblk0','/dev/mmcblk0p3')]:
            self.assertEqual(partition_device(source, 3), expected)

    def test_linux_data_ownership_is_set_without_recursion(self):
        script = ownership_script('/dev/sdb1', 'ext4', (1000, 1000))
        self.assertIn('chown 1000:1000 "$volume_mount"', script)
        self.assertNotIn('chown -R', script)
        self.assertIn('umount "$volume_mount"', script)
        self.assertEqual(ownership_script('/dev/sdb1', 'exfat', (1000, 1000)), '')

    def test_layout_script_is_valid_shell_and_maps_exfat_partition_type(self):
        plan = plan_layout(500 * GIB, [{'label': 'Shared Data', 'filesystem': 'exfat'}])
        script = layout_script('/dev/nvme0n1', plan, (1000, 1000))
        self.assertIn("mkpart 'Shared Data' ntfs", script)
        self.assertIn("mkfs.exfat -n 'Shared Data' /dev/nvme0n1p1", script)
        self.assertIn('test -b /dev/nvme0n1p1', script)
        self.assertIn('for _try in 1 2 3', script)
        self.assertEqual(subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True).returncode, 0)

    def test_unknown_readonly_and_mounted_targets_never_spawn_commands(self):
        for inventory in ([], [disk(read_only=True)], [disk(partitions=[{'device':'/dev/sdb1','mounted':True}])]):
            with patch.object(DiskManager, 'get_storage_info', return_value=inventory), patch('disk_manager.subprocess.run') as run:
                result = DiskManager.apply_solution('/dev/sdb', 'wipe_disk')
                self.assertFalse(result['success'])
                run.assert_not_called()

    def test_zstd_is_not_silently_interpreted_as_ext4(self):
        with patch('disk_manager.subprocess.run') as run:
            self.assertFalse(DiskManager.apply_solution('/dev/sdb', 'format_storage', fs_type='zstd')['success'])
            run.assert_not_called()

    def test_new_layout_rechecks_device_after_elevation(self):
        with patch.object(DiskManager, 'get_storage_info', return_value=[disk()]), \
             patch('disk_manager.shutil.which', return_value='/usr/bin/tool'), \
             patch('disk_manager.desktop_owner', return_value=(1000,1000)), \
             patch('disk_manager.subprocess.run', return_value=Mock(returncode=0, stdout='', stderr='')) as run:
            result = DiskManager.apply_solution('/dev/sdb', 'partition_storage', volumes=[{'label':'A'}])
            self.assertTrue(result['success'])
            script = run.call_args.args[0][-1]
            self.assertIn('lsblk -dnro RO /dev/sdb', script)
            self.assertIn('lsblk -nro MOUNTPOINT /dev/sdb', script)
            self.assertNotIn('umount -f', script)
            self.assertNotIn('\\"', script)
            self.assertIn('chown 1000:1000', script)

        self.assertEqual(subprocess.run(['bash', '-n'], input=script, text=True, capture_output=True).returncode, 0)


    def test_data_disk_is_not_misdiagnosed_as_missing_boot_partition(self):
        data = disk(raw_pttype='gpt')
        issues = DiskManager.diagnose_disk(data, is_uefi=True, live=False)
        self.assertFalse(any(p['type'] == 'missing_efi' for p in issues))
        self.assertTrue(all(not p['action_id'] for p in issues))


    def test_system_layout_matches_uefi_and_bios_without_changing_root_owner(self):
        uefi = system_layout_script('/dev/nvme0n1','ext4','DevOS',True)
        bios = system_layout_script('/dev/sdb','ext4','DevOS',False)
        self.assertIn('esp on',uefi)
        self.assertIn('mkfs.vfat -F32 -n DEVOS_EFI /dev/nvme0n1p1',uefi)
        self.assertIn('bios_grub on',bios)
        self.assertNotIn('mkfs.vfat',bios)
        self.assertIn('mkpart DevOS ext4 3MiB 100%',bios)
        self.assertNotIn('chown',uefi+bios)
        for script in (uefi,bios):
            self.assertEqual(subprocess.run(['bash','-n'],input=script,text=True,capture_output=True).returncode,0)
