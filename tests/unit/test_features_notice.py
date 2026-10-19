#!/usr/bin/env python3
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "components", "features"))

import feature_catalog as catalog
import features_cli as cli
import first_boot_notice as notice


class TestFeaturesAndNotice(unittest.TestCase):
    def test_winapps_packages_valid(self):
        """Verify winapps does not request non-existent packages like dxvk/vkd3d."""
        winapps = catalog.feature("winapps")
        self.assertIsNotNone(winapps)
        self.assertNotIn("dxvk", winapps.get("apt", []))
        self.assertNotIn("vkd3d", winapps.get("apt", []))
        self.assertIn("wine", winapps.get("apt", []))
        self.assertIn("wine64", winapps.get("apt", []))
        self.assertIn("winetricks", winapps.get("apt", []))
        self.assertIn("libvkd3d1", winapps.get("apt", []))

    def test_notice_messages(self):
        title, body = notice.start_message({"pending": ["winapps"]})
        self.assertEqual(title, "Setting up your apps")
        self.assertIn("1 app you picked during install", body)

        done_title, done_body = notice.done_message({"pending": [], "failed": {}})
        self.assertEqual(done_title, "Your apps are ready")

        fail_title, fail_body = notice.done_message({"pending": ["winapps"], "failed": {"winapps": "error"}})
        self.assertEqual(fail_title, "Some apps didn't install")
        self.assertIn("Windows apps (.exe, .msi)", fail_body)

    def test_needs_notice_with_done_marker(self):
        with tempfile.TemporaryDirectory() as td:
            marker = os.path.join(td, "first_boot_notice.done")
            orig_marker = notice.DONE_MARKER
            try:
                notice.DONE_MARKER = marker
                # Without marker and pending apps -> needs notice
                self.assertTrue(notice.needs_notice({"pending": ["winapps"]}))

                # With marker and not running -> suppressed
                with open(marker, "w") as f:
                    f.write("1")
                self.assertFalse(notice.needs_notice({"pending": ["winapps"], "running": False}))

                # With marker but actively running -> needs notice
                self.assertTrue(notice.needs_notice({"pending": ["winapps"], "running": True}))
            finally:
                notice.DONE_MARKER = orig_marker

    def test_sddm_devos_theme_files_exist(self):
        theme_dir = os.path.join(ROOT, "build", "includes.chroot", "usr", "share", "sddm", "themes", "devos")
        self.assertTrue(os.path.isdir(theme_dir))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "Main.qml")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "theme.conf")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "metadata.desktop")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "background.png")))
        self.assertTrue(os.path.isfile(os.path.join(theme_dir, "logo.png")))

    def test_sddm_config_uses_devos_theme(self):
        conf_path = os.path.join(ROOT, "build", "includes.chroot", "etc", "sddm.conf.d", "devos-theme.conf")
        with open(conf_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Current=devos", content)
        self.assertIn("DisplayServer=x11", content)


if __name__ == "__main__":
    unittest.main()
