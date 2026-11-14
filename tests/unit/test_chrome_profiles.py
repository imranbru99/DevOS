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
    def test_get_chrome_profiles_empty_when_no_chrome_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            profiles = chrome_profiles.get_chrome_profiles(tmpdir)
            # Do not invent Work/Guest menu apps before the user opens Chrome.
            self.assertEqual(profiles, {})

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

            main = os.path.join(tmp_home, ".local/share/applications/google-chrome.desktop")
            self.assertTrue(os.path.isfile(main))
            text = open(main, encoding="utf-8").read()
            self.assertIn("StartupWMClass=google-chrome", text)
            work = open(os.path.join(tmp_home, ".local/share/applications/chrome-work.desktop"), encoding="utf-8").read()
            self.assertIn("StartupWMClass=chrome-work", work)
            self.assertIn("--class=chrome-work", work)
            self.assertIn("Icon=chrome-work", work)
            # Profile launchers are for the taskbar only — never Start menu.
            self.assertIn("NoDisplay=true", work)
            guest = open(os.path.join(tmp_home, ".local/share/applications/chrome-guest.desktop"), encoding="utf-8").read()
            self.assertIn("NoDisplay=true", guest)
            self.assertNotIn("NoDisplay=true", text)

            # Verify policy file was created
            pol_file = os.path.join(tmp_home, ".config", "devos", "chrome-policies", "devos-familysafe.json")
            self.assertTrue(os.path.isfile(pol_file))
            with open(pol_file, "r", encoding="utf-8") as f:
                pol = json.load(f)
            self.assertTrue(pol.get("BrowserGuestModeEnabled"))
            self.assertTrue(pol.get("BrowserAddPersonEnabled"))

    def test_plasma_launchers_windows_style_profile_pins(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            cfg_dir = os.path.join(tmp_home, ".config")
            apps = os.path.join(tmp_home, ".local/share/applications")
            os.makedirs(cfg_dir, exist_ok=True)
            os.makedirs(apps, exist_ok=True)
            for slug in ("work", "mirza"):
                open(os.path.join(apps, f"chrome-{slug}.desktop"), "w", encoding="utf-8").write("[Desktop Entry]\n")
            appletsrc = os.path.join(cfg_dir, "plasma-org.kde.plasma.desktop-appletsrc")
            with open(appletsrc, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Containments][3][Applets][6]\n"
                    "plugin=org.kde.plasma.icontasks\n"
                    "\n"
                    "[Containments][3][Applets][6][Configuration][General]\n"
                    "launchers=applications:devos-search.desktop,applications:google-chrome.desktop\n"
                    "groupingStrategy=1\n"
                    "separateLaunchers=false\n"
                )
            # Open profiles → hide Chrome pin, show avatar pins (Guest included).
            open(os.path.join(apps, "chrome-guest.desktop"), "w", encoding="utf-8").write(
                "[Desktop Entry]\n"
            )
            ok = chrome_profiles.sync_plasma_profile_launchers(tmp_home, ["work", "mirza", "guest"])
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:chrome-work.desktop", text)
            self.assertIn("applications:chrome-mirza.desktop", text)
            self.assertIn("applications:chrome-guest.desktop", text)
            self.assertNotIn("applications:google-chrome.desktop", text)
            self.assertIn("separateLaunchers=true", text)
            self.assertIn("applications:devos-search.desktop", text)
            # Profile literally named "Default" must still get its own pin.
            open(os.path.join(apps, "chrome-default.desktop"), "w", encoding="utf-8").write(
                "[Desktop Entry]\n"
            )
            ok = chrome_profiles.sync_plasma_profile_launchers(tmp_home, ["default", "work"])
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:chrome-default.desktop", text)
            self.assertIn("applications:chrome-work.desktop", text)
            # All closed → restore Chrome pin.
            ok = chrome_profiles.sync_plasma_profile_launchers(tmp_home, [])
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:google-chrome.desktop", text)
            self.assertNotIn("chrome-work.desktop", text)

    def test_class_for_profile_uses_display_name(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            chrome = os.path.join(tmp_home, ".config/google-chrome")
            os.makedirs(chrome, exist_ok=True)
            with open(os.path.join(chrome, "Local State"), "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {"name": "Work"},
                                "Profile 1": {"name": "Mirza"},
                            }
                        }
                    },
                    fh,
                )
            old_home = os.environ.get("HOME")
            os.environ["HOME"] = tmp_home
            try:
                self.assertEqual(
                    chrome_profiles.class_for_profile_key("Default", tmp_home),
                    "chrome-work",
                )
                self.assertEqual(
                    chrome_profiles.class_for_profile_key("Profile 1", tmp_home),
                    "chrome-mirza",
                )
            finally:
                if old_home is None:
                    os.environ.pop("HOME", None)
                else:
                    os.environ["HOME"] = old_home

    def test_detect_window_profile_markers(self):
        profiles = {"Default": "Work", "Profile 1": "Mirza", "Profile 4": "Blog"}
        w_guest = {"id": 1, "title": "Welcome - Google Chrome (Guest)", "wm_class": "Google-chrome"}
        self.assertEqual(chrome_profiles.detect_window_profile(w_guest, profiles), "Guest")

        w_new_guest = {
            "id": 55,
            "title": "You're browsing as a Guest",
            "wm_class": "google-chrome.Google-chrome",
        }
        self.assertEqual(chrome_profiles.detect_window_profile(w_new_guest, profiles), "Guest")

        w_tag = {"id": 2, "title": "[Mirza] Project Dashboard - Google Chrome", "wm_class": "Google-chrome"}
        self.assertEqual(chrome_profiles.detect_window_profile(w_tag, profiles), "Mirza")

        w_title_paren = {"id": 3, "title": "Settings (Blog) - Google Chrome", "wm_class": "Google-chrome"}
        self.assertEqual(chrome_profiles.detect_window_profile(w_title_paren, profiles), "Blog")

    def test_detect_window_profile_session_match(self):
        profiles = {"Default": "Work", "Profile 1": "Mirza", "Profile 4": "Blog"}
        prof_session_data = {
            "Default": {"titles": {"google search", "gmail"}, "domains": {"google"}, "mtime": 100},
            "Profile 1": {"titles": {"whatsapp business", "youtube studio"}, "domains": {"whatsapp", "youtube"}, "mtime": 200},
            "Profile 4": {"titles": {"cloudflare dashboard", "domain overview"}, "domains": {"cloudflare"}, "mtime": 300},
        }

        w_wa = {"id": 101, "title": "WhatsApp Business - Google Chrome", "wm_class": "Google-chrome"}
        self.assertEqual(chrome_profiles.detect_window_profile(w_wa, profiles, prof_session_data=prof_session_data), "Mirza")

        w_cf = {"id": 102, "title": "Cloudflare Dashboard - Google Chrome", "wm_class": "Google-chrome"}
        self.assertEqual(chrome_profiles.detect_window_profile(w_cf, profiles, prof_session_data=prof_session_data), "Blog")

    def test_get_ranked_active_profiles(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            conf_dir = os.path.join(tmp_home, ".config", "google-chrome")
            os.makedirs(conf_dir, exist_ok=True)
            with open(os.path.join(conf_dir, "Local State"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "profile": {
                            "last_active_profiles": ["Profile 4", "Profile 1"],
                            "info_cache": {
                                "Default": {"name": "Work"},
                                "Profile 1": {"name": "Mirza"},
                                "Profile 4": {"name": "Blog"},
                            },
                        }
                    },
                    f,
                )
            profiles = {"Default": "Work", "Profile 1": "Mirza", "Profile 4": "Blog"}
            ranked = chrome_profiles.get_ranked_active_profiles(conf_dir, profiles)
            self.assertEqual(ranked[0], "Profile 4")
            self.assertEqual(ranked[1], "Profile 1")
            self.assertIn("Default", ranked)


if __name__ == "__main__":
    unittest.main()
