#!/usr/bin/env python3
"""Universal AV basics: mic seed, speaker scoring, camera probe."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components" / "assistant"))
sys.path.insert(0, str(ROOT / "components"))

import voice_prefs  # noqa: E402
import voice  # noqa: E402
from audio import camera_defaults, mic_defaults  # noqa: E402


class TestVoicePrefsSeed(unittest.TestCase):
    def test_first_login_seed_does_not_recurse(self):
        with tempfile.TemporaryDirectory() as tmp:
            user = os.path.join(tmp, "assistant.json")
            system = os.path.join(tmp, "voice-prefs.json")
            with open(system, "w", encoding="utf-8") as fh:
                json.dump({
                    "hands_free": True,
                    "wake_name": "Mira",
                    "tts_gender": "female",
                    "tts_language": "auto",
                }, fh)
            old_sys = voice_prefs.SYSTEM_PREFS
            try:
                voice_prefs.SYSTEM_PREFS = system
                data = voice_prefs.load(user)
                self.assertTrue(os.path.isfile(user))
                self.assertEqual(data["wake_name"], "Mira")
                self.assertTrue(data["hands_free"])
                # Second load reads the user file without reseeding forever.
                again = voice_prefs.load(user)
                self.assertEqual(again["wake_name"], "Mira")
            finally:
                voice_prefs.SYSTEM_PREFS = old_sys


class TestSpeakerScoring(unittest.TestCase):
    def test_output_reconnect_restores_saved_speaker_without_changing_gain(self):
        sinks = [{"name": "hdmi"}, {"name": "usb-speaker"}]
        with patch.object(mic_defaults, "list_output_sinks", return_value=sinks), \
             patch.object(mic_defaults, "load_preferences", return_value={}) as prefs, \
             patch.object(mic_defaults, "get_default_sink", return_value="hdmi"), \
             patch.object(mic_defaults, "set_default_sink") as select, \
             patch.object(mic_defaults, "ensure_sink_ready") as unmute:
            mic_defaults.restore_output()
            select.assert_not_called()
            prefs.return_value = {"preferred_sink_name": "usb-speaker"}
            mic_defaults.restore_output()
            select.assert_called_once_with("usb-speaker")
            unmute.assert_not_called()

    def test_usb_speaker_ranks_above_hdmi(self):
        text = """
Sink #0
	Name: alsa_output.pci-0000_00_02.0.hdmi-stereo
	Description: HDMI / DisplayPort
	Mute: no
	Properties:
		device.bus = "pci"
		device.form_factor = "sink"
		device.product.name = "HDMI"
Sink #1
	Name: alsa_output.usb-Generic_USB_Audio-00.analog-stereo
	Description: USB Soundbox
	Mute: no
	Properties:
		device.bus = "usb"
		device.form_factor = "speaker"
		device.serial = "ABC123"
		device.product.name = "USB Soundbox"
"""
        sinks = mic_defaults._parse_sinks(text)
        self.assertEqual(len(sinks), 2)
        self.assertTrue(sinks[0]["is_usb"])
        self.assertIn("usb-", sinks[0]["name"])
        self.assertGreater(sinks[0]["score"], sinks[1]["score"])
        chosen = mic_defaults.find_preferred_sink(sinks)
        self.assertEqual(chosen["name"], sinks[0]["name"])


class TestMicrophoneRecording(unittest.TestCase):
    def test_usb_status_distinguishes_connection_capture_and_sound_server(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(mic_defaults, "_run", return_value=(0, "")) as pulse:
            root = Path(tmp)
            self.assertIn("No USB audio device", mic_defaults.usb_input_status(root))
            interface = root / "bus/usb/devices/1-1:1.0"
            interface.mkdir(parents=True)
            (interface / "bInterfaceClass").write_text("01\n")
            self.assertIn("no USB recording input", mic_defaults.usb_input_status(root))
            card = root / "class/sound"
            card.mkdir(parents=True)
            (card / "idVendor").touch()
            (card / "pcmC2D0c").mkdir()
            self.assertIn("choose a USB profile", mic_defaults.usb_input_status(root))
            pulse.return_value = (0, "Source #2\n\tName: alsa_input.usb-Test_Mic-00.mono-fallback\n")
            self.assertIn("A USB input is ready", mic_defaults.usb_input_status(root))

    def test_reconnect_respects_selected_input_and_does_not_unmute(self):
        inputs = [{"name": "usb", "is_usb": True}, {"name": "internal", "is_usb": False}]
        with patch.object(mic_defaults, "list_input_sources", return_value=inputs), \
             patch.object(mic_defaults, "load_preferences", return_value={"preferred_source_name": "internal"}) as prefs, \
             patch.object(mic_defaults, "get_default_source", return_value="internal"), \
             patch.object(mic_defaults, "set_default_source") as select, \
             patch.object(mic_defaults, "ensure_source_ready") as unmute:
            mic_defaults.restore_input()
            select.assert_not_called()
            prefs.return_value = {}
            mic_defaults.restore_input()
            select.assert_called_once_with("usb")
            unmute.assert_not_called()

    def test_uses_usb_alsa_input_when_pipewire_has_no_real_source(self):
        cards = "card 0: PCH [HD Audio], device 0: Analog\ncard 2: USB [USB Audio], device 1: USB Audio\n"
        with patch.object(voice, "_preferred_capture_source", return_value=None):
            cmd = voice.record_command(lambda _: True, run=lambda _: cards)
        self.assertEqual(cmd[0], "arecord")
        self.assertEqual(cmd[-2:], ["-D", "plughw:2,1"])

    def test_keeps_pipewire_preference_and_does_not_use_an_output_monitor(self):
        with patch.object(voice, "_preferred_capture_source", return_value="alsa_input.usb-mic"):
            cmd = voice.record_command(lambda _: True, run=lambda _: self.fail("Unexpected ALSA probe"))
        self.assertEqual(cmd[:2], ["parecord", "--device=alsa_input.usb-mic"])
        with patch.object(voice, "_preferred_capture_source", return_value="alsa_output.speakers.monitor"):
            self.assertIsNone(voice.record_command(lambda _: True, run=lambda _: ""))


class TestCameraProbe(unittest.TestCase):
    def test_list_cameras_from_sysfs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            v0 = root / "video0"
            v0.mkdir()
            (v0 / "name").write_text("USB Camera", encoding="utf-8")
            (v0 / "device").mkdir()
            (v0 / "device" / "uevent").write_text(
                "DEVPATH=/devices/pci0000:00/usb1/1-3/video4linux/video0\n",
                encoding="utf-8",
            )
            v1 = root / "video1"
            v1.mkdir()
            (v1 / "name").write_text("USB Camera: Metadata", encoding="utf-8")
            cams = camera_defaults.list_cameras(sys_root=root)
            self.assertEqual(len(cams), 1)
            self.assertEqual(cams[0]["name"], "USB Camera")
            self.assertTrue(cams[0]["usb"])
            self.assertTrue(camera_defaults.has_camera(sys_root=root))


if __name__ == "__main__":
    unittest.main()
