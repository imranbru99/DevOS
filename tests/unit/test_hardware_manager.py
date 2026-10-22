"""
Unit tests for DevOS Hardware, Network, Audio & Driver Controller
Verifies Wi-Fi & Ethernet scanning, PipeWire audio settings, and GPU driver detection.
"""

import sys
import os
import unittest
import subprocess
from unittest.mock import patch

SYS_PATH_SETTINGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/settings"))
sys.path.insert(0, SYS_PATH_SETTINGS)

from hardware_manager import HardwareManager


class TestHardwareManager(unittest.TestCase):

    def setUp(self):
        # Unit checks must never join networks, alter volume, or install drivers.
        self.which = self.enterContext(patch("hardware_manager.shutil.which", side_effect=lambda name: "/usr/bin/" + name if name != "nvidia-smi" else None))
        self.output = self.enterContext(patch("hardware_manager.subprocess.check_output", return_value=""))
        self.run = self.enterContext(patch("hardware_manager.subprocess.run"))

    def test_01_network_status(self):
        net = HardwareManager.get_network_status()
        self.assertIn("connected", net)
        self.assertIn("interfaces", net)
        self.assertIsInstance(net["interfaces"], list)
        self.assertIn("dns_servers", net)
        self.assertIn("1.1.1.1", net["dns_servers"])

    def test_02_wifi_scan(self):
        self.output.return_value = "Office\\:Guest:85:WPA2\nOpen network:41:\n"
        wifis = HardwareManager.scan_wifi()
        self.assertEqual(wifis, [
            {"ssid": "Office:Guest", "signal": "85%", "security": "WPA2"},
            {"ssid": "Open network", "signal": "41%", "security": "Open"},
        ])
        self.assertEqual(self.output.call_args.args[0], [
            "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"])

    def test_03_wifi_connect(self):
        res = HardwareManager.connect_wifi("DevOS-HighSpeed-5G", "securepassword")
        self.assertIn("status", res)
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(self.output.call_args.args[0], [
            "nmcli", "device", "wifi", "connect", "DevOS-HighSpeed-5G", "password", "securepassword"])

    def test_04_audio_status(self):
        audio = HardwareManager.get_audio_status()
        self.assertIn("PipeWire", audio["audio_server"])
        self.assertIn("WirePlumber", audio["session_manager"])
        self.assertIn("output_device", audio)
        self.assertIn("LDAC", audio["codecs_supported"])

    def test_05_volume_control(self):
        vol = HardwareManager.set_volume(85)
        self.assertEqual(vol["status"], "SUCCESS")
        self.assertEqual(vol["volume_level"], 85)
        self.run.assert_called_with(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.85"], check=True)

        # Test clamp limits
        vol_clamped = HardwareManager.set_volume(150)
        self.assertEqual(vol_clamped["volume_level"], 100)
        self.run.assert_called_with(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "1.0"], check=True)

    def test_06_driver_status(self):
        drv = HardwareManager.get_driver_status()
        self.assertIn("gpu_hardware", drv)
        self.assertIn("active_gpu_driver", drv)
        self.assertIn("Vulkan", drv["vulkan_acceleration"])
        self.assertIn("SOF", drv["sound_open_firmware"])
        self.assertIn("BlueZ", drv["bluetooth_subsystem"])
        self.assertIn("driverless_printing", drv)

    def test_07_proprietary_driver_installer(self):
        res = HardwareManager.install_proprietary_drivers()
        self.assertIn("status", res)
        self.assertEqual(res["status"], "SUCCESS")
        self.run.assert_called_once_with(["ubuntu-drivers", "install"], check=True)

    def test_missing_tools_do_not_report_success(self):
        self.which.side_effect = None
        self.which.return_value = None
        self.assertEqual(HardwareManager.scan_wifi(), [])
        self.assertEqual(HardwareManager.connect_wifi("Office")["status"], "UNAVAILABLE")
        self.assertEqual(HardwareManager.set_volume(50)["status"], "UNAVAILABLE")
        self.assertEqual(HardwareManager.install_proprietary_drivers()["status"], "UNAVAILABLE")
        self.output.assert_not_called()
        self.run.assert_not_called()

    def test_command_failures_do_not_report_success(self):
        self.output.side_effect = subprocess.CalledProcessError(1, "nmcli")
        self.run.side_effect = subprocess.CalledProcessError(1, "command")
        self.assertEqual(HardwareManager.scan_wifi(), [])
        self.assertEqual(HardwareManager.connect_wifi("Office")["status"], "ERROR")
        self.assertEqual(HardwareManager.set_volume(50)["status"], "ERROR")
        self.assertEqual(HardwareManager.install_proprietary_drivers()["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()
