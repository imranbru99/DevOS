"""
Unit tests for DevOS Hardware, Network, Audio & Driver Controller
Verifies Wi-Fi & Ethernet scanning, PipeWire audio settings, and GPU driver detection.
"""

import sys
import os
import unittest

SYS_PATH_SETTINGS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/settings"))
sys.path.insert(0, SYS_PATH_SETTINGS)

from hardware_manager import HardwareManager


class TestHardwareManager(unittest.TestCase):

    def test_01_network_status(self):
        net = HardwareManager.get_network_status()
        self.assertIn("connected", net)
        self.assertIn("interfaces", net)
        self.assertIsInstance(net["interfaces"], list)
        self.assertIn("dns_servers", net)
        self.assertIn("1.1.1.1", net["dns_servers"])

    def test_02_wifi_scan(self):
        wifis = HardwareManager.scan_wifi()
        self.assertIsInstance(wifis, list)
        self.assertGreater(len(wifis), 0)
        self.assertIn("ssid", wifis[0])
        self.assertIn("signal", wifis[0])

    def test_03_wifi_connect(self):
        res = HardwareManager.connect_wifi("DevOS-HighSpeed-5G", "securepassword")
        self.assertIn("status", res)
        self.assertIn(res["status"], ["SUCCESS", "SIMULATED_SUCCESS"])

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

        # Test clamp limits
        vol_clamped = HardwareManager.set_volume(150)
        self.assertEqual(vol_clamped["volume_level"], 100)

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
        self.assertIn(res["status"], ["SUCCESS", "SIMULATED_SUCCESS"])


if __name__ == "__main__":
    unittest.main()
