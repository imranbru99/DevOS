import errno
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module
access = load('devos_storage_access', 'components/settings/storage_access.py')
common = load('devos_security_common_storage_test', 'components/security/seccommon.py')


class StorageAccessTests(unittest.TestCase):
    def test_home_probe_cleans_up_files(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'.config').mkdir()
            self.assertTrue(access.check_home(folder)['success'])
            self.assertEqual(list((Path(folder)/'.config').iterdir()), [])
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['.config'])

    def test_write_errors_are_distinguished(self):
        for number, cause in [(errno.EACCES,'permission_denied'),(errno.EROFS,'read_only_filesystem'),(errno.ENOSPC,'disk_or_inodes_full'),(errno.EIO,'disk_io_error')]:
            with patch.object(access.tempfile, 'mkstemp', side_effect=OSError(number,'test failure')):
                self.assertEqual(access.check_directory('/fake')['cause'], cause)

    def test_failed_security_write_preserves_original_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state'; path.write_text('original')
            with patch.object(common.os, 'replace', side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError): common.write_text(str(path), 'replacement')
            self.assertEqual(path.read_text(), 'original')
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['state'])

    def test_predictable_temp_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'state'; victim = Path(folder)/'untouched'; victim.write_text('safe')
            Path(str(path)+'.devos-new').symlink_to(victim)
            common.write_text(str(path), 'new', 0o600)
            self.assertEqual(victim.read_text(), 'safe')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_boot_diagnostics_do_not_write_or_repair_disks(self):
        helper = ROOT/'build/includes.chroot/etc/initramfs-tools/scripts/local-bottom/devos-btrfs-heal'
        with tempfile.TemporaryDirectory() as folder:
            env = dict(__import__('os').environ, rootmnt=folder, ROOT='/dev/fake-test-disk', ROOTFSTYPE='btrfs')
            result = subprocess.run(['sh',str(helper)],env=env,capture_output=True,text=True,check=True)
            self.assertIn('No automatic repair', result.stdout)
            self.assertEqual(list(Path(folder).iterdir()), [])
            source=helper.read_text()
            self.assertNotIn('btrfs rescue zero-log',source)
            self.assertNotIn('mount -o remount',source)
