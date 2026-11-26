import inspect
import json
import os
import tempfile
import unittest
from unittest.mock import patch

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

    def test_window_task_class_unique_per_window(self):
        a = chrome_profiles.window_task_class("work", 0x1A2B)
        b = chrome_profiles.window_task_class("work", 0x3C4D)
        self.assertTrue(a.startswith("chrome-work-w"))
        self.assertTrue(b.startswith("chrome-work-w"))
        self.assertNotEqual(a, b)

    def test_generate_badged_icon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            icon_48 = os.path.join(tmpdir, "icon48.png")
            icon_128 = os.path.join(tmpdir, "icon128.png")
            chrome_profiles.generate_badged_icon("Mirza", icon_48, icon_128)
            self.assertTrue(os.path.isfile(icon_48))
            self.assertTrue(os.path.isfile(icon_128))
            self.assertGreater(os.path.getsize(icon_48), 500)
            self.assertGreater(os.path.getsize(icon_128), 1000)

    def test_account_photo_is_found_without_the_gaia_flag(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "Profile 1")
            os.makedirs(folder, exist_ok=True)
            photo = os.path.join(folder, "Google Profile Picture.png")
            img = PILImage.new("RGB", (96, 96))
            pixels = img.load()
            for y in range(96):
                for x in range(96):
                    pixels[x, y] = ((x * 13) % 256, (y * 17) % 256, ((x * y) + 40) % 256)
            img.save(photo)
            found = chrome_profiles.get_profile_avatar_path(
                tmp, "Profile 1", {"name": "Mirza", "avatar_icon": "chrome://theme/IDR_PROFILE_AVATAR_26"}
            )
            self.assertEqual(found, photo)
            plain = os.path.join(folder, "Google Profile Picture.jpg")
            PILImage.new("RGB", (64, 64), (200, 120, 80)).save(plain, format="JPEG")
            # A flat account picture must still be used. The strict color check
            # is for unnamed default avatars, not this file.
            self.assertFalse(chrome_profiles._is_usable_profile_photo(plain))
            named = chrome_profiles.get_profile_avatar_path(tmp, "Profile 1", {})
            self.assertEqual(named, photo)
            self.assertIn("XChangeProperty.argtypes", inspect.getsource(chrome_profiles.set_window_icon))
            images = os.path.join(folder, "Accounts", "Avatar Images", "0")
            os.makedirs(images, exist_ok=True)
            cached = os.path.join(images, "128")
            PILImage.new("RGB", (128, 128), (20, 80, 200)).save(cached, format="PNG")
            os.remove(photo)
            if os.path.isfile(plain):
                os.remove(plain)
            found_cached = chrome_profiles.get_profile_avatar_path(tmp, "Profile 1", {})
            self.assertEqual(found_cached, cached)

    def test_one_open_account_uses_its_own_photo(self):
        badge = "/tmp/chrome-imran-w1.png"
        self.assertEqual(
            chrome_profiles._shared_launcher_icon([
                {"key": "Default", "icon": badge, "avatar": "/tmp/face.png"},
            ]),
            badge,
        )
        # A second account must not strip the photo off the default Chrome icon.
        self.assertEqual(
            chrome_profiles._shared_launcher_icon([
                {"key": "Profile 1", "icon": "/tmp/other.png", "avatar": "/tmp/other-face.png"},
                {"key": "Default", "icon": badge, "avatar": "/tmp/face.png"},
            ]),
            badge,
        )
        self.assertEqual(chrome_profiles._kde_desktop_file_name("chrome-imran-w1.desktop"), "chrome-imran-w1")
        win_app = {
            "wm_class": "chrome-windows.cloud.microsoft__-Default.chrome-windows.cloud.microsoft__-Default",
            "title": "Home",
        }
        self.assertTrue(chrome_profiles._is_windows_app_window(win_app))
        self.assertFalse(chrome_profiles._is_profile_browser_window(win_app))
        self.assertTrue(chrome_profiles._is_profile_browser_window({
            "wm_class": "google-chrome.Google-chrome",
            "title": "Inbox - Google Chrome",
        }))
        self.assertFalse(chrome_profiles._is_chrome_launcher(
            "applications:chrome-windows.cloud.microsoft__-Default.desktop"
        ))
        self.assertTrue(chrome_profiles._cmdline_is_app_window(
            "/opt/google/chrome/chrome --app-id=abc --class=chrome-windows.cloud.microsoft__-Default"
        ))
        self.assertFalse(chrome_profiles._cmdline_is_app_window(
            "/opt/google/chrome/chrome --profile-directory=Default"
        ))
        self.assertEqual(
            chrome_profiles._shared_launcher_icon([
                {"key": "Default", "icon": badge, "avatar": ""},
            ]),
            badge,
        )
        with tempfile.TemporaryDirectory() as tmp_home:
            from PIL import Image as PILImage

            badge_file = os.path.join(tmp_home, "badge.png")
            PILImage.new("RGB", (8, 8), (1, 2, 3)).save(badge_file)
            marker_dir = os.path.join(tmp_home, ".local/share/icons/hicolor")
            os.makedirs(marker_dir, exist_ok=True)
            with open(os.path.join(marker_dir, ".devos-chrome-badge"), "w", encoding="utf-8") as handle:
                handle.write(badge_file)
            self.assertEqual(chrome_profiles._launcher_icon_line(tmp_home), badge_file)
            menu = chrome_profiles.repair_windows_app_launcher(tmp_home)
            body = open(menu, encoding="utf-8").read()
            self.assertIn("Exec=/usr/local/bin/devos-windows-app", body)
            self.assertNotIn("NoDisplay=true", body)
            self.assertNotIn("Hidden=true", body)
        self.assertNotIn("bind_each_chrome_window_once", inspect.getsource(chrome_profiles.watch_chrome_windows))
        self.assertTrue(chrome_profiles._is_chrome_launcher("applications:google-chrome.desktop"))
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, "Default")
            os.makedirs(folder)
            url = "https://lh3.googleusercontent.com/a/example"
            with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as handle:
                json.dump({"account_info": [{"picture_url": url, "email": "a@b.c"}]}, handle)
            self.assertEqual(chrome_profiles._account_picture_url(folder), url)
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image as PILImage

            photo = os.path.join(tmp, "Google Profile Picture.png")
            PILImage.new("RGB", (96, 96), (10, 180, 40)).save(photo)
            png = os.path.join(tmp, "old.png")
            PILImage.new("RGB", (48, 48), (0, 0, 0)).save(png)
            self.assertFalse(chrome_profiles._badge_is_current(png, photo))
            chrome_profiles.generate_badged_icon("Imran", png, avatar_path=photo)
            self.assertTrue(chrome_profiles._badge_is_current(png, photo))

    def test_account_photo_is_a_badge_on_the_chrome_logo(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp:
            photo = os.path.join(tmp, "Google Profile Picture.png")
            PILImage.new("RGB", (96, 96), (220, 30, 30)).save(photo)
            out = os.path.join(tmp, "badge48.png")
            chrome_profiles.generate_badged_icon("Mirza", out, avatar_path=photo)
            img = PILImage.open(out).convert("RGB")
            # The Chrome logo stays in the top of the button. The photo is the
            # corner, so the top-left pixel is not the account photo's red.
            top = img.getpixel((4, 4))
            self.assertLess(top[0] - max(top[1], top[2]), 80)
            out = os.path.join(tmp, "face48.png")
            chrome_profiles.generate_badged_icon("Mirza", out, avatar_path=photo)
            self.assertGreater(os.path.getsize(out), 400)

    def test_letter_badge_when_no_photo(self):
        self.assertEqual(chrome_profiles._profile_initial("Work"), "W")
        self.assertEqual(chrome_profiles._profile_initial("guest"), "G")
        self.assertEqual(chrome_profiles._profile_initial(""), "C")
        with tempfile.TemporaryDirectory() as tmpdir:
            # No avatar_path → must still write a real PNG (letter badge, not blank).
            out = os.path.join(tmpdir, "work48.png")
            chrome_profiles.generate_badged_icon("Work", out, avatar_path=None)
            self.assertTrue(os.path.isfile(out))
            self.assertGreater(os.path.getsize(out), 400)
            # Fake gray silhouette must be rejected → letter badge instead.
            from PIL import Image as PILImage

            fake = os.path.join(tmpdir, "avatar_default.png")
            PILImage.new("RGB", (64, 64), (120, 120, 120)).save(fake)
            out2 = os.path.join(tmpdir, "guest48.png")
            chrome_profiles.generate_badged_icon("Guest", out2, avatar_path=fake)
            self.assertTrue(os.path.isfile(out2))
            self.assertGreater(os.path.getsize(out2), 400)

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
                    "launchers=applications:devos-search.desktop,applications:devos-browser.desktop\n"
                    "groupingStrategy=1\n"
                    "separateLaunchers=false\n"
                )
            # Open profiles → hide DevOS Browser pin, show avatar pins (Guest included).
            open(os.path.join(apps, "chrome-guest.desktop"), "w", encoding="utf-8").write(
                "[Desktop Entry]\n"
            )
            ok = chrome_profiles.sync_plasma_profile_launchers(tmp_home, ["work", "mirza", "guest"])
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:chrome-work.desktop", text)
            self.assertIn("applications:chrome-mirza.desktop", text)
            self.assertIn("applications:chrome-guest.desktop", text)
            self.assertNotIn("applications:devos-browser.desktop", text)
            self.assertIn("separateLaunchers=true", text)
            self.assertIn("groupingStrategy=0", text)
            self.assertIn("groupPopups=false", text)
            self.assertIn("applications:devos-search.desktop", text)
            # Per-window desktops take priority (Plasma paints these icons, not gray person).
            open(os.path.join(apps, "chrome-work-w1a2.desktop"), "w", encoding="utf-8").write(
                "[Desktop Entry]\n"
            )
            open(os.path.join(apps, "chrome-work-w3b4.desktop"), "w", encoding="utf-8").write(
                "[Desktop Entry]\n"
            )
            ok = chrome_profiles.sync_plasma_profile_launchers(
                tmp_home,
                ["work"],
                window_desktops=["chrome-work-w1a2.desktop", "chrome-work-w3b4.desktop"],
            )
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:chrome-work-w1a2.desktop", text)
            self.assertIn("applications:chrome-work-w3b4.desktop", text)
            self.assertNotIn("applications:chrome-work.desktop,", text + ",")
            # All closed → the browser icon leaves. Other pins stay.
            ok = chrome_profiles.sync_plasma_profile_launchers(tmp_home, [])
            self.assertTrue(ok)
            text = open(appletsrc, encoding="utf-8").read()
            self.assertIn("applications:devos-search.desktop", text)
            self.assertNotIn("devos-browser.desktop", text)
            self.assertNotIn("chrome-work-w1a2.desktop", text)

    def test_closed_chrome_window_leaves_the_taskbar(self):
        existing = [
            "applications:devos-search.desktop",
            "applications:chrome-work-w11.desktop",
            "applications:chrome-mirza-w22.desktop",
            "applications:devos-browser.desktop",
        ]
        idle = "applications:devos-browser.desktop"
        still_open = chrome_profiles._reconcile_launcher_entries(
            existing, [{"id": 0x11, "wm_class": "chrome-work-w11"}], idle
        )
        self.assertIn("applications:chrome-work-w11.desktop", still_open)
        self.assertNotIn("applications:chrome-mirza-w22.desktop", still_open)
        self.assertIn("applications:devos-search.desktop", still_open)
        # The window is still the normal Chrome class. Keep that button and
        # put the photo on it. A second pin was the plain logo beside it.
        separate = chrome_profiles._reconcile_launcher_entries(
            existing,
            [
                {"id": 0x11, "wm_class": "google-chrome.Google-chrome", "task_desktop": "chrome-work-w11.desktop"},
                {"id": 0x22, "wm_class": "google-chrome.Google-chrome", "task_desktop": "chrome-mirza-w22.desktop"},
            ],
            idle,
        )
        self.assertIn("applications:devos-browser.desktop", separate)
        self.assertNotIn("applications:chrome-work-w11.desktop", separate)
        self.assertNotIn("applications:chrome-mirza-w22.desktop", separate)
        self.assertNotIn(
            "applications:devos-browser.desktop",
            chrome_profiles._reconcile_launcher_entries(
                existing, [{"id": 0x11, "wm_class": "chrome-work-w11"}], idle
            ),
        )
        closed = chrome_profiles._reconcile_launcher_entries(existing, [], idle)
        self.assertEqual(closed, ["applications:devos-search.desktop"])
        live = inspect.getsource(chrome_profiles.apply_plasma_launchers_live)
        self.assertNotIn("var panels = panels()", live)
        self.assertNotIn("reloadConfig", live)
        self.assertIn("devos-launchers-ok", live)
        self.assertIn('writeConfig("launchers", parts)', live)
        watch_src = inspect.getsource(chrome_profiles.watch_chrome_windows)
        self.assertIn("publish_chrome_task_launchers", watch_src)
        self.assertIn("if publish_chrome_task_launchers", watch_src)

    def test_desktop_shortcut_uses_the_profile_photo(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp_home:
            badge = os.path.join(tmp_home, "badge.png")
            PILImage.new("RGB", (8, 8), (9, 8, 7)).save(badge)
            desktop = os.path.join(tmp_home, "Desktop")
            os.makedirs(desktop)
            path = os.path.join(desktop, "browser.desktop")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Desktop Entry]\nName=DevOS Browser\nIcon=devos-browser\nType=Application\n"
                )
            self.assertTrue(chrome_profiles._point_shared_launchers(tmp_home, badge))
            text = open(path, encoding="utf-8").read()
            self.assertIn(f"Icon={os.path.abspath(badge)}", text)
            other = os.path.join(tmp_home, "other.png")
            self.assertEqual(
                chrome_profiles._shared_launcher_icon([
                    {"key": "Profile 1", "icon": other},
                    {"key": "Default", "icon": os.path.abspath(badge)},
                ]),
                os.path.abspath(badge),
            )

    def test_same_pins_do_not_rewrite_the_panel(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            cfg_dir = os.path.join(tmp_home, ".config")
            apps = os.path.join(tmp_home, ".local/share/applications")
            os.makedirs(cfg_dir, exist_ok=True)
            os.makedirs(apps, exist_ok=True)
            open(os.path.join(apps, "chrome-work.desktop"), "w", encoding="utf-8").write("[Desktop Entry]\n")
            appletsrc = os.path.join(cfg_dir, "plasma-org.kde.plasma.desktop-appletsrc")
            with open(appletsrc, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Containments][3][Applets][6]\n"
                    "plugin=org.kde.plasma.icontasks\n"
                    "\n"
                    "[Containments][3][Applets][6][Configuration][General]\n"
                    "launchers=applications:devos-browser.desktop\n"
                )
            with patch.object(chrome_profiles, "apply_plasma_launchers_live", return_value=True) as live:
                chrome_profiles.sync_plasma_profile_launchers(tmp_home, ["work"])
                live.assert_not_called()
                text = open(appletsrc, encoding="utf-8").read()
                self.assertIn("applications:chrome-work.desktop", text)
                chrome_profiles.sync_plasma_profile_launchers(tmp_home, ["work"])
                live.assert_not_called()

    def test_tray_watch_does_not_restart_the_footer(self):
        path = os.path.join(ROOT, "build/includes.chroot/usr/local/bin/devos-tray-overflow")
        text = open(path, encoding="utf-8").read()
        once = text.split("def once", 1)[1].split("def watch", 1)[0]
        self.assertNotIn("restart_plasmashell()", once)

    def test_window_switch_does_not_restart_the_footer(self):
        apply_src = inspect.getsource(chrome_profiles.apply_window_profiles)
        watch_src = inspect.getsource(chrome_profiles.watch_chrome_windows)
        kwin_src = inspect.getsource(chrome_profiles.apply_kwin_window_desktops)
        self.assertNotIn("reload_plasmashell", apply_src)
        self.assertNotIn("reload_plasmashell", watch_src)
        self.assertIn("paint_chrome_icons", watch_src)
        self.assertIn("refresh_open_profile_icons", watch_src)
        self.assertLess(
            watch_src.index("refresh_open_profile_icons"),
            watch_src.index("now - last_icon"),
        )
        self.assertNotIn("apply_window_profiles", watch_src)
        self.assertNotIn("set_window_wm_class", inspect.getsource(chrome_profiles.refresh_open_profile_icons))
        self.assertNotIn("set_window_wm_class", inspect.getsource(chrome_profiles.paint_chrome_icons))
        self.assertNotIn("reloadConfig", inspect.getsource(chrome_profiles.apply_plasma_launchers_live))
        self.assertNotIn('"org.kde.kwin.Scripting.start"', kwin_src)
        ident_src = inspect.getsource(chrome_profiles._chrome_switch_identity)
        self.assertNotIn('["title"]', ident_src)
        self.assertNotIn('.get("title")', ident_src)

    def test_unchanged_kwin_map_does_not_reload(self):
        rows = [{"id": 5, "pid": 1, "title": "Inbox - Google Chrome", "desktop": "chrome-a-w5.desktop"}]
        with tempfile.TemporaryDirectory() as home, patch("subprocess.run") as run:
            chrome_profiles.apply_kwin_window_desktops(rows, home)
            run.reset_mock()
            self.assertTrue(chrome_profiles.apply_kwin_window_desktops(rows, home))
            run.assert_not_called()

    def test_title_change_is_not_a_profile_switch(self):
        wins = [{
            "id": 7,
            "title": "WhatsApp - Google Chrome",
            "wm_class": "chrome-work-w7.chrome-work-w7",
        }]
        with patch.object(chrome_profiles, "_window_pid", return_value=3), \
                patch.object(chrome_profiles, "_cmdline_is_guest", return_value=False), \
                patch.object(chrome_profiles, "_cmdline_profile_directory", return_value="Default"):
            first = chrome_profiles._chrome_switch_identity(wins)
            wins[0]["title"] = "nebula - WhatsApp"
            second = chrome_profiles._chrome_switch_identity(wins)
        self.assertEqual(first, second)

    def test_dodge_windows_is_turned_off(self):
        with tempfile.TemporaryDirectory() as home:
            cfg = os.path.join(home, ".config")
            os.makedirs(cfg, exist_ok=True)
            path = os.path.join(cfg, "plasma-org.kde.plasma.desktop-appletsrc")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Containments][3]\n"
                    "plugin=org.kde.panel\n"
                    "hiding=2\n"
                    "location=4\n"
                )
            with patch("subprocess.run"), patch("shutil.which", return_value=None):
                self.assertTrue(chrome_profiles.keep_footer_visible(home))
            text = open(path, encoding="utf-8").read()
            self.assertIn("hiding=0", text)
            self.assertNotIn("hiding=2", text)

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

    def test_main_profile_uses_google_account_not_the_letter_m(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Local State"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {
                                    "name": "Main",
                                    "gaia_name": "IMRAN",
                                    "gaia_given_name": "IMRAN",
                                    "user_name": "imranbru99@gmail.com",
                                },
                                "Profile 1": {
                                    "name": "Mirza",
                                    "gaia_given_name": "Mirza",
                                    "user_name": "mirzatoma18@gmail.com",
                                },
                            }
                        }
                    },
                    handle,
                )
            profiles = chrome_profiles.get_chrome_profiles(tmpdir)
            self.assertEqual(profiles["Default"], "IMRAN")
            self.assertEqual(profiles["Profile 1"], "Mirza")
            self.assertEqual(chrome_profiles.badge_letter(profiles["Default"]), "I")
            self.assertEqual(chrome_profiles.badge_letter(profiles["Profile 1"]), "M")

    def test_profile_directory_beats_a_sticky_mirza_class(self):
        profiles = {"Default": "IMRAN", "Profile 1": "Mirza"}
        window = {
            "id": 9091,
            "title": "Facebook - Google Chrome",
            "wm_class": "chrome-mirza",
        }
        original_pid = chrome_profiles._window_pid
        original_key = chrome_profiles._cmdline_profile_key
        chrome_profiles.WINDOW_PROFILE_CACHE.pop(9091, None)
        chrome_profiles._window_pid = lambda wid: 4242
        chrome_profiles._cmdline_profile_key = lambda pid: "Default" if pid == 4242 else None
        try:
            self.assertEqual(chrome_profiles.detect_window_profile(window, profiles), "IMRAN")
        finally:
            chrome_profiles._window_pid = original_pid
            chrome_profiles._cmdline_profile_key = original_key
            chrome_profiles.WINDOW_PROFILE_CACHE.pop(9091, None)

    def test_focused_new_tab_uses_the_profile_chrome_has_open(self):
        profiles = {"Default": "IMRAN", "Profile 1": "Mirza"}
        windows = [
            {"id": 1, "title": "New Tab - Google Chrome", "wm_class": "google-chrome"},
            {"id": 2, "title": "New Tab - Google Chrome", "wm_class": "google-chrome"},
        ]
        session = {
            "Default": {"titles": {"new tab"}, "domains": {"google"}, "mtime": 10},
            "Profile 1": {"titles": {"new tab"}, "domains": {"google"}, "mtime": 20},
        }
        names = chrome_profiles.assign_chrome_window_profiles(
            windows, profiles, ["Default", "Profile 1"], session,
            last_used_key="Profile 1", active_wid=2,
        )
        self.assertEqual(names[2], "Mirza")
        self.assertEqual(names[1], "IMRAN")
        self.assertNotEqual(names[1], names[2])

    def test_one_open_profile_uses_its_photo_on_every_window(self):
        profiles = {"Default": "IMRAN", "Profile 1": "Mirza"}
        windows = [
            {"id": 1, "title": "New Tab - Google Chrome", "wm_class": "google-chrome"},
            {"id": 2, "title": "Inbox - Google Chrome", "wm_class": "google-chrome"},
        ]
        names = chrome_profiles.assign_chrome_window_profiles(
            windows, profiles, ["Default"], {},
            last_used_key="Default", active_wid=1,
        )
        self.assertEqual(names[1], "IMRAN")
        self.assertEqual(names[2], "IMRAN")

    def test_unique_page_keeps_its_own_profile(self):
        profiles = {"Default": "IMRAN", "Profile 1": "Mirza"}
        windows = [
            {"id": 1, "title": "New Tab - Google Chrome", "wm_class": "google-chrome"},
            {"id": 2, "title": "BlogCutter Dashboard - Google Chrome", "wm_class": "google-chrome"},
        ]
        session = {
            "Default": {"titles": {"new tab", "inbox"}, "domains": {"gmail"}, "mtime": 10},
            "Profile 1": {"titles": {"blogcutter dashboard"}, "domains": {"blogcutter"}, "mtime": 30},
        }
        names = chrome_profiles.assign_chrome_window_profiles(
            windows, profiles, ["Default", "Profile 1"], session,
            last_used_key="Default", active_wid=1,
        )
        self.assertEqual(names[1], "IMRAN")
        self.assertEqual(names[2], "Mirza")

    def test_shared_browser_pid_uses_each_windows_own_profile(self):
        profiles = {"Default": "IMRAN", "Profile 1": "Mirza"}
        session = {
            "Default": {"titles": {"inbox"}, "domains": {"gmail"}, "mtime": 10},
            "Profile 1": {
                "titles": {"blogcutter dashboard"},
                "domains": {"blogcutter"},
                "mtime": 20,
            },
        }
        windows = [
            {"id": 9101, "title": "Inbox - Google Chrome", "wm_class": "chrome-imran-w1"},
            {
                "id": 9102,
                "title": "BlogCutter Dashboard - Google Chrome",
                "wm_class": "chrome-imran-w2",
            },
        ]
        original_pid = chrome_profiles._window_pid
        original_key = chrome_profiles._cmdline_profile_key
        chrome_profiles._window_pid = lambda wid: 7
        chrome_profiles._cmdline_profile_key = lambda pid: "Default"
        try:
            with tempfile.TemporaryDirectory() as home:
                for window in windows:
                    chrome_profiles.WINDOW_PROFILE_CACHE.pop(window["id"], None)
                first = chrome_profiles.detect_window_profile(
                    windows[0], profiles, home_dir=home, prof_session_data=session,
                    shared_pids={7},
                )
                second = chrome_profiles.detect_window_profile(
                    windows[1], profiles, home_dir=home, prof_session_data=session,
                    shared_pids={7}, trust_class=False,
                )
            self.assertEqual(first, "IMRAN")
            self.assertEqual(second, "Mirza")
            self.assertNotEqual(first, second)
        finally:
            chrome_profiles._window_pid = original_pid
            chrome_profiles._cmdline_profile_key = original_key
            for window in windows:
                chrome_profiles.WINDOW_PROFILE_CACHE.pop(window["id"], None)

    def test_kwin_script_gives_each_window_its_own_desktop(self):
        rows = [
            {"id": 0x12A0, "pid": 40, "title": "Inbox - Google Chrome", "desktop": "chrome-imran-w12a0.desktop"},
            {"id": 0x12B0, "pid": 41, "title": "Create Lab Dip - Neo Zipper ERP", "desktop": "chrome-mirza-w12b0.desktop"},
        ]
        by_window, by_pid, by_title = chrome_profiles.kwin_assignment_maps(rows)
        self.assertEqual(by_window["4768"], "chrome-imran-w12a0.desktop")
        self.assertEqual(by_window["4784"], "chrome-mirza-w12b0.desktop")
        self.assertNotEqual(by_window["4768"], by_window["4784"])
        script = chrome_profiles.kwin_chrome_desktop_script(by_window, by_pid, by_title)
        self.assertIn("chrome-imran-w12a0.desktop", script)
        self.assertIn("chrome-mirza-w12b0.desktop", script)
        self.assertIn("win.desktopFileName = desk", script)
        self.assertIn("Create Lab Dip - Neo Zipper ERP", script)

    def test_shared_chrome_pid_does_not_collapse_windows(self):
        rows = [
            {"id": 1, "pid": 9, "title": "Logs", "desktop": "chrome-imran-w1.desktop"},
            {"id": 2, "pid": 9, "title": "Logs", "desktop": "chrome-imran-w2.desktop"},
            {"id": 3, "pid": 8, "title": "Guest", "desktop": "chrome-guest-w3.desktop"},
        ]
        by_window, by_pid, by_title = chrome_profiles.kwin_assignment_maps(rows)
        self.assertEqual(len(by_window), 3)
        self.assertNotIn("9", by_pid)
        self.assertEqual(by_pid.get("8"), "chrome-guest-w3.desktop")
        # Same title on two windows must not pin both to one desktop file.
        self.assertNotIn("Logs", by_title)
        self.assertEqual(by_title.get("Guest"), "chrome-guest-w3.desktop")

    def test_chrome_badge_does_not_replace_system_icons(self):
        from PIL import Image as PILImage

        with tempfile.TemporaryDirectory() as tmp_home:
            badge = os.path.join(tmp_home, "badge.png")
            PILImage.new("RGBA", (32, 32), (10, 20, 30, 255)).save(badge)
            root = os.path.join(tmp_home, ".local/share/icons/hicolor")
            os.makedirs(root, exist_ok=True)
            index = os.path.join(root, "index.theme")
            with open(index, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Icon Theme]\nName=Hicolor\nComment=DevOS profile badges\n"
                    "Directories=48x48/apps,128x128/apps,256x256/apps\n"
                )
            cache = os.path.join(root, "icon-theme.cache")
            with open(cache, "wb") as handle:
                handle.write(b"cache")
            os.makedirs(os.path.join(tmp_home, ".cache"), exist_ok=True)
            kcache = os.path.join(tmp_home, ".cache", "icon-cache.kcache")
            with open(kcache, "wb") as handle:
                handle.write(b"k")
            with patch.object(chrome_profiles, "_nudge_icon_theme"):
                chrome_profiles._install_theme_chrome_icon(tmp_home, badge)
                self.assertFalse(os.path.isfile(index))
                self.assertFalse(os.path.isfile(cache))
                self.assertFalse(os.path.isfile(kcache))
                png = os.path.join(root, "48x48", "apps", "google-chrome.png")
                self.assertTrue(os.path.isfile(png))
                # The photo is already installed. A later pass must not put
                # the private theme file back, or the next start blanks icons.
                chrome_profiles._install_theme_chrome_icon(tmp_home, badge)
            self.assertFalse(os.path.isfile(index))
            self.assertFalse(os.path.isfile(cache))
            self.assertTrue(os.path.isfile(png))

    def test_repair_leaves_a_foreign_icon_theme(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            root = os.path.join(tmp_home, ".local/share/icons/hicolor")
            os.makedirs(root, exist_ok=True)
            index = os.path.join(root, "index.theme")
            with open(index, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Icon Theme]\nName=Hicolor\nInherits=Adwaita\n"
                    "Directories=16x16/apps,48x48/apps\n"
                )
            cache = os.path.join(root, "icon-theme.cache")
            with open(cache, "wb") as handle:
                handle.write(b"keep")
            self.assertFalse(chrome_profiles.repair_user_icon_theme(tmp_home))
            self.assertTrue(os.path.isfile(index))
            self.assertEqual(open(cache, "rb").read(), b"keep")

    def test_repair_drops_an_orphan_icon_cache(self):
        with tempfile.TemporaryDirectory() as tmp_home:
            apps = os.path.join(tmp_home, ".local/share/icons/hicolor/48x48/apps")
            os.makedirs(apps, exist_ok=True)
            png = os.path.join(apps, "chrome-work.png")
            with open(png, "wb") as handle:
                handle.write(b"png")
            cache = os.path.join(tmp_home, ".local/share/icons/hicolor/icon-theme.cache")
            with open(cache, "wb") as handle:
                handle.write(b"old")
            with patch.object(chrome_profiles, "_nudge_icon_theme") as nudge:
                self.assertTrue(chrome_profiles.repair_user_icon_theme(tmp_home))
            nudge.assert_called()
            self.assertFalse(os.path.isfile(cache))
            self.assertTrue(os.path.isfile(png))


def _save_portrait(path, center):
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (96, 96), (248, 248, 248))
    px = img.load()
    for y in range(96):
        for x in range(96):
            px[x, y] = ((x * 7) % 256, (y * 5 + 20) % 256, (x + y * 3) % 256)
    for y in range(40, 56):
        for x in range(40, 56):
            px[x, y] = center
    img.save(path)


class TestChromeProfilePhoto(unittest.TestCase):
    def test_account_photo_is_used_even_with_a_theme_avatar_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = os.path.join(tmpdir, "Default")
            os.makedirs(folder)
            photo = os.path.join(folder, "Google Profile Picture.png")
            _save_portrait(photo, (210, 48, 150))
            with open(os.path.join(tmpdir, "Local State"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "profile": {
                            "info_cache": {
                                "Default": {
                                    "name": "IMRAN",
                                    "avatar_icon": "chrome://theme/IDR_PROFILE_AVATAR_26",
                                }
                            }
                        }
                    },
                    handle,
                )
            found = chrome_profiles.get_profile_avatar_path(tmpdir, "Default")
            self.assertEqual(found, photo)

    def test_preferences_picture_is_found_when_local_state_has_no_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = os.path.join(tmpdir, "Profile 1")
            os.makedirs(folder)
            photo = os.path.join(folder, "Google Profile Picture.png")
            _save_portrait(photo, (40, 90, 200))
            with open(os.path.join(tmpdir, "Local State"), "w", encoding="utf-8") as handle:
                json.dump({"profile": {"info_cache": {"Profile 1": {"name": "Mirza"}}}}, handle)
            with open(os.path.join(folder, "Preferences"), "w", encoding="utf-8") as handle:
                json.dump(
                    {"profile": {"gaia_picture_file_name": "Google Profile Picture.png", "use_gaia_picture": True}},
                    handle,
                )
            self.assertEqual(
                chrome_profiles.get_profile_avatar_path(tmpdir, "Profile 1"),
                photo,
            )

    def test_flat_saved_picture_is_not_a_photo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            folder = os.path.join(tmpdir, "Default")
            os.makedirs(folder)
            flat = os.path.join(folder, "avatar.png")
            from PIL import Image as PILImage

            PILImage.new("RGB", (96, 96), (20, 120, 220)).save(flat)
            self.assertFalse(chrome_profiles._accept_account_photo(flat))

    def test_taskbar_icon_updates_when_the_account_photo_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            photo = os.path.join(tmpdir, "Google Profile Picture.png")
            _save_portrait(photo, (220, 30, 140))
            icons = os.path.join(tmpdir, "icons")
            os.makedirs(icons)
            first = chrome_profiles.profile_icon_fingerprint("IMRAN", photo)
            path_48, _short = chrome_profiles.profile_icon_file(icons, "chrome-imran", first)
            path_128, _short = chrome_profiles.profile_icon_file(
                os.path.join(tmpdir, "icons128"), "chrome-imran", first
            )
            self.assertTrue(chrome_profiles.ensure_badged_icon("IMRAN", path_48, path_128, photo, first))
            self.assertFalse(chrome_profiles.ensure_badged_icon("IMRAN", path_48, path_128, photo, first))
            self.assertTrue(chrome_profiles.icon_matches_photo(path_48, first))
            _save_portrait(photo, (20, 40, 230))
            second = chrome_profiles.profile_icon_fingerprint("IMRAN", photo)
            self.assertNotEqual(first, second)
            self.assertFalse(chrome_profiles.icon_matches_photo(path_48, second))
            new_48, _short = chrome_profiles.profile_icon_file(icons, "chrome-imran", second)
            new_128, _short = chrome_profiles.profile_icon_file(
                os.path.join(tmpdir, "icons128"), "chrome-imran", second
            )
            self.assertNotEqual(path_48, new_48)
            self.assertTrue(chrome_profiles.ensure_badged_icon("IMRAN", new_48, new_128, photo, second))
            from PIL import Image as PILImage

            img = PILImage.open(new_48).convert("RGB")
            corner = list(img.crop((30, 30, 47, 47)).getdata())
            blues = sum(1 for px in corner if px[2] > 150 and px[0] < 80)
            self.assertGreater(blues, 4)


if __name__ == "__main__":
    unittest.main()
