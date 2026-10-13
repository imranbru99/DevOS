"""
Unit tests for DevOS Apps (installed apps manager).
Covers desktop-file discovery and filtering, package-owner and size parsing,
Windows folder grouping, Android app parsing, uninstall command building,
browser cookie reset plans and the safety checks on every deletion.
No display, no root and no system tools are needed: HOME and the app
folders are temp dirs and subprocess calls go through a fake runner.
"""

import os
import sys
import shutil
import tempfile
import unittest

SYS_PATH_APPS = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../components/apps"))
sys.path.insert(0, SYS_PATH_APPS)

import apps_manager as am  # noqa: E402


class FakeRunner:
    """Maps the first words of argv to (rc, output) and records calls."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def __call__(self, argv, timeout=120, env=None):
        self.calls.append(list(argv))
        best = None
        for key, val in self.responses.items():
            if tuple(argv[:len(key)]) == key and (best is None or len(key) > len(best[0])):
                best = (key, val)
        if best is None:
            return 127, f"{argv[0]}: not found"
        val = best[1]
        return val(argv) if callable(val) else val


def which_all(_name):
    return "/usr/bin/fake"


def which_none(_name):
    return None


def write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def desktop(name, exec_="app", extra=""):
    return f"[Desktop Entry]\nType=Application\nName={name}\nExec={exec_}\nIcon=app\n{extra}"


class AppsManagerBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="devos-apps-test-")
        self.home = os.path.join(self.tmp, "home", "user")
        self.sys_apps = os.path.join(self.tmp, "usr", "share", "applications")
        self.user_apps = os.path.join(self.home, ".local", "share", "applications")
        os.makedirs(self.sys_apps)
        os.makedirs(self.user_apps)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def discovery(self, runner=None, which=which_none):
        return am.AppDiscovery(home=self.home, app_dirs=[self.sys_apps, self.user_apps],
                               runner=runner or FakeRunner(), which=which)


class TestParsers(AppsManagerBase):

    def test_desktop_parsing_ignores_other_groups_and_locales(self):
        e = am.parse_desktop_text(
            "[Desktop Entry]\nName=Writer\nName[de]=Schreiber\nExec=writer %U\n"
            "[Desktop Action new]\nName=New Document\n")
        self.assertEqual(e["Name"], "Writer")
        self.assertEqual(e["Exec"], "writer %U")

    def test_visibility_rules(self):
        base = {"Type": "Application", "Name": "X", "Exec": "x"}
        self.assertTrue(am.desktop_visible(base))
        self.assertFalse(am.desktop_visible(dict(base, NoDisplay="true")))
        self.assertFalse(am.desktop_visible(dict(base, Hidden="true")))
        self.assertFalse(am.desktop_visible(dict(base, OnlyShowIn="GNOME;")))
        self.assertTrue(am.desktop_visible(dict(base, OnlyShowIn="GNOME;KDE;")))
        self.assertFalse(am.desktop_visible(dict(base, NotShowIn="KDE;")))
        self.assertFalse(am.desktop_visible(dict(base, TryExec="nope"), which_none))
        self.assertFalse(am.desktop_visible(dict(base, Type="Link")))

    def test_dpkg_search_parsing(self):
        out = ("vlc-bin: /usr/share/applications/vlc.desktop\n"
               "libreoffice-writer:amd64: /usr/share/applications/libreoffice-writer.desktop\n"
               "diversion by foo from: /usr/share/applications/x.desktop\n"
               "kate, kwrite: /usr/share/applications/org.kde.kate.desktop\n"
               "dpkg-query: no path found matching pattern /home/u/a.desktop\n")
        r = am.parse_dpkg_search(out)
        self.assertEqual(r["/usr/share/applications/vlc.desktop"], "vlc-bin")
        self.assertEqual(r["/usr/share/applications/libreoffice-writer.desktop"], "libreoffice-writer")
        self.assertEqual(r["/usr/share/applications/org.kde.kate.desktop"], "kate")
        self.assertNotIn("/home/u/a.desktop", r)
        self.assertEqual(len(r), 3)

    def test_installed_size_parsing(self):
        out = ("123456\tgoogle-chrome-stable\toptional\tno\t130.0.1\n"
               "\tbroken\t\t\t\n"
               "2048\tcoreutils\trequired\tyes\t9.4\n"
               "512\tlegacy\n")
        r = am.parse_dpkg_info(out)
        self.assertEqual(r["google-chrome-stable"]["size_kib"], 123456)
        self.assertEqual(r["google-chrome-stable"]["version"], "130.0.1")
        self.assertIsNone(r["broken"]["size_kib"])
        self.assertEqual(r["coreutils"]["priority"], "required")
        self.assertTrue(r["coreutils"]["essential"])
        self.assertEqual(r["legacy"]["size_kib"], 512)

    def test_human_sizes(self):
        self.assertEqual(am.parse_human_size("1.5 GB"), 1500000000)
        self.assertEqual(am.parse_human_size("352,6\u00a0MB"), 352600000)
        self.assertEqual(am.parse_human_size("12 kB"), 12000)
        self.assertIsNone(am.parse_human_size(""))
        self.assertEqual(am.human_size(None), "—")
        self.assertEqual(am.human_size(1536), "1.5 KB")

    def test_wineprefix_extraction(self):
        h = "/home/u"
        self.assertEqual(am.extract_wineprefix(
            'env WINEPREFIX="/home/u/.wine-office" wine C:\\\\\\\\Program\\\\ Files\\\\\\\\x.exe', h),
            "/home/u/.wine-office")
        self.assertEqual(am.extract_wineprefix("env WINEPREFIX=/home/u/.wine wine start x.lnk", h),
                         "/home/u/.wine")
        self.assertEqual(am.extract_wineprefix('env WINEPREFIX="$HOME/My\\\\ Apps" wine x', h),
                         "/home/u/My Apps")
        self.assertEqual(am.extract_wineprefix("env WINEPREFIX='~/.wine-x' wine x", h), "/home/u/.wine-x")
        self.assertIsNone(am.extract_wineprefix("firefox %u", h))

    def test_waydroid_list_parsing(self):
        out = ("Name: Calculator\npackageName: com.android.calculator2\ncategories:\n"
               "\tandroid.intent.category.LAUNCHER\n"
               "Name: WhatsApp\npackageName: com.whatsapp\ncategories:\n")
        r = am.parse_waydroid_list(out)
        self.assertEqual(r, [{"name": "Calculator", "package": "com.android.calculator2"},
                             {"name": "WhatsApp", "package": "com.whatsapp"}])
        self.assertTrue(am.waydroid_running("Session:\tRUNNING\nContainer:\tRUNNING"))
        self.assertFalse(am.waydroid_running("Session:\tSTOPPED"))

    def test_apt_simulation_parsing(self):
        out = "Inst x\nRemv vlc [3.0]\nRemv vlc-bin:amd64 [3.0]\nConf y\n"
        self.assertEqual(am.parse_apt_simulation(out), ["vlc", "vlc-bin"])

    def test_scrub_removes_tool_names(self):
        s = am.scrub("E: dpkg was interrupted; apt-get failed under Wine on KDE Plasma (Ubuntu)")
        for word in ("dpkg", "apt", "Wine", "KDE", "Plasma", "Ubuntu"):
            self.assertNotIn(word.lower(), s.lower().replace("installer", ""))

    def test_exec_to_argv(self):
        self.assertEqual(am.exec_to_argv('vlc --started-from-file %U'), ["vlc", "--started-from-file"])
        self.assertEqual(am.exec_to_argv('"/opt/My App/run" %f --name=%c', name="My"),
                         ["/opt/My App/run", "--name=My"])


class TestDiscovery(AppsManagerBase):

    def test_linux_filtering_and_packages(self):
        write(os.path.join(self.sys_apps, "vlc.desktop"), desktop("VLC media player", "vlc %U"))
        write(os.path.join(self.sys_apps, "hidden.desktop"), desktop("Hidden", extra="NoDisplay=true\n"))
        write(os.path.join(self.sys_apps, "gone.desktop"), desktop("Gone", extra="Hidden=true\n"))
        write(os.path.join(self.sys_apps, "org.kde.dolphin.desktop"), desktop("Dolphin"))
        write(os.path.join(self.sys_apps, "devos-apphub.desktop"), desktop("App Hub"))
        write(os.path.join(self.sys_apps, "org.kde.konsole.desktop"), desktop("Konsole"))
        write(os.path.join(self.sys_apps, "waydroid.com.whatsapp.desktop"), desktop("WhatsApp"))
        write(os.path.join(self.sys_apps, "org.kde.kate.desktop"), desktop("Kate"))
        write(os.path.join(self.sys_apps, "google-chrome.desktop"), desktop("Google Chrome"))
        write(os.path.join(self.user_apps, "myscript.desktop"), desktop("My Script"))
        p = lambda n: os.path.join(self.sys_apps, n)  # noqa: E731
        runner = FakeRunner({
            ("dpkg-query", "-S"): (1, f"vlc: {p('vlc.desktop')}\nkate: {p('org.kde.kate.desktop')}\n"
                                      f"google-chrome-stable: {p('google-chrome.desktop')}\n"),
            ("dpkg-query", "-W"): (0, "70000\tvlc\toptional\tno\t3.0.20\n"
                                      "9000\tkate\toptional\tno\t23.08\n"
                                      "300000\tgoogle-chrome-stable\toptional\tno\t130\n"),
        })
        apps = {a.id: a for a in self.discovery(runner, which_all).discover_linux()}
        self.assertEqual(set(apps), {"deb:vlc", "deb:kate", "deb:google-chrome-stable", "desktop:myscript"})
        self.assertEqual(apps["deb:vlc"].size_bytes, 70000 * 1024)
        self.assertEqual(apps["deb:vlc"].version, "3.0.20")
        self.assertTrue(apps["deb:google-chrome-stable"].uninstallable)
        self.assertEqual(apps["deb:vlc"].type_label, "Linux app")
        self.assertTrue(apps["desktop:myscript"].uninstallable)
        # dpkg-query -S was called once for all paths (batched)
        s_calls = [c for c in runner.calls if c[:2] == ["dpkg-query", "-S"]]
        self.assertEqual(len(s_calls), 1)
        self.assertEqual(len(s_calls[0]) - 2, 4)

    def test_protected_package_becomes_system_app(self):
        write(os.path.join(self.sys_apps, "org.kde.ark.desktop"), desktop("Ark"))
        write(os.path.join(self.sys_apps, "core.desktop"), desktop("Core Tool"))
        p = lambda n: os.path.join(self.sys_apps, n)  # noqa: E731
        runner = FakeRunner({
            ("dpkg-query", "-S"): (0, f"ark: {p('org.kde.ark.desktop')}\ncoreutils: {p('core.desktop')}\n"),
            ("dpkg-query", "-W"): (0, "100\tark\toptional\tno\t1\n100\tcoreutils\trequired\tyes\t9\n"),
        })
        apps = {a.id: a for a in self.discovery(runner, which_all).discover_linux()}
        for key in ("deb:ark", "deb:coreutils"):
            self.assertTrue(apps[key].system)
            self.assertFalse(apps[key].uninstallable)
            self.assertEqual(apps[key].type_label, "System app")
        plan = am.AppActions(self.discovery(runner, which_all)).uninstall_plan(apps["deb:ark"])
        self.assertEqual(plan["kind"], "refuse")

    def test_no_tools_still_lists(self):
        write(os.path.join(self.sys_apps, "vlc.desktop"), desktop("VLC"))
        apps = self.discovery().discover_all()
        self.assertEqual([a.name for a in apps], ["VLC"])
        self.assertFalse(apps[0].uninstallable)  # unknown owner in a system folder

    def test_windows_grouping(self):
        prefixes = os.path.join(self.home, ".local/share/winlayer/prefixes")
        os.makedirs(os.path.join(prefixes, "notepadpp", "drive_c"))
        os.makedirs(os.path.join(self.home, ".wine-office", "drive_c"))
        write(os.path.join(self.user_apps, "winlayer-notepadpp.desktop"),
              desktop("notepadpp (Windows)", 'python3 "/x/prefix_manager.py" launch "/d/n.exe"'))
        office = os.path.join(self.home, ".wine-office")
        progs = os.path.join(self.user_apps, "wine", "Programs", "Office")
        write(os.path.join(progs, "Word.desktop"),
              desktop("Word", f'env WINEPREFIX="{office}" wine C:\\\\\\\\x\\\\\\\\word.lnk'))
        write(os.path.join(progs, "Uninstall Office.desktop"),
              desktop("Uninstall Office", f'env WINEPREFIX="{office}" wine uninstaller'))
        write(os.path.join(self.user_apps, "wine-extension-doc.desktop"),
              desktop("doc", f'env WINEPREFIX="{office}" wine start', "NoDisplay=true\n"))
        disc = self.discovery()
        apps = {a.prefix: a for a in disc.discover_windows()}
        self.assertEqual(set(apps), {os.path.join(prefixes, "notepadpp"), office})
        self.assertEqual(apps[os.path.join(prefixes, "notepadpp")].name, "notepadpp")
        o = apps[office]
        self.assertEqual(o.name, "Word")
        self.assertEqual(len(o.desktop_files), 3)
        self.assertEqual(o.type_label, "Windows app")
        self.assertTrue(o.uninstallable)
        self.assertGreater(disc.compute_size(o), -1)
        # wine entries never show up as Linux apps
        self.assertEqual(disc.discover_linux(), [])

    def test_android_from_desktop_files_and_running_session(self):
        write(os.path.join(self.user_apps, "waydroid.com.whatsapp.desktop"),
              desktop("WhatsApp", "waydroid app launch com.whatsapp"))
        runner = FakeRunner({
            ("waydroid", "status"): (0, "Session:\tRUNNING\n"),
            ("waydroid", "app", "list"): (0, "Name: WhatsApp\npackageName: com.whatsapp\n"
                                             "Name: Settings\npackageName: com.android.settings\n"),
        })
        apps = {a.android_package: a for a in self.discovery(runner, which_all).discover_android()}
        self.assertEqual(set(apps), {"com.whatsapp", "com.android.settings"})
        self.assertEqual(apps["com.whatsapp"].type_label, "Android app")
        self.assertTrue(apps["com.android.settings"].system)
        # session not running: only the desktop files
        stopped = FakeRunner({("waydroid", "status"): (0, "Session:\tSTOPPED\n")})
        apps = self.discovery(stopped, which_all).discover_android()
        self.assertEqual([a.android_package for a in apps], ["com.whatsapp"])

    def test_flatpak_listing(self):
        runner = FakeRunner({("flatpak", "list"): (
            0, "org.videolan.VLC\tVLC\t3.0.21\t87.2 MB\tsystem\ncom.spotify.Client\tSpotify\t1.2\t1.1 GB\tuser\n")})
        apps = {a.appid: a for a in self.discovery(runner, which_all).discover_flatpak()}
        self.assertEqual(apps["org.videolan.VLC"].size_bytes, 87200000)
        self.assertEqual(apps["com.spotify.Client"].installation, "user")
        self.assertEqual(apps["com.spotify.Client"].type_label, "Linux app")

    def test_find_app_by_desktop_path(self):
        path = write(os.path.join(self.user_apps, "myscript.desktop"), desktop("My Script"))
        apps = self.discovery().discover_all()
        self.assertEqual(am.find_app(apps, path).id, "desktop:myscript")
        self.assertEqual(am.find_app(apps, "desktop:myscript").id, "desktop:myscript")
        self.assertIsNone(am.find_app(apps, "/nope/devos-apps.desktop"))


class TestActions(AppsManagerBase):

    def actions(self, runner=None, which=which_all):
        disc = self.discovery(runner, which)
        return am.AppActions(disc)

    def test_uninstall_commands(self):
        acts = self.actions()
        deb = am.App(id="deb:vlc", name="VLC", platform="linux", kind="deb", package="vlc")
        self.assertEqual(acts.uninstall_plan(deb)["argv"], ["pkexec", "apt-get", "remove", "-y", "vlc"])
        fp_user = am.App(id="flatpak:a.b.C", name="C", platform="linux", kind="flatpak",
                         appid="a.b.C", installation="user")
        self.assertEqual(acts.uninstall_plan(fp_user)["argv"],
                         ["flatpak", "uninstall", "-y", "--noninteractive", "--user", "a.b.C"])
        fp_sys = am.App(id="flatpak:a.b.C", name="C", platform="linux", kind="flatpak",
                        appid="a.b.C", installation="system")
        self.assertNotIn("--user", acts.uninstall_plan(fp_sys)["argv"])
        andr = am.App(id="android:com.x", name="X", platform="android", kind="android",
                      android_package="com.x")
        plan = acts.uninstall_plan(andr)
        self.assertEqual(plan["argv"], ["waydroid", "app", "remove", "com.x"])
        self.assertTrue(plan["requires_android"])

    def test_android_uninstall_needs_running_session(self):
        runner = FakeRunner({("waydroid", "status"): (0, "Session:\tSTOPPED\n")})
        acts = self.actions(runner)
        andr = am.App(id="android:com.x", name="X", platform="android", kind="android",
                      android_package="com.x")
        res = acts.execute(acts.uninstall_plan(andr))
        self.assertFalse(res["ok"])
        self.assertIn("Open Android first", res["message"])
        self.assertNotIn(["waydroid", "app", "remove", "com.x"], runner.calls)

    def test_deb_precheck_blocks_system_cascade(self):
        runner = FakeRunner({
            ("apt-get", "-s"): (0, "Remv libfoo [1]\nRemv plasma-desktop [5]\n"),
            ("dpkg-query", "-W"): (0, "1\tlibfoo\toptional\tno\t1\n"),
        })
        acts = self.actions(runner)
        deb = am.App(id="deb:libfoo", name="Foo", platform="linux", kind="deb", package="libfoo")
        plan = acts.prepare_uninstall(deb)
        self.assertEqual(plan["kind"], "refuse")
        self.assertEqual(plan["blocked_by"], ["plasma-desktop"])
        res = acts.execute(plan)
        self.assertFalse(res["ok"])
        self.assertFalse(any(c[0] == "pkexec" for c in runner.calls))

    def test_deb_uninstall_failure_is_friendly(self):
        runner = FakeRunner({("pkexec",): (100, "Reading...\nline2\nE: dpkg was interrupted\nE: apt broke\n")})
        acts = self.actions(runner)
        deb = am.App(id="deb:vlc", name="VLC", platform="linux", kind="deb", package="vlc")
        res = acts.execute(acts.uninstall_plan(deb))
        self.assertFalse(res["ok"])
        self.assertNotIn("dpkg", res["message"])
        self.assertEqual(len(res["message"].splitlines()), 3)
        cancelled = FakeRunner({("pkexec",): (126, "Error executing command as another user: Request dismissed")})
        res = self.actions(cancelled).execute(acts.uninstall_plan(deb))
        self.assertIn("cancelled", res["message"])

    def test_windows_uninstall_removes_prefix_and_entries(self):
        prefixes = os.path.join(self.home, ".local/share/winlayer/prefixes")
        write(os.path.join(prefixes, "tool", "drive_c", "x.exe"), "MZ")
        entry = write(os.path.join(self.user_apps, "winlayer-tool.desktop"), desktop("tool (Windows)"))
        runner = FakeRunner({("update-desktop-database",): (0, "")})
        acts = self.actions(runner)
        app = [a for a in acts.d.discover_windows()][0]
        res = acts.execute(acts.uninstall_plan(app))
        self.assertTrue(res["ok"], res)
        self.assertFalse(os.path.exists(os.path.join(prefixes, "tool")))
        self.assertFalse(os.path.exists(entry))
        self.assertIn(["update-desktop-database", self.user_apps], runner.calls)

    def test_windows_uninstall_refuses_outside_prefix(self):
        outside = os.path.join(self.tmp, "important")
        write(os.path.join(outside, "drive_c", "keep.txt"), "keep")
        acts = self.actions()
        app = am.App(id="win:x", name="X", platform="windows", kind="windows", prefix=outside)
        plan = acts.uninstall_plan(app)
        self.assertEqual(plan["kind"], "refuse")
        acts.execute(plan)
        self.assertTrue(os.path.exists(os.path.join(outside, "drive_c", "keep.txt")))
        # default shared ~/.wine is not removable either
        shared = am.App(id="win:wine", name="W", platform="windows", kind="windows",
                        prefix=os.path.join(self.home, ".wine"))
        self.assertEqual(acts.uninstall_plan(shared)["kind"], "refuse")

    def test_windows_prefix_symlink_escape_refused(self):
        prefixes = os.path.join(self.home, ".local/share/winlayer/prefixes")
        os.makedirs(prefixes)
        outside = os.path.join(self.tmp, "victim")
        write(os.path.join(outside, "drive_c", "keep.txt"), "keep")
        os.symlink(outside, os.path.join(prefixes, "evil"))
        acts = self.actions()
        app = am.App(id="win:evil", name="Evil", platform="windows", kind="windows",
                     prefix=os.path.join(prefixes, "evil"))
        self.assertEqual(acts.uninstall_plan(app)["kind"], "refuse")
        self.assertTrue(os.path.exists(os.path.join(outside, "drive_c", "keep.txt")))

    def _chrome(self):
        root = os.path.join(self.home, ".config", "google-chrome")
        for prof in ("Default", "Profile 1"):
            for f in ("Cookies", "Cookies-journal", "Network/Cookies", "Login Data",
                      "Bookmarks", "History", "Cache/data_0", "Code Cache/js/x"):
                write(os.path.join(root, prof, f), "x" * 100)
        write(os.path.join(self.home, ".cache", "google-chrome", "Default", "Cache", "f"), "x")
        return root, am.App(id="deb:google-chrome-stable", name="Google Chrome", platform="linux",
                            kind="deb", package="google-chrome-stable",
                            desktop_ids=["google-chrome.desktop"])

    def test_browser_cookie_reset_keeps_passwords_and_bookmarks(self):
        root, app = self._chrome()
        acts = self.actions(FakeRunner())
        plan = acts.data_plan(app, full=False)
        self.assertTrue(plan["is_browser"])
        self.assertEqual(plan["needs_closed"], ["chrome"])
        rel = {os.path.relpath(p, root) for p in plan["paths"] if p.startswith(root)}
        for prof in ("Default", "Profile 1"):
            for f in ("Cookies", "Cookies-journal", os.path.join("Network", "Cookies"), "Cache", "Code Cache"):
                self.assertIn(os.path.join(prof, f), rel)
            for kept in ("Login Data", "Bookmarks", "History"):
                self.assertNotIn(os.path.join(prof, kept), rel)
        res = acts.execute(plan)
        self.assertTrue(res["ok"], res)
        self.assertGreater(res["freed_bytes"], 0)
        for prof in ("Default", "Profile 1"):
            self.assertFalse(os.path.exists(os.path.join(root, prof, "Cookies")))
            self.assertTrue(os.path.exists(os.path.join(root, prof, "Login Data")))
            self.assertTrue(os.path.exists(os.path.join(root, prof, "Bookmarks")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".cache", "google-chrome")))

    def test_browser_full_reset_removes_profile_folder(self):
        root, app = self._chrome()
        acts = self.actions(FakeRunner())
        plan = acts.data_plan(app, full=True)
        self.assertIn(root, plan["paths"])
        acts.execute(plan)
        self.assertFalse(os.path.exists(root))
        self.assertTrue(os.path.isdir(self.home))

    def test_firefox_cookie_plan(self):
        prof = os.path.join(self.home, ".mozilla", "firefox", "abcd.default-release")
        for f in ("cookies.sqlite", "cache2/entries/x", "logins.json", "places.sqlite"):
            write(os.path.join(prof, f), "x")
        app = am.App(id="deb:firefox", name="Firefox", platform="linux", kind="deb", package="firefox")
        names = {os.path.basename(p) for p in self.actions().data_plan(app)["paths"]}
        self.assertIn("cookies.sqlite", names)
        self.assertIn("cache2", names)
        self.assertNotIn("logins.json", names)
        self.assertNotIn("places.sqlite", names)

    def test_symlink_escape_refused_on_delete(self):
        outside = os.path.join(self.tmp, "outside")
        write(os.path.join(outside, "Default", "Cookies"), "secret")
        os.makedirs(os.path.join(self.home, ".config"))
        os.symlink(outside, os.path.join(self.home, ".config", "google-chrome"))
        _root, app = self._chrome_app_only()
        acts = self.actions(FakeRunner())
        plan = acts.data_plan(app, full=False)
        res = acts.execute(plan)
        self.assertTrue(os.path.exists(os.path.join(outside, "Default", "Cookies")))
        self.assertTrue(res["errors"])
        # deleting the link itself (full reset) removes only the link
        acts.execute(acts.data_plan(app, full=True))
        self.assertTrue(os.path.exists(os.path.join(outside, "Default", "Cookies")))
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".config", "google-chrome")))

    def _chrome_app_only(self):
        return None, am.App(id="deb:google-chrome-stable", name="Google Chrome", platform="linux",
                            kind="deb", package="google-chrome-stable")

    def test_safe_target(self):
        self.assertTrue(am.safe_target(os.path.join(self.home, ".cache", "x"), [self.home]))
        self.assertFalse(am.safe_target(self.home, [self.home]))
        self.assertFalse(am.safe_target(os.path.join(self.home, "..", "other"), [self.home]))
        self.assertFalse(am.safe_target("/etc/passwd", [self.home]))

    def test_cache_plan_generic_and_windows(self):
        write(os.path.join(self.home, ".cache", "vlc", "art", "x"), "x")
        write(os.path.join(self.home, ".config", "Code", "CachedData", "x"), "x")
        write(os.path.join(self.home, ".config", "Code", "User", "settings.json"), "{}")
        acts = self.actions()
        vlc = am.App(id="deb:vlc", name="VLC media player", platform="linux", kind="deb",
                     package="vlc", desktop_ids=["vlc.desktop"])
        self.assertIn(os.path.join(self.home, ".cache", "vlc"), acts.cache_plan(vlc)["paths"])
        code = am.App(id="deb:code", name="Visual Studio Code", platform="linux", kind="deb",
                      package="code", desktop_ids=["code.desktop"])
        paths = acts.cache_plan(code)["paths"]
        self.assertIn(os.path.join(self.home, ".config", "Code", "CachedData"), paths)
        self.assertNotIn(os.path.join(self.home, ".config", "Code", "User"), paths)

        prefix = os.path.join(self.home, ".local/share/winlayer/prefixes/tool")
        write(os.path.join(prefix, "drive_c/users/me/AppData/Local/Temp/t.tmp"), "x" * 10)
        write(os.path.join(prefix, "drive_c/Program Files/tool/tool.exe"), "MZ")
        win = am.App(id="win:tool", name="Tool", platform="windows", kind="windows", prefix=prefix)
        res = acts.execute(acts.cache_plan(win))
        self.assertTrue(res["ok"])
        self.assertTrue(os.path.isdir(os.path.join(prefix, "drive_c/users/me/AppData/Local/Temp")))
        self.assertFalse(os.path.exists(os.path.join(prefix, "drive_c/users/me/AppData/Local/Temp/t.tmp")))
        self.assertTrue(os.path.exists(os.path.join(prefix, "drive_c/Program Files/tool/tool.exe")))

    def test_android_data_and_cache(self):
        acts = self.actions()
        andr = am.App(id="android:com.x", name="X", platform="android", kind="android",
                      android_package="com.x")
        self.assertEqual(acts.cache_plan(andr)["kind"], "refuse")
        self.assertEqual(acts.data_plan(andr)["argv"], ["pkexec", "waydroid", "shell", "pm", "clear", "com.x"])

    def test_generic_reset_skips_shared_folders(self):
        write(os.path.join(self.home, ".config", "kde", "x"), "x")
        write(os.path.join(self.home, ".config", "kate", "x"), "x")
        write(os.path.join(self.home, ".config", "katerc"), "x")
        app = am.App(id="deb:kate", name="Kate", platform="linux", kind="deb", package="kate",
                     desktop_ids=["org.kde.kate.desktop"])
        paths = self.actions().data_plan(app)["paths"]
        self.assertIn(os.path.join(self.home, ".config", "kate"), paths)
        self.assertIn(os.path.join(self.home, ".config", "katerc"), paths)
        self.assertNotIn(os.path.join(self.home, ".config", "kde"), paths)

    def test_running_browser_detected(self):
        runner = FakeRunner({("pgrep", "-x", "chrome"): (0, "1234\n5678\n")})
        _r, app = self._chrome_app_only()
        self.assertEqual(self.actions(runner).running_pids(app), [1234, 5678])


if __name__ == "__main__":
    unittest.main()
