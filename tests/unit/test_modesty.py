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
            self.assertEqual(first["version"], "1.1.0")
            parsed = crx3.parse_crx3((root / modesty.INSTALL_DIR / modesty.CRX_NAME).read_bytes())
            with zipfile.ZipFile(io.BytesIO(parsed["zip"])) as archive:
                names = archive.namelist()
                self.assertIn("models/body-pix/model.json", names)
                self.assertIn("models/body-pix/group1-shard1of1.bin", names)
                self.assertIn("vendor/body-pix/body-pix.js", names)
                self.assertEqual(json.loads(archive.read("manifest.json"))["version"], "1.1.0")
            modesty.disable(temp)
            self.assertTrue(key.exists())
            second = modesty.enable(temp, mode="women")
            self.assertEqual(first["extension_id"], second["extension_id"])


if __name__ == "__main__":
    unittest.main()
