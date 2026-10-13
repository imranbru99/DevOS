import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "components", "apphub"))

import native_alternatives as native  # noqa: E402


class TestNativeAlternatives(unittest.TestCase):
    def test_known_installers_get_the_devos_version(self):
        # AnyDesk's Windows build crashed under the Windows layer once used.
        self.assertEqual(native.match("/home/u/Downloads/AnyDesk.exe")["flatpak"], "com.anydesk.Anydesk")
        self.assertEqual(native.match("ZoomInstallerFull.msi")["flatpak"], "us.zoom.Zoom")
        self.assertEqual(native.match("DiscordSetup.exe")["flatpak"], "com.discordapp.Discord")

    def test_other_files_run_as_windows_apps(self):
        self.assertIsNone(native.match("setup.exe"))
        self.assertIsNone(native.match("notepad++.exe"))
        self.assertIsNone(native.match("my-game.apk"))
        self.assertIsNone(native.match("report.pdf"))

    def test_popular_apks_skip_the_android_download(self):
        self.assertEqual(native.match("WhatsApp.apk")["flatpak"], "com.rtosta.zapzap")
        self.assertEqual(native.match("telegram-10.2.apk")["flatpak"], "org.telegram.desktop")

    def test_flatpak_progress_is_read(self):
        self.assertEqual(native.parse_progress("Installing 2/3... 45%  2.1 MB/s"), 45)
        self.assertIsNone(native.parse_progress("Looking for matches"))

    def test_retired_services_are_not_offered(self):
        self.assertFalse(any("skype" in e["flatpak"].lower() for e in native.CATALOG))


if __name__ == "__main__":
    unittest.main()
