import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'components'))
sys.path.insert(0, str(ROOT/'components/cloudpc'))
from session import Reminder
from cloudpc import save_settings, load_settings, open_windows_app
from launchers import integrate
from app_identity import desktop_metadata

spec = importlib.util.spec_from_file_location('base_release', ROOT/'build/verify-base-release.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


class ReminderTests(unittest.TestCase):
    def test_warning_expiry_reset_and_pause(self):
        reminder = Reminder()
        self.assertIsNone(reminder.tick(900))
        reminder.start(100)
        self.assertIsNone(reminder.tick(579))
        self.assertEqual(reminder.tick(580), 'warning')
        self.assertIsNone(reminder.tick(581))
        self.assertEqual(reminder.tick(700), 'expired')
        self.assertIsNone(reminder.tick(900))
        reminder.start(900)
        self.assertEqual(reminder.remaining(900), 600)
        reminder.pause()
        self.assertIsNone(reminder.tick(9999))

    def test_wake_after_deadline(self):
        reminder = Reminder(); reminder.start(10)
        self.assertEqual(reminder.tick(10000), 'expired')
        self.assertEqual(reminder.remaining(10000), 0)

    def test_settings_invalid_save_preserves_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'settings.json'
            save_settings(path,600,120)
            with self.assertRaises(ValueError): save_settings(path,60,120)
            self.assertEqual(load_settings(path),(600,120))
            path.write_text('{broken')
            self.assertEqual(load_settings(path),(600,120))

    def test_open_uses_vendor_launcher_without_shell(self):
        with patch('cloudpc.shutil.which',return_value='/usr/local/bin/devos-pwa'), patch('cloudpc.subprocess.Popen') as launch:
            open_windows_app()
            self.assertEqual(launch.call_args.args[0], ['/usr/local/bin/devos-pwa','https://windows.cloud.microsoft/','Windows App',''])
            self.assertNotIn('shell',launch.call_args.kwargs)

    def test_existing_vendor_shortcut_keeps_actions_and_other_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/('chrome-'+'a'*32+'-Default.desktop')
            p.write_text('[Desktop Entry]\nName=Windows App\nExec=chrome --app-id='+'a'*32+'\nIcon=vendor\n[Desktop Action new]\nExec=original\n')
            other=Path(directory)/('chrome-'+'b'*32+'-Default.desktop')
            other.write_text('[Desktop Entry]\nName=Other App\nExec=chrome --app-id='+'b'*32+'\n')
            previous=other.read_bytes()
            self.assertEqual(integrate(directory),1)
            self.assertIn('Exec=/usr/local/bin/devos-windows-app',p.read_text())
            self.assertIn('[Desktop Action new]\nExec=original',p.read_text())
            self.assertEqual(other.read_bytes(),previous)
            self.assertEqual(integrate(directory),0)


class IdentityTests(unittest.TestCase):
    def test_desktop_name_icon_and_wm_class(self):
        self.assertEqual(desktop_metadata('devos-optimizer'),('DevOS Optimizer','devos-optimizer','devos-optimizer'))
        self.assertIsNone(desktop_metadata('../outside'))

    def test_upstream_identity_rejects_branded_or_old_base(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'usr/lib/os-release.ubuntu';p.parent.mkdir(parents=True)
            p.write_text('ID=ubuntu\nVERSION_ID="26.04"\nVERSION_CODENAME=resolute\n')
            base.validate(directory,'26.04','resolute')
            for text in ('ID=devos\nVERSION_ID=26.04\nVERSION_CODENAME=resolute\n','ID=ubuntu\nVERSION_ID=24.04\nVERSION_CODENAME=noble\n'):
                p.write_text(text)
                with self.assertRaises(ValueError): base.validate(directory,'26.04','resolute')

if __name__=='__main__': unittest.main()
