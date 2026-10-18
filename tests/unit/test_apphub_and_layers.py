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

    def test_06_package_link_parsing(self):
        import app_resolver
        deb = app_resolver.parse_link("https://example.com/downloads/cool-tool_amd64.deb")
        self.assertIsNotNone(deb)
        self.assertEqual(deb["store"], "deb")
        self.assertEqual(deb["id"], "cool-tool_amd64.deb")

        appimage = app_resolver.parse_link("https://example.com/apps/SuperApp-1.0.0.AppImage")
        self.assertIsNotNone(appimage)
        self.assertEqual(appimage["store"], "appimage")

        gh = app_resolver.parse_link("https://github.com/my-org/my-project/releases")
        self.assertIsNotNone(gh)
        self.assertEqual(gh["store"], "github")
        self.assertEqual(gh["repo"], "my-project")

    def test_07_clean_app_name(self):
        import app_resolver
        self.assertEqual(app_resolver.clean_app_name_from_filename("google-chrome-stable_current_amd64.deb"), "Google Chrome")
        self.assertEqual(app_resolver.clean_app_name_from_filename("Obsidian-1.5.8.AppImage"), "Obsidian")
        self.assertEqual(app_resolver.clean_app_name_from_filename("fastfetch-linux-amd64.deb"), "Fastfetch")
        self.assertEqual(app_resolver.clean_app_name_from_filename("ZoomInstaller.exe"), "Zoom")

    def test_08_referral_page_inspection(self):
        import app_resolver
        html = """
        <html><body>
          <a href="/release/v1/app_arm64.deb">arm64 deb</a>
          <a href="/release/v1/app_amd64.deb">amd64 deb</a>
          <a href="/release/v1/app.AppImage">appimage</a>
        </body></html>
        """
        ref = app_resolver.inspect_referral_page("https://example.com/downloads", html)
        self.assertEqual(ref.get("kind"), "deb")
        self.assertEqual(ref.get("url"), "https://example.com/release/v1/app_amd64.deb")

    def test_09_direct_package_resolution(self):
        import app_resolver
        res = app_resolver.resolve(link="https://example.com/packages/my-editor_1.0_amd64.deb")
        self.assertTrue(res["known"])
        self.assertEqual(res["option"]["kind"], "deb")
        reply = app_resolver.reply_text(res)
        self.assertIn("My Editor", reply)
        self.assertIn("Debian package (.deb)", reply)
        self.assertIn("Install My Editor", reply)

    def test_10_ai_server_thread_plan(self):
        SYS_PATH_AI = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/ai-core"))
        sys.path.insert(0, SYS_PATH_AI)
        import server
        gen, batch = server.thread_plan(20, 14, 4)
        self.assertGreaterEqual(gen, 6)
        self.assertGreaterEqual(batch, 16)


if __name__ == "__main__":
    unittest.main()
