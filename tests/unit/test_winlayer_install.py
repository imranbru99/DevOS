"""WinLayer installs local .exe/.msi as Windows apps (Start + Apps console)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "winlayer"))

from prefix_manager import WinLayerManager  # noqa: E402


class TestWinLayerInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="devos-winlayer-")
        self.addCleanup(self.tmp.cleanup)
        self.home = self.tmp.name
        self.prefixes = os.path.join(self.home, ".local/share/winlayer/prefixes")
        self.desktop = os.path.join(self.home, ".local/share/applications")
        os.makedirs(self.prefixes, exist_ok=True)
        os.makedirs(self.desktop, exist_ok=True)

        # Point manager storage at the temp home for this test process.
        import prefix_manager as pm

        self._old = (pm.PREFIXES_ROOT, pm.DESKTOP_DIR, pm.BASE_PREFIX, pm.OPEN_APP)
        pm.PREFIXES_ROOT = self.prefixes
        pm.DESKTOP_DIR = self.desktop
        pm.BASE_PREFIX = os.path.join(self.home, ".local/share/winlayer/base")
        pm.OPEN_APP = os.path.join(self.home, "devos-open-app")
        Path(pm.OPEN_APP).write_text("#!/bin/sh\n", encoding="utf-8")
        os.chmod(pm.OPEN_APP, 0o755)
        self.mgr = WinLayerManager()
        self.addCleanup(self._restore)

    def _restore(self):
        import prefix_manager as pm

        pm.PREFIXES_ROOT, pm.DESKTOP_DIR, pm.BASE_PREFIX, pm.OPEN_APP = self._old

    def test_display_name_strips_installer_noise(self):
        self.assertEqual(WinLayerManager.display_name("ZoomInstaller.exe"), "Zoom")
        self.assertEqual(WinLayerManager.display_name("app-setup-1.2.3-win64.exe"), "App")
        self.assertEqual(WinLayerManager.display_name("tool.msi"), "Tool")

    def test_is_installer(self):
        self.assertTrue(WinLayerManager.is_installer("/tmp/FooSetup.exe"))
        self.assertTrue(WinLayerManager.is_installer("/tmp/package.msi"))
        self.assertFalse(WinLayerManager.is_installer("/tmp/portable-tool.exe"))

    def test_write_desktop_entry_is_windows_app(self):
        prefix = os.path.join(self.prefixes, "zoom")
        os.makedirs(os.path.join(prefix, "drive_c"), exist_ok=True)
        exe = os.path.join(prefix, "drive_c", "zoom.exe")
        Path(exe).write_bytes(b"MZ")
        info = self.mgr.write_desktop_entry("zoom", "Zoom", exe, prefix)
        self.assertTrue(info["created"])
        path = info["path"]
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn("Name=Zoom\n", text)
        self.assertIn("GenericName=Windows app\n", text)
        self.assertIn("Comment=Windows app on DevOS\n", text)
        self.assertIn(f'Exec={os.path.join(self.home, "devos-open-app")} "{exe}"', text)
        self.assertTrue(path.endswith("winlayer-zoom.desktop"))
        again = self.mgr.write_desktop_entry("zoom", "Zoom", exe, prefix)
        self.assertFalse(again["created"])

    def test_stage_portable_copies_into_prefix(self):
        prefix = os.path.join(self.prefixes, "tool")
        os.makedirs(os.path.join(prefix, "drive_c"), exist_ok=True)
        src = os.path.join(self.home, "Downloads", "CoolTool.exe")
        os.makedirs(os.path.dirname(src), exist_ok=True)
        Path(src).write_bytes(b"MZ" + b"\0" * 32)
        dest = self.mgr.stage_executable(src, prefix, "cooltool")
        self.assertTrue(dest.startswith(os.path.join(prefix, "drive_c")))
        self.assertTrue(os.path.isfile(dest))
        self.assertNotEqual(os.path.realpath(src), os.path.realpath(dest))

    def test_launch_registers_windows_app_without_wine(self):
        pe = os.path.join(self.home, "HelloWorld.exe")
        Path(pe).write_bytes(b"MZ" + b"\0" * 0x3C + b"PE\0\0" + b"\0" * 64)
        # Minimal fake PE still fails deeper parse; stub doctor + wine path.
        with mock.patch.object(
            self.mgr,
            "prepare_prefix",
            return_value={"status": "READY"},
        ), mock.patch.object(
            self.mgr,
            "run_in_wine",
            return_value={"status": "STARTED", "pid": 1, "log": "/tmp/x.log"},
        ), mock.patch(
            "prefix_manager.WinLayerDoctor.analyze_pe",
            return_value={
                "is_pe": True,
                "compatibility_rating": "Works",
                "architecture": "i386 (32-bit)",
                "anti_cheat_flagged": False,
            },
        ):
            res = self.mgr.launch(pe)
        self.assertEqual(res["status"], "LAUNCHED")
        self.assertEqual(res["app_name"], "HelloWorld")
        self.assertTrue(res.get("registered"))
        shortcut = res["desktop_shortcut"]
        self.assertTrue(os.path.isfile(shortcut))
        body = Path(shortcut).read_text(encoding="utf-8")
        self.assertIn("GenericName=Windows app", body)
        self.assertIn("Name=HelloWorld", body)

    def test_apps_console_has_install_windows_action(self):
        apps_src = (ROOT / "components" / "apps" / "apps_manager.py").read_text(encoding="utf-8")
        self.assertIn("def install_windows_app(self):", apps_src)
        self.assertIn("Install Windows app…", apps_src)
        self.assertIn("Windows apps (*.exe *.msi *.bat *.cmd)", apps_src)


if __name__ == "__main__":
    unittest.main()
