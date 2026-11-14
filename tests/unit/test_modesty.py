import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "components/modesty"))
import modesty
import crx3


class ModestyPackageTests(unittest.TestCase):
    def test_disabled_status_does_not_need_a_signing_key(self):
        with tempfile.TemporaryDirectory() as root:
            state = modesty.status(root)
            self.assertFalse(state["enabled"])
            self.assertIsNone(state["extension_id"])

    def test_device_key_survives_disable_and_new_bundle_contains_local_models(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = modesty.enable(temp, mode="women")
            key = root / modesty.DEVICE_KEY
            self.assertEqual(key.stat().st_mode & 0o777, 0o600)
            self.assertEqual(first["version"], "1.2.2")
            parsed = crx3.parse_crx3((root / modesty.INSTALL_DIR / modesty.CRX_NAME).read_bytes())
            with zipfile.ZipFile(io.BytesIO(parsed["zip"])) as archive:
                names = archive.namelist()
                self.assertIn("models/body-pix/model.json", names)
                self.assertIn("models/body-pix/group1-shard1of1.bin", names)
                self.assertIn("vendor/body-pix/body-pix.js", names)
                self.assertEqual(json.loads(archive.read("manifest.json"))["version"], "1.2.2")
                rules = archive.read("rules.js").decode("utf-8")
                self.assertIn("bodySkinOnlyRatio", rules)
                popup = archive.read("popup.html").decode("utf-8")
                self.assertIn("openSettings", popup)
                self.assertNotIn("blurred on this page", popup)
            modesty.disable(temp)
            self.assertTrue(key.exists())
            second = modesty.enable(temp, mode="women")
            self.assertEqual(first["extension_id"], second["extension_id"])

    def test_rules_face_score_threshold_rejects_inanimate_objects(self):
        rules_js = (ROOT / "components/modesty/extension/rules.js").read_text(encoding="utf-8")
        self.assertIn("faceScore: 0.50", rules_js)
        self.assertIn("bodySkinOnlyRatio: 0.15", rules_js)

    def test_overlay_blur_and_tech_context_guards(self):
        content_js = (ROOT / "components/modesty/extension/content.js").read_text(encoding="utf-8")
        self.assertIn("st.overlay = overlay", content_js)
        self.assertIn("blurLayer", content_js)
        self.assertIn("TECH_DEVICE_REGEX", content_js)
        self.assertIn("isHardwareOrTechContext", content_js)


if __name__ == "__main__":
    unittest.main()
