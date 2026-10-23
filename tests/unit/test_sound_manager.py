"""Unit tests for DevOS Windows 11 Sound Settings & Volume Hub."""

import json
import os
import runpy
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
SOUND_SCRIPT = str(ROOT / "build/includes.chroot/usr/local/bin/devos-sound")


class SoundManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.mod = runpy.run_path(SOUND_SCRIPT)

    def test_audio_manager_state(self):
        AudioManager = self.mod["AudioManager"]
        state = AudioManager.get_audio_state()
        self.assertIsInstance(state, dict)
        self.assertIn("sinks", state)
        self.assertIn("sources", state)
        self.assertIn("master_volume", state)
        self.assertIn("master_muted", state)
        self.assertTrue(0 <= state["master_volume"] <= 100)

    def test_vector_sound_icons(self):
        make_icon = self.mod["make_vector_sound_icon"]
        for name in ("volume-high", "volume-medium", "volume-low", "volume-muted", "mic", "mic-muted", "play", "mixer", "settings"):
            icon = make_icon(name, size=24)
            self.assertFalse(icon.isNull(), f"Icon {name} should not be null")

    def test_settings_window_instantiation(self):
        cls = self.mod["WindowsSoundSettingsWindow"]
        win = cls()
        self.assertEqual(win.windowTitle(), "Sound - DevOS Settings")
        self.assertIsNotNone(win.slider_master)
        self.assertIsNotNone(win.card_output)
        self.assertIsNotNone(win.card_input)
        self.assertIsNotNone(win.card_mixer)

    def test_volume_flyout_instantiation(self):
        cls = self.mod["WindowsVolumeFlyout"]
        flyout = cls()
        self.assertIsNotNone(flyout.card)
        self.assertIsNotNone(flyout.slider)
        flyout.refresh_data()

    def test_audio_manager_volume_clamping(self):
        AudioManager = self.mod["AudioManager"]
        # Should not crash on boundary or out of range values
        AudioManager.set_master_volume(-5)
        AudioManager.set_master_volume(150)


if __name__ == "__main__":
    unittest.main()
