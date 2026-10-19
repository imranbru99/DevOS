#!/usr/bin/env python3
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

DISPLAY_BIN = os.path.join(ROOT, "build", "includes.chroot", "usr", "local", "bin", "devos-display")
DESKTOP_ENTRY = os.path.join(ROOT, "build", "includes.chroot", "usr", "share", "applications", "devos-display.desktop")


class TestDisplaySettings(unittest.TestCase):
    def test_binary_and_desktop_file_exist(self):
        self.assertTrue(os.path.isfile(DISPLAY_BIN), "devos-display binary must exist")
        self.assertTrue(os.access(DISPLAY_BIN, os.X_OK), "devos-display must be executable")
        self.assertTrue(os.path.isfile(DESKTOP_ENTRY), "devos-display.desktop must exist")

        with open(DESKTOP_ENTRY, "r", encoding="utf-8") as f:
            content = f.read()
            self.assertIn("Name=Display Settings", content)
            self.assertIn("Exec=devos-display", content)

    def test_display_parser_and_auto_logic(self):
        from importlib.machinery import SourceFileLoader
        import importlib.util
        loader = SourceFileLoader("devos_display", DISPLAY_BIN)
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("devos_display", loader))
        loader.exec_module(mod)

        displays = mod.get_displays()
        self.assertIsInstance(displays, list)
        if displays:
            disp = displays[0]
            self.assertIn("name", disp)
            self.assertIn("connected", disp)
            self.assertIn("modes", disp)


if __name__ == "__main__":
    unittest.main()
