import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'components/settings'))
import installer_storage as storage
from storage_layout import GIB


def disk(device='/dev/sdb', **changes):
    d={'device':device,'model':'Example SSD','serial':'serial-'+device,'size_bytes':500*GIB,
       'partitions':[],'read_only':False,'is_live_media':False,'is_system_disk':False}
    d.update(changes); return d


def selection(disks, **changes):
    plan={'confirmed':True,'drives':[dict(d,volumes=[{'label':'A','filesystem':'ext4','size_gib':0}]) for d in disks]}
    plan.update(changes); return json.dumps(plan)


OS_PARTITIONS = [{'device':'/dev/nvme0n1p2','mountPoint':'/'}]


class InstallerStorageTests(unittest.TestCase):
    def test_system_reserve_is_capped_only_on_the_new_mounted_ext4_device(self):
        part = dict(OS_PARTITIONS[0], fs='ext4', claimed=True)
        target = '/tmp/calamares-target'
        info = 'Reserved block count: 6000000\nBlock size: 4096\n'
        block = SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=123)
        mount = SimpleNamespace(st_dev=123)
        with patch.object(storage.os.path, 'realpath', return_value=target), \
             patch.object(storage.os.path, 'ismount', return_value=True), \
             patch.object(storage.os, 'stat', side_effect=[block, mount, block, mount, block, SimpleNamespace(st_dev=456)]), \
             patch.object(storage.subprocess, 'check_output', side_effect=[info, info.replace('6000000', '200000')]) as read, \
             patch.object(storage.subprocess, 'run') as write:
            storage.cap_system_reserve(target, [dict(part, claimed=False)])
            storage.cap_system_reserve(target, [dict(part, fs='btrfs')])
            read.assert_not_called()
            storage.cap_system_reserve(target, [part])
            write.assert_called_once()
            self.assertEqual(write.call_args.args[0], ['tune2fs', '-r', '1310720', part['device']])
            storage.cap_system_reserve(target, [part])
            with self.assertRaisesRegex(ValueError, 'does not match'):
                storage.cap_system_reserve(target, [part])
            write.assert_called_once()

    def test_unconfirmed_or_empty_plan_never_changes_disks(self):
        for raw in ('{}',selection([disk()],confirmed=False)):
            self.assertEqual(storage.prepare(raw,[disk()],OS_PARTITIONS),[])

    def test_os_and_manually_claimed_disks_are_handled_by_calamares(self):
        current=disk()
        for part in ({'device':'/dev/sdb2','mountPoint':'/'}, {'device':'/dev/sdb1','claimed':True}):
            self.assertEqual(storage.prepare(selection([current]),[current],[part]),[])

    def test_identity_changes_or_protected_disks_are_rejected(self):
        original=disk()
        variants=[disk(serial='changed'),disk(model='changed'),disk(size_bytes=100*GIB),disk(read_only=True),
                  disk(is_live_media=True),disk(partitions=[{'mounted':True}])]
        for current in variants:
            with self.subTest(current=current),self.assertRaises(ValueError):
                storage.prepare(selection([original]),[current],OS_PARTITIONS)

    def test_all_drives_are_preflighted_before_any_mutation(self):
        d1,d2=disk('/dev/sdb'),disk('/dev/sdc')
        d2_current=disk('/dev/sdc',read_only=True)
        with patch.object(storage.DiskManager,'get_storage_info',return_value=[d1,d2_current]), \
             patch.object(storage.DiskManager,'apply_solution') as mutate:
            with self.assertRaises(ValueError): storage.apply(selection([d1,d2]),'/fake',OS_PARTITIONS)
            mutate.assert_not_called()

    def test_missing_filesystem_tool_blocks_all_selected_drives(self):
        with patch.object(storage.shutil,'which',side_effect=lambda name: None if name=='mkfs.ext4' else '/tool'):
            with self.assertRaisesRegex(ValueError,'mkfs.ext4'):
                storage.prepare(selection([disk()]),[disk()],OS_PARTITIONS)

    def test_automatic_extra_drives_require_ext4(self):
        plan=json.loads(selection([disk()]));plan['drives'][0]['volumes'][0]['filesystem']='btrfs'
        with self.assertRaisesRegex(ValueError,'ext4'):
            storage.prepare(json.dumps(plan),[disk()],OS_PARTITIONS)

    def test_only_explicit_disks_are_formatted_as_installed_owner(self):
        selected=disk('/dev/sdb'); untouched=disk('/dev/sdc')
        with patch.object(storage.shutil,'which',return_value='/tool'), \
             patch.object(storage.DiskManager,'get_storage_info',return_value=[selected,untouched]), \
             patch.object(storage,'installed_owner',return_value=(1001,1001)), \
             patch.object(storage.DiskManager,'apply_solution',return_value={'success':True}) as mutate:
            storage.apply(selection([selected]),'/fake-root',OS_PARTITIONS)
            mutate.assert_called_once()
            self.assertEqual(mutate.call_args.args,('/dev/sdb','partition_storage'))
            self.assertEqual(mutate.call_args.kwargs['owner'],(1001,1001))

    def test_missing_installer_partition_map_blocks_formatting(self):
        with self.assertRaisesRegex(ValueError, 'partition map'):
            storage.prepare(selection([disk()]), [disk()], [])

    def test_failure_on_one_disk_is_collected_and_next_disk_still_runs(self):
        d1,d2=disk('/dev/sdb'),disk('/dev/sdc')
        with patch.object(storage.shutil,'which',return_value='/tool'), \
             patch.object(storage.DiskManager,'get_storage_info',return_value=[d1,d2]), \
             patch.object(storage,'installed_owner',return_value=(1000,1000)), \
             patch.object(storage.DiskManager,'apply_solution',return_value={'success':False,'error':'I/O failure'}) as mutate:
            failures = storage.apply(selection([d1,d2]),'/fake-root',OS_PARTITIONS)
            self.assertEqual(len(failures), 2)
            self.assertIn('not rolled back', failures[0])
            # Optional storage must not raise — install/bootloader keep going.
            self.assertEqual(mutate.call_count, 2)

    def test_calamares_job_forwards_root_and_partition_map(self):
        import importlib.util
        from types import SimpleNamespace
        choice='Erase selected additional drives (ext4):<br/>/dev/sdb → A remaining<br/>OS and manually configured disks are excluded.'
        raw=storage.parse_choice(choice,[disk()])
        values={'packagechooser_storage':choice,'rootMountPoint':'/tmp/example-target','partitions':OS_PARTITIONS}
        lib=SimpleNamespace(
            globalstorage=SimpleNamespace(value=lambda key: values.get(key)),
            utils=SimpleNamespace(warning=lambda *_a, **_k: None),
        )
        path=ROOT/'build/includes.chroot/usr/lib/x86_64-linux-gnu/calamares/modules/devosstorage/main.py'
        with patch.dict(sys.modules,{'libcalamares':lib}):
            spec=importlib.util.spec_from_file_location('devosstorage_job_test',path)
            job=importlib.util.module_from_spec(spec);spec.loader.exec_module(job)
            with patch.object(job.Path,'read_text',return_value=json.dumps([disk()])), patch.object(storage,'apply',return_value=[]) as apply:
                self.assertIsNone(job.run())
                apply.assert_called_once_with(raw,values['rootMountPoint'],OS_PARTITIONS)
            with patch.object(job.Path,'read_text',return_value=json.dumps([disk()])), patch.object(storage,'apply',return_value=['/dev/sda: mkfs segfault']):
                # Optional data-drive failures must not abort bootloader/finalize.
                self.assertIsNone(job.run())
            with patch.object(job.Path,'read_text',return_value=json.dumps([disk()])), patch.object(storage,'apply',side_effect=ValueError('drive changed')):
                self.assertIsNone(job.run())

    def test_data_drive_job_runs_after_user_creation_and_bootloader(self):
        text=(ROOT/'build/includes.chroot/etc/calamares/settings.conf').read_text()
        sequence=text.split('- exec:')[1].split('- show:')[0]
        self.assertLess(sequence.index('- usersq'),sequence.index('- shellprocess@finalize'))
        self.assertLess(sequence.index('- devosbootloader'),sequence.index('- devosstorage'))
        self.assertLess(sequence.index('- devosbootloader'),sequence.index('- shellprocess@features-shell'))

    def test_human_review_round_trips_abc_layout_and_scanned_identity(self):
        choice='Erase selected additional drives (ext4):<br/>/dev/sdb → Work A 100 GiB · B 150.5 GiB · C remaining<br/>OS and manually configured disks are excluded.'
        plan=json.loads(storage.parse_choice(choice,[disk()]))
        self.assertTrue(plan['confirmed'])
        self.assertEqual(plan['drives'][0]['serial'],disk()['serial'])
        self.assertEqual([v['size_gib'] for v in plan['drives'][0]['volumes']],[100,150.5,0])
        self.assertEqual(plan['drives'][0]['volumes'][0]['label'],'Work A')

    def test_unknown_disks_and_unreviewed_strings_are_rejected(self):
        for choice in ('anything', 'Erase selected additional drives (ext4):<br/>/dev/sdc → A remaining<br/>OS and manually configured disks are excluded.'):
            with self.assertRaises(ValueError):storage.parse_choice(choice,[disk()])
        self.assertEqual(storage.parse_choice('Preserve all additional drives',[]),'{}')
