"""Unit tests for DevOS Windows 11 Sound Settings & Volume Hub."""

import json
import os
import runpy
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
SOUND_SCRIPT = str(ROOT / "build/includes.chroot/usr/local/bin/devos-sound")


class SoundManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.TemporaryDirectory()
        cls.state_file = os.path.join(cls.test_dir.name, "sound_state.json")
        os.environ["DEVOS_AUDIO_STATE_FILE"] = cls.state_file

        cls.app = QApplication.instance() or QApplication([])
        cls.mod = runpy.run_path(SOUND_SCRIPT)

    @classmethod
    def tearDownClass(cls):
        cls.test_dir.cleanup()
        os.environ.pop("DEVOS_AUDIO_STATE_FILE", None)

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
        with patch("subprocess.run") as mock_run:
            AudioManager.set_master_volume(-5, is_user_action=False)
            mock_run.assert_called_with(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "0%"], check=False)
            AudioManager.set_master_volume(150, is_user_action=False)
            mock_run.assert_called_with(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "100%"], check=False)

    def test_volume_tracking_and_persistence(self):
        AudioManager = self.mod["AudioManager"]
        with patch("subprocess.run"):
            # Set to 42%
            AudioManager.set_master_volume(42, is_user_action=True)
            tracked = AudioManager.load_tracked_state()
            self.assertEqual(tracked.get("master_volume"), 42)

            # Set mute
            AudioManager.set_master_mute(True, is_user_action=True)
            tracked = AudioManager.load_tracked_state()
            self.assertTrue(tracked.get("master_muted"))

            # Unmute
            AudioManager.set_master_mute(False, is_user_action=True)
            tracked = AudioManager.load_tracked_state()
            self.assertFalse(tracked.get("master_muted"))

    def test_anti_jump_protection_from_rogue_100_percent(self):
        AudioManager = self.mod["AudioManager"]
        with patch("subprocess.run") as mock_run:
            # User previously set 38%
            AudioManager.set_master_volume(38, is_user_action=True)
            AudioManager._last_user_action_time = time.time() - 10.0  # long ago
            AudioManager.save_tracked_state({"last_user_set_time": time.time() - 10.0})

            # Rogue event jumps volume to 100%
            rogue_state = {
                "master_volume": 100,
                "master_muted": False,
                "default_sink": "test-sink",
            }
            fixed_state = AudioManager.enforce_volume_protection(rogue_state)

            # Should have clamped back to user preference 38%
            self.assertEqual(fixed_state["master_volume"], 38)
            mock_run.assert_called_with(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "38%"], check=False)

    def test_intentional_100_percent_volume_not_clamped(self):
        AudioManager = self.mod["AudioManager"]
        with patch("subprocess.run"):
            # User intentionally sets 100%
            AudioManager.set_master_volume(100, is_user_action=True)
            state = {
                "master_volume": 100,
                "master_muted": False,
                "default_sink": "test-sink",
            }
            result_state = AudioManager.enforce_volume_protection(state)
            self.assertEqual(result_state["master_volume"], 100)


if __name__ == "__main__":
    unittest.main()
