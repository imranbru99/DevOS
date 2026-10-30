import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys_path = os.path.join(ROOT, "components", "browser")
if sys_path not in os.sys.path:
    os.sys.path.insert(0, sys_path)

import chrome_profiles


class TestChromeProfiles(unittest.TestCase):
    def test_get_chrome_profiles_default_fallback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles = chrome_profiles.get_chrome_profiles(tmpdir)
            self.assertIn("Default", profiles)
            self.assertEqual(profiles["Default"], "Work")

    def test_get_chrome_profiles_from_local_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            local_state = os.path.join(tmpdir, "Local State")
            with open(local_state, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {"name": "Work"},
                                "Profile 1": {"name": "Mirza"},
                                "Profile 2": {"name": "Tony"},
                            }
                        }
                    },
                    f,
                )
            profiles = chrome_profiles.get_chrome_profiles(tmpdir)
            self.assertEqual(len(profiles), 3)
            self.assertEqual(profiles["Default"], "Work")
            self.assertEqual(profiles["Profile 1"], "Mirza")
            self.assertEqual(profiles["Profile 2"], "Tony")

    def test_slugify(self):
        self.assertEqual(chrome_profiles.slugify("Work"), "work")
        self.assertEqual(chrome_profiles.slugify("Profile 1"), "profile-1")
        self.assertEqual(chrome_profiles.slugify("Mirza"), "mirza")

    def test_generate_badged_icon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            icon_48 = os.path.join(tmpdir, "icon48.png")
            icon_128 = os.path.join(tmpdir, "icon128.png")
            chrome_profiles.generate_badged_icon("Mirza", icon_48, icon_128)
            self.assertTrue(os.path.isfile(icon_48))
            self.assertTrue(os.path.isfile(icon_128))
            self.assertGreater(os.path.getsize(icon_48), 500)
            self.assertGreater(os.path.getsize(icon_128), 1000)

    def test_sync_all_profiles(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            # Create simulated ~/.config/google-chrome/Local State
            conf_dir = os.path.join(tmp_home, ".config", "google-chrome")
            os.makedirs(conf_dir, exist_ok=True)
            with open(os.path.join(conf_dir, "Local State"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {"name": "Work"},
                                "Profile 1": {"name": "Mirza"},
                            }
                        }
                    },
                    f,
                )

            desktops = chrome_profiles.sync_all_profiles(tmp_home)
            self.assertGreaterEqual(len(desktops), 3)  # Default, Profile 1, Guest
            self.assertTrue(any("chrome-work.desktop" in d for d in desktops))
            self.assertTrue(any("chrome-mirza.desktop" in d for d in desktops))
            self.assertTrue(any("chrome-guest.desktop" in d for d in desktops))

            # Verify policy file was created
            pol_file = os.path.join(tmp_home, ".config", "devos", "chrome-policies", "devos-familysafe.json")
            self.assertTrue(os.path.isfile(pol_file))
            with open(pol_file, "r", encoding="utf-8") as f:
                pol = json.load(f)
            self.assertTrue(pol.get("BrowserGuestModeEnabled"))
            self.assertTrue(pol.get("BrowserAddPersonEnabled"))


if __name__ == "__main__":
    unittest.main()
