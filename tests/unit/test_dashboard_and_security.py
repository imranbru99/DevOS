"""
Unit tests for DevOS Luxury Dashboard, Security & PIN Setup
Verifies PIN hashing, verification, password setting, hardware telemetry, and HTTP API endpoints.
"""

import sys
import os
import json
import time
import unittest
import threading
import urllib.request
from http.server import HTTPServer

# Add dashboard directory to sys.path
SYS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/dashboard"))
sys.path.insert(0, SYS_PATH)

from dashboard_server import DevOSSecurityManager, DevOSSystemMetrics, DevOSDashboardHandler


class TestDashboardAndSecurity(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.port = 7088
        cls.server = HTTPServer(("127.0.0.1", cls.port), DevOSDashboardHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.4)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.security = DevOSSecurityManager()
        # Clean test pin file if exists
        if os.path.exists(self.security.PIN_FILE):
            try:
                os.remove(self.security.PIN_FILE)
            except Exception:
                pass

    def test_01_pin_management(self):
        # Invalid length
        res_short = self.security.set_pin("12")
        self.assertFalse(res_short["success"])

        # Invalid characters
        res_alpha = self.security.set_pin("abcd")
        self.assertFalse(res_alpha["success"])

        # Valid PIN
        res_valid = self.security.set_pin("849201")
        self.assertTrue(res_valid["success"])
        self.assertTrue(self.security.is_pin_configured())

        # Verify correct PIN
        self.assertTrue(self.security.verify_pin("849201"))
        # Verify incorrect PIN
        self.assertFalse(self.security.verify_pin("111111"))

    def test_02_password_management(self):
        # Short password
        res_short = self.security.set_system_password("ab")
        self.assertFalse(res_short["success"])

        # Valid password
        res_valid = self.security.set_system_password("SuperSecret2027!", username="devos")
        self.assertTrue(res_valid["success"])

    def test_03_telemetry_metrics(self):
        metrics = DevOSSystemMetrics.get_metrics()
        self.assertIn("os_name", metrics)
        self.assertIn("version", metrics)
        self.assertIn("cpu_cores", metrics)
        self.assertIn("memory", metrics)
        self.assertIn("disk", metrics)

    def test_04_api_system_status(self):
        url = f"http://127.0.0.1:{self.port}/api/system/status"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data["os_name"], "DevOS 2027")

    def test_05_api_pin_and_password(self):
        pin_url = f"http://127.0.0.1:{self.port}/api/setup/pin"
        pin_payload = json.dumps({"pin": "654321"}).encode("utf-8")
        req = urllib.request.Request(pin_url, data=pin_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res["success"])

        # Verify through API
        verify_url = f"http://127.0.0.1:{self.port}/api/verify/pin"
        verify_payload = json.dumps({"pin": "654321"}).encode("utf-8")
        req = urllib.request.Request(verify_url, data=verify_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res["valid"])

    def test_06_storage_devices_api(self):
        url = f"http://127.0.0.1:{self.port}/api/storage/devices"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("devices", data)
            self.assertIn("is_uefi", data)
            self.assertGreater(len(data["devices"]), 0)
            first_dev = data["devices"][0]
            self.assertIn("device", first_dev)
            self.assertIn("partition_table", first_dev)
            self.assertIn("issues", first_dev)

    def test_07_storage_action_api(self):
        url = f"http://127.0.0.1:{self.port}/api/storage/action"
        payload = json.dumps({"device": "/dev/sda", "action": "format_devos"}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res["success"])


if __name__ == "__main__":
    unittest.main()
