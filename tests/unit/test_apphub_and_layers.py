"""
Unit tests for DevOS Universal App Hub, Type Router, Safety Scanner, and WinLayer Doctor.
Verifies magic-byte routing, malware detection (EICAR), APK permission flags, and PE analysis.
"""

import sys
import os
import zipfile
import unittest

SYS_PATH_APPHUB = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/apphub"))
SYS_PATH_WIN = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/winlayer"))
sys.path.insert(0, SYS_PATH_APPHUB)
sys.path.insert(0, SYS_PATH_WIN)

from type_router import AppTypeRouter
from safety_scanner import AppSafetyScanner
from doctor import WinLayerDoctor


class TestAppHubAndLayers(unittest.TestCase):

    def setUp(self):
        self.test_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "tmp_test_files"))
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        import shutil
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_01_magic_byte_pe_routing(self):
        # Create a mock Windows PE file with MZ header
        pe_path = os.path.join(self.test_dir, "mislabeled_app.png")  # Deliberately wrong extension!
        with open(pe_path, "wb") as f:
            f.write(b"MZ" + b"\x00" * 100)

        res = AppTypeRouter.identify_type(pe_path)
        self.assertEqual(res["detected_runtime"], AppTypeRouter.TARGET_WINDOWS)
        self.assertIn("WinLayer", res["runtime_badge"])

    def test_02_magic_byte_android_routing(self):
        # Create a mock APK (ZIP with AndroidManifest.xml)
        apk_path = os.path.join(self.test_dir, "sample.bin")  # Wrong extension!
        with zipfile.ZipFile(apk_path, "w") as zf:
            zf.writestr("AndroidManifest.xml", "<manifest></manifest>")

        res = AppTypeRouter.identify_type(apk_path)
        self.assertEqual(res["detected_runtime"], AppTypeRouter.TARGET_ANDROID)
        self.assertIn("Waydroid", res["runtime_badge"])

    def test_03_safety_scanner_eicar_detection(self):
        eicar_file = os.path.join(self.test_dir, "test_malware.exe")
        with open(eicar_file, "wb") as f:
            f.write(AppSafetyScanner.EICAR_SIGNATURE)

        scan = AppSafetyScanner.scan_file(eicar_file)
        self.assertEqual(scan["status"], "MALWARE_DETECTED")
        self.assertFalse(scan["safe_to_run"])
        self.assertIn("EICAR", scan["threat_name"])

    def test_04_safety_scanner_apk_high_risk_permissions(self):
        risky_apk = os.path.join(self.test_dir, "risky.apk")
        with zipfile.ZipFile(risky_apk, "w") as zf:
            manifest_content = """
            <manifest>
                <uses-permission android:name="android.permission.SEND_SMS" />
                <uses-permission android:name="android.permission.BIND_ACCESSIBILITY_SERVICE" />
            </manifest>
            """
            zf.writestr("AndroidManifest.xml", manifest_content)

        scan = AppSafetyScanner.scan_file(risky_apk)
        self.assertEqual(scan["status"], "FLAGGED_HIGH_RISK")
        self.assertFalse(scan["safe_to_run"])
        self.assertEqual(len(scan["flagged_permissions"]), 2)

    def test_05_winlayer_doctor_non_pe(self):
        text_file = os.path.join(self.test_dir, "notes.txt")
        with open(text_file, "w") as f:
            f.write("Just text")
        doc = WinLayerDoctor.analyze_pe(text_file)
        self.assertFalse(doc["is_pe"])


if __name__ == "__main__":
    unittest.main()
